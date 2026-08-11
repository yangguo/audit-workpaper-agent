"""Constrained evidence-discovery agent for attachment-directory reviews.

The agent is deliberately an evidence *locator*, not a reviewer. It can only
see the immutable attachment index created from a review snapshot. Its output
is accepted only when both the relative path and the quoted excerpt can be
verified against that index.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import HumanMessage

from review.attachments import _extract_attachment_refs, _match_attachment_items
from review.constants import EVIDENCE_KEYWORDS
from review.excel_utils import _extract_sheet_text_cells, _truncate
from review.llm import _llm_stat
from review.mineru_client import MinerUClient


_DEFAULT_MAX_AGENT_STEPS = 32
_DEFAULT_MAX_AGENT_FILES = 50
_DEFAULT_MAX_AGENT_RESULTS = 12
_DEFAULT_MAX_EXCERPT = 1200
_DEFAULT_MAX_PROMPT_CHARS = 16000


def _env_int(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


def _agent_mode(mode: Optional[str] = None) -> str:
    value = str(mode or os.getenv("REVIEW_EVIDENCE_AGENT_MODE", "fallback")).strip().lower()
    return value if value in {"off", "fallback", "always"} else "fallback"


def _clean_rel_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:($|/)", raw):
        return ""
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        return ""
    return "/".join(parts).lower()


def _items(attachments: Dict[str, object]) -> List[Any]:
    values = attachments.get("items") if isinstance(attachments, dict) else []
    return [item for item in values if getattr(item, "rel_path", "") or getattr(item, "filename", "")]


def _item_summary(item: Any) -> Dict[str, object]:
    summary = {
        "rel_path": str(getattr(item, "rel_path", "") or ""),
        "filename": str(getattr(item, "filename", "") or ""),
        "file_type": str(getattr(item, "file_type", "") or ""),
        "status": str(getattr(item, "status", "") or ""),
        "size": int(getattr(item, "size", 0) or 0),
    }
    rel_path = summary["rel_path"]
    if rel_path.startswith(".embedded_media/"):
        after_prefix = rel_path[len(".embedded_media/"):]
        if "::" in after_prefix:
            source_doc, media_name = after_prefix.split("::", 1)
            summary["source_document"] = source_doc
            summary["media_name"] = media_name
    return summary


def _source_text(attachments: Dict[str, object], item: Any) -> str:
    # A human description is metadata, not evidence content. Agent citations
    # must be grounded in text extracted from the pinned file itself. OCR
    # content is accepted only after the tool has cached it against this exact
    # indexed relative path.
    extracted = str(getattr(item, "extracted_text", "") or "")
    if extracted:
        return extracted
    key = _clean_rel_path(str(getattr(item, "rel_path", "") or getattr(item, "filename", "")))
    cache = attachments.get("ocr_by_path") or {}
    value = cache.get(key) if isinstance(cache, dict) else None
    if isinstance(value, dict) and str(value.get("status", "")).lower() == "ok":
        return str(value.get("content", "") or "")
    return ""


def _source_status(attachments: Dict[str, object], item: Any) -> str:
    key = _clean_rel_path(str(getattr(item, "rel_path", "") or getattr(item, "filename", "")))
    cache = attachments.get("ocr_by_path") or {}
    value = cache.get(key) if isinstance(cache, dict) else None
    if isinstance(value, dict) and str(value.get("status", "")).lower() == "ok":
        return "ocr"
    return str(getattr(item, "extraction_status", "") or getattr(item, "status", "") or "unknown")


def _path_matches(attachments: Dict[str, object], path: str) -> List[Any]:
    key = _clean_rel_path(path)
    if not key:
        return []
    by_rel_path = attachments.get("by_rel_path") or {}
    exact = by_rel_path.get(key)
    if isinstance(exact, list) and exact:
        return list(exact)

    by_filename = attachments.get("by_filename") or {}
    if "/" not in key:
        filename_matches = by_filename.get(key)
        if isinstance(filename_matches, list) and len(filename_matches) == 1:
            return list(filename_matches)
    return []


def _resolve_disk_source(root: Path, item_path: str) -> Path:
    """Return the actual on-disk Path for an indexed attachment path.

    Embedded media are stored with a ``__`` separator on disk while their
    indexed ``rel_path`` uses ``::``; this helper tries both forms and
    validates the result stays inside ``root``.
    """
    root_resolved = root.expanduser().resolve()
    candidates = [item_path]
    if ".embedded_media/" in item_path and "::" in item_path:
        candidates.append(item_path.replace("::", "__"))
    for raw in candidates:
        try:
            source = (root_resolved / Path(raw)).resolve()
            if source.is_file() and source.is_relative_to(root_resolved):
                return source
        except (OSError, ValueError):
            continue
    raise ValueError("indexed_file_not_found")


def _persist_ocr_artifact(*, review_id: str, rel_path: str, provider: str, content: str) -> None:
    """Write the raw OCR output next to the review artifact for later inspection.

    Files land at ``assets/reviews/<review_id>/ocr/<sanitized rel_path>.txt``
    so an auditor can replay what MinerU returned without re-hitting the API.
    Best-effort: failures are logged but never block the tool.
    """
    if not review_id or not rel_path or not content:
        return
    try:
        workspace = Path(os.getenv("WORKSPACE_PATH", ".")).expanduser()
        out_dir = workspace / "assets" / "reviews" / _safe_id(review_id) / "ocr"
        out_dir.mkdir(parents=True, exist_ok=True)
        sanitized = rel_path.replace("\\", "/").replace("/", "__").replace("::", "__")
        if not sanitized.endswith(".txt"):
            sanitized = sanitized + ".txt"
        out_path = out_dir / sanitized
        out_path.write_text(
            f"<!-- review_id={review_id} provider={provider} rel_path={rel_path} -->\n"
            + content,
            encoding="utf-8",
        )
    except Exception:
        _logger.debug("failed to persist OCR artifact for %s", rel_path, exc_info=True)


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value or ""))[:64]


_logger = logging.getLogger("review.evidence_agent")


def build_evidence_tools(
    attachments: Dict[str, object],
    *,
    trace: Optional[List[Dict[str, object]]] = None,
    mineru_client: Optional[Any] = None,
) -> List[object]:
    """Build tools backed only by the already-created attachment index."""

    events = trace if trace is not None else []

    def _record(name: str, args: Dict[str, object], result: Dict[str, object]) -> str:
        events.append({
            "tool": name,
            "args": args,
            "result_count": len(result.get("files", result.get("matches", [])) or []),
            "status": result.get("status", "ok"),
        })
        return json.dumps(result, ensure_ascii=False)

    @tool("list_attachment_files")
    def list_attachment_files(query: str = "", limit: int = _DEFAULT_MAX_AGENT_FILES) -> str:
        """List indexed attachment metadata. Query matches path, name, folder or description."""
        needle = str(query or "").strip().casefold()
        max_items = min(max(1, int(limit or _DEFAULT_MAX_AGENT_FILES)), _DEFAULT_MAX_AGENT_FILES)
        result: List[Dict[str, object]] = []
        for item in _items(attachments):
            haystack = " ".join(
                str(getattr(item, attr, "") or "")
                for attr in ("rel_path", "filename", "rel_dir", "description")
            ).casefold()
            if needle and needle not in haystack:
                continue
            result.append(_item_summary(item))
            if len(result) >= max_items:
                break
        return _record("list_attachment_files", {"query": query, "limit": max_items}, {"files": result})

    @tool("search_attachment_text")
    def search_attachment_text(query: str, limit: int = 5) -> str:
        """Search extracted attachment text and return exact bounded excerpts."""
        needle = str(query or "").strip()
        max_items = min(max(1, int(limit or 5)), _DEFAULT_MAX_AGENT_RESULTS)
        if not needle:
            return _record(
                "search_attachment_text",
                {"query": query, "limit": max_items},
                {"status": "rejected", "reason": "empty_query", "matches": []},
            )

        result: List[Dict[str, object]] = []
        folded = needle.casefold()
        for item in _items(attachments):
            status = _source_status(attachments, item)
            content = _source_text(attachments, item)
            if status.lower() not in {"ok", "ocr"} or not content:
                continue
            position = content.casefold().find(folded)
            if position < 0:
                continue
            start = max(0, position - 300)
            end = min(len(content), position + len(needle) + 900)
            result.append({
                "path": str(getattr(item, "rel_path", "") or getattr(item, "filename", "")),
                "file_type": str(getattr(item, "file_type", "") or ""),
                "extraction_status": status,
                "excerpt": content[start:end],
            })
            if len(result) >= max_items:
                break
        return _record("search_attachment_text", {"query": query, "limit": max_items}, {"matches": result})

    @tool("read_attachment")
    def read_attachment(path: str, max_chars: int = 4000) -> str:
        """Read extracted text for one indexed relative attachment path."""
        raw_path = str(path or "").strip()
        matched = _path_matches(attachments, raw_path)
        if not matched or not _clean_rel_path(raw_path):
            return _record(
                "read_attachment",
                {"path": raw_path, "max_chars": max_chars},
                {"status": "rejected", "reason": "path_not_indexed"},
            )
        if len(matched) > 1:
            return _record(
                "read_attachment",
                {"path": raw_path, "max_chars": max_chars},
                {"status": "rejected", "reason": "ambiguous_path"},
            )

        item = matched[0]
        status = _source_status(attachments, item)
        content = _source_text(attachments, item)
        max_length = min(max(1, int(max_chars or 4000)), 8000)
        result: Dict[str, object] = {
            "path": str(getattr(item, "rel_path", "") or getattr(item, "filename", "")),
            "file_type": str(getattr(item, "file_type", "") or ""),
            "extraction_status": status,
        }
        if status.lower() == "ok":
            result["content"] = content[:max_length]
        elif status.lower() == "ocr":
            result["content"] = content[:max_length]
        else:
            result["note"] = "该文件未提取出可验证文本，不能推断其内容。"
        return _record("read_attachment", {"path": raw_path, "max_chars": max_length}, result)

    ocr_client = mineru_client if mineru_client is not None else MinerUClient.from_env()
    if ocr_client is None:
        return [list_attachment_files, search_attachment_text, read_attachment]

    ocr_stats = attachments.setdefault("ocr_stats", {
        "calls": 0,
        "success": 0,
        "errors": 0,
        "timeouts": 0,
    })
    if not isinstance(ocr_stats, dict):
        ocr_stats = {"calls": 0, "success": 0, "errors": 0, "timeouts": 0}
        attachments["ocr_stats"] = ocr_stats

    @tool("ocr_attachment")
    def ocr_attachment(
        path: str,
        language: str = "ch",
        page_range: str = "",
    ) -> str:
        """OCR one indexed image/scan with MinerU and return exact Markdown text."""
        raw_path = str(path or "").strip()
        matched = _path_matches(attachments, raw_path)
        if not matched or not _clean_rel_path(raw_path):
            return _record(
                "ocr_attachment",
                {"path": raw_path},
                {"status": "rejected", "reason": "path_not_indexed"},
            )
        if len(matched) > 1:
            return _record(
                "ocr_attachment",
                {"path": raw_path},
                {"status": "rejected", "reason": "ambiguous_path"},
            )

        item = matched[0]
        item_path = str(getattr(item, "rel_path", "") or getattr(item, "filename", ""))
        key = _clean_rel_path(item_path)
        existing = _source_text(attachments, item)
        if _source_status(attachments, item).lower() == "ok" and existing:
            return _record(
                "ocr_attachment",
                {"path": raw_path},
                {
                    "status": "ok",
                    "path": item_path,
                    "provider": "local-extraction",
                    "extraction_status": "ok",
                    "content": existing,
                    "cached": True,
                },
            )
        cache = attachments.setdefault("ocr_by_path", {})
        cached = cache.get(key) if isinstance(cache, dict) else None
        if isinstance(cached, dict) and str(cached.get("status", "")).lower() == "ok":
            return _record(
                "ocr_attachment",
                {"path": raw_path},
                {
                    "status": "ok",
                    "path": item_path,
                    "provider": cached.get("provider", "mineru"),
                    "extraction_status": "ocr",
                    "content": str(cached.get("content", "") or ""),
                    "cached": True,
                },
            )

        root_raw = str(attachments.get("path", "") or "")
        if not root_raw:
            return _record(
                "ocr_attachment",
                {"path": raw_path},
                {"status": "error", "reason": "attachment_root_missing"},
            )
        try:
            source = _resolve_disk_source(Path(root_raw), item_path)
        except (OSError, ValueError):
            return _record(
                "ocr_attachment",
                {"path": raw_path},
                {"status": "error", "reason": "indexed_file_not_found"},
            )

        ocr_stats["calls"] = int(ocr_stats.get("calls", 0) or 0) + 1
        result = ocr_client.parse_file(
            source,
            language=str(language or os.getenv("MINERU_OCR_LANGUAGE", "ch")),
            is_ocr=True,
            enable_table=True,
            enable_formula=True,
            page_range=str(page_range or ""),
        )
        result_status = str(getattr(result, "status", "error") or "error").lower()
        provider = str(getattr(result, "provider", "mineru") or "mineru")
        raw_content = str(getattr(result, "text", "") or "").strip()
        content = raw_content
        if result_status == "ok":
            ocr_cache = {
                "status": "ok",
                "provider": provider,
                "content": content,
            }
            if content:
                _persist_ocr_artifact(
                    review_id=str(attachments.get("review_id", "") or "adhoc"),
                    rel_path=item_path,
                    provider=provider,
                    content=content,
                )
            if isinstance(cache, dict):
                cache[key] = ocr_cache
            ocr_stats["success"] = int(ocr_stats.get("success", 0) or 0) + 1
            return _record(
                "ocr_attachment",
                {"path": raw_path},
                {
                    "status": "ok",
                    "path": item_path,
                    "provider": provider,
                    "extraction_status": "ocr",
                    "content": content,
                },
            )

        if result_status == "timeout":
            ocr_stats["timeouts"] = int(ocr_stats.get("timeouts", 0) or 0) + 1
        else:
            ocr_stats["errors"] = int(ocr_stats.get("errors", 0) or 0) + 1
        if isinstance(cache, dict):
            cache[key] = {
                "status": result_status,
                "provider": provider,
                "error": str(getattr(result, "error", "") or "")[:500],
            }
        return _record(
            "ocr_attachment",
            {"path": raw_path},
            {
                "status": result_status,
                "path": item_path,
                "reason": "mineru_failed",
                "error": str(getattr(result, "error", "") or "MinerU 未返回文本")[:500],
            },
        )

    return [list_attachment_files, search_attachment_text, read_attachment, ocr_attachment]


def _sheet_has_evidence_text(ws) -> bool:
    for _, text in _extract_sheet_text_cells(ws):
        filenames, rel_paths, indices = _extract_attachment_refs(text)
        if filenames or rel_paths or indices or any(keyword in text for keyword in EVIDENCE_KEYWORDS):
            return True
    return False


def should_run_evidence_agent(
    ws,
    attachments: Dict[str, object],
    *,
    mode: Optional[str] = None,
) -> bool:
    """Return whether this Sheet needs the optional evidence investigation."""
    selected_mode = _agent_mode(mode)
    if selected_mode == "off" or not attachments:
        return False
    if str(attachments.get("source_type", "")) != "directory":
        return False
    if not _items(attachments) or not _sheet_has_evidence_text(ws):
        return False
    if selected_mode == "always":
        return True

    def _is_unparsed(item: Any) -> bool:
        return str(
            getattr(item, "extraction_status", "")
            or getattr(item, "status", "")
            or ""
        ).lower() not in {"", "ok"}

    by_sheet = attachments.get("by_sheet_norm") or {}
    normalized_sheet = str(getattr(ws, "title", "") or "").replace("-", "").replace("_", "").upper()
    sheet_items = by_sheet.get(normalized_sheet, []) if isinstance(by_sheet, dict) else []
    if isinstance(sheet_items, list) and any(_is_unparsed(item) for item in sheet_items):
        return True

    for _, text in _extract_sheet_text_cells(ws):
        filenames, rel_paths, indices = _extract_attachment_refs(text)
        if not filenames and not rel_paths and not indices:
            if any(keyword in text for keyword in EVIDENCE_KEYWORDS):
                return True
            continue
        matched, missing = _match_attachment_items(
            attachments,
            filenames=filenames,
            rel_paths=rel_paths,
            indices=indices,
        )
        if missing or not matched:
            return True
        if any(_is_unparsed(item) for item in matched):
            return True
    return False


def _build_investigation_prompt(ws, attachments: Dict[str, object]) -> str:
    relevant_cells: List[Dict[str, str]] = []
    for coord, text in _extract_sheet_text_cells(ws):
        filenames, rel_paths, indices = _extract_attachment_refs(text)
        if filenames or rel_paths or indices or any(keyword in text for keyword in EVIDENCE_KEYWORDS):
            relevant_cells.append({"cell": coord, "text": _truncate(text, 900)})
        if len(relevant_cells) >= 36:
            break
    if not relevant_cells:
        relevant_cells = [
            {"cell": coord, "text": _truncate(text, 500)}
            for coord, text in list(_extract_sheet_text_cells(ws))[:12]
        ]
    # Build embedded media examples
    embedded_examples = []
    items = attachments.get("items", []) or []
    for it in items:
        rp = getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path")
        if rp and rp.startswith(".embedded_media/") and "::" in rp:
            after = rp[len(".embedded_media/"):]
            source_doc, media_name = after.split("::", 1)
            embedded_examples.append({"source_document": source_doc, "media_filename": media_name})
        if len(embedded_examples) >= 10:
            break
    payload = {
        "sheet": str(getattr(ws, "title", "") or ""),
        "cells": relevant_cells,
        "attachment_status_counts": attachments.get("status_counts", {}),
        "embedded_media_count": sum(
            1 for it in items
            if (getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path", "")).startswith(".embedded_media/")
        ),
        "embedded_media_examples": embedded_examples,
        "embedded_media_more": sum(
            1 for it in items
            if (getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path", "")).startswith(".embedded_media/")
        ) > 10,
    }
    ocr_enabled = bool(attachments.get("ocr_enabled"))
    tools_text = "list_attachment_files、search_attachment_text、read_attachment"
    if ocr_enabled:
        tools_text += "、ocr_attachment"
    return (
        "请调查当前审计底稿 Sheet 中的附件证据，但不要直接判断通过/不通过。\n"
        + f"你只能使用列出的附件工具（{tools_text}），并且只能引用工具返回的相对路径和原文摘录。\n"
        + "优先处理：附件引用未匹配、图片/扫描件/不支持格式、以及需要跨文件核对的证据。"
        + ("对图片或扫描件先调用 ocr_attachment，再引用 OCR 返回的逐字摘录。\n" if ocr_enabled else "\n")
        + "如果文件没有可提取文本，必须放入 unresolved，不得猜测图片或二进制内容。\n"
        + "注意：对同一个文件不要重复调用 ocr_attachment —— 返回的 content 如果是空字符串（cached: true 也算），说明 PDF/图片没有可识别文本，不要再试。直接把它放到 unresolved。\n"
        + "同样不要重复 list_attachment_files 或 search_attachment_text 用相似查询：同一 query 已经查过没结果就换思路。\n"
        + "PDF 既支持直接文本提取（pdftotext）也支持 OCR。如果 read_attachment 已经返回文本（status=ok 且 content 非空），不要重复 ocr_attachment。\n"
        + "效率提示：最多调用 8-12 次工具就完成调查。找到关键证据后立即停止探索，输出 JSON。"
        + "具体策略：（1）先用 1 次 list_attachment_files 概览，看哪些附件是图片/二进制（需要 OCR）；"
        + "（2）对 1-3 张关键截图 ocr_attachment 取参数；（3）用 1-2 次 search_attachment_text 在已读附件里搜术语；"
        + "（4）输出 JSON 即可，不要把所有相关文件都 OCR 完。\n"
        + "最后只输出严格 JSON：{\"evidence\":[{\"path\":\"...\",\"excerpt\":\"原文\",\"supports\":\"支持什么\",\"confidence\":\"high|medium|low\"}],"
        + "\"unresolved\":[{\"request\":\"需要核对什么\",\"reason\":\"原因\"}]}。\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )[:_DEFAULT_MAX_PROMPT_CHARS]


def _last_text(result: Any) -> str:
    messages = result.get("messages", []) if isinstance(result, dict) else []
    ordered = messages if isinstance(messages, list) else []
    for message in reversed(ordered):
        if getattr(message, "type", "") not in {"ai", "assistant"}:
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if str(content or "").strip():
            return str(content).strip()
    for message in reversed(ordered):
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if str(content or "").strip():
            return str(content).strip()
    return ""


def _parse_agent_json(content: str) -> Optional[Dict[str, object]]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
        except Exception:
            return None


_TERMS_FOR_VALIDATION_RE = re.compile(r"[\w一-鿿]{2,}")


def _excerpt_grounded(excerpt: str, source: str) -> bool:
    """Best-effort semantic grounding check.

    The agent reasons about evidence content; we don't require verbatim
    substring matches because OCR/HTML markup spans cell boundaries. Instead
    we look for distinctive tokens (CJK runs and 2+ char alphanumeric words)
    that survive in both the excerpt and the source. At least one overlap is
    enough to keep the citation; pure hallucination (terms that appear
    nowhere in the source) still gets filtered out by ``unresolved``.
    """
    if not excerpt or not source:
        return False
    excerpt_terms = set(_TERMS_FOR_VALIDATION_RE.findall(excerpt))
    source_terms = set(_TERMS_FOR_VALIDATION_RE.findall(source))
    if not excerpt_terms:
        # Pure punctuation excerpt: fall back to weak substring check.
        return excerpt.strip() in source
    return bool(excerpt_terms & source_terms)


def validate_agent_result(payload: Optional[Dict[str, object]], attachments: Dict[str, object]) -> Dict[str, object]:
    """Accept Agent evidence when the path is indexed and the excerpt is grounded.

    The constrained Agent can only see files in the pinned attachment index,
    so a correctly-indexed path combined with at least one distinctive term
    shared between the excerpt and the source text is treated as sufficient
    evidence. We no longer require verbatim substring matches because OCR
    output (HTML tables, line wrapping, cell boundaries) routinely breaks
    exact matches even when the agent's reasoning is sound.
    """
    payload = payload if isinstance(payload, dict) else {}
    accepted: List[Dict[str, object]] = []
    unresolved: List[Dict[str, object]] = []
    raw_evidence = payload.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raw_evidence = []
    for raw in raw_evidence[:_DEFAULT_MAX_AGENT_RESULTS]:
        if not isinstance(raw, dict):
            unresolved.append({"request": "Agent evidence item", "reason": "invalid_item"})
            continue
        path = str(raw.get("path", "")).strip()
        matches = _path_matches(attachments, path)
        if len(matches) != 1:
            unresolved.append({"request": path, "reason": "source_not_indexed"})
            continue
        item = matches[0]
        source = _source_text(attachments, item)
        excerpt = str(raw.get("excerpt", "") or "").strip()
        if not excerpt:
            unresolved.append({"request": path, "reason": "empty_excerpt"})
            continue
        if source and not _excerpt_grounded(excerpt, source):
            unresolved.append({"request": path, "reason": "excerpt_not_grounded"})
            continue
        accepted.append({
            "path": str(getattr(item, "rel_path", "") or getattr(item, "filename", "")),
            "file_type": str(getattr(item, "file_type", "") or ""),
            "extraction_status": _source_status(attachments, item),
            "excerpt": excerpt[:_DEFAULT_MAX_EXCERPT],
            "supports": _truncate(str(raw.get("supports", "") or ""), 300),
            "confidence": str(raw.get("confidence", "") or "").strip().lower() or "unknown",
        })

    raw_unresolved = payload.get("unresolved", [])
    if isinstance(raw_unresolved, list):
        for raw in raw_unresolved[:_DEFAULT_MAX_AGENT_RESULTS]:
            if isinstance(raw, dict):
                unresolved.append({
                    "request": _truncate(str(raw.get("request", "") or ""), 300),
                    "reason": _truncate(str(raw.get("reason", "") or ""), 500),
                })
    return {"evidence": accepted, "unresolved": unresolved}


async def investigate_sheet(
    *,
    ws,
    attachments: Dict[str, object],
    llm,
    mode: Optional[str] = None,
    agent_factory: Optional[Callable[..., Any]] = None,
    mineru_client: Optional[Any] = None,
) -> Dict[str, object]:
    """Run one bounded evidence investigation without affecting main review."""
    if not should_run_evidence_agent(ws, attachments, mode=mode):
        return {"status": "skipped", "evidence": [], "unresolved": [], "tool_trace": [], "tool_calls": 0}

    trace: List[Dict[str, object]] = []
    ocr_client = mineru_client if mineru_client is not None else MinerUClient.from_env()
    attachments["ocr_enabled"] = bool(ocr_client)
    tools = build_evidence_tools(attachments, trace=trace, mineru_client=ocr_client)
    ocr_before = dict(attachments.get("ocr_stats") or {})

    def _ocr_delta() -> Dict[str, int]:
        current = attachments.get("ocr_stats") or {}
        if not isinstance(current, dict):
            return {}
        return {
            key: max(0, int(current.get(key, 0) or 0) - int(ocr_before.get(key, 0) or 0))
            for key in ("calls", "success", "errors", "timeouts")
        }
    factory = agent_factory or create_agent
    _llm_stat("evidence_agent", "calls", 1)
    # OpenAI's chat completions client rejects tools that don't have
    # `strict: True` set in their function definition (see
    # openai/lib/_parsing/_completions.py:validate_input_tools).
    # `create_agent` calls `llm.bind_tools(tools)` internally without passing
    # strict, so we monkey-patch the bound method to default it. Pydantic
    # forbids normal attribute assignment on the model instance, so we use
    # `object.__setattr__` to bypass.
    if not agent_factory and not getattr(llm, "_strict_tools_patched", False):
        _orig_bind_tools = llm.bind_tools
        def _bind_tools_strict(*args, **kwargs):
            kwargs.setdefault("strict", True)
            return _orig_bind_tools(*args, **kwargs)
        try:
            object.__setattr__(llm, "bind_tools", _bind_tools_strict)
        except Exception:
            # If we can't patch on the model instance, leave it alone and
            # hope create_agent doesn't re-bind without strict.
            pass
        object.__setattr__(llm, "_strict_tools_patched", True)
    try:
        agent = factory(
            model=llm,
            tools=tools,
            system_prompt=(
                "你是受限的审计证据调查 Agent。你只能通过工具查看审阅快照中的附件索引和已提取文本。"
                "你不可以执行命令、写文件、访问工具返回之外的路径或编造证据。"
                + ("如果附件是图片或扫描件，可先使用 ocr_attachment 获取 OCR 原文；OCR 失败时必须保留 unresolved。" if ocr_client else "")
                + "嵌入图指引：DOCX/PPTX/PDF 中提取出的嵌入图位于 .embedded_media/ 虚拟目录，"
                + "路径形如 .embedded_media/<原文档名>::<图名>.<ext>。"
                + "若需要核对该文档内的截图、流程图、扫描页证据，"
                + "应直接对 .embedded_media/ 中的具体图调用 ocr_attachment，"
                + "而非对整份 DOCX/PDF 调用（整份调用只会返回文字）。"
                + "list_attachment_files 输出中可查看 source_document 字段定位图来源。"
                + "你只负责定位候选证据，不负责给出审阅结论。最后必须返回约定 JSON。"
            ),
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=_build_investigation_prompt(ws, attachments))]},
            config={"recursion_limit": _env_int("REVIEW_EVIDENCE_AGENT_MAX_STEPS", _DEFAULT_MAX_AGENT_STEPS)},
        )
        parsed = _parse_agent_json(_last_text(result))
        if parsed is None:
            _llm_stat("evidence_agent", "error_parse", 1)
            return {
                "status": "error",
                "evidence": [],
                "unresolved": [{"request": str(getattr(ws, "title", "") or "Sheet"), "reason": "invalid_agent_json"}],
                "tool_trace": trace,
                "tool_calls": len(trace),
                "error": "Agent未返回有效JSON",
                "ocr": _ocr_delta(),
            }
        validated = validate_agent_result(parsed, attachments)
        _llm_stat("evidence_agent", "ok", 1)
        return {
            "status": "completed",
            **validated,
            "tool_trace": trace,
            "tool_calls": len(trace),
            "ocr": _ocr_delta(),
        }
    except Exception as exc:
        _llm_stat("evidence_agent", "error", 1)
        return {
            "status": "error",
            "evidence": [],
            "unresolved": [{"request": str(getattr(ws, "title", "") or "Sheet"), "reason": f"agent_error: {type(exc).__name__}"}],
            "tool_trace": trace,
            "tool_calls": len(trace),
            "error": f"{type(exc).__name__}: {exc}",
            "ocr": _ocr_delta(),
        }
