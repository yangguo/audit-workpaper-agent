import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from review.evaluation import (
    compare_v1_v2,
    evaluate_quality_cases,
    evaluate_repeated_runs,
    semantic_finding_key,
)


def _manifest():
    return {
        "schema_version": "review-quality/1",
        "cases": [
            {
                "case_id": "case-1",
                "input_sha256": "sha-1",
                "adjudication_status": "adjudicated",
                "expected_findings": [
                    {
                        "match_key": {
                            "issue_type": "覆盖性",
                            "sheet": "SA-1",
                            "cell": "C5",
                        },
                        "status": "fail",
                        "severity": "P1",
                        "evidence_ids": ["cell:1"],
                        "primary_location": {
                            "source_kind": "cell",
                            "sheet": "SA-1",
                            "cell_or_range": "C5",
                        },
                    },
                    {
                        "match_key": {
                            "issue_type": "证据不足",
                            "sheet": "SA-1",
                            "cell": "C8",
                        },
                        "status": "unknown",
                        "severity": "P2",
                        "evidence_ids": [],
                        "primary_location": None,
                    },
                ],
            }
        ],
    }


def test_evaluate_quality_cases_calculates_quality_metrics_and_failures():
    actual = {
        "case-1": [
            {
                "issue_type": "覆盖性",
                "sheet": "SA-1",
                "cell": "C5",
                "status": "fail",
                "severity": "P1",
                "quality": {
                    "primary_location": {
                        "source_kind": "cell",
                        "sheet": "SA-1",
                        "cell_or_range": "C5",
                    },
                    "citation_validation": {
                        "status": "verified",
                        "verified_count": 1,
                        "rejected_count": 0,
                        "evidence_ids": ["cell:1"],
                    },
                    "gates": {
                        "deterministic_cross_check": {"status": "passed"},
                        "model_re_review": {"status": "not_run"},
                    },
                    "grouping": {"duplicate_of": None},
                },
            },
            {
                "issue_type": "多余发现",
                "sheet": "SA-1",
                "cell": "C9",
                "status": "fail",
                "severity": "P2",
                "quality": {
                    "citation_validation": {"status": "not_available"},
                    "gates": {},
                },
            },
        ]
    }

    result = evaluate_quality_cases(_manifest(), actual)

    assert result["metrics"]["finding_precision"] == 0.5
    assert result["metrics"]["finding_recall"] == 0.5
    assert result["metrics"]["citation_reproduction_rate"] == 1.0
    assert result["metrics"]["primary_location_resolvable_rate"] == 1.0
    assert result["metrics"]["gate_status_coverage"] == 0.5
    assert result["metrics"]["duplicate_rate"] == 0.0
    assert result["failures"]
    assert result["failures"][0]["case_id"] == "case-1"


def test_evaluate_quality_cases_requires_adjudication_before_promotion():
    manifest = _manifest()
    manifest["cases"][0]["adjudication_status"] = "pending"

    result = evaluate_quality_cases(manifest, {"case-1": []})

    assert result["promotion_ready"] is False
    assert any(item["code"] == "missing_adjudication" for item in result["failures"])


def test_legacy_manifest_keeps_baseline_metrics_but_never_promotes():
    manifest = {
        "schema_version": "review-quality/1",
        "cases": [
            {
                "case_id": "baseline-only",
                "input_sha256": "input-1",
                "adjudication_status": "adjudicated",
                "expected_findings": [],
            }
        ],
    }

    result = evaluate_quality_cases(manifest, {"baseline-only": []})

    assert result["metrics"]["finding_precision"] == 0.0
    assert result["promotion_ready"] is False
    assert any(
        failure["code"] == "legacy_manifest_not_promotion_eligible"
        for failure in result["failures"]
    )


def test_compare_v1_v2_returns_stable_difference_matrix():
    v1 = [
        {"finding_id": "f-1", "status": "fail", "quality": {"citation_validation": {"evidence_ids": ["e-1"]}}},
        {"finding_id": "f-2", "status": "unknown", "quality": {"citation_validation": {"evidence_ids": []}}},
    ]
    v2 = [
        {"finding_id": "f-1", "status": "fail", "evidence_refs_v2": [{"evidence_id": "e-1"}]},
        {"finding_id": "f-3", "status": "pass", "evidence_refs_v2": []},
    ]

    result = compare_v1_v2(v1, v2)

    assert result["counts"] == {
        "agreement": 1,
        "legacy_only": 1,
        "shadow_only": 1,
        "status_conflict": 0,
        "evidence_conflict": 0,
        "not_comparable": 0,
    }
    assert result["items"][0]["category"] == "agreement"


def test_evaluation_script_help_works_when_run_as_a_file():
    script = Path(__file__).parents[2] / "scripts" / "evaluate_review_quality.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "gold-set manifest" in completed.stdout


def test_review_quality_schema_and_examples_describe_v2_promotion_inputs():
    root = Path(__file__).parents[2] / "evaluation_sets" / "review-quality"
    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
    v2_manifest = schema["$defs"]["quality_manifest_v2"]
    v2_case = schema["$defs"]["quality_case_v2"]
    v2_finding = schema["$defs"]["expected_finding_v2"]

    assert v2_manifest["properties"]["schema_version"]["const"] == "review-quality/2"
    assert set(v2_case["required"]) >= {
        "input_set_sha256",
        "execution_sha256",
        "minimum_runs",
    }
    assert set(v2_finding["required"]) >= {
        "allowed_evidence_ids",
        "expected_duplicate_of",
        "expected_conflict",
        "expected_remediation",
    }

    example_manifest = json.loads(
        (root / "example-manifest.json").read_text(encoding="utf-8")
    )
    example_results = json.loads(
        (root / "example-results.json").read_text(encoding="utf-8")
    )
    assert example_manifest["schema_version"] == "review-quality/2"
    assert set(example_results) == {"v1", "v2", "repeated_runs"}
    case_id = example_manifest["cases"][0]["case_id"]
    assert len(example_results["repeated_runs"][case_id]) == 5
    example_report = evaluate_quality_cases(
        example_manifest,
        example_results["v1"],
        v2_by_case=example_results["v2"],
        repeated_runs_by_case=example_results["repeated_runs"],
    )
    assert not any(
        failure["code"] == "input_set_sha256_mismatch"
        for failure in example_report["failures"]
    )
    assert example_report["metrics"]["semantic_finding_stability"] == 1.0


def test_evaluation_fails_promotion_when_citation_reproduction_is_not_complete():
    manifest = _manifest()
    manifest["cases"][0]["expected_findings"][0]["evidence_ids"] = ["cell:missing"]

    result = evaluate_quality_cases(
        manifest,
        {
            "case-1": [
                {
                    "issue_type": "覆盖性",
                    "sheet": "SA-1",
                    "cell": "C5",
                    "status": "fail",
                    "quality": {
                        "primary_location": {
                            "source_kind": "cell",
                            "sheet": "SA-1",
                            "cell_or_range": "C5",
                        },
                        "citation_validation": {
                            "status": "invalid",
                            "evidence_ids": [],
                        },
                        "gates": {
                            "deterministic_cross_check": {"status": "passed"}
                        },
                    },
                },
                {
                    "issue_type": "证据不足",
                    "sheet": "SA-1",
                    "cell": "C8",
                    "status": "unknown",
                    "quality": {
                        "citation_validation": {"status": "not_available"},
                        "gates": {"deterministic_cross_check": {"status": "passed"}},
                    },
                },
            ]
        },
    )

    assert result["promotion_ready"] is False
    assert any(
        failure["code"] == "citation_reproduction_below_100"
        for failure in result["failures"]
    )


def test_evaluation_fails_when_not_run_is_mislabeled_as_passed():
    manifest = _manifest()
    result = evaluate_quality_cases(
        manifest,
        {
            "case-1": [
                {
                    "issue_type": "覆盖性",
                    "sheet": "SA-1",
                    "cell": "C5",
                    "status": "fail",
                    "quality": {
                        "citation_validation": {
                            "status": "verified",
                            "evidence_ids": ["cell:1"],
                        },
                        "gates": {
                            "deterministic_cross_check": {
                                "status": "passed",
                                "reason": "not_run by configuration",
                            }
                        },
                    },
                },
                {
                    "issue_type": "证据不足",
                    "sheet": "SA-1",
                    "cell": "C8",
                    "status": "unknown",
                    "quality": {
                        "citation_validation": {"status": "not_available"},
                        "gates": {"deterministic_cross_check": {"status": "not_run"}},
                    },
                },
            ]
        },
    )

    assert result["promotion_ready"] is False
    assert any(
        failure["code"] == "not_run_encoded_as_passed"
        for failure in result["failures"]
    )


def test_evaluation_fails_when_v2_p0_p1_precision_decreases():
    manifest = _manifest()
    manifest["cases"][0]["expected_findings"] = [
        manifest["cases"][0]["expected_findings"][0]
    ]
    v1 = {
        "case-1": [
            {
                "issue_type": "覆盖性",
                "sheet": "SA-1",
                "cell": "C5",
                "status": "fail",
                "severity": "P1",
                "quality": {
                    "citation_validation": {"status": "verified", "evidence_ids": ["cell:1"]},
                    "gates": {"deterministic_cross_check": {"status": "passed"}},
                },
            }
        ]
    }
    v2 = {
        "case-1": [
            {
                "issue_type": "覆盖性",
                "sheet": "SA-1",
                "cell": "C5",
                "status": "unknown",
                "severity": "P1",
                "quality": {
                    "citation_validation": {"status": "verified", "evidence_ids": ["cell:1"]},
                    "gates": {"deterministic_cross_check": {"status": "passed"}},
                },
            }
        ]
    }

    result = evaluate_quality_cases(manifest, v1, v2_by_case=v2)

    assert result["promotion_ready"] is False
    assert any(
        failure["code"] == "v2_p0_p1_precision_decreased"
        for failure in result["failures"]
    )


def test_p0_p1_precision_details_report_correct_findings_over_actual_high_findings():
    manifest = _manifest()
    manifest["cases"][0]["expected_findings"] = [
        manifest["cases"][0]["expected_findings"][0]
    ]
    correct = {
        "issue_type": "覆盖性",
        "sheet": "SA-1",
        "cell": "C5",
        "status": "fail",
        "severity": "P1",
        "quality": {
            "citation_validation": {"status": "verified", "evidence_ids": ["cell:1"]},
            "gates": {"deterministic_cross_check": {"status": "passed"}},
        },
    }
    unexpected = {
        **correct,
        "issue_type": "额外高风险发现",
        "cell": "C9",
    }

    result = evaluate_quality_cases(
        manifest,
        {"case-1": [correct, unexpected]},
        v2_by_case={"case-1": [correct, unexpected]},
    )

    assert result["metrics"]["v1_p0_p1_precision"] == 0.5
    assert result["metric_details"]["v1_p0_p1_precision"] == {
        "value": 0.5,
        "numerator": 1,
        "denominator": 2,
        "threshold": None,
        "status": "measured",
        "failure_case_ids": ["case-1"],
    }


def test_evaluation_fails_when_matched_finding_status_or_severity_differs():
    manifest = _manifest()
    manifest["cases"][0]["expected_findings"] = [
        manifest["cases"][0]["expected_findings"][0]
    ]
    actual = {
        "case-1": [
            {
                "issue_type": "覆盖性",
                "sheet": "SA-1",
                "cell": "C5",
                "status": "unknown",
                "severity": "P2",
                "quality": {
                    "primary_location": {
                        "source_kind": "cell",
                        "sheet": "SA-1",
                        "cell_or_range": "C5",
                    },
                    "citation_validation": {
                        "status": "verified",
                        "evidence_ids": ["cell:1"],
                    },
                    "gates": {
                        "deterministic_cross_check": {"status": "passed"},
                    },
                },
            }
        ]
    }

    result = evaluate_quality_cases(manifest, actual)

    assert result["promotion_ready"] is False
    assert {failure["code"] for failure in result["failures"]} >= {
        "status_mismatch",
        "severity_mismatch",
    }


def test_evaluation_fails_when_results_are_not_from_the_case_input_snapshot():
    manifest = _manifest()
    manifest["cases"][0]["expected_findings"] = [
        manifest["cases"][0]["expected_findings"][0]
    ]
    actual = {
        "case-1": [
            {
                "issue_type": "覆盖性",
                "sheet": "SA-1",
                "cell": "C5",
                "status": "fail",
                "severity": "P1",
                "quality": {
                    "primary_location": {
                        "source_kind": "cell",
                        "sheet": "SA-1",
                        "cell_or_range": "C5",
                    },
                    "citation_validation": {
                        "status": "verified",
                        "evidence_ids": ["cell:1"],
                    },
                    "gates": {
                        "deterministic_cross_check": {"status": "passed"},
                    },
                    "provenance": {"input_sha256": "wrong-source-sha"},
                },
            }
        ]
    }

    result = evaluate_quality_cases(manifest, actual)

    assert result["promotion_ready"] is False
    assert any(
        failure["code"] == "input_sha256_mismatch"
        for failure in result["failures"]
    )


def test_evaluation_fails_when_fail_finding_has_no_quality_envelope():
    manifest = _manifest()
    result = evaluate_quality_cases(
        manifest,
        {
            "case-1": [
                {
                    "issue_type": "覆盖性",
                    "sheet": "SA-1",
                    "cell": "C5",
                    "status": "fail",
                    "severity": "P1",
                },
                {
                    "issue_type": "证据不足",
                    "sheet": "SA-1",
                    "cell": "C8",
                    "status": "unknown",
                    "severity": "P2",
                    "quality": {"gates": {"deterministic_cross_check": {"status": "not_run"}}},
                },
            ]
        },
    )

    assert result["promotion_ready"] is False
    assert any(
        failure["code"] == "missing_quality_envelope"
        for failure in result["failures"]
    )


def test_v2_evaluation_matches_assertion_before_display_issue_type():
    manifest = {
        "schema_version": "review-quality/2",
        "cases": [
            {
                "case_id": "case-v2",
                "input_sha256": "sha-1",
                "adjudication_status": "adjudicated",
                "expected_findings": [
                    {
                        "match_key": {
                            "assertion_id": "attachment.reference.mapping",
                            "claim_subject": "SA-1|attachment:backup.docx",
                        },
                        "status": "fail",
                        "severity": "P1",
                    }
                ],
            }
        ],
    }
    actual = {
        "case-v2": [
            {
                "issue_type": "措辞完全不同",
                "assertion_id": "attachment.reference.mapping",
                "claim_subject": "SA-1|attachment:backup.docx",
                "status": "fail",
                "severity": "P1",
                "quality": {
                    "provenance": {"input_sha256": "sha-1"},
                    "citation_validation": {"status": "not_available"},
                    "gates": {},
                },
            }
        ]
    }

    result = evaluate_quality_cases(manifest, actual)

    assert result["metrics"]["finding_recall"] == 1.0
    assert not any(failure["code"] == "missing_finding" for failure in result["failures"])


def test_v2_evaluation_uses_sheet_as_the_legacy_scope_key_fallback():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    manifest = _v2_manifest([expected])
    finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    finding.pop("scope_key")

    result = evaluate_quality_cases(manifest, {"case-1": [finding]})

    assert result["metrics"]["finding_recall"] == 1.0
    assert not any(failure["code"] == "missing_finding" for failure in result["failures"])


def test_v2_evaluation_reports_a_non_mapping_match_key_without_crashing():
    manifest = {
        "schema_version": "review-quality/2",
        "cases": [
            {
                "case_id": "case-invalid-key",
                "input_sha256": "sha-1",
                "adjudication_status": "adjudicated",
                "expected_findings": [
                    {
                        "match_key": ["issue_type"],
                        "status": "fail",
                        "severity": "P1",
                    }
                ],
            }
        ],
    }

    result = evaluate_quality_cases(manifest, {"case-invalid-key": []})

    assert any(
        failure["code"] == "invalid_controlled_match_key"
        for failure in result["failures"]
    )


def test_v2_evaluation_rejects_a_controlled_match_key_without_scope():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    expected["match_key"].pop("scope_key")
    manifest = _v2_manifest([expected])
    finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )

    result = evaluate_quality_cases(manifest, {"case-1": [finding]})

    assert any(
        failure["code"] == "invalid_controlled_match_key"
        for failure in result["failures"]
    )


def test_v2_evaluation_rejects_an_expected_finding_without_required_contract_fields():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    expected.pop("allowed_evidence_ids")
    manifest = _v2_manifest([expected])
    finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )

    result = evaluate_quality_cases(manifest, {"case-1": [finding]})

    assert any(
        failure["code"] == "invalid_v2_expected_finding"
        and failure["field"] == "allowed_evidence_ids"
        for failure in result["failures"]
    )


def _quality_finding(
    assertion_id: str,
    claim_subject: str,
    *,
    finding_id: str = "",
    scope_key: str = "SA-11",
    status: str = "fail",
    severity: str = "P1",
    execution_sha256: str = "exec-1",
    evidence_ids: tuple[str, ...] = ("evidence:1",),
    claim_support_status: str = "supported",
    consistency_status: str = "consistent",
    duplicate_of: str | None = None,
    remediation_complete: bool = True,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id or f"run-local:{assertion_id}:{claim_subject}",
        "issue_type": "mutable display wording",
        "assertion_id": assertion_id,
        "claim_subject": claim_subject,
        "scope_key": scope_key,
        "sheet": scope_key,
        "status": status,
        "severity": severity,
        "quality": {
            "schema_version": "review-quality/2",
            "finding_id": finding_id or f"run-local:{assertion_id}:{claim_subject}",
            "citation_validation": {
                "status": "verified",
                "evidence_ids": list(evidence_ids),
            },
            "claim_support": {"status": claim_support_status},
            "consistency": {"status": consistency_status},
            "provenance": {
                "input_sha256": "input-1",
                "input_set_sha256": "input-set-1",
                "execution_sha256": execution_sha256,
            },
            "grouping": {"duplicate_of": duplicate_of},
            "remediation": (
                {
                    "status": "actionable",
                    "action": "Apply the approved correction.",
                    "required_evidence": ["reperformed control"],
                    "acceptance_criteria": ["independent reviewer signs off"],
                }
                if remediation_complete
                else {
                    "status": "needs_human_refinement",
                    "action": "",
                    "required_evidence": [],
                    "acceptance_criteria": [],
                }
            ),
        },
    }


def _v2_manifest(expected_findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "review-quality/2",
        "cases": [
            {
                "case_id": "case-1",
                "input_sha256": "input-1",
                "input_set_sha256": "input-set-1",
                "execution_sha256": "exec-1",
                "minimum_runs": 5,
                "adjudication_status": "adjudicated",
                "expected_findings": expected_findings,
            }
        ],
    }


def _expected(
    assertion_id: str,
    claim_subject: str,
    *,
    status: str = "fail",
    severity: str = "P1",
    requires_attachment_support: bool = False,
) -> dict[str, Any]:
    return {
        "match_key": {
            "assertion_id": assertion_id,
            "claim_subject": claim_subject,
            "scope_key": "SA-11",
        },
        "status": status,
        "severity": severity,
        "evidence_ids": ["evidence:1"],
        "allowed_evidence_ids": ["evidence:1"],
        "requires_attachment_support": requires_attachment_support,
        "expected_duplicate_of": None,
        "expected_conflict": False,
        "expected_remediation": {"required": severity in {"P0", "P1"}},
    }


def test_semantic_finding_key_uses_controlled_identity_not_display_or_run_id():
    first = _quality_finding(
        "attachment.reference.mapping",
        " SA-11 | attachment:backup.docx ",
        finding_id="run-one",
    )
    second = _quality_finding(
        "attachment.reference.mapping",
        "sa-11|attachment:backup.docx",
        finding_id="run-two",
    )
    second["issue_type"] = "completely changed prose"
    second["quality"]["citation_validation"]["evidence_ids"] = ["evidence:other"]

    assert semantic_finding_key(first) == (
        "attachment.reference.mapping",
        "sa-11|attachment:backup.docx",
        "sa-11",
    )
    assert semantic_finding_key(second) == semantic_finding_key(first)


def test_repeated_run_gate_rejects_unstable_semantic_findings():
    manifest = _v2_manifest([])
    key_sets = [
        [("a", "subject-a"), ("b", "subject-b"), ("c", "subject-c")],
        [("a", "subject-a"), ("d", "subject-d")],
        [("a", "subject-a"), ("e", "subject-e")],
        [("a", "subject-a"), ("f", "subject-f")],
        [("a", "subject-a"), ("g", "subject-g")],
    ]

    report = evaluate_repeated_runs(
        manifest,
        {
            "case-1": [
                [_quality_finding(assertion_id, subject) for assertion_id, subject in keys]
                for keys in key_sets
            ]
        },
    )

    assert report["metrics"]["semantic_finding_stability"] < 0.90
    assert report["metric_details"]["semantic_finding_stability"]["threshold"] == 0.90
    assert report["promotion_ready"] is False
    assert any(
        failure["code"] == "semantic_stability_below_threshold"
        for failure in report["failures"]
    )


def test_repeated_run_gate_marks_different_execution_identity_non_comparable():
    manifest = _v2_manifest([])
    runs = [[_quality_finding("a", "subject-a")] for _ in range(5)]
    runs[3] = [_quality_finding("a", "subject-a", execution_sha256="exec-other")]

    report = evaluate_repeated_runs(manifest, {"case-1": runs})

    assert report["promotion_ready"] is False
    assert any(
        failure["code"] == "non_comparable_runs" and failure["case_id"] == "case-1"
        for failure in report["failures"]
    )


def test_repeated_run_gate_rejects_a_different_input_set():
    manifest = _v2_manifest([])
    runs = [[_quality_finding("a", "subject-a")] for _ in range(5)]
    runs[2][0]["quality"]["provenance"]["input_set_sha256"] = "input-set-other"

    report = evaluate_repeated_runs(manifest, {"case-1": runs})

    assert report["promotion_ready"] is False
    assert any(
        failure["code"] == "input_set_sha256_mismatch"
        and failure["case_id"] == "case-1"
        for failure in report["failures"]
    )


def test_repeated_run_gate_rejects_a_v2_case_with_an_invalid_minimum_run_count():
    manifest = _v2_manifest([])
    manifest["cases"][0]["minimum_runs"] = "five"
    runs = [[_quality_finding("a", "subject-a")] for _ in range(5)]

    report = evaluate_repeated_runs(manifest, {"case-1": runs})

    assert report["promotion_ready"] is False
    assert any(
        failure["code"] == "invalid_v2_case"
        and failure["field"] == "minimum_runs"
        and failure["case_id"] == "case-1"
        for failure in report["failures"]
    )


def test_repeated_run_gate_accepts_five_identical_controlled_runs():
    manifest = _v2_manifest([])
    runs = [[_quality_finding("a", "subject-a")] for _ in range(5)]

    report = evaluate_repeated_runs(manifest, {"case-1": runs})

    assert report["promotion_ready"] is True
    assert report["metrics"]["semantic_finding_stability"] == 1.0
    assert report["metrics"]["status_agreement_rate"] == 1.0
    assert report["metrics"]["citation_identity_stability"] == 1.0


def test_quality_promotion_reports_publishable_conflicts_as_a_gate_failure():
    expected = _expected(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        requires_attachment_support=True,
    )
    manifest = _v2_manifest([expected])
    finding = _quality_finding(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        consistency_status="conflicted",
    )

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [finding]},
        v2_by_case={"case-1": [finding]},
        repeated_runs_by_case={"case-1": [[finding] for _ in range(5)]},
    )

    assert report["promotion_ready"] is False
    assert report["metrics"]["internal_conflict_rate"] == 1.0
    assert any(
        failure["code"] == "internal_conflict_rate_above_zero"
        for failure in report["failures"]
    )


def test_quality_promotion_requires_candidate_citation_reproduction():
    expected = _expected(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        requires_attachment_support=True,
    )
    manifest = _v2_manifest([expected])
    v1_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding = _quality_finding(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        evidence_ids=("evidence:wrong",),
    )

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [v1_finding]},
        v2_by_case={"case-1": [v2_finding]},
        repeated_runs_by_case={"case-1": [[v2_finding] for _ in range(5)]},
    )

    assert report["metrics"]["citation_reproduction_rate"] == 1.0
    assert report["metrics"]["v2_citation_reproduction_rate"] == 0.0
    assert any(
        failure["code"] == "v2_citation_reproduction_below_100"
        for failure in report["failures"]
    )


def test_quality_promotion_rejects_a_legacy_quality_envelope():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    manifest = _v2_manifest([expected])
    v1_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding["quality"]["schema_version"] = "review-quality/1"

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [v1_finding]},
        v2_by_case={"case-1": [v2_finding]},
        repeated_runs_by_case={"case-1": [[v2_finding] for _ in range(5)]},
    )

    assert report["promotion_ready"] is False
    assert any(
        failure["code"] == "quality_schema_not_promotion_eligible"
        and failure["case_id"] == "case-1"
        for failure in report["failures"]
    )


def test_quality_promotion_rejects_a_candidate_from_another_input_snapshot():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    manifest = _v2_manifest([expected])
    v1_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding["quality"]["provenance"]["input_sha256"] = "input-other"

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [v1_finding]},
        v2_by_case={"case-1": [v2_finding]},
        repeated_runs_by_case={"case-1": [[v2_finding] for _ in range(5)]},
    )

    assert any(
        failure["code"] == "input_sha256_mismatch"
        and failure.get("result_set") == "v2"
        and failure["case_id"] == "case-1"
        for failure in report["failures"]
    )


def test_quality_promotion_rejects_a_candidate_from_another_execution():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    manifest = _v2_manifest([expected])
    v1_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding = _quality_finding(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        execution_sha256="exec-other",
    )
    repeated_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [v1_finding]},
        v2_by_case={"case-1": [v2_finding]},
        repeated_runs_by_case={"case-1": [[repeated_finding] for _ in range(5)]},
    )

    assert any(
        failure["code"] == "execution_sha256_mismatch"
        and failure.get("result_set") == "v2"
        and failure["case_id"] == "case-1"
        for failure in report["failures"]
    )


def test_quality_promotion_rejects_a_candidate_gate_that_lies_about_not_running():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    manifest = _v2_manifest([expected])
    v1_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    v2_finding["quality"]["gates"] = {
        "deterministic_cross_check": {
            "status": "passed",
            "reason": "not_run by configuration",
        }
    }
    repeated_finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [v1_finding]},
        v2_by_case={"case-1": [v2_finding]},
        repeated_runs_by_case={"case-1": [[repeated_finding] for _ in range(5)]},
    )

    assert any(
        failure["code"] == "not_run_encoded_as_passed"
        and failure.get("result_set") == "v2"
        and failure["case_id"] == "case-1"
        for failure in report["failures"]
    )


def test_quality_promotion_rejects_duplicate_merge_of_distinct_assertions():
    first = _quality_finding(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        finding_id="finding:first",
    )
    second = _quality_finding(
        "configuration.asset_coverage.support",
        "SA-11|asset:backup-server",
        finding_id="finding:second",
        duplicate_of="finding:first",
    )
    manifest = _v2_manifest(
        [
            _expected("attachment.reference.mapping", "SA-11|attachment:backup.docx"),
            _expected("configuration.asset_coverage.support", "SA-11|asset:backup-server"),
        ]
    )

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [first, second]},
        v2_by_case={"case-1": [first, second]},
        repeated_runs_by_case={"case-1": [[first, second] for _ in range(5)]},
    )

    assert report["promotion_ready"] is False
    assert report["metrics"]["false_duplicate_merge_count"] == 1
    assert any(
        failure["code"] == "false_duplicate_merge_detected"
        for failure in report["failures"]
    )


def test_quality_promotion_counts_an_undeclared_duplicate_merge_as_false():
    expected = _expected(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    manifest = _v2_manifest([expected])
    first = _quality_finding(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        finding_id="finding:first",
    )
    duplicate = _quality_finding(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        finding_id="finding:unexpected-duplicate",
        duplicate_of="finding:first",
    )

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [first, duplicate]},
        v2_by_case={"case-1": [first, duplicate]},
        repeated_runs_by_case={"case-1": [[first] for _ in range(5)]},
    )

    assert report["metrics"]["false_duplicate_merge_count"] == 1
    assert any(
        failure["code"] == "false_duplicate_merge_detected"
        and failure["finding_id"] == "finding:unexpected-duplicate"
        for failure in report["failures"]
    )


def test_quality_promotion_rejects_incomplete_p0_p1_remediation():
    expected = _expected(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
    )
    manifest = _v2_manifest([expected])
    finding = _quality_finding(
        "attachment.reference.mapping",
        "SA-11|attachment:backup.docx",
        remediation_complete=False,
    )

    report = evaluate_quality_cases(
        manifest,
        {"case-1": [finding]},
        v2_by_case={"case-1": [finding]},
        repeated_runs_by_case={"case-1": [[finding] for _ in range(5)]},
    )

    assert report["promotion_ready"] is False
    assert report["metrics"]["p0_p1_remediation_completeness"] == 0.0
    assert any(
        failure["code"] == "p0_p1_remediation_incomplete"
        for failure in report["failures"]
    )


def test_evaluation_script_reads_repeated_run_payload(tmp_path):
    manifest = _v2_manifest(
        [_expected("attachment.reference.mapping", "SA-11|attachment:backup.docx")]
    )
    finding = _quality_finding(
        "attachment.reference.mapping", "SA-11|attachment:backup.docx"
    )
    manifest_path = tmp_path / "manifest.json"
    results_path = tmp_path / "results.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    results_path.write_text(
        json.dumps(
            {
                "v1": {"case-1": [finding]},
                "v2": {"case-1": [finding]},
                "repeated_runs": {"case-1": [[finding] for _ in range(5)]},
            }
        ),
        encoding="utf-8",
    )
    script = Path(__file__).parents[2] / "scripts" / "evaluate_review_quality.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--manifest",
            str(manifest_path),
            "--results",
            str(results_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # One synthetic case cannot satisfy the 6-case / 60-finding release sample,
    # but the CLI must still evaluate and display the supplied repeated runs.
    assert completed.returncode == 2
    assert '"semantic_finding_stability"' in completed.stdout
    assert '"missing_repeated_runs"' not in completed.stdout


def test_quality_promotion_requires_and_accepts_a_full_controlled_sample():
    manifest: dict[str, Any] = {"schema_version": "review-quality/2", "cases": []}
    v1: dict[str, list[dict[str, Any]]] = {}
    v2: dict[str, list[dict[str, Any]]] = {}
    repeated_runs: dict[str, list[list[dict[str, Any]]]] = {}
    for case_number in range(6):
        case_id = f"case-{case_number}"
        scope_key = f"SA-{case_number}"
        expected_findings = []
        findings = []
        for finding_number in range(10):
            assertion_id = "attachment.reference.mapping"
            subject = f"{scope_key}|attachment:backup-{finding_number}.docx"
            expected = _expected(assertion_id, subject)
            expected["match_key"]["scope_key"] = scope_key
            expected_findings.append(expected)
            findings.append(
                _quality_finding(
                    assertion_id,
                    subject,
                    finding_id=f"{case_id}:finding-{finding_number}",
                    scope_key=scope_key,
                )
            )
        manifest["cases"].append(
            {
                "case_id": case_id,
                "input_sha256": "input-1",
                "input_set_sha256": "input-set-1",
                "execution_sha256": "exec-1",
                "minimum_runs": 5,
                "adjudication_status": "adjudicated",
                "expected_findings": expected_findings,
            }
        )
        v1[case_id] = findings
        v2[case_id] = findings
        repeated_runs[case_id] = [findings for _ in range(5)]

    report = evaluate_quality_cases(
        manifest,
        v1,
        v2_by_case=v2,
        repeated_runs_by_case=repeated_runs,
    )

    assert report["promotion_ready"] is True
    assert report["metrics"]["adjudicated_case_count"] == 6
    assert report["metrics"]["adjudicated_finding_count"] == 60
    assert report["metric_details"]["attachment_claim_support_rate"]["status"] == "not_applicable"
