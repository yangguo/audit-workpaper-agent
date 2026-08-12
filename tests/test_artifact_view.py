import pytest

import main as main_mod
from review.artifact_view import build_artifact_view
from review.contracts import ReviewManifest
from storage.review_artifact_store import ReviewArtifactStore


def _manifest():
    return {
        "review_id": "rid-1",
        "artifact_status": "completed",
        "engine_version": "stage-b-policy-shadow",
        "created_at": "2026-08-04T00:00:00Z",
        "requested_sheets": ["SA-4c"],
        "inputs": [
            {
                "role": "workpaper",
                "path": "/private/server/path/workpaper.xlsx",
                "filename": "workpaper.xlsx",
                "sha256": "sha-workpaper",
                "size": 42,
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        ],
        "policy_pack": {"id": "itgc-core", "version": "1.0.0"},
        "judgement_policy_pack": {"id": "itgc-judgement", "version": "1.0.0"},
    }


def test_build_artifact_view_exposes_stages_without_server_paths():
    payload = build_artifact_view(
        review_id="rid-1",
        manifest=_manifest(),
        evidence={
            "source_sha256": "source-sha",
            "capture_status": "complete",
            "captured_cell_count": 12,
            "omitted_cell_count": 0,
            "sheets": [{"name": "SA-4c"}],
        },
        plan={
            "plan_id": "plan-1",
            "scope": {"target_sheets": ["SA-4c"], "status": "ok"},
            "items": [{"rule_id": "rule-1"}],
            "skipped": [],
        },
        policy_findings={
            "stats": {"candidates": 1},
            "findings": [
                {
                    "finding_id": "finding-b",
                    "rule_id": "rule-1",
                    "rule_version": "1.0.0",
                    "issue_type": "证据类型缺失",
                    "severity": "P1",
                    "status": "fail",
                    "verification_status": "supported",
                    "evidence_refs_v2": [
                        {
                            "evidence_id": "ev-1",
                            "quote": "执行描述",
                            "content_hash": "hash-1",
                        }
                    ],
                }
            ],
        },
        v2_findings={
            "stats": {"total_findings": 1},
            "findings": [
                {
                    "finding_id": "finding-c",
                    "rule_id": "rule-c",
                    "issue_type": "程序对应性不足",
                    "status": "unknown",
                    "decision": "insufficient",
                    "verification_status": "invalid",
                    "unknown_reason": "引用不足",
                }
            ],
        },
    )

    assert payload["source_sha256"] == "source-sha"
    assert payload["inputs"] == [
        {
            "role": "workpaper",
            "filename": "workpaper.xlsx",
            "sha256": "sha-workpaper",
            "size": 42,
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    ]
    assert "path" not in payload["inputs"][0]
    assert payload["stages"]["stage_a"]["captured_cell_count"] == 12
    assert payload["stages"]["stage_b"]["findings"][0]["rule_id"] == "rule-1"
    assert payload["stages"]["stage_c"]["findings"][0]["status"] == "unknown"


def test_build_artifact_view_marks_stage_c_disabled_when_not_configured():
    manifest = _manifest()
    manifest["judgement_policy_pack"] = None

    payload = build_artifact_view(review_id="rid-1", manifest=manifest)

    assert payload["stages"]["stage_b"]["status"] == "running"
    assert payload["stages"]["stage_c"] == {"status": "disabled", "findings": []}


def test_build_artifact_view_keeps_completed_stage_b_visible_when_stage_c_fails():
    manifest = _manifest()
    manifest["artifact_status"] = "error"
    manifest["artifact_error"] = "RuntimeError: stage c boom"

    payload = build_artifact_view(
        review_id="rid-stage-c-error",
        manifest=manifest,
        evidence={"sheets": []},
        plan={"scope": {}, "items": [], "skipped": []},
        policy_findings={"stats": {}, "findings": []},
    )

    assert payload["stages"]["stage_a"]["status"] == "completed"
    assert payload["stages"]["stage_b"]["status"] == "completed"
    assert payload["stages"]["stage_c"]["status"] == "error"


def test_build_artifact_view_exposes_bounded_v1_shadow_comparison():
    payload = build_artifact_view(
        review_id="rid-compare",
        manifest=_manifest(),
        comparison={
            "schema_version": "review-finding-comparison/1",
            "counts": {"agreement": 1, "legacy_only": 2},
            "items": [
                {
                    "category": "legacy_only",
                    "legacy_finding_id": "legacy-1",
                    "shadow_finding_id": None,
                    "v1_status": "fail",
                    "v2_status": None,
                }
            ],
        },
    )

    assert payload["comparison"]["status"] == "available"
    assert payload["comparison"]["authority"] == "v1"
    assert payload["comparison"]["candidate_source"] == "stage_c_shadow"
    assert payload["comparison"]["counts"]["legacy_only"] == 2
    assert payload["comparison"]["items"][0]["legacy_finding_id"] == "legacy-1"


def test_build_artifact_view_exposes_only_whitelisted_execution_identity():
    manifest = _manifest()
    manifest.update(
        {
            "input_set_sha256": "input-set-sha",
            "execution_sha256": "execution-sha",
            "runtime_config": {
                "review_model": "review-model-a",
                "review_endpoint_sha256": "endpoint-sha",
                "review_temperature": 0.2,
                "quality_mode": "shadow",
                "judgement_mode": "off",
                "api_key": "must-not-leak",
            },
            "components": [
                {
                    "component_id": "review-quality-remediation",
                    "version": "1.0.0",
                    "sha256": "component-sha",
                    "path": "/private/server/policy_packs",
                }
            ],
        }
    )

    payload = build_artifact_view(review_id="rid-identity", manifest=manifest)

    assert payload["input_set_sha256"] == "input-set-sha"
    assert payload["execution_sha256"] == "execution-sha"
    assert payload["runtime_config"] == {
        "review_model": "review-model-a",
        "review_endpoint_sha256": "endpoint-sha",
        "review_temperature": 0.2,
        "quality_mode": "shadow",
        "judgement_mode": "off",
    }
    assert payload["components"] == [
        {
            "component_id": "review-quality-remediation",
            "version": "1.0.0",
            "sha256": "component-sha",
        }
    ]
    assert "/private/server" not in str(payload)
    assert "must-not-leak" not in str(payload)


@pytest.mark.asyncio
async def test_review_artifact_route_returns_bounded_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    store = ReviewArtifactStore()
    store.begin(ReviewManifest(review_id="rid-api", source="workpaper.xlsx"))

    payload = await main_mod.review_artifact("rid-api")

    assert payload["review_id"] == "rid-api"
    assert payload["artifact_status"] == "running"
    assert "inputs" in payload
    assert payload["stages"]["stage_b"]["status"] == "disabled"
    assert payload["stages"]["stage_c"]["status"] == "disabled"


@pytest.mark.asyncio
async def test_review_artifact_route_returns_404_for_unknown_review(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))

    with pytest.raises(main_mod.HTTPException) as exc_info:
        await main_mod.review_artifact("missing-review")

    assert exc_info.value.status_code == 404
