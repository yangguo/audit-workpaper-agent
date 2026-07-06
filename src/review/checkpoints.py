"""Checkpoint loading helpers (ported from analyze_excel.py)."""
import os
import re
from collections import defaultdict
from typing import Dict, List

import openpyxl

from review.constants import CHECKPOINT_VOCAB


def load_checkpoints_xlsx(checkpoints_path: str) -> Dict[str, List[str]]:
    """Load a checkpoints workbook into a {sheet_id: [check_text, ...]} map.

    Column 1 holds the sheet id (sticky: following rows inherit it until a new
    non-empty value appears); column 3 holds the check text.
    """
    if not checkpoints_path:
        return {}
    if not os.path.exists(checkpoints_path):
        raise FileNotFoundError(checkpoints_path)

    wb = openpyxl.load_workbook(checkpoints_path, data_only=True)
    ws = wb.active

    checkpoints_by_sheet: Dict[str, List[str]] = defaultdict(list)
    last_sheet = None
    for row in range(1, (ws.max_row or 0) + 1):
        sheet_id = ws.cell(row=row, column=1).value
        check_text = ws.cell(row=row, column=3).value
        if isinstance(sheet_id, str):
            sheet_id = sheet_id.strip()
        if isinstance(check_text, str):
            check_text = check_text.strip()

        if sheet_id:
            last_sheet = str(sheet_id).strip()
        if not last_sheet:
            continue
        if not check_text:
            continue

        checkpoints_by_sheet[last_sheet].append(str(check_text).strip())

    return dict(checkpoints_by_sheet)


def _split_checkpoints(text: str) -> List[str]:
    """Split a checkpoint cell into individual checkpoint strings."""
    if not text:
        return []
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    parts: List[str] = []
    for chunk in normalized.split("\n"):
        s = chunk.strip()
        if not s:
            continue
        s = re.sub(r"^\s*\d+\s*[.、]\s*", "", s)
        if s:
            parts.append(s)
    if parts:
        return parts
    return [normalized.strip()] if normalized.strip() else []


def _extract_checkpoint_keywords(checkpoint: str) -> List[str]:
    """Extract evidence-vocabulary keywords from a checkpoint string."""
    t = checkpoint or ""
    hits = [w for w in CHECKPOINT_VOCAB if w and w in t]
    if hits:
        seen = set()
        out: List[str] = []
        for h in hits:
            if h in seen:
                continue
            seen.add(h)
            out.append(h)
        return out

    segments = re.split(r"[，；。;,.、()\[\]（）]+", t)
    picked: List[str] = []
    for seg in segments:
        s = seg.strip()
        if not s:
            continue
        if len(s) < 4:
            continue
        if len(s) > 26:
            s = s[:26]
        if any("一" <= ch <= "鿿" for ch in s):
            picked.append(s)
        if len(picked) >= 3:
            break
    return picked or [t[:16].strip()] if t.strip() else []
