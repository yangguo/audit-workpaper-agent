import json
from pathlib import Path

from review.finding_taxonomy import load_assertion_catalog


def _finding(
    finding_id: str,
    assertion_id: str,
    claim_subject: str,
    claim_value: str,
    *,
    status: str = "fail",
):
    return {
        "status": status,
        "severity": "P1",
        "assertion_id": assertion_id,
        "claim_type": load_assertion_catalog().assertion(assertion_id).claim_type,
        "claim_subject": claim_subject,
        "claim_value": claim_value,
        "quality": {
            "finding_id": finding_id,
            "gates": {},
            "disposition": {
                "original_status": status,
                "effective_status": status,
                "original_severity": "P1",
                "reason_codes": [],
            },
        },
    }


def test_attachment_present_and_absent_are_conflicted_in_one_execution():
    from review.finding_consistency import annotate_finding_consistency

    rows, conflicts = annotate_finding_consistency(
        [
            _finding(
                "f-present",
                "attachment.inventory.presence",
                "SA-11|attachment:backup.docx",
                "present",
            ),
            _finding(
                "f-absent",
                "attachment.inventory.presence",
                "SA-11|attachment:backup.docx",
                "absent",
            ),
        ],
        input_set_sha256="input-set-1",
        catalog=load_assertion_catalog(),
        quality_mode="shadow",
    )

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "exclusive_claim_values"
    assert conflicts[0].claim_subject == "SA-11|attachment:backup.docx"
    assert {row["quality"]["consistency"]["status"] for row in rows} == {
        "conflicted"
    }
    assert [row["status"] for row in rows] == ["fail", "fail"]
    assert {
        row["quality"]["gates"]["cross_finding_consistency"]["status"]
        for row in rows
    } == {"flagged"}


def test_only_exact_controlled_subjects_can_be_compared():
    from review.finding_consistency import annotate_finding_consistency

    fixture = Path(__file__).parent / "fixtures" / "quality_regressions.json"
    rows, conflicts = annotate_finding_consistency(
        [
            {
                **item,
                "quality": {
                    "finding_id": item["finding_id"],
                    "gates": {},
                    "disposition": {
                        "original_status": item["status"],
                        "effective_status": item["status"],
                        "original_severity": item["severity"],
                        "reason_codes": [],
                    },
                },
            }
            for item in json.loads(fixture.read_text("utf-8"))["findings"]
        ],
        input_set_sha256="input-set-1",
        catalog=load_assertion_catalog(),
        quality_mode="shadow",
    )

    assert len(conflicts) == 1
    statuses = {
        row["quality"]["finding_id"]: row["quality"]["consistency"]["status"]
        for row in rows
    }
    assert statuses["f-present"] == "conflicted"
    assert statuses["f-absent"] == "conflicted"
    assert statuses["f-other-subject"] == "not_comparable"
    assert statuses["f-other-assertion"] == "not_comparable"


def test_on_mode_downgrades_only_conflicted_failures():
    from review.finding_consistency import annotate_finding_consistency

    rows, _ = annotate_finding_consistency(
        [
            _finding(
                "f-present",
                "attachment.inventory.presence",
                "SA-11|attachment:backup.docx",
                "present",
            ),
            _finding(
                "f-absent",
                "attachment.inventory.presence",
                "SA-11|attachment:backup.docx",
                "absent",
            ),
        ],
        input_set_sha256="input-set-1",
        catalog=load_assertion_catalog(),
        quality_mode="on",
    )

    assert {row["status"] for row in rows} == {"unknown"}
    assert all(
        "cross_finding_conflict" in row["quality"]["disposition"]["reason_codes"]
        for row in rows
    )
