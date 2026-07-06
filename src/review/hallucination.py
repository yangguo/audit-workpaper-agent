"""Hallucination-reduction helpers: cross-validation and adversarial challenge.

Ported from analyze_excel.py. _challenge_finding_with_llm is adapted to async
over the project's ChatOpenAI-based llm helper.
"""
import json
import re
from typing import List, Optional

from openpyxl.utils import get_column_letter

from review.excel_utils import _get_cell_text
from review.llm import _llm_chat
from review.validation import _excerpt_matches

_EXCEPTION_FLAG_TOKENS = ("是", "有异常", "Y", "异常", "缺陷", "未通过")


def _cross_validate_finding(finding, wb) -> List[str]:
    """Deterministic cross-checks against the workbook.

    Returns issue codes; empty means no issues found.
    """
    issues: List[str] = []
    sheet = finding.sheet
    cell_refs: List[str] = []
    if finding.cell:
        for c in str(finding.cell).split(","):
            c = c.strip()
            if c:
                cell_refs.append(c)
    try:
        refs = json.loads(finding.evidence_refs) if finding.evidence_refs else []
    except Exception:
        refs = []
    if isinstance(refs, list):
        for r in refs:
            if isinstance(r, dict) and r.get("cell_or_range"):
                cell_refs.append(r["cell_or_range"])

    if not wb or sheet not in wb.sheetnames:
        return issues
    ws = wb[sheet]

    if finding.status == "pass":
        for c in cell_refs:
            txt = _get_cell_text(ws, c)
            if txt and any(tok in txt for tok in _EXCEPTION_FLAG_TOKENS):
                issues.append("exception_flag_contradicts_pass")
                break

    if finding.risk_type == "覆盖性":
        found_sample_size = False
        for row in ws.iter_rows(values_only=False, min_row=1, max_row=min(80, ws.max_row or 80)):
            for c in row:
                if not c.value:
                    continue
                cv = str(c.value)
                if any(k in cv for k in ("样本量", "样本数量", "测试期间样本")):
                    for r in range(c.row, min(c.row + 5, ws.max_row + 1)):
                        for cc in range(c.column, min(c.column + 6, ws.max_column + 1)):
                            v = ws.cell(row=r, column=cc).value
                            if v is not None and str(v).strip() and str(v).strip() not in ("样本量", "样本数量", "测试期间样本"):
                                found_sample_size = True
                                break
                        if found_sample_size:
                            break
                if found_sample_size:
                    break
            if found_sample_size:
                break
        if not found_sample_size:
            issues.append("coverage_claim_but_no_sample_size")

    for r in refs if isinstance(refs, list) else []:
        if not isinstance(r, dict):
            continue
        cell = r.get("cell_or_range", "")
        excerpt = r.get("excerpt", "")
        if cell and excerpt:
            actual = _get_cell_text(ws, cell)
            if actual and not _excerpt_matches(excerpt, actual):
                issues.append("evidence_excerpt_mismatch")
                break

    if finding.status == "fail" and finding.severity == "P0":
        if not refs:
            issues.append("high_severity_no_evidence")

    return issues


def _build_minimal_context(finding, ws, max_chars: int = 2000) -> str:
    """Build a minimal context (500-2000 chars) for an LLM re-review."""
    if not ws:
        return ""
    parts: List[str] = []
    try:
        refs = json.loads(finding.evidence_refs) if finding.evidence_refs else []
    except Exception:
        refs = []
    if not isinstance(refs, list):
        refs = []
    target_cells: List[str] = []
    for r in refs[:6]:
        if isinstance(r, dict) and r.get("cell_or_range"):
            target_cells.append(r["cell_or_range"])
    if not target_cells and finding.cell:
        for c in str(finding.cell).split(","):
            c = c.strip()
            if c:
                target_cells.append(c)
    if not target_cells and finding.snippet:
        hits = re.findall(r"\b[A-Z]{1,3}\d{1,7}\b", finding.snippet)
        target_cells.extend(hits[:3])

    seen_rows: set = set()
    seen_cells: set = set()
    for cell in target_cells[:5]:
        actual = _get_cell_text(ws, cell)
        if actual and cell not in seen_cells:
            parts.append(f"{cell}: {actual[:160]}")
            seen_cells.add(cell)
        m = re.match(r"^([A-Z]+)(\d+)$", cell)
        if not m:
            continue
        col_letters, row_num = m.group(1), int(m.group(2))
        for hdr_row in range(1, 4):
            key = ("hdr", hdr_row)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            for c in range(1, min(ws.max_column + 1, 12)):
                v = ws.cell(row=hdr_row, column=c).value
                if v:
                    parts.append(f"{get_column_letter(c)}{hdr_row}: {str(v)[:80]}")
        for r_off in (-1, 1):
            r = row_num + r_off
            if r < 1 or r > (ws.max_row or 0):
                continue
            key = ("row", r)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            for c in range(1, min(ws.max_column + 1, 10)):
                v = ws.cell(row=r, column=c).value
                if v:
                    parts.append(f"{get_column_letter(c)}{r}: {str(v)[:120]}")

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


async def _challenge_finding_with_llm(*, llm, finding, minimal_context: str) -> Optional[str]:
    """Run a 'challenge' LLM call to verify a P0/needs_review finding.

    Returns "agree" / "disagree" / None on error.
    """
    if not llm or not minimal_context:
        return None
    challenge_prompt = (
        "你是一名严格的审计质量复核专家，正在以质疑者的角度审阅以下复核发现。\n"
        "你的任务：判断该发现是否真实成立，或仅是表面/缺证据/逻辑不严。\n\n"
        f"【finding JSON】\n{finding.basis[:1000]}\n\n"
        f"【相关最小上下文（底稿原文片段）】\n{minimal_context[:1500]}\n\n"
        "请回答：agree（成立）/disagree（不成立/无依据）。只输出一个词。"
    )
    try:
        answer = await _llm_chat(
            llm=llm,
            messages=[
                {"role": "system", "content": "你是审计复核的质疑者。"},
                {"role": "user", "content": challenge_prompt},
            ],
            stage="challenge",
            max_attempts=2,
            max_tokens=64,
        )
        answer = (answer or "").strip().lower()
        if "disagree" in answer or "不同意" in answer or "不成立" in answer:
            return "disagree"
        if "agree" in answer or "同意" in answer or "成立" in answer:
            return "agree"
        return None
    except Exception:
        return None
