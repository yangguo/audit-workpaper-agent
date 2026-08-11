import openpyxl

from review.evidence import build_evidence_graph
from review.evidence_provenance import (
    EvidenceProvenanceIndex,
    verify_finding_evidence,
)
from review.attachments import build_attachment_index


def _workbook_with_sheet(text: str = ""):
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "SA-1"
    worksheet["A1"] = text
    worksheet["C5"] = "密码长度至少 8"
    return workbook


def test_cell_reference_resolves_to_graph_identity_and_offsets():
    workbook = _workbook_with_sheet()
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(graph, workbook=workbook)

    result = index.verify_refs(
        [
            {
                "sheet": "SA-1",
                "cell_or_range": "C5",
                "excerpt": "密码长度至少 8",
            }
        ]
    )

    assert result.rejected_count == 0
    assert len(result.accepted_refs) == 1
    ref = result.accepted_refs[0]
    assert ref["source_kind"] == "cell"
    assert ref["evidence_id"].startswith("ev:")
    assert ref["content_hash"]
    assert ref["start_offset"] == 0
    assert ref["end_offset"] == len("密码长度至少 8")


def test_attachment_reference_requires_unique_scoped_verbatim_source(tmp_path):
    attachments_root = tmp_path / "attachments"
    attachments_root.mkdir()
    (attachments_root / "policy.txt").write_text("minimum password length: 8", encoding="utf-8")
    workbook = _workbook_with_sheet("请参阅 policy.txt")
    attachments = build_attachment_index(str(attachments_root))
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(graph, attachments=attachments, workbook=workbook)

    result = index.verify_refs(
        [
            {
                "sheet": "SA-1",
                "attachment": "policy.txt",
                "excerpt": "minimum password length: 8",
            }
        ]
    )

    assert result.rejected_count == 0
    ref = result.accepted_refs[0]
    assert ref["source_kind"] == "attachment"
    assert ref["source_ref"] == "policy.txt"
    assert ref["source_sha256"]
    assert ref["content_hash"]
    assert ref["start_offset"] == 0
    assert ref["end_offset"] == len("minimum password length: 8")


def test_attachment_reference_rejects_ambiguous_and_out_of_scope_sources(tmp_path):
    attachments_root = tmp_path / "attachments"
    (attachments_root / "one").mkdir(parents=True)
    (attachments_root / "two").mkdir(parents=True)
    (attachments_root / "one" / "policy.txt").write_text("shared text", encoding="utf-8")
    (attachments_root / "two" / "policy.txt").write_text("shared text", encoding="utf-8")
    (attachments_root / "foreign.txt").write_text("foreign text", encoding="utf-8")
    workbook = _workbook_with_sheet("请参阅 foreign.txt")
    attachments = build_attachment_index(str(attachments_root))
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(graph, attachments=attachments, workbook=workbook)

    ambiguous = index.verify_refs(
        [
            {
                "sheet": "SA-1",
                "attachment": "policy.txt",
                "excerpt": "shared text",
            }
        ]
    )
    out_of_scope = index.verify_refs(
        [
            {
                "sheet": "SA-1",
                "attachment": "one/policy.txt",
                "excerpt": "shared text",
            }
        ]
    )

    assert "ambiguous_source" in ambiguous.rejection_codes
    assert "out_of_scope_source" in out_of_scope.rejection_codes


def test_changed_attachment_snapshot_fails_closed(tmp_path):
    attachments_root = tmp_path / "attachments"
    attachments_root.mkdir()
    attachment = attachments_root / "policy.txt"
    attachment.write_text("old text", encoding="utf-8")
    workbook = _workbook_with_sheet("请参阅 policy.txt")
    attachments = build_attachment_index(str(attachments_root))
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(graph, attachments=attachments, workbook=workbook)

    attachment.write_text("new text", encoding="utf-8")
    result = index.verify_refs(
        [
            {
                "sheet": "SA-1",
                "attachment": "policy.txt",
                "excerpt": "old text",
            }
        ]
    )

    assert result.accepted_refs == []
    assert "content_mismatch" in result.rejection_codes


def test_fail_without_verified_evidence_is_downgraded_to_unknown():
    workbook = _workbook_with_sheet()
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(graph, workbook=workbook)
    finding = {
        "status": "fail",
        "severity": "P1",
        "risk_type": "证据不足",
        "sheet": "SA-1",
        "cell": "C5",
        "evidence_refs": [
            {"sheet": "SA-1", "cell_or_range": "C5", "excerpt": "错误摘录"}
        ],
    }

    updated, result = verify_finding_evidence(finding, index)

    assert result.rejected_count == 1
    assert updated["status"] == "unknown"
    assert updated["severity"] == "P2"
    assert "无法引用原始证据" in updated["unknown_reason"]
    assert updated["evidence_refs"] == []
