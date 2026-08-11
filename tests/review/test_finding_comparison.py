from review.finding_comparison import compare_finding_sets


def _v1(*, finding_id, issue_type, sheet="SA-1", cell="C5", status="fail", evidence_ids=None):
    return {
        "finding_id": finding_id,
        "issue_type": issue_type,
        "risk_type": "覆盖性",
        "sheet": sheet,
        "cell": cell,
        "status": status,
        "quality": {
            "citation_validation": {"evidence_ids": evidence_ids or []},
        },
    }


def _v2(*, finding_id, issue_type, sheet="SA-1", cell="C5", status="fail", evidence_ids=None):
    return {
        "finding_id": finding_id,
        "issue_type": issue_type,
        "risk_type": "覆盖性",
        "sheet": sheet,
        "cell": cell,
        "status": status,
        "evidence_refs_v2": [
            {"evidence_id": evidence_id} for evidence_id in (evidence_ids or [])
        ],
    }


def test_compare_finding_sets_uses_exact_identity_and_reports_all_difference_categories():
    v1 = [
        _v1(finding_id="legacy-agree", issue_type="覆盖性", evidence_ids=["e-1"]),
        _v1(finding_id="legacy-status", issue_type="一致性", evidence_ids=["e-2"]),
        _v1(finding_id="legacy-evidence", issue_type="方法性", evidence_ids=["e-3"]),
        _v1(finding_id="legacy-only", issue_type="证据不足", cell="C8"),
    ]
    v2 = [
        _v2(finding_id="shadow-agree", issue_type="覆盖性", evidence_ids=["e-1"]),
        _v2(finding_id="shadow-status", issue_type="一致性", status="pass", evidence_ids=["e-2"]),
        _v2(finding_id="shadow-evidence", issue_type="方法性", evidence_ids=["e-4"]),
        _v2(finding_id="shadow-only", issue_type="逻辑性", cell="C9"),
    ]

    result = compare_finding_sets(v1, v2)

    assert result["counts"] == {
        "agreement": 1,
        "legacy_only": 1,
        "shadow_only": 1,
        "status_conflict": 1,
        "evidence_conflict": 1,
        "not_comparable": 0,
    }
    categories = {item["legacy_finding_id"] or item["shadow_finding_id"]: item["category"] for item in result["items"]}
    assert categories["legacy-agree"] == "agreement"
    assert categories["legacy-status"] == "status_conflict"
    assert categories["legacy-evidence"] == "evidence_conflict"


def test_compare_finding_sets_fails_closed_for_ambiguous_or_missing_identity():
    result = compare_finding_sets(
        [
            _v1(finding_id="legacy-ambiguous-a", issue_type="覆盖性", evidence_ids=["e-1"]),
            _v1(finding_id="legacy-ambiguous-b", issue_type="覆盖性", evidence_ids=["e-2"]),
            {"finding_id": "legacy-unidentifiable", "status": "fail"},
        ],
        [_v2(finding_id="shadow-ambiguous", issue_type="覆盖性", evidence_ids=["e-1"])],
    )

    assert result["counts"]["not_comparable"] == 4
    assert all(
        item["reason_code"] in {"ambiguous_identity", "missing_identity"}
        for item in result["items"]
        if item["category"] == "not_comparable"
    )
