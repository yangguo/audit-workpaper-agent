from review.remediation import (
    annotate_finding_groups,
    build_remediation,
)
from review.remediation_catalog import load_remediation_catalog


def _finding(
    finding_id: str,
    *,
    rule_hint: str = "checkpoint-1",
    cell: str = "C5",
    status: str = "fail",
    suggestion: str = "补充该期间管理员权限清单并完成复核记录",
):
    return {
        "finding_id": finding_id,
        "issue_type": "覆盖性",
        "severity": "P1",
        "status": status,
        "risk_type": "覆盖性",
        "sheet": "SA-1",
        "cell": cell,
        "origin": "checkpoint",
        "rule_hint": rule_hint,
        "assertion_id": "scope.privileged_account.coverage",
        "claim_type": "population_coverage",
        "claim_subject": "SA-1|scope:privileged_account_scope",
        "claim_value": "coverage_insufficient",
        "suggestion": suggestion,
        "fix_suggestion_detail": {
            "required_evidence_type": "权限清单、复核记录",
            "acceptance_criteria": ["抽样记录与完整范围一致"],
        },
        "evidence_refs": [
            {
                "evidence_id": "cell:1",
                "sheet": "SA-1",
                "cell_or_range": "C5",
                "content_hash": "hash-1",
            }
        ],
        "quality": {
            "finding_id": finding_id,
            "provenance": {"input_set_sha256": "set-1"},
            "citation_validation": {
                "evidence_ids": ["cell:1"],
                "verified_refs": [
                    {
                        "evidence_id": "cell:1",
                        "content_hash": "hash-1",
                        "source_kind": "cell",
                    }
                ],
            },
            "grouping": {},
            "remediation": {},
        },
    }


def test_annotate_finding_groups_marks_exact_duplicates_without_deleting_rows():
    rows = annotate_finding_groups(
        [_finding("f-1"), _finding("f-2")], input_sha256="sha-1"
    )

    assert len(rows) == 2
    assert rows[0]["quality"]["grouping"]["duplicate_of"] is None
    assert rows[1]["quality"]["grouping"]["duplicate_of"] == rows[0]["quality"]["finding_id"]
    assert rows[0]["quality"]["grouping"]["root_cause_id"]
    assert rows[1]["quality"]["grouping"]["root_cause_id"] == rows[0]["quality"]["grouping"]["root_cause_id"]


def test_grouping_does_not_merge_same_cell_with_different_rule():
    rows = annotate_finding_groups(
        [
            _finding("f-1"),
            {
                **_finding("f-2", rule_hint="checkpoint-2"),
                "assertion_id": "record.period_date.consistency",
                "claim_type": "period_date",
                "claim_subject": "SA-1|scope:period",
                "claim_value": "date_mismatch",
            },
        ],
        input_sha256="sha-1",
    )

    assert rows[1]["quality"]["grouping"]["duplicate_of"] is None
    assert rows[1]["quality"]["grouping"]["root_cause_id"] != rows[0]["quality"]["grouping"]["root_cause_id"]


def test_unknown_rule_hint_is_unclustered():
    row = {**_finding("f-1", rule_hint=""), "assertion_id": ""}

    annotated = annotate_finding_groups([row], input_sha256="sha-1")[0]

    assert annotated["quality"]["grouping"]["root_cause_id"] is None


def test_distinct_assertions_with_same_location_and_evidence_are_not_duplicates():
    first = _finding("f-1")
    second = {
        **_finding("f-2"),
        "assertion_id": "record.period_date.consistency",
        "claim_type": "period_date",
        "claim_subject": "SA-1|scope:privileged_account_scope",
        "claim_value": "date_mismatch",
    }

    rows = annotate_finding_groups([first, second], input_set_sha256="set-1")

    assert rows[0]["quality"]["grouping"]["duplicate_of"] is None
    assert rows[1]["quality"]["grouping"]["duplicate_of"] is None


def test_grouping_never_uses_unverified_raw_evidence_for_duplicates():
    first = _finding("f-1")
    second = _finding("f-2")
    for row in (first, second):
        row["quality"]["citation_validation"] = {
            "evidence_ids": [],
            "verified_refs": [],
        }
        row["evidence_refs"] = [
            {"evidence_id": "cell:raw-only", "content_hash": "unverified"}
        ]

    rows = annotate_finding_groups([first, second], input_set_sha256="set-1")

    assert rows[0]["quality"]["grouping"]["duplicate_of"] is None
    assert rows[1]["quality"]["grouping"]["duplicate_of"] is None
    assert rows[0]["quality"]["grouping"]["root_cause_id"] is None


def test_grouping_uses_explicit_input_set_when_quality_provenance_is_absent():
    first = _finding("f-1")
    second = _finding("f-2")
    for row in (first, second):
        row["quality"]["provenance"] = {}

    rows = annotate_finding_groups([first, second], input_set_sha256="set-1")

    assert rows[0]["quality"]["grouping"]["duplicate_of"] is None
    assert rows[1]["quality"]["grouping"]["duplicate_of"] == rows[0]["quality"]["finding_id"]
    assert rows[0]["quality"]["grouping"]["root_cause_id"]


def test_grouping_normalizes_controlled_claim_components_for_duplicates():
    first = _finding("f-1")
    second = {
        **_finding("f-2"),
        "claim_subject": " sa-1 | scope:privileged_account_scope ",
        "claim_value": " COVERAGE_INSUFFICIENT ",
    }

    rows = annotate_finding_groups([first, second], input_set_sha256="set-1")

    assert rows[1]["quality"]["grouping"]["duplicate_of"] == rows[0]["quality"]["finding_id"]
    assert rows[1]["quality"]["grouping"]["root_cause_id"] == rows[0]["quality"]["grouping"]["root_cause_id"]


def test_grouping_preserves_existing_v1_finding_id():
    row = _finding("legacy-finding-id")

    annotated = annotate_finding_groups([row], input_set_sha256="set-1")[0]

    assert annotated["finding_id"] == "legacy-finding-id"
    assert annotated["quality"]["finding_id"].startswith("finding:")


def test_build_remediation_marks_generic_suggestion_for_human_refinement():
    remediation = build_remediation(
        {
            "assertion_id": "finding.unclassified",
            "risk_type": "证据不足",
            "suggestion": "建议补充完整证据",
            "sheet": "SA-1",
            "cell": "C5",
        },
        catalog=load_remediation_catalog(),
    )

    assert remediation["status"] == "needs_human_refinement"
    assert "trusted_template" in remediation["missing_fields"]
    assert remediation["required_evidence"] == []


def test_build_remediation_returns_actionable_structured_result():
    remediation = build_remediation(
        _finding("f-1"), catalog=load_remediation_catalog()
    )

    assert remediation["status"] == "actionable"
    assert remediation["action"]
    assert remediation["required_evidence"]
    assert remediation["acceptance_criteria"]
