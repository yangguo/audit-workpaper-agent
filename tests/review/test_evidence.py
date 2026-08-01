import hashlib

import openpyxl

from review.evidence import build_evidence_graph, build_input_files


def test_build_input_files_hashes_workpaper_and_optional_inputs(tmp_path):
    workpaper = tmp_path / "wp.xlsx"
    checkpoints = tmp_path / "checkpoints.xlsx"
    attachments = tmp_path / "attachments.xlsx"
    workpaper.write_bytes(b"workpaper")
    checkpoints.write_bytes(b"checkpoints")
    attachments.write_bytes(b"attachments")

    inputs = build_input_files(
        workpaper_path=str(workpaper),
        checkpoints_path=str(checkpoints),
        attachments_preview_path=str(attachments),
    )

    assert [item.role for item in inputs] == [
        "workpaper",
        "checkpoints",
        "attachments_preview",
    ]
    assert inputs[0].filename == "wp.xlsx"
    assert inputs[0].size == len(b"workpaper")
    assert inputs[0].sha256 == hashlib.sha256(b"workpaper").hexdigest()


def test_build_evidence_graph_is_deterministic_and_preserves_formula():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PE-6"
    ws["A1"] = "标准审计程序"
    ws["B2"] = "=1+1"

    first = build_evidence_graph(wb, source_sha256="a" * 64)
    second = build_evidence_graph(wb, source_sha256="a" * 64)

    first_cells = first.sheets[0].cells
    second_cells = second.sheets[0].cells
    formula_cell = next(cell for cell in first_cells if cell.coordinate == "B2")

    assert [cell.evidence_id for cell in first_cells] == [
        cell.evidence_id for cell in second_cells
    ]
    assert first.sheets[0].sheet_hash == second.sheets[0].sheet_hash
    assert formula_cell.value == "=1+1"
    assert formula_cell.formula == "=1+1"


def test_build_evidence_graph_marks_explicit_truncation():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PE-6"
    ws["A1"] = "first"
    ws["B1"] = "second"
    ws["C1"] = "third"

    graph = build_evidence_graph(wb, source_sha256="a" * 64, max_cells=2)

    assert graph.capture_status == "truncated"
    assert graph.captured_cell_count == 2
    assert graph.omitted_cell_count == 1
    assert [cell.coordinate for cell in graph.sheets[0].cells] == ["A1", "B1"]


def test_build_evidence_graph_records_detected_layout_and_merged_ranges():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PE-6"
    ws["A1"] = "标准审计程序"
    ws["B1"] = "执行审计程序"
    ws["A2"] = "合并的标准程序"
    ws.merge_cells("A2:B2")

    graph = build_evidence_graph(wb, source_sha256="a" * 64)
    sheet = graph.sheets[0]

    assert sheet.layout_header_row == 1
    assert sheet.standard_column == 1
    assert sheet.execution_columns == [2]
    assert sheet.merged_ranges == ["A2:B2"]
