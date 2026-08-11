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
# Common audit verb phrases that appear right before `《doc》` references.
# When matched, the doc reference is more likely to mean an evidence document.
_DOC_REF_HINT_RE = re.compile(r"《([^》]+?)》")


def _build_doc_to_media_map(attachments):
    """Map a document-name stem to its embedded-media paths.

    The V1 LLM often writes generic titles like `《SAP系统密码策略》` while the
    attachment index stores concrete files such as `sap应用系统密码策略.docx`.
    Resolution first tries exact/substring matches, then falls back to token
    overlap so generic titles can still be linked to their screenshots.
    Keys are lowercased for case-insensitive matching.
    """
    if not attachments:
        return {}
    items = attachments.get("items", []) or []
    by_stem = {}
    for it in items:
        rel = getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path", "")
        if not rel or not rel.startswith(".embedded_media/"):
            continue
        after = rel[len(".embedded_media/"):]
        if "::" not in after:
            continue
        source_doc, _media = after.split("::", 1)
        for stem_candidate in (source_doc, source_doc.rsplit(".", 1)[0] if "." in source_doc else source_doc):
            by_stem.setdefault(stem_candidate.lower(), []).append(rel)
    return by_stem


_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def _token_set(text: str):
    """Case-folded token set for fuzzy doc-name matching.

    Alphanumeric runs (2+) are kept as words; CJK text is represented as
    character bigrams so that partial overlaps like `系统密码策略` work
    without requiring a full segmenter.
    """
    text = str(text or "").lower()
    tokens = set(_TOKEN_RE.findall(text))
    chars = list(text)
    for i in range(len(chars) - 1):
        a, b = chars[i], chars[i + 1]
        if "一" <= a <= "鿿" or "一" <= b <= "鿿":
            tokens.add(a + b)
    return tokens


def _resolve_doc_name_to_media(doc_name, doc_to_media):
    """Resolve a referenced document name to embedded-media paths.

    Resolution order:
    1. Exact lowercased match.
    2. Bidirectional substring match.
    3. Token-overlap fallback (score >= 0.5, top 3 stems).
    """
    if not doc_name or not doc_to_media:
        return []
    norm = doc_name.lower()
    if norm in doc_to_media:
        return list(doc_to_media[norm])
    for stem, paths in doc_to_media.items():
        if norm in stem or stem in norm:
            return list(paths)

    doc_tokens = _token_set(doc_name)
    if not doc_tokens:
        return []

    scored = []
    for stem, paths in doc_to_media.items():
        stem_tokens = _token_set(stem)
        if not stem_tokens:
            continue
        score = len(doc_tokens & stem_tokens) / max(len(doc_tokens), len(stem_tokens))
        if score >= 0.5:
            scored.append((score, paths))

    scored.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    result = []
    for _score, paths in scored[:3]:
        for p in paths:
            if p not in seen:
                seen.add(p)
                result.append(p)
    return result


def _backfill_embedded_evidence_refs(findings_dicts, attachments=None):
    """Lift attachment paths into `evidence_refs[].attachment`.

    Searches across `basis`, `snippet`, and any excerpts recorded in
    `llm_evidence_refs`. Direct paths (`.embedded_media/...`, `审计证据/...`)
    are lifted as-is; `《...》` document references are resolved to embedded
    media via token overlap.

    For embedded-media paths we also lift a short excerpt from the cached OCR
    text so the UI's evidence panel can render what was actually read, even
    when the agent's structured citation was rejected by validation.

    Cheap post-process; doesn't change the LLM's findings text, only fills
    the structural `evidence_refs` fields so the UI can render what was
    actually inspected.
    """
    if not findings_dicts:
        return findings_dicts
    doc_to_media = _build_doc_to_media_map(attachments)
    ocr_cache = (attachments or {}).get("ocr_by_path") or {}

    def _text_sources(fnd):
        for key in ("basis", "snippet"):
            v = fnd.get(key) or ""
            if v:
                yield str(v)
        llm_refs = fnd.get("llm_evidence_refs")
        if isinstance(llm_refs, str) and llm_refs.strip():
            try:
                llm_refs = json.loads(llm_refs)
            except Exception:
                llm_refs = None
        if isinstance(llm_refs, list):
            for lr in llm_refs:
                if isinstance(lr, dict):
                    for key in ("excerpt", "attachment"):
                        v = lr.get(key) or ""
                        if v:
                            yield str(v)

    def _ocr_excerpt(rel_path: str, fallback_text: str) -> str:
        """Pick a brief excerpt from the OCR cache for an embedded-media path."""
        candidates: List[str] = []
        key = rel_path.lower()
        cached = ocr_cache.get(key)
        if isinstance(cached, dict) and str(cached.get("status", "")).lower() == "ok":
            candidates.append(str(cached.get("content", "") or ""))
        # The cache key uses "::" while the path uses "__" in some backends.
        if "::" in key:
            candidates.append(ocr_cache.get(key.replace("::", "__")) or "")
        for raw in candidates:
            if raw:
                excerpt = _extract_excerpt(raw, fallback_text)
                if excerpt:
                    return excerpt
        return ""

    def _ocr_full_text(rel_path: str) -> str:
        """Return the full OCR text for an embedded-media path, or empty string."""
        candidates: List[str] = []
        key = rel_path.lower()
        cached = ocr_cache.get(key)
        if isinstance(cached, dict) and str(cached.get("status", "")).lower() == "ok":
            candidates.append(str(cached.get("content", "") or ""))
        if "::" in key:
            candidates.append(ocr_cache.get(key.replace("::", "__")) or "")
        for raw in candidates:
            if raw:
                return raw
        return ""

    def _attachment_extracted_text(rel_path: str) -> str:
        """Return the directly-extracted text for a real attachment from the index."""
        if not attachments:
            return ""
        items = attachments.get("items") or []
        target = str(rel_path or "").strip().lower().replace("\\", "/")
        for item in items:
            if not item:
                continue
            rel = str(getattr(item, "rel_path", "") or "").lower().replace("\\", "/")
            if rel == target:
                text = str(getattr(item, "extracted_text", "") or "").strip()
                if text:
                    return text
        return ""

    def _extract_excerpt(content: str, hint: str, limit: int = 240) -> str:
        """Return a single-line excerpt around the hint, or the first line."""
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        hint = str(hint or "").strip()
        if hint:
            position = text.find(hint)
            if position < 0:
                # Try a 12+ char substring of the hint to tolerate punctuation.
                for size in (24, 16, 12):
                    snippet = hint[:size]
                    if not snippet:
                        continue
                    position = text.find(snippet)
                    if position >= 0:
                        break
            if position >= 0:
                start = max(0, position - 60)
                end = min(len(text), position + limit - 60)
                return text[start:end].strip()
        return text[:limit].strip()

    for fnd in findings_dicts:
        refs = fnd.get("evidence_refs") or []
        existing = {str(r.get("attachment") or "") for r in refs}
        snippet_hint = str(fnd.get("snippet") or "")
        new_paths: List[Tuple[str, str]] = []
        for text in _text_sources(fnd):
            for m in _EMBEDDED_RE.findall(text):
                p = m.rstrip(".,;，。，")
                if p and p not in existing and not any(np[0] == p for np in new_paths):
                    new_paths.append((p, text))
            for m in _REAL_ATTACH_RE.findall(text):
                p = m.rstrip(".,;，。，")
                if p and p not in existing and not any(np[0] == p for np in new_paths):
                    new_paths.append((p, text))
            for m in _DOC_REF_HINT_RE.finditer(text):
                doc_name = m.group(1).strip()
                if not doc_name or len(doc_name) < 2:
                    continue
                for p in _resolve_doc_name_to_media(doc_name, doc_to_media):
                    if p not in existing and not any(np[0] == p for np in new_paths):
                        new_paths.append((p, text))

        # Topic-based association: even when a finding doesn't literally mention
        # an embedded-media path or a 《doc》 reference, attach any screenshot
        # whose source document name **contains a distinctive compound term**
        # from the finding's text. We avoid bag-of-bigrams matching because
        # generic terms like 「策略」 or 「系统」 would otherwise pull in
        # unrelated docs (备份策略.docx, SAP系统周巡检报告.docx).
        topic_text_parts: List[str] = []
        for key in ("basis", "snippet", "issue_type", "risk_type"):
            v = fnd.get(key)
            if v:
                topic_text_parts.append(str(v))
        llm_reasons = fnd.get("llm_reasons")
        if isinstance(llm_reasons, str) and llm_reasons.strip():
            try:
                parsed_reasons = json.loads(llm_reasons)
                if isinstance(parsed_reasons, list):
                    topic_text_parts.extend(str(r) for r in parsed_reasons)
            except Exception:
                pass
        topic_text = " ".join(topic_text_parts)
        # Extract distinctive compound keywords (3+ CJK chars) from the finding
        # text. These are real terms like 「密码策略」 / 「操作系统」 / 「SAP数据库」
        # — generic 2-char bigrams like 「策略」 / 「设置」 are deliberately
        # excluded so unrelated docs aren't pulled in.
        compound_keywords: set[str] = set()
        if topic_text:
            text = str(topic_text)
            for size in (4, 3):
                i = 0
                while i + size <= len(text):
                    chunk = text[i:i + size]
                    if all("一" <= ch <= "鿿" for ch in chunk):
                        compound_keywords.add(chunk)
                    i += 1
        if compound_keywords:
            # Restrict to compound keywords that contain a topic-distinctive
            # term. Generic 3-char chunks like 「配置及」「置截图」 appear in
            # nearly every docx filename and would otherwise pull in unrelated
            # docs (服务器的安装/防病毒/防火墙).
            domain_terms = (
                "密码", "口令", "验证", "身份", "鉴权", "授权",
                "安全", "登录", "锁定", "失败", "会话",
                "策略", "参数", "配置", "密码策", "登录失败",
                "应用", "操作", "数据库", "系统", "OS",
            )
            specific_kws = {
                kw for kw in compound_keywords
                if any(term in kw for term in domain_terms)
            }
            for stem, paths in doc_to_media.items():
                stem_lower = stem.lower()
                hit = False
                for kw in specific_kws:
                    if kw in stem_lower or stem_lower in kw:
                        hit = True
                        break
                if not hit:
                    continue
                for p in paths:
                    if p in existing or any(np[0] == p for np in new_paths):
                        continue
                    new_paths.append((p, topic_text))
        for p, source_text in new_paths:
            excerpt = ""
            full_text = ""
            attachment_text = ""
            if p.startswith(".embedded_media/"):
                excerpt = _ocr_excerpt(p, source_text)
                full_text = _ocr_full_text(p)
            else:
                attachment_text = _attachment_extracted_text(p)
                if attachment_text:
                    excerpt = _extract_excerpt(attachment_text, source_text, limit=240)
            new_ref = {
                "sheet": fnd.get("sheet"),
                "cell_or_range": "",
                "attachment": p,
                "excerpt": excerpt or snippet_hint[:240],
            }
            if full_text:
                new_ref["full_text"] = full_text
            if attachment_text:
                new_ref["attachment_text"] = attachment_text
            refs.append(new_ref)
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

    # Lift attachment paths into evidence_refs[].attachment / full_text /
    # attachment_text BEFORE the reviewer runs so it can see the actual OCR
    # content for each finding rather than guessing from cell text alone.
    pre_review_dicts: List[dict] = []
    for fnd in findings_sorted:
        d = _finding_to_dict(fnd)
        pre_review_dicts.append(d)
    _backfill_embedded_evidence_refs(pre_review_dicts, attachments)
    # Mirror the backfilled refs onto the Finding objects so the reviewer (which
    # consumes Finding instances, not dicts) sees the same content.
    for fnd, d in zip(findings_sorted, pre_review_dicts):
        refs = d.get("evidence_refs") or []
        if refs:
            object.__setattr__(
                fnd, "evidence_refs", json.dumps(refs, ensure_ascii=False)
            )

    # LLM re-review of rule-based (non-LLM-tagged) findings
    _emit_progress(on_progress, "findings_review", "", findings, "进入发现复核")
    review = await _llm_review_findings(wb, findings_sorted, llm, attachments=attachments)

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
    # structured `evidence_refs[].attachment` field. Also resolve document
    # names like `《SAP系统密码策略》` to their underlying embedded-media
    # paths via the attachment index, so the UI's evidence panel can render
    # what was actually inspected.
    _backfill_embedded_evidence_refs(out, attachments)

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
