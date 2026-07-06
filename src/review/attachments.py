"""Attachment-preview loading and reference matching (ported from analyze_excel.py)."""
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

import openpyxl

from review.constants import CHECKPOINT_VOCAB
from review.excel_utils import (
    _build_sheet_text_for_llm,
    _extract_sheet_text_cells,
    _normalize_sheet_id,
    _truncate,
)
from review.models import AttachmentPreviewItem, Finding

ATTACHMENT_FILE_RE = re.compile(
    r"([0-9A-Za-z_\-\.一-鿿]+?\.(?:png|jpg|jpeg|pdf|xlsx|xls|docx|doc))",
    re.IGNORECASE,
)
ATTACHMENT_PATH_RE = re.compile(
    r"([0-9A-Za-z_\-\.一-鿿]+(?:[\\/][0-9A-Za-z_\-\.一-鿿]+)+\.(?:png|jpg|jpeg|pdf|xlsx|xls|docx|doc))",
    re.IGNORECASE,
)
ATTACHMENT_INDEX_RE = re.compile(r"(?:附件|证据|图片|截图|索引|目录索引)\s*([0-9]{1,3})")

_SHEET_TAG_RE = re.compile(r"\b((?:SA|PM)[-_ ]?\d{1,2}[A-Za-z]?)\b", re.IGNORECASE)
_SHEET_TAG_NODELIM_RE = re.compile(r"\b((?:SA|PM)\d{1,2}[A-Za-z]?)\b", re.IGNORECASE)


def _extract_attachment_refs(text: str) -> Tuple[List[str], List[str], List[str]]:
    s = (text or "").strip()
    if not s:
        return [], [], []
    rel_paths = [m.group(1) for m in ATTACHMENT_PATH_RE.finditer(s)]
    filenames = [m.group(1) for m in ATTACHMENT_FILE_RE.finditer(s)]
    indices = [m.group(1) for m in ATTACHMENT_INDEX_RE.finditer(s)]
    return filenames, rel_paths, indices


def _compact_keywords(text: str) -> List[str]:
    s = (text or "").strip()
    if not s:
        return []
    tokens = re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", s)
    stop = {"审计", "程序", "执行", "标准", "附件", "证据", "截图", "导出", "清单", "日志", "台账"}
    out: List[str] = []
    seen = set()
    for t in tokens:
        tt = t.strip().lower()
        if not tt or tt in stop:
            continue
        if tt in seen:
            continue
        seen.add(tt)
        out.append(t.strip())
        if len(out) >= 18:
            break
    return out


def _evidence_matches_step(step_text: str, attachment_desc: str) -> bool:
    if not step_text or not attachment_desc:
        return True
    step_keys = set(_compact_keywords(step_text) + [k for k in CHECKPOINT_VOCAB if k in step_text])
    desc_keys = set(_compact_keywords(attachment_desc) + [k for k in CHECKPOINT_VOCAB if k in attachment_desc])
    if not step_keys or not desc_keys:
        return True
    inter = step_keys.intersection(desc_keys)
    return len(inter) >= 1


def _extract_sheet_norms(*texts: str) -> List[str]:
    joined = " ".join(str(t or "") for t in texts if t)
    if not joined:
        return []
    norms: List[str] = []
    for m in _SHEET_TAG_RE.findall(joined) + _SHEET_TAG_NODELIM_RE.findall(joined):
        nm = _normalize_sheet_id(m)
        if nm and nm not in norms:
            norms.append(nm)
    return norms


def load_attachments_preview_xlsx(preview_path: str) -> Dict[str, object]:
    if not preview_path:
        return {}
    wb = openpyxl.load_workbook(preview_path, data_only=True)
    ws = wb["图片描述"] if "图片描述" in wb.sheetnames else wb.active

    header_row = 1
    header_map: Dict[str, int] = {}
    max_scan_col = min(ws.max_column or 0, 40)
    for c in range(1, max_scan_col + 1):
        v = ws.cell(row=header_row, column=c).value
        if not v:
            continue
        key = str(v).strip().replace("\n", "").replace(" ", "")
        if key:
            header_map[key] = c

    def _col(*names: str) -> int:
        for n in names:
            n2 = str(n).strip().replace("\n", "").replace(" ", "")
            if n2 in header_map:
                return int(header_map[n2])
        return 0

    col_index = _col("目录索引", "索引")
    col_rel_dir = _col("相对目录", "目录", "文件夹", "相对文件夹")
    col_filename = _col("附件文件名", "文件名", "附件名称", "图片文件名")
    col_rel_path = _col("相对路径", "路径", "附件路径", "图片路径")
    col_file_type = _col("文件类型", "类型", "后缀", "格式")
    col_desc = _col("详细描述", "描述", "内容", "图片描述")
    col_status = _col("状态", "校验状态", "结果")

    items: List[AttachmentPreviewItem] = []
    by_filename: Dict[str, List[AttachmentPreviewItem]] = defaultdict(list)
    by_rel_path: Dict[str, List[AttachmentPreviewItem]] = defaultdict(list)
    by_index: Dict[str, List[AttachmentPreviewItem]] = defaultdict(list)
    by_sheet_norm: Dict[str, List[AttachmentPreviewItem]] = defaultdict(list)
    status_counts: Dict[str, int] = defaultdict(int)

    for r in range(2, (ws.max_row or 0) + 1):
        raw_filename = ws.cell(row=r, column=col_filename).value if col_filename else None
        raw_desc = ws.cell(row=r, column=col_desc).value if col_desc else None
        raw_rel_path = ws.cell(row=r, column=col_rel_path).value if col_rel_path else None
        raw_status = ws.cell(row=r, column=col_status).value if col_status else None
        raw_index = ws.cell(row=r, column=col_index).value if col_index else None
        raw_rel_dir = ws.cell(row=r, column=col_rel_dir).value if col_rel_dir else None
        raw_file_type = ws.cell(row=r, column=col_file_type).value if col_file_type else None

        filename = str(raw_filename).strip() if raw_filename else ""
        description = str(raw_desc).strip() if raw_desc else ""
        rel_path = str(raw_rel_path).strip() if raw_rel_path else ""
        status = str(raw_status).strip() if raw_status else ""
        index = str(raw_index).strip() if raw_index is not None else ""
        rel_dir = str(raw_rel_dir).strip() if raw_rel_dir else ""
        file_type = str(raw_file_type).strip() if raw_file_type else ""

        if not filename and not rel_path and not description:
            continue

        item = AttachmentPreviewItem(
            index=index,
            rel_dir=rel_dir,
            filename=filename,
            rel_path=rel_path,
            file_type=file_type,
            description=description,
            status=status,
        )
        items.append(item)

        if filename:
            by_filename[filename.lower()].append(item)
        if rel_path:
            by_rel_path[rel_path.lower().replace("/", "\\")].append(item)
        if index:
            by_index[index].append(item)
        for sn in _extract_sheet_norms(rel_dir, rel_path):
            by_sheet_norm[sn].append(item)
        status_counts[status or ""] += 1

    return {
        "path": preview_path,
        "items": items,
        "by_filename": dict(by_filename),
        "by_rel_path": dict(by_rel_path),
        "by_index": dict(by_index),
        "by_sheet_norm": dict(by_sheet_norm),
        "status_counts": dict(status_counts),
    }


def _match_preview_items(
    preview: Dict[str, object],
    *,
    filenames: Sequence[str],
    rel_paths: Sequence[str],
    indices: Sequence[str],
) -> Tuple[List[AttachmentPreviewItem], List[str]]:
    if not preview:
        return [], list(filenames)
    by_filename = preview.get("by_filename") or {}
    by_rel_path = preview.get("by_rel_path") or {}
    by_index = preview.get("by_index") or {}

    picked: List[AttachmentPreviewItem] = []
    picked_keys = set()
    missing: List[str] = []

    def _add(items: Iterable[AttachmentPreviewItem]) -> None:
        for it in items:
            key = (it.rel_path or "").lower() or (it.filename or "").lower()
            if not key:
                continue
            if key in picked_keys:
                continue
            picked_keys.add(key)
            picked.append(it)

    for idx in indices:
        lst = by_index.get(str(idx).strip())
        if isinstance(lst, list) and lst:
            _add(lst)
        else:
            missing.append(f"索引{idx}")

    for p in rel_paths:
        key = str(p).strip().lower().replace("/", "\\")
        lst = by_rel_path.get(key)
        if isinstance(lst, list) and lst:
            _add(lst)
            continue
        missing.append(p)

    for f in filenames:
        key = str(f).strip().lower()
        lst = by_filename.get(key)
        if isinstance(lst, list) and lst:
            _add(lst)
            continue
        missing.append(f)

    return picked, missing


def _attachments_context_for_sheet(ws, preview: Dict[str, object], limit_chars: int = 6000) -> str:
    if not preview:
        return ""
    text = _build_sheet_text_for_llm(ws, max_cells=260, max_chars=24000)
    filenames, rel_paths, indices = _extract_attachment_refs(text)
    matched, _ = _match_preview_items(preview, filenames=filenames, rel_paths=rel_paths, indices=indices)
    by_sheet = preview.get("by_sheet_norm") or {}
    if isinstance(by_sheet, dict):
        norm = _normalize_sheet_id(getattr(ws, "title", "") or "")
        lst = by_sheet.get(norm)
        if isinstance(lst, list) and lst:
            seen = set(id(it) for it in matched)
            for it in lst[:80]:
                if not isinstance(it, AttachmentPreviewItem):
                    continue
                if id(it) in seen:
                    continue
                matched.append(it)
                seen.add(id(it))
                if len(matched) >= 80:
                    break
    if not matched:
        return ""
    parts: List[str] = []
    total = 0
    for it in matched[:40]:
        line = f"- {it.rel_path or it.filename} | 状态={it.status or ''} | {it.description or ''}"
        if total + len(line) + 1 > limit_chars:
            break
        parts.append(line)
        total += len(line) + 1
    return "\n".join(parts).strip()


def _check_attachment_references(ws_title: str, ws, attachments_preview: Dict[str, object]) -> List[Finding]:
    if not attachments_preview:
        return []
    findings: List[Finding] = []

    used_any = False
    for coord, text in _extract_sheet_text_cells(ws):
        filenames, rel_paths, indices = _extract_attachment_refs(text)
        if not filenames and not rel_paths and not indices:
            continue
        used_any = True
        matched, missing = _match_preview_items(
            attachments_preview,
            filenames=filenames,
            rel_paths=rel_paths,
            indices=indices,
        )
        if missing:
            findings.append(
                Finding(
                    issue_type="附件证据引用未匹配到预览清单",
                    severity="P2",
                    sheet=ws_title,
                    cell=coord,
                    snippet=_truncate(text, 220),
                    basis=_truncate(
                        "引用: "
                        + "、".join(sorted({m for m in missing if m}))
                        + f"\n预览清单: {attachments_preview.get('path','')}",
                        1200,
                    ),
                    suggestion="核对底稿中的附件编号/文件名/路径是否与附件清单一致；如存在重命名或遗漏，请补齐清单或更新引用。",
                )
            )
        bad = [it for it in matched if (it.status or "").strip() and str(it.status).strip().upper() != "OK"]
        for it in bad[:5]:
            findings.append(
                Finding(
                    issue_type="附件预览状态异常",
                    severity="P1",
                    sheet=ws_title,
                    cell=coord,
                    snippet=_truncate(text, 220),
                    basis=_truncate(
                        f"附件: {it.rel_path or it.filename}\n状态: {it.status}\n描述: {it.description}",
                        1200,
                    ),
                    suggestion="检查该附件是否OCR/解析失败或内容不清晰；必要时补充可复核版本（导出清单/日志/原始报表）并在底稿中明确指向。",
                )
            )

    if not used_any:
        return []
    return findings
