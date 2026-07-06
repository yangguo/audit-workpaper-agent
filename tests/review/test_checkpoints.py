import openpyxl

from review.checkpoints import (
    load_checkpoints_xlsx,
    _split_checkpoints,
    _extract_checkpoint_keywords,
)


def test_split_checkpoints_strips_numbering():
    assert _split_checkpoints("1. 检查用户清单\n2. 核对权限") == ["检查用户清单", "核对权限"]


def test_split_checkpoints_handles_empty():
    assert _split_checkpoints("") == []
    assert _split_checkpoints("   ") == []


def test_split_checkpoints_single_chunk():
    assert _split_checkpoints("单条检查要点") == ["单条检查要点"]


def test_extract_checkpoint_keywords_vocab_hits():
    assert _extract_checkpoint_keywords("获取用户清单并核对权限") == ["用户清单"]


def test_extract_checkpoint_keywords_segments_when_no_vocab():
    out = _extract_checkpoint_keywords("某段含中文的关键描述文字")
    assert out == ["某段含中文的关键描述文字"]


def test_extract_checkpoint_keywords_empty():
    assert _extract_checkpoint_keywords("") == []


def test_load_checkpoints_xlsx_groups_by_sheet(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="SA-4c")
    ws.cell(row=1, column=3, value="检查用户清单")
    ws.cell(row=2, column=1, value=None)
    ws.cell(row=2, column=3, value="核对权限矩阵")
    ws.cell(row=3, column=1, value="SA-5")
    ws.cell(row=3, column=3, value="检查变更日志")
    path = tmp_path / "checkpoints.xlsx"
    wb.save(str(path))

    result = load_checkpoints_xlsx(str(path))
    assert result == {
        "SA-4c": ["检查用户清单", "核对权限矩阵"],
        "SA-5": ["检查变更日志"],
    }


def test_load_checkpoints_xlsx_empty_path_returns_empty():
    assert load_checkpoints_xlsx("") == {}
