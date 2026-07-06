"""LLM re-review of rule-based findings (ported from analyze_excel.py, async)."""
import asyncio
import json
from typing import Dict, List, Sequence

from review.excel_utils import _truncate
from review.llm import _llm_request_json_list, _llm_stat
from review.models import Finding


def _safe_cell_text(value, limit: int = 30000) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) > limit:
        return s[:limit] + "..."
    return s


def _extract_context_cells(ws, keywords: Sequence[str], limit: int = 8) -> List[tuple]:
    from review.excel_utils import _extract_sheet_text_cells
    if not keywords:
        return []
    hits: List[tuple] = []
    for coord, text in _extract_sheet_text_cells(ws):
        if any(k and k in text for k in keywords):
            hits.append((coord, _truncate(text, 220)))
            if len(hits) >= limit:
                break
    return hits


async def _llm_review_findings(
    wb,
    findings_sorted: Sequence[Finding],
    llm,
    batch_size: int = 6,
    sleep_seconds: float = 0.2,
) -> Dict[int, Dict[str, str]]:
    selected: List[tuple] = []
    for idx, item in enumerate(findings_sorted, start=1):
        if str(item.issue_type or "").startswith("LLM判定："):
            continue
        selected.append((idx, item))
    results: Dict[int, Dict[str, str]] = {}
    if not selected:
        return results

    from review.checkpoints import _extract_checkpoint_keywords

    def _mk_item_payload(index_1_based: int, item: Finding) -> dict:
        keywords = _extract_checkpoint_keywords(item.snippet) if item.issue_type == "检查要点覆盖不足" else []
        context_cells: List[tuple] = []
        if item.sheet in wb.sheetnames and keywords:
            context_cells = _extract_context_cells(wb[item.sheet], keywords=keywords, limit=8)
        return {
            "id": index_1_based,
            "issue_type": item.issue_type,
            "rule_severity": item.severity,
            "sheet": item.sheet,
            "cell": item.cell or "",
            "excerpt": _safe_cell_text(item.snippet, 1200),
            "rule_basis": _safe_cell_text(item.basis, 1200),
            "rule_suggestion": _safe_cell_text(item.suggestion, 1200),
            "checkpoint_keywords": keywords,
            "context_cells": [{"cell": c, "text": t} for c, t in context_cells],
        }

    system_prompt = (
        "你是一名严格的IT审计/财务审计质量复核专家。\n"
        "你将收到一组“规则/启发式”识别的问题点（每条含：问题类型、严重级别、Sheet/单元格定位、原文摘录、判定依据、整改建议，以及可能的上下文单元格）。\n"
        "你的任务：逐条复核其是否成立、风险影响、需要补充的证据/程序、以及更合适的整改建议。\n"
        "要求：\n"
        "1) 不要泛泛而谈，要结合该条的摘录/上下文给出具体可执行建议（证据类型、样本总体/抽样基准、覆盖范围、职责分离、日志/台账/审批/协议等）。\n"
        "2) 如果你认为该条可能误报/信息不足，要明确说明需要补充哪些信息才能判断。\n"
        "3) 输出必须为严格JSON对象，格式为 {\"results\": [...]}。\n"
        "4) results 内每个元素对应输入的id，且必须包含字段：\n"
        "   - id: 整数\n"
        "   - status: \"pass\"/\"fail\"/\"unknown\"\n"
        "   - llm_validity: 成立/不成立/不确定（向后兼容）\n"
        "   - llm_severity: 高/中/低（向后兼容）\n"
        "   - severity: P0/P1/P2（结构化）\n"
        "   - conclusion: 一句话结论\n"
        "   - reasons: 字符串数组，2-5条要点\n"
        "   - evidence_refs: 数组，{sheet, cell_or_range, excerpt}。excerpt必须逐字来自摘录/上下文。fail时必填。\n"
        "   - llm_comment: 字符串（向后兼容）\n"
        "   - llm_missing_evidence: 字符串数组（向后兼容）\n"
        "   - llm_next_actions: 字符串数组（向后兼容）\n"
        "   - risk_type: 覆盖性/一致性/证据不足/方法性/逻辑性/跨字段一致性\n"
        "   - fix_suggestion: {missing_field, supplement_explanation, required_evidence_type}\n"
        "   - unknown_reason: 当status=unknown时必填，≥10字符\n"
        "5) 不要输出Markdown代码块，不要输出多余解释文字。\n"
    )

    for start in range(0, len(selected), max(1, int(batch_size))):
        chunk = selected[start: start + max(1, int(batch_size))]
        payload = [_mk_item_payload(idx, item) for idx, item in chunk]
        user_prompt = (
            "请对以下问题逐条进行复核，给出结构化结论。\n\n"
            f"输入问题（JSON）：\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "请输出严格JSON对象，格式为 {\"results\": [...]}，其中 results 的每个元素必须包含字段：id, llm_validity, llm_severity, llm_comment, llm_missing_evidence, llm_next_actions。\n"
        )

        def _consume_results(objs: List[object]) -> None:
            from review.models import _SEVERITY_FROM_CHINESE
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                idx = obj.get("id")
                if not isinstance(idx, int):
                    continue
                raw_status = str(obj.get("status", "")).strip()
                if raw_status == "成立":
                    status = "fail"
                elif raw_status == "不成立":
                    status = "pass"
                elif raw_status == "不确定":
                    status = "unknown"
                else:
                    status = raw_status or str(obj.get("llm_validity", "")).strip()
                    if not status:
                        lv = str(obj.get("llm_validity", "")).strip()
                        if lv == "成立":
                            status = "fail"
                        elif lv == "不成立":
                            status = "pass"
                        elif lv == "不确定":
                            status = "unknown"
                raw_sev = str(obj.get("severity") or obj.get("llm_severity", "")).strip()
                severity = _SEVERITY_FROM_CHINESE.get(raw_sev, raw_sev)
                raw_refs = obj.get("evidence_refs")
                evidence_refs_list: List[dict] = []
                if isinstance(raw_refs, list) and raw_refs:
                    for ref in raw_refs:
                        if not isinstance(ref, dict):
                            continue
                        evidence_refs_list.append({
                            "sheet": str(ref.get("sheet", "")).strip(),
                            "cell_or_range": str(ref.get("cell_or_range", "")).strip(),
                            "attachment": str(ref.get("attachment", "")).strip(),
                            "excerpt": str(ref.get("excerpt", "")).strip(),
                        })
                reasons_raw = obj.get("reasons", [])
                reasons_list = [str(r).strip() for r in reasons_raw if r] if isinstance(reasons_raw, list) else []
                fix_sug = obj.get("fix_suggestion") or {}
                if not isinstance(fix_sug, dict):
                    fix_sug = {}
                results[idx] = {
                    "llm_validity": str(obj.get("llm_validity", "")).strip(),
                    "llm_severity": str(obj.get("llm_severity", "")).strip(),
                    "llm_comment": str(obj.get("llm_comment", "")).strip(),
                    "llm_missing_evidence": json.dumps(obj.get("llm_missing_evidence", []), ensure_ascii=False),
                    "llm_next_actions": json.dumps(obj.get("llm_next_actions", []), ensure_ascii=False),
                    "llm_status": status,
                    "llm_severity_p": severity,
                    "llm_conclusion": str(obj.get("conclusion", "")).strip(),
                    "llm_reasons": json.dumps(reasons_list, ensure_ascii=False),
                    "llm_evidence_refs": json.dumps(evidence_refs_list, ensure_ascii=False),
                    "llm_risk_type": str(obj.get("risk_type", "")).strip(),
                    "llm_fix_suggestion": json.dumps(fix_sug, ensure_ascii=False),
                    "llm_unknown_reason": str(obj.get("unknown_reason", "")).strip(),
                }

        stage = "review_findings"
        parsed, last_error = await _llm_request_json_list(
            llm=llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stage=stage,
            max_attempts=3,
        )
        if parsed is not None:
            _consume_results(parsed)
        else:
            if len(chunk) > 1:
                _llm_stat(stage, "fallback_single", 1)
                for idx, item in chunk:
                    payload1 = [_mk_item_payload(idx, item)]
                    user_prompt1 = (
                        "请对以下问题逐条进行复核，给出结构化结论。\n\n"
                        f"输入问题（JSON）：\n{json.dumps(payload1, ensure_ascii=False, indent=2)}\n\n"
                        "请输出严格JSON对象，格式为 {\"results\": [...]}。\n"
                    )
                    parsed1, err1 = await _llm_request_json_list(
                        llm=llm, system_prompt=system_prompt, user_prompt=user_prompt1,
                        stage=stage, max_attempts=3,
                    )
                    if parsed1 is not None:
                        _consume_results(parsed1)
                    else:
                        results[idx] = _unknown_review_result(err1)
            else:
                for idx, _ in chunk:
                    results[idx] = _unknown_review_result(last_error)

        if sleep_seconds > 0:
            await asyncio.sleep(float(sleep_seconds))

    return results


def _unknown_review_result(error) -> Dict[str, str]:
    return {
        "llm_validity": "不确定",
        "llm_severity": "",
        "llm_comment": f"LLM调用失败: {error}",
        "llm_missing_evidence": "[]",
        "llm_next_actions": "[]",
        "llm_status": "unknown",
        "llm_severity_p": "P2",
        "llm_conclusion": "LLM调用失败",
        "llm_reasons": "[]",
        "llm_evidence_refs": "[]",
        "llm_risk_type": "",
        "llm_fix_suggestion": "{}",
        "llm_unknown_reason": "LLM调用失败，无法复核",
    }
