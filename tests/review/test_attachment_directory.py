import openpyxl
from review.models import AttachmentFile

from review.attachments import (
    _attachments_context_for_sheet,
    _check_attachment_references,
    _extract_attachment_refs,
    _match_attachment_items,
    _verify_attachment_evidence_refs,
    build_attachment_index,
)


def test_build_attachment_index_recurses_and_extracts_text(tmp_path):
    root = tmp_path / "attachments"
    evidence_dir = root / "SA-4c"
    evidence_dir.mkdir(parents=True)
    evidence = evidence_dir / "附件1-用户清单.txt"
    evidence.write_text("用户名：admin\n权限：管理员", encoding="utf-8")

    index = build_attachment_index(str(root))

    assert index["source_type"] == "directory"
    assert len(index["items"]) == 1
    item = index["items"][0]
    assert item.rel_path == "SA-4c/附件1-用户清单.txt"
    assert item.extracted_text == "用户名：admin\n权限：管理员"
    assert item.extraction_status == "ok"
    assert item in index["by_filename"]["附件1-用户清单.txt"]
    assert item in index["by_index"]["1"]
    assert item in index["by_sheet_norm"]["SA4C"]


def test_match_attachment_items_accepts_index_and_relative_path_suffix(tmp_path):
    root = tmp_path / "attachments"
    evidence_dir = root / "bundle" / "SA-4c"
    evidence_dir.mkdir(parents=True)
    evidence = evidence_dir / "附件1-user-list.csv"
    evidence.write_text("user,role\nadm,admin", encoding="utf-8")
    index = build_attachment_index(str(root))

    filenames, rel_paths, indices = _extract_attachment_refs(
        "见附件1，文件为 SA-4c/附件1-user-list.csv"
    )
    matched, missing = _match_attachment_items(
        index,
        filenames=filenames,
        rel_paths=rel_paths,
        indices=indices,
    )

    assert len(matched) == 1
    assert matched[0].filename == "附件1-user-list.csv"
    assert missing == []


def test_match_attachment_items_rejects_parent_path_reference(tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    evidence = root / "evidence.txt"
    evidence.write_text("admin,administrator", encoding="utf-8")
    index = build_attachment_index(str(root))

    matched, missing = _match_attachment_items(
        index,
        filenames=[],
        rel_paths=["../evidence.txt"],
        indices=[],
    )

    assert matched == []
    assert missing == ["../evidence.txt"]


def test_build_attachment_index_reads_xlsx_evidence(tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    path = root / "permission-matrix.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "账号"
    workbook.active["B1"] = "角色"
    workbook.active["A2"] = "admin"
    workbook.active["B2"] = "管理员"
    workbook.save(path)

    index = build_attachment_index(str(root))

    item = index["items"][0]
    assert "admin" in item.extracted_text
    assert "管理员" in item.extracted_text


def test_build_attachment_index_keeps_unsupported_files_as_metadata(tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    path = root / "export.rar"
    path.write_bytes(b"not parsed")

    index = build_attachment_index(str(root))

    assert index["items"][0].filename == "export.rar"
    assert index["items"][0].extraction_status == "unsupported"
    assert index["items"][0].extracted_text == ""


def test_attachment_context_contains_matched_file_content(tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    (root / "user-list.txt").write_text("admin,administrator", encoding="utf-8")
    index = build_attachment_index(str(root))

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SA-4c"
    sheet["A1"] = "执行程序"
    sheet["A2"] = "导出用户清单，见 user-list.txt"

    context = _attachments_context_for_sheet(sheet, index)

    assert "user-list.txt" in context
    assert "admin,administrator" in context


def test_attachment_context_contains_validated_agent_evidence():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SA-4c"
    sheet["A1"] = "执行程序"
    attachments = {
        "items": [],
        "by_filename": {},
        "by_rel_path": {},
        "by_index": {},
        "by_sheet_norm": {},
        "agent_evidence_by_sheet": {
            "SA4C": [{
                "path": "SA-4c/user-list.txt",
                "file_type": "txt",
                "extraction_status": "ok",
                "excerpt": "admin,administrator",
                "supports": "用户清单中的管理员权限",
                "confidence": "high",
            }],
        },
    }

    context = _attachments_context_for_sheet(sheet, attachments)

    assert "SA-4c/user-list.txt" in context
    assert "admin,administrator" in context


def test_verify_attachment_evidence_refs_drops_unverified_attachment_hint():
    item = AttachmentFile(
        index="1", rel_dir="SA-4c", filename="users.txt",
        rel_path="SA-4c/users.txt", file_type="txt", status="ok",
        extraction_status="ok", extracted_text="admin,administrator", size=19,
    )
    attachments = {
        "path": "/pinned/attachments",
        "items": [item],
        "by_filename": {"users.txt": [item]},
        "by_rel_path": {"sa-4c/users.txt": [item]},
        "by_index": {"1": [item]},
        "by_sheet_norm": {},
    }
    refs = _verify_attachment_evidence_refs([
        {"sheet": "SA-4c", "cell_or_range": "B5", "attachment": "SA-4c/users.txt", "excerpt": "admin,administrator"},
        {"sheet": "SA-4c", "cell_or_range": "B5", "attachment": "missing.txt", "excerpt": "编造"},
        {"sheet": "SA-4c", "cell_or_range": "B5", "attachment": "users.txt", "excerpt": "编造"},
    ], attachments)

    assert refs[0]["attachment"] == "SA-4c/users.txt"
    assert "attachment" not in refs[1]
    assert "attachment" not in refs[2]


def test_verify_attachment_evidence_refs_keeps_attachment_excerpt_when_cell_is_valid():
    item = AttachmentFile(
        index="1", rel_dir="SA-4c", filename="users.txt",
        rel_path="SA-4c/users.txt", file_type="txt", status="ok",
        extraction_status="ok", extracted_text="admin,administrator", size=19,
    )
    attachments = {
        "items": [item],
        "by_filename": {"users.txt": [item]},
        "by_rel_path": {"sa-4c/users.txt": [item]},
        "by_index": {"1": [item]},
        "by_sheet_norm": {},
    }
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["B5"] = "见附件1并核验用户权限"

    refs = _verify_attachment_evidence_refs([
        {
            "sheet": "SA-4c",
            "cell_or_range": "B5",
            "attachment": "SA-4c/users.txt",
            "excerpt": "admin,administrator",
        }
    ], attachments, ws=sheet)

    assert refs[0]["attachment"] == "SA-4c/users.txt"
    assert refs[0]["excerpt"] == "admin,administrator"


def test_verify_attachment_evidence_refs_accepts_verified_ocr_excerpt():
    item = AttachmentFile(
        index="1", rel_dir="SA-4c", filename="screenshot.png",
        rel_path="SA-4c/screenshot.png", file_type="png", status="binary",
        extraction_status="binary", extracted_text="", size=19,
    )
    attachments = {
        "items": [item],
        "by_filename": {"screenshot.png": [item]},
        "by_rel_path": {"sa-4c/screenshot.png": [item]},
        "by_index": {"1": [item]},
        "by_sheet_norm": {},
        "ocr_by_path": {
            "sa-4c/screenshot.png": {
                "status": "ok",
                "provider": "mineru-lightweight",
                "content": "用户 admin 具有管理员权限",
            },
        },
    }

    refs = _verify_attachment_evidence_refs([
        {
            "sheet": "SA-4c",
            "cell_or_range": "B5",
            "attachment": "SA-4c/screenshot.png",
            "excerpt": "用户 admin 具有管理员权限",
        }
    ], attachments)

    assert refs[0]["attachment"] == "SA-4c/screenshot.png"


def test_check_attachment_references_does_not_flag_successful_ocr_as_unparsed():
    item = AttachmentFile(
        index="1", rel_dir="SA-4c", filename="screenshot.webp",
        rel_path="SA-4c/screenshot.webp", file_type="webp", status="binary",
        extraction_status="binary", extracted_text="", size=19,
    )
    attachments = {
        "items": [item],
        "by_filename": {"screenshot.webp": [item]},
        "by_rel_path": {"sa-4c/screenshot.webp": [item]},
        "by_index": {"1": [item]},
        "by_sheet_norm": {},
        "ocr_by_path": {
            "sa-4c/screenshot.webp": {
                "status": "ok",
                "content": "用户 admin 具有管理员权限",
            },
        },
    }
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SA-4c"
    sheet["B5"] = "见附件1"

    assert _check_attachment_references("SA-4c", sheet, attachments) == []


def test_build_attachment_index_rejects_missing_directory(tmp_path):
    assert build_attachment_index(str(tmp_path / "missing")) == {}
