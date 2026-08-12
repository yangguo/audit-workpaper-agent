import openpyxl

from review.attachments import build_attachment_index
from review.evidence import build_evidence_graph
from review.evidence_provenance import EvidenceProvenanceIndex
from review.finding_taxonomy import load_assertion_catalog


def _workbook(text: str = "见附件 backup.txt"):
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "SA-11"
    worksheet["A1"] = text
    worksheet["C5"] = "底稿中声明已检查备份策略"
    return workbook


def test_cell_quote_does_not_support_attachment_content_claim(tmp_path):
    from review.evidence_facts import EvidenceFactRegistry, evaluate_claim_support

    workbook = _workbook()
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(graph, workbook=workbook)
    registry = EvidenceFactRegistry.from_provenance(index)
    cell_ref = index.verify_refs(
        [{"sheet": "SA-11", "cell_or_range": "C5", "excerpt": "底稿中声明"}]
    ).accepted_refs
    assertion = load_assertion_catalog().assertion("attachment.content.support")

    support = evaluate_claim_support(
        finding={
            "status": "fail",
            "assertion_id": "attachment.content.support",
            "claim_type": "attachment_content",
            "claim_subject": "SA-11|attachment:backup.txt",
            "claim_value": "backup_policy_present",
        },
        assertion=assertion,
        verified_refs=cell_ref,
        registry=registry,
    )

    assert support.status == "partial"
    assert support.supporting_evidence_ids == []
    assert "verified_attachment_evidence" in support.missing_requirements


def test_frozen_attachment_quote_supports_attachment_content_claim(tmp_path):
    from review.evidence_facts import EvidenceFactRegistry, evaluate_claim_support

    root = tmp_path / "attachments"
    root.mkdir()
    (root / "backup.txt").write_text("backup retention is 30 days", encoding="utf-8")
    workbook = _workbook()
    attachments = build_attachment_index(str(root))
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(graph, attachments=attachments, workbook=workbook)
    refs = index.verify_refs(
        [
            {
                "sheet": "SA-11",
                "attachment": "backup.txt",
                "excerpt": "backup retention is 30 days",
            }
        ]
    ).accepted_refs
    registry = EvidenceFactRegistry.from_provenance(index)
    assertion = load_assertion_catalog().assertion("attachment.content.support")

    support = evaluate_claim_support(
        finding={
            "status": "fail",
            "assertion_id": assertion.assertion_id,
            "claim_type": assertion.claim_type,
            "claim_subject": "SA-11|attachment:backup.txt",
            "claim_value": "backup_policy_present",
        },
        assertion=assertion,
        verified_refs=refs,
        registry=registry,
    )

    assert support.status == "supported"
    assert support.supporting_evidence_ids == [refs[0]["evidence_id"]]


def test_preview_attachment_can_only_partially_support_presence_claim():
    from review.contracts import EvidenceFact
    from review.evidence_facts import EvidenceFactRegistry, evaluate_claim_support

    registry = EvidenceFactRegistry(
        [
            EvidenceFact(
                fact_id="attachment:preview-1",
                fact_type="attachment",
                source_ref="backup.txt",
                source_sha256="",
                content_hash="preview-content",
                sheet_scope=["SA-11"],
                extraction_status="ok",
                source_type="preview",
            )
        ]
    )
    assertion = load_assertion_catalog().assertion("attachment.inventory.presence")

    support = evaluate_claim_support(
        finding={
            "status": "fail",
            "assertion_id": assertion.assertion_id,
            "claim_type": assertion.claim_type,
            "claim_subject": "SA-11|attachment:backup.txt",
            "claim_value": "present",
        },
        assertion=assertion,
        verified_refs=[
            {
                "source_kind": "attachment",
                "evidence_id": "attachment:preview-1",
                "source_ref": "backup.txt",
            }
        ],
        registry=registry,
    )

    assert support.status == "partial"
    assert "frozen_attachment_source" in support.missing_requirements


def test_unparsed_frozen_file_supports_presence_but_not_content(tmp_path):
    from review.evidence_facts import EvidenceFactRegistry, evaluate_claim_support

    root = tmp_path / "attachments"
    root.mkdir()
    (root / "backup.pdf").write_bytes(b"not a parseable pdf")
    workbook = _workbook("见附件 backup.pdf")
    graph = build_evidence_graph(workbook, source_sha256="workpaper-sha")
    index = EvidenceProvenanceIndex(
        graph,
        attachments=build_attachment_index(str(root)),
        workbook=workbook,
    )
    refs = index.verify_refs(
        [{"sheet": "SA-11", "attachment": "backup.pdf"}]
    ).accepted_refs
    registry = EvidenceFactRegistry.from_provenance(index)
    catalog = load_assertion_catalog()

    presence = evaluate_claim_support(
        finding={"status": "fail", "sheet": "SA-11"},
        assertion=catalog.assertion("attachment.inventory.presence"),
        verified_refs=refs,
        registry=registry,
    )
    content = evaluate_claim_support(
        finding={"status": "fail", "sheet": "SA-11"},
        assertion=catalog.assertion("attachment.content.support"),
        verified_refs=refs,
        registry=registry,
    )

    assert presence.status == "supported"
    assert content.status == "partial"
    assert "attachment_content_quote" in content.missing_requirements


def test_pass_finding_does_not_require_claim_support():
    from review.evidence_facts import EvidenceFactRegistry, evaluate_claim_support

    assertion = load_assertion_catalog().assertion("attachment.content.support")
    support = evaluate_claim_support(
        finding={"status": "pass", "assertion_id": assertion.assertion_id},
        assertion=assertion,
        verified_refs=[],
        registry=EvidenceFactRegistry([]),
    )

    assert support.status == "not_required"
