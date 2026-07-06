import openpyxl

from review.attachments import (
    _extract_attachment_refs,
    _compact_keywords,
    _evidence_matches_step,
    _match_preview_items,
    load_attachments_preview_xlsx,
    _check_attachment_references,
)
from review.models import AttachmentPreviewItem


def test_extract_attachment_refs():
    filenames, rel_paths, indices = _extract_attachment_refs(
        "见附件1，截图 screenshot.png，路径 dir/sub/file.xlsx"
    )
    assert "screenshot.png" in filenames
    assert "dir/sub/file.xlsx" in rel_paths
    assert "1" in indices


def test_extract_attachment_refs_empty():
    assert _extract_attachment_refs("") == ([], [], [])


def test_compact_keywords_filters_stopwords():
    out = _compact_keywords("审计 程序 用户清单 权限矩阵")
    assert out == ["用户清单", "权限矩阵"]


def test_evidence_matches_step_overlap():
    assert _evidence_matches_step("获取用户清单", "用户清单导出截图") is True


def test_evidence_matches_step_no_overlap():
    assert _evidence_matches_step("密码策略复杂度", "用户清单导出") is False


def test_evidence_matches_step_empty_is_true():
    assert _evidence_matches_step("", "x") is True
    assert _evidence_matches_step("x", "") is True


def _make_item(**kw):
    base = dict(index="1", rel_dir="d", filename="a.png", rel_path="d/a.png",
                file_type="png", description="desc", status="OK")
    base.update(kw)
    return AttachmentPreviewItem(**base)


def test_match_preview_items_by_filename_and_missing_index():
    item = _make_item()
    preview = {
        "by_filename": {"a.png": [item]},
        "by_rel_path": {},
        "by_index": {"1": [item]},
        "by_sheet_norm": {},
        "path": "p",
        "items": [item],
        "status_counts": {"OK": 1},
    }
    picked, missing = _match_preview_items(
        preview, filenames=["a.png"], rel_paths=[], indices=["2"],
    )
    assert item in picked
    assert "索引2" in missing


def test_load_attachments_preview_xlsx(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "图片描述"
    headers = ["目录索引", "相对目录", "附件文件名", "相对路径", "文件类型", "详细描述", "状态"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    ws.cell(row=2, column=1, value=1)
    ws.cell(row=2, column=2, value="SA-4c")
    ws.cell(row=2, column=3, value="a.png")
    ws.cell(row=2, column=4, value="SA-4c/a.png")
    ws.cell(row=2, column=5, value="png")
    ws.cell(row=2, column=6, value="用户清单截图")
    ws.cell(row=2, column=7, value="OK")
    path = tmp_path / "preview.xlsx"
    wb.save(str(path))

    preview = load_attachments_preview_xlsx(str(path))
    assert len(preview["items"]) == 1
    assert preview["items"][0].filename == "a.png"
    assert "a.png" in preview["by_filename"]
    assert "1" in preview["by_index"]
    assert "SA4C" in preview["by_sheet_norm"]


def test_check_attachment_references_flags_missing_index():
    item = _make_item(status="OK")
    preview = {
        "by_filename": {}, "by_rel_path": {},
        "by_index": {"1": [item]}, "by_sheet_norm": {},
        "path": "p", "items": [item], "status_counts": {"OK": 1},
    }
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "见附件9"
    findings = _check_attachment_references("SA-1", ws, preview)
    assert len(findings) == 1
    assert findings[0].issue_type == "附件证据引用未匹配到预览清单"
    assert findings[0].severity == "P2"


def test_check_attachment_references_empty_preview_returns_empty(layout_workbook):
    assert _check_attachment_references("SA-1", layout_workbook.active, {}) == []
