from review.remediation import (
    annotate_finding_groups,
    build_remediation,
)


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
    assert rows[1]["quality"]["grouping"]["duplicate_of"] == "f-1"
    assert rows[0]["quality"]["grouping"]["root_cause_id"]
    assert rows[1]["quality"]["grouping"]["root_cause_id"] == rows[0]["quality"]["grouping"]["root_cause_id"]


def test_grouping_does_not_merge_same_cell_with_different_rule():
    rows = annotate_finding_groups(
        [_finding("f-1"), _finding("f-2", rule_hint="checkpoint-2")],
        input_sha256="sha-1",
    )

    assert rows[1]["quality"]["grouping"]["duplicate_of"] is None
    assert rows[1]["quality"]["grouping"]["root_cause_id"] != rows[0]["quality"]["grouping"]["root_cause_id"]


def test_unknown_rule_hint_is_unclustered():
    row = _finding("f-1", rule_hint="")

    annotated = annotate_finding_groups([row], input_sha256="sha-1")[0]

    assert annotated["quality"]["grouping"]["root_cause_id"] is None


def test_build_remediation_marks_generic_suggestion_for_human_refinement():
    remediation = build_remediation(
        {
            "risk_type": "证据不足",
            "suggestion": "建议补充完整证据",
            "sheet": "SA-1",
            "cell": "C5",
        }
    )

    assert remediation["status"] == "needs_human_refinement"
    assert "action" in remediation["missing_fields"]
    assert remediation["required_evidence"]


def test_build_remediation_returns_actionable_structured_result():
    remediation = build_remediation(_finding("f-1"))

    assert remediation["status"] == "actionable"
    assert remediation["action"]
    assert remediation["required_evidence"] == ["权限清单、复核记录"]
    assert remediation["acceptance_criteria"] == ["抽样记录与完整范围一致"]
