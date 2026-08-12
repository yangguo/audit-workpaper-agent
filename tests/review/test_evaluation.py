import subprocess
import sys
from pathlib import Path

from review.evaluation import evaluate_quality_cases, compare_v1_v2


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
