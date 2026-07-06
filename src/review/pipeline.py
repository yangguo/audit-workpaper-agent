"""Pipeline orchestration: runs all review stages and merges findings.

Ported from analyze_excel.py's generate_report review core (no xlsx/txt rendering).
"""
import dataclasses
import json
from typing import Dict, List, Optional, Tuple

import openpyxl

from review.attachments import _check_attachment_references
from review.checkpoints import _llm_check_sheet_by_checkpoints
from review.evidence_steps import _llm_check_evidence_vs_steps
from review.findings_review import _llm_review_findings
from review.hallucination import (
    _build_minimal_context,
    _challenge_finding_with_llm,
    _cross_validate_finding,
)
from review.llm import LLM_CALL_STATS
from review.models import Finding, _SEVERITY_DISPLAY
from review.procedure_pairs import (
    _check_procedure_pairs,
    _check_sheet_scope,
    _llm_check_procedure_pairs,
)

_SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def _parse_sheet_filter(raw: Optional[str]) -> Optional[List[str]]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"all", "*", "全部"}:
        return None
    parts = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out or None


def _finding_to_dict(f: Finding) -> dict:
    d = dataclasses.asdict(f)
    for k, default in (("evidence_refs", []), ("reasons", []), ("fix_suggestion_detail", {})):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            try:
                d[k] = json.loads(v)
            except Exception:
                d[k] = v
        else:
            d[k] = default
    d["severity_display"] = _SEVERITY_DISPLAY.get(f.severity, f.severity)
    return d


def _sort_findings(findings: List[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: (
        _SEVERITY_ORDER.get(f.severity, 9),
        f.sheet or "",
        str(f.cell or ""),
    ))


async def run_review(
    *,
    wb: openpyxl.Workbook,
    checkpoints: Optional[Dict[str, List[str]]] = None,
    attachments_preview: Optional[Dict[str, object]] = None,
    sheets: Optional[str] = None,
    llm,
) -> Tuple[List[dict], dict]:
    """Run the full review pipeline. Returns (findings_dicts, stats)."""
    checkpoints = checkpoints or {}
    attachments_preview = attachments_preview or {}
    target = _parse_sheet_filter(sheets) or list(wb.sheetnames)

    findings: List[Finding] = []
    for sheet in target:
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        # 1) checkpoint-based review
        if checkpoints.get(sheet):
            findings += await _llm_check_sheet_by_checkpoints(
                llm=llm, ws_title=sheet, ws=ws,
                checkpoints=checkpoints[sheet],
                attachments_preview=attachments_preview or None,
            )
        # 2) attachment-reference matching
        if attachments_preview:
            findings += _check_attachment_references(sheet, ws, attachments_preview)
        # 3) evidence <-> step consistency
        if attachments_preview:
            findings += await _llm_check_evidence_vs_steps(
                llm=llm, ws_title=sheet, ws=ws,
                attachments_preview=attachments_preview,
            )
        # 4) rule-based procedure-pair checks
        findings += _check_procedure_pairs(sheet, ws)
        # 5) sheet-scope checks
        findings += _check_sheet_scope(sheet, ws)
        # 6) A-C correspondence LLM judgement
        _, ac_findings = await _llm_check_procedure_pairs(
            llm=llm, wb=wb, target_sheets=[sheet],
        )
        findings += ac_findings

    findings_sorted = _sort_findings(findings)

    # LLM re-review of rule-based (non-LLM-tagged) findings
    review = await _llm_review_findings(wb, findings_sorted, llm)

    # Cross-validation + adversarial challenge for P0 / needs_review findings
    cross_issues: Dict[int, List[str]] = {}
    challenge: Dict[int, Optional[str]] = {}
    for idx, f in enumerate(findings_sorted, start=1):
        if f.severity == "P0" or f.needs_review:
            try:
                cross_issues[idx] = _cross_validate_finding(f, wb)
            except Exception:
                cross_issues[idx] = []
            if f.severity == "P0":
                ws = wb[f.sheet] if f.sheet in wb.sheetnames else None
                ctx = _build_minimal_context(f, ws)
                challenge[idx] = await _challenge_finding_with_llm(
                    llm=llm, finding=f, minimal_context=ctx,
                )

    out: List[dict] = []
    for idx, f in enumerate(findings_sorted, start=1):
        d = _finding_to_dict(f)
        if idx in review:
            d.update(review[idx])
        d["cross_validate_issues"] = cross_issues.get(idx, [])
        d["challenge_verdict"] = challenge.get(idx)
        out.append(d)

    stats = {
        "total_findings": len(out),
        "by_severity": _counts_by(out, "severity"),
        "by_status": _counts_by(out, "status"),
        "by_risk_type": _counts_by(out, "risk_type"),
        "llm_call_stats": {k: dict(v) for k, v in LLM_CALL_STATS.items()},
    }
    return out, stats


def _counts_by(items: List[dict], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for it in items:
        k = str(it.get(key, "") or "")
        counts[k] = counts.get(k, 0) + 1
    return counts
