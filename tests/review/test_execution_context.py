import json

from review.evidence import build_input_files


def _runtime_config(**overrides):
    from review.contracts import RuntimeConfigSnapshot

    values = {
        "review_model": "review-model-a",
        "review_endpoint_sha256": "endpoint-sha",
        "review_temperature": 0.1,
        "review_json_mode": True,
        "verify_ssl": True,
        "quality_mode": "shadow",
        "deterministic_crosscheck_mode": "all_findings",
        "evidence_agent_mode": "fallback",
        "evidence_snapshot_max_cells": 50_000,
        "challenger_full_text": True,
        "mineru_ocr_mode": "off",
        "mineru_ocr_language": "ch",
        "mineru_model_version": "vlm",
        "policy_mode": "shadow",
        "judgement_mode": "off",
        "judgement_max_requests": 200,
        "prompt_bundle_version": "review-prompts/1",
    }
    values.update(overrides)
    return RuntimeConfigSnapshot(**values)


def test_input_set_hash_is_order_independent_and_changes_with_attachment_contents(tmp_path):
    from review.execution_context import stable_input_set_sha256

    workpaper = tmp_path / "workpaper.xlsx"
    attachments = tmp_path / "attachments"
    attachment = attachments / "evidence.txt"
    attachments.mkdir()
    workpaper.write_bytes(b"xlsx-v1")
    attachment.write_text("config=10", encoding="utf-8")

    first_inputs = build_input_files(
        workpaper_path=str(workpaper), attachments_dir=str(attachments)
    )
    first_hash = stable_input_set_sha256(
        inputs=first_inputs, requested_sheets=["SA-11", "PE-6"]
    )

    attachment.write_text("config=20", encoding="utf-8")
    second_inputs = build_input_files(
        workpaper_path=str(workpaper), attachments_dir=str(attachments)
    )
    second_hash = stable_input_set_sha256(
        inputs=list(reversed(second_inputs)), requested_sheets=["PE-6", "SA-11"]
    )

    assert first_hash != second_hash
    assert second_hash == stable_input_set_sha256(
        inputs=second_inputs, requested_sheets=["SA-11", "PE-6"]
    )


def test_execution_context_keeps_snapshot_paths_private_and_fingerprints_runtime(tmp_path):
    from review.contracts import ExecutionComponentRef, PolicyPackRef
    from review.execution_context import (
        build_review_execution_context,
        stable_execution_sha256,
    )

    workpaper = tmp_path / "workpaper.xlsx"
    workpaper.write_bytes(b"xlsx-v1")
    inputs = build_input_files(workpaper_path=str(workpaper))
    runtime = _runtime_config()
    components = [
        ExecutionComponentRef(
            component_id="itgc-core", version="1.0.0", sha256="policy-sha"
        )
    ]
    context = build_review_execution_context(
        review_id="review-1",
        source="upload",
        requested_sheets=["SA-11"],
        inputs=inputs,
        snapshot_paths={"workpaper": str(workpaper)},
        policy_pack=PolicyPackRef(id="itgc-core", version="1.0.0"),
        judgement_policy_pack=None,
        engine_version="stage-a-quality-shadow",
        components=components,
        runtime_config=runtime,
    )

    serialized = context.model_dump(mode="json")
    serialized_text = json.dumps(serialized, ensure_ascii=False)
    assert "snapshot_paths" not in serialized
    assert str(workpaper) not in serialized_text
    assert context.manifest.inputs[0].path == "inputs/workpaper/workpaper.xlsx"
    assert context.manifest.input_set_sha256 == context.input_set_sha256
    assert context.manifest.execution_sha256 == context.execution_sha256
    assert context.manifest.runtime_config == runtime
    assert context.manifest.components == components

    changed_runtime = _runtime_config(review_model="review-model-b")
    changed_execution_hash = stable_execution_sha256(
        input_set_sha256=context.input_set_sha256,
        engine_version=context.manifest.engine_version,
        policy_pack=context.manifest.policy_pack,
        judgement_policy_pack=context.manifest.judgement_policy_pack,
        components=components,
        runtime_config=changed_runtime,
    )
    assert changed_execution_hash != context.execution_sha256
    assert context.input_set_sha256 == context.manifest.input_set_sha256


def test_runtime_config_fingerprints_endpoint_without_serializing_credentials(monkeypatch):
    from review.execution_context import capture_runtime_config

    monkeypatch.setenv(
        "LLM_BASE_URL", "https://client:secret@example.test/v1?token=private#fragment"
    )
    monkeypatch.setenv("REVIEW_LLM_MODEL", "review-model-a")
    monkeypatch.setenv("REVIEW_RESULT_QUALITY_MODE", "shadow")

    snapshot = capture_runtime_config()

    serialized = snapshot.model_dump_json()
    assert snapshot.review_endpoint_sha256
    assert "secret" not in serialized
    assert "private" not in serialized
    assert "example.test" not in serialized
