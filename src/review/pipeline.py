"""Pipeline orchestration: runs all review stages and merges findings.

Ported from analyze_excel.py's generate_report review core (no xlsx/txt rendering).
"""
import dataclasses
import json
import logging
import os
import re
from typing import Callable, Dict, List, Optional, Tuple

import openpyxl

from review.attachments import _check_attachment_references
from review.checkpoints import _llm_check_sheet_by_checkpoints
from review.evidence_steps import _llm_check_evidence_vs_steps
from review.evidence_agent import investigate_sheet
from review.excel_utils import _detect_layout, _normalize_sheet_id
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

_logger = logging.getLogger("review.pipeline")

_SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def _emit_progress(on_progress, stage: str, current_sheet: str, findings, msg: str) -> None:
    """Best-effort progress report. Never raises — pipeline must not break on a bad callback."""
    if on_progress is None:
        return
    try:
        sev = {"P0": 0, "P1": 0, "P2": 0}
        for f in findings:
            s = getattr(f, "severity", None) or "P2"
            if s not in sev:
                s = "P2"
            sev[s] += 1
        on_progress({
            "stage": stage,
            "current_sheet": current_sheet or "",
            "llm_calls": {k: int(v.get("calls", 0)) for k, v in LLM_CALL_STATS.items()},
            "findings_so_far": {
                "P0": sev["P0"], "P1": sev["P1"], "P2": sev["P2"],
                "total": len(findings),
            },
            "msg": msg,
        })
    except Exception:
        pass


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


_EMBEDDED_RE = re.compile(r"\.embedded_media/[^\s\)\]\}\,\"。，;]+")
_REAL_ATTACH_RE = re.compile(r"(?<![/.])(审计证据/[^\s\)\]\}\,\"。，;]+\.[A-Za-z0-9]+)")


def _backfill_embedded_evidence_refs(findings_dicts: List[dict]) -> List[dict]:
    """Lift attachment paths mentioned in `basis` into `evidence_refs[].attachment`.

    The V1 main review LLM frequently references `.embedded_media/...` paths or
    real attachment paths in the `basis` text, but doesn't always populate the
    structured `evidence_refs[].attachment` field. The UI relies on the
    structured field to render the evidence panel; an empty `attachment`
    leaves the user with no trace of what was actually inspected.

    This pass is a no-op for findings whose evidence_refs already cover every
    path that appears in their basis. It only adds missing entries.
    """
    if not findings_dicts:
        return findings_dicts
    for fnd in findings_dicts:
        basis = fnd.get("basis") or ""
        if not basis:
            continue
        refs = fnd.get("evidence_refs") or []
        existing = {str(r.get("attachment") or "") for r in refs}
        new_paths = []
        for m in _EMBEDDED_RE.findall(basis):
            p = m.rstrip(".,;，。，")
            if p and p not in existing and p not in new_paths:
                new_paths.append(p)
        for m in _REAL_ATTACH_RE.findall(basis):
            p = m.rstrip(".,;，。，")
            if p and p not in existing and p not in new_paths:
                new_paths.append(p)
        for p in new_paths:
            refs.append({
                "sheet": fnd.get("sheet"),
                "cell_or_range": "",
                "attachment": p,
                "excerpt": "",
            })
        if new_paths:
            fnd["evidence_refs"] = refs
    return findings_dicts


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
    attachments: Optional[Dict[str, object]] = None,
    sheets: Optional[str] = None,
    llm,
    attachments_preview: Optional[Dict[str, object]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> Tuple[List[dict], dict]:
    """Run the full review pipeline. Returns (findings_dicts, stats)."""
    checkpoints = checkpoints or {}
    attachments = attachments if attachments is not None else attachments_preview
    attachments = attachments or {}
    filtered = _parse_sheet_filter(sheets)
    warning = ""
    if filtered is None:
        target = list(wb.sheetnames)
    else:
        # Resolve requested names to actual workbook tabs, tolerating the
        # case/dash/space variants an LLM naturally produces (e.g. "pe6" -> "PE-6").
        # _normalize_sheet_id is the same helper attachments/evidence_steps use
        # for sheet-id matching.
        norm_to_actual = {_normalize_sheet_id(s): s for s in wb.sheetnames}
        resolved: List[str] = []
        unmatched: List[str] = []
        seen = set()
        for req in filtered:
            actual = norm_to_actual.get(_normalize_sheet_id(req))
            if actual is None:
                unmatched.append(req)
                continue
            if actual in seen:
                continue
            seen.add(actual)
            resolved.append(actual)
        reviewable = [
            s for s in resolved
            if _detect_layout(wb[s])[0] is not None or checkpoints.get(s)
        ]
        if not reviewable:
            _logger.warning(
                "sheets=%r yielded no reviewable sheets (resolved=%r unmatched=%r); "
                "falling back to all sheets", sheets, resolved, unmatched,
            )
            target = list(wb.sheetnames)
            detail = "无可审阅内容（无审计程序布局/检查要点）" if resolved else "未在底稿中找到"
            warning = f"指定的 Sheet（{sheets}）{detail}，已回退到全部 Sheet。"
        else:
            target = resolved
            if unmatched:
                warning = f"部分指定 Sheet 未匹配：{', '.join(unmatched)}；已审阅：{', '.join(resolved)}。"
    _logger.info(
        "run_review start: sheets_arg=%r target=%r wb_sheets=%r "
        "checkpoints_keys=%r attachment_items=%r warning=%r",
        sheets, target, list(wb.sheetnames),
        list(checkpoints.keys()), len(attachments.get("items", []) if attachments else []),
        warning,
    )

    findings: List[Finding] = []
    agent_stats = {
        "mode": str(os.environ.get("REVIEW_EVIDENCE_AGENT_MODE", "fallback")),
        "runs": 0,
        "tool_calls": 0,
        "accepted_evidence": 0,
        "unresolved": 0,
        "errors": 0,
        "ocr": {"calls": 0, "success": 0, "errors": 0, "timeouts": 0},
        "details": [],
    }
    _emit_progress(on_progress, "starting", "", findings, f"开始审阅，共 {len(target)} 个 sheet")
    for sheet in target:
        if sheet not in wb.sheetnames:
            _logger.info("  sheet=%r skipped (not in workbook)", sheet)
            continue
        ws = wb[sheet]
        _emit_progress(on_progress, "checkpoints", sheet, findings, f"开始处理 {sheet}")
        _logger.info(
            "  sheet=%r cp=%r attachments=%r",
            sheet, bool(checkpoints.get(sheet)), bool(attachments),
        )
        agent_result = await investigate_sheet(ws=ws, attachments=attachments, llm=llm)
        if agent_result.get("status") != "skipped":
            agent_stats["runs"] += 1
            agent_stats["tool_calls"] += int(agent_result.get("tool_calls", 0) or 0)
            agent_stats["accepted_evidence"] += len(agent_result.get("evidence", []) or [])
            agent_stats["unresolved"] += len(agent_result.get("unresolved", []) or [])
            if agent_result.get("status") == "error":
                agent_stats["errors"] += 1
            ocr_result = agent_result.get("ocr") or {}
            if isinstance(ocr_result, dict):
                ocr_stats = agent_stats["ocr"]
                for key in ("calls", "success", "errors", "timeouts"):
                    ocr_stats[key] += int(ocr_result.get(key, 0) or 0)
            evidence = agent_result.get("evidence", []) or []
            agent_stats["details"].append({
                "sheet": sheet,
                "status": agent_result.get("status"),
                "tool_calls": int(agent_result.get("tool_calls", 0) or 0),
                "evidence": list(evidence),
                "unresolved": list(agent_result.get("unresolved", []) or []),
                "tool_trace": list(agent_result.get("tool_trace", []) or []),
                "ocr": dict(ocr_result) if isinstance(ocr_result, dict) else {},
            })
            if evidence:
                by_sheet = attachments.setdefault("agent_evidence_by_sheet", {})
                if isinstance(by_sheet, dict):
                    by_sheet[_normalize_sheet_id(sheet)] = list(evidence)
        # 1) checkpoint-based review
        if checkpoints.get(sheet):
            findings += await _llm_check_sheet_by_checkpoints(
                llm=llm, ws_title=sheet, ws=ws,
                checkpoints=checkpoints[sheet],
                attachments=attachments or None,
                on_progress=lambda stage, msg: _emit_progress(
                    on_progress, "checkpoints", sheet, findings, msg,
                ),
            )
        _emit_progress(on_progress, "checkpoints", sheet, findings, f"完成 {sheet} checkpoint 评审")
        # 2) attachment-reference matching
        if attachments:
            findings += _check_attachment_references(sheet, ws, attachments)
        # 3) evidence <-> step consistency
        if attachments:
            findings += await _llm_check_evidence_vs_steps(
                llm=llm, ws_title=sheet, ws=ws,
                attachments=attachments,
            )
        _emit_progress(on_progress, "evidence_steps", sheet, findings, f"完成 {sheet} 证据-步骤一致性检查")
        # 4) rule-based procedure-pair checks
        findings += _check_procedure_pairs(sheet, ws)
        # 5) sheet-scope checks
        findings += _check_sheet_scope(sheet, ws)
        # 6) A-C correspondence LLM judgement
        _, ac_findings = await _llm_check_procedure_pairs(
            llm=llm, wb=wb, target_sheets=[sheet],
            attachments=attachments,
        )
        findings += ac_findings
        _emit_progress(on_progress, "procedure_pairs", sheet, findings, f"完成 {sheet} 程序配对检查")

    findings_sorted = _sort_findings(findings)

    # LLM re-review of rule-based (non-LLM-tagged) findings
    _emit_progress(on_progress, "findings_review", "", findings, "进入发现复核")
    review = await _llm_review_findings(wb, findings_sorted, llm)

    # Cross-validation + adversarial challenge for P0 / needs_review findings
    cross_issues: Dict[int, List[str]] = {}
    challenge: Dict[int, Optional[str]] = {}
    _emit_progress(on_progress, "hallucination", "", findings_sorted, "进入交叉验证/对抗挑战")
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
    # Lift attachment paths that the V1 LLM cited in `basis` text into the
    # structured `evidence_refs[].attachment` field. Without this, the UI's
    # evidence panel shows empty attachments because the LLM only mentioned
    # `.embedded_media/...` in prose. Cheap post-process; doesn't change findings.
    _backfill_embedded_evidence_refs(out)

    _emit_progress(on_progress, "done", "", findings_sorted, "审阅完成")
    stats = {
        "total_findings": len(out),
        "by_severity": _counts_by(out, "severity"),
        "by_status": _counts_by(out, "status"),
        "by_risk_type": _counts_by(out, "risk_type"),
        "llm_call_stats": {k: dict(v) for k, v in LLM_CALL_STATS.items()},
        "evidence_agent": agent_stats,
        "warning": warning,
    }
    return out, stats


def _counts_by(items: List[dict], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for it in items:
        k = str(it.get(key, "") or "")
        counts[k] = counts.get(k, 0) + 1
    return counts
