"""Finding validation, repair and evidence-ref verification (ported from analyze_excel.py).

No jsonschema dependency: the schema is enforced by hand here.
"""
import re
from typing import Any, Collection, List, Optional, Tuple

from review.models import (
    _EXCERPT_CONSTRUCTED_MARKER,
    _EXCERPT_MAX_LEN,
    _SEVERITY_FROM_CHINESE,
)

_VALID_STATUSES = {"pass", "fail", "unknown"}
_VALID_SEVERITIES = {"P0", "P1", "P2"}
_VALID_RISK_TYPES = {"覆盖性", "一致性", "证据不足", "方法性", "逻辑性", "跨字段一致性"}
_VALID_CLAIM_TYPES = {
    "workpaper_text",
    "attachment_presence",
    "attachment_content",
    "period_date",
    "configuration_value",
    "population_coverage",
    "record_consistency",
}

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w一-鿿]+", re.UNICODE)


def _excerpt_matches(excerpt: str, actual_text: str) -> bool:
    """Check if excerpt is a substring of actual_text after normalisation."""
    norm_ex = _PUNCT_RE.sub("", _WS_RE.sub("", excerpt or "")).lower()
    norm_at = _PUNCT_RE.sub("", _WS_RE.sub("", actual_text or "")).lower()
    if not norm_ex or not norm_at:
        return False
    return norm_ex in norm_at


def _validate_finding_result(
    obj: Any, *, allowed_assertion_ids: Collection[str] | None = None
) -> Tuple[bool, List[str]]:
    """Validate a single finding dict. Returns (valid, errors).

    Beyond shape checks, enforces:
    - status == "fail" => evidence_refs non-empty
    - status == "unknown" => unknown_reason non-empty and >= 10 chars
    - status != "pass" => severity and risk_type required
    """
    if not isinstance(obj, dict):
        return False, ["result is not a dict"]
    errors: List[str] = []

    status = str(obj.get("status", "")).strip()
    if status not in _VALID_STATUSES:
        errors.append(f"status must be one of {sorted(_VALID_STATUSES)}; got {status!r}")

    conclusion = str(obj.get("conclusion", "")).strip()
    if len(conclusion) < 4:
        errors.append("conclusion must be a string of >= 4 chars")

    refs = obj.get("evidence_refs")
    if not isinstance(refs, list):
        errors.append("evidence_refs must be an array")

    sev = str(obj.get("severity", "")).strip()
    if sev and sev not in _VALID_SEVERITIES:
        errors.append(f"severity must be one of {sorted(_VALID_SEVERITIES)}; got {sev!r}")

    risk = str(obj.get("risk_type", "")).strip()
    if risk and risk not in _VALID_RISK_TYPES:
        errors.append(f"risk_type must be one of {sorted(_VALID_RISK_TYPES)}; got {risk!r}")

    assertion_id = obj.get("assertion_id")
    if assertion_id is not None and not str(assertion_id).strip():
        errors.append("assertion_id must be non-empty when supplied")
    if assertion_id is not None and allowed_assertion_ids is not None:
        allowed = {str(value).strip() for value in allowed_assertion_ids}
        if str(assertion_id).strip() not in allowed:
            errors.append("assertion_id is not in the producer allow-list")
    claim_type = str(obj.get("claim_type", "")).strip()
    if claim_type and claim_type not in _VALID_CLAIM_TYPES:
        errors.append(
            f"claim_type must be one of {sorted(_VALID_CLAIM_TYPES)}; got {claim_type!r}"
        )
    for key in ("claim_subject", "claim_value"):
        value = obj.get(key)
        if value is not None and len(str(value)) > 500:
            errors.append(f"{key} must be at most 500 characters")

    if status == "fail":
        if not isinstance(refs, list) or len(refs) == 0:
            errors.append("status=fail but evidence_refs is empty")
    if status == "unknown":
        reason = str(obj.get("unknown_reason", "")).strip()
        if len(reason) < 10:
            errors.append("status=unknown but unknown_reason is empty or <10 chars")
    if status != "pass":
        if not sev:
            errors.append("status!=pass but severity is missing")
        if not risk:
            errors.append("status!=pass but risk_type is missing")

    return (len(errors) == 0, errors)


def _repair_finding_result(obj: Any) -> Optional[dict]:
    """Attempt to fix common issues in a finding dict. Returns repaired dict or None."""
    if not isinstance(obj, dict):
        return None
    repaired = dict(obj)

    # --- status migration: legacy Chinese -> pass/fail/unknown ---
    old_status = str(repaired.get("status", "")).strip()
    if old_status == "无问题":
        repaired["status"] = "pass"
    elif old_status == "有问题":
        repaired["status"] = "fail"
    elif old_status == "不确定":
        repaired["status"] = "unknown"
    status = repaired.get("status", "fail")

    # --- severity migration: 高/中/低 -> P0/P1/P2 ---
    sev = str(repaired.get("severity", "")).strip()
    if sev in _SEVERITY_FROM_CHINESE:
        repaired["severity"] = _SEVERITY_FROM_CHINESE[sev]
    elif sev not in ("P0", "P1", "P2", ""):
        repaired["severity"] = "P1"
    if status != "pass" and not repaired.get("severity"):
        repaired["severity"] = "P1"

    # --- conclusion: derive from basis if missing ---
    if not repaired.get("conclusion"):
        basis = str(repaired.get("basis", "")).strip()
        if basis:
            repaired["conclusion"] = basis[:200]
        else:
            repaired["conclusion"] = f"发现{status}类问题"

    # --- evidence_refs: construct from related_cells + snippet if missing ---
    refs = repaired.get("evidence_refs")
    constructed_from_fallback = False
    if not isinstance(refs, list) or not refs:
        constructed: List[dict] = []
        related = repaired.get("related_cells") or repaired.get("cell") or ""
        if isinstance(related, list):
            cells = related
        elif isinstance(related, str):
            cells = [c.strip() for c in re.split(r"[,;，；\s]+", related) if c.strip()]
        else:
            cells = []
        snippet_text = str(repaired.get("snippet", "") or repaired.get("basis", "")).strip()
        for c in cells:
            ref: dict = {"cell_or_range": c}
            if snippet_text:
                ref["excerpt"] = snippet_text[:_EXCERPT_MAX_LEN]
            constructed.append(ref)
        if not constructed and snippet_text:
            constructed.append({"cell_or_range": "", "excerpt": snippet_text[:_EXCERPT_MAX_LEN]})
        constructed_from_fallback = bool(constructed)
        if constructed_from_fallback:
            for ref in constructed:
                if isinstance(ref, dict) and ref.get("cell_or_range"):
                    ref["cell_or_range"] = str(ref.get("cell_or_range", "")) + _EXCERPT_CONSTRUCTED_MARKER
        repaired["evidence_refs"] = constructed

    # --- fail with empty evidence_refs => downgrade to unknown ---
    if repaired.get("status") == "fail":
        refs = repaired.get("evidence_refs") or []
        if not isinstance(refs, list) or len(refs) == 0:
            repaired["status"] = "unknown"
            repaired["unknown_reason"] = "无法引用原始证据佐证该判定，降级为不确定"
            repaired["severity"] = "P2"
            status = "unknown"

    # --- risk_type: default if missing ---
    if status != "pass" and not repaired.get("risk_type"):
        repaired["risk_type"] = "证据不足"

    # --- unknown_reason: auto-generate if missing ---
    if status == "unknown":
        reason = str(repaired.get("unknown_reason", "")).strip()
        if len(reason) < 10:
            repaired["unknown_reason"] = "LLM未说明不确定原因：需要补充更多信息以判定"

    # --- reasons: derive from basis if missing ---
    if not repaired.get("reasons"):
        basis = str(repaired.get("basis", "")).strip()
        if basis:
            repaired["reasons"] = [basis[:300]]
        else:
            repaired["reasons"] = [repaired.get("conclusion", "")]

    # --- fix_suggestion: derive from suggestion if missing ---
    if not repaired.get("fix_suggestion"):
        sug = str(repaired.get("suggestion", "")).strip()
        if sug:
            repaired["fix_suggestion"] = {"supplement_explanation": sug[:300]}
        else:
            repaired["fix_suggestion"] = {}

    return repaired


def _validate_llm_results(
    results_list: List[Any], *, allowed_assertion_ids: Collection[str] | None = None
) -> Tuple[List[dict], bool]:
    """Validate and repair a list of finding dicts.

    Returns (valid_results, needs_retry). If any result is unrepairable,
    needs_retry=True.
    """
    valid: List[dict] = []
    needs_retry = False
    allowed = (
        {str(value).strip() for value in allowed_assertion_ids}
        if allowed_assertion_ids is not None
        else None
    )
    for obj in results_list:
        if not isinstance(obj, dict):
            needs_retry = True
            continue
        ok, _ = _validate_finding_result(
            obj, allowed_assertion_ids=allowed_assertion_ids
        )
        if ok:
            valid.append(obj)
        else:
            repaired = _repair_finding_result(obj)
            if repaired is not None:
                # A model may not create a semantic assertion. Preserve the
                # review result, but replace an unapproved identifier with the
                # explicit human-review fallback instead of dropping the
                # entire finding after the final retry.
                supplied_assertion = str(repaired.get("assertion_id", "")).strip()
                if allowed is not None and supplied_assertion and supplied_assertion not in allowed:
                    repaired = dict(repaired)
                    if "finding.unclassified" in allowed:
                        repaired["assertion_id"] = "finding.unclassified"
                    else:
                        repaired.pop("assertion_id", None)
                ok2, _ = _validate_finding_result(
                    repaired, allowed_assertion_ids=allowed
                )
                if ok2:
                    valid.append(repaired)
                else:
                    needs_retry = True
            else:
                needs_retry = True
    return valid, needs_retry


def _verify_evidence_refs(evidence_refs: List[dict], ws) -> List[dict]:
    """Verify evidence_refs excerpts match actual cell text; repair or drop.

    Constructed refs (marker suffix) are preserved as-is.
    """
    if not ws:
        return evidence_refs
    verified: List[dict] = []
    for ref in evidence_refs:
        if not isinstance(ref, dict):
            continue
        cell = ref.get("cell_or_range", "")
        excerpt = ref.get("excerpt", "")
        if _EXCERPT_CONSTRUCTED_MARKER in str(cell):
            verified.append(ref)
            continue
        clean_ref = str(cell).replace(_EXCERPT_CONSTRUCTED_MARKER, "").strip()
        try:
            ws_cell = ws[clean_ref] if clean_ref else None
            val = ws_cell.value if ws_cell is not None else None
        except Exception:
            val = None
        actual_text = str(val).strip() if val is not None else ""
        if actual_text and _excerpt_matches(excerpt, actual_text):
            verified.append(ref)
        elif actual_text:
            verified.append({**ref, "excerpt": actual_text[:_EXCERPT_MAX_LEN]})
        # else: cell invalid or empty -> drop
    return verified
