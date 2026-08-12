"""Immutable identity for one review's frozen inputs and runtime choices."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from review.contracts import (
    ExecutionComponentRef,
    InputFile,
    InputRole,
    PolicyPackRef,
    ReviewManifest,
    RuntimeConfigSnapshot,
)
from review.evidence import sha256_path
from review.llm import review_llm_runtime_settings


_DEFAULT_MAX_CELLS = 50_000
_DEFAULT_JUDGEMENT_MAX_REQUESTS = 200
_CHOICE_VALUES = {
    "quality": {"off", "shadow", "on"},
    "crosscheck": {"all_findings", "p0_only", "off"},
    "agent": {"off", "fallback", "always"},
    "policy": {"shadow", "off"},
    "judgement": {"shadow", "off"},
    "mineru": {"off", "auto", "lightweight", "precise"},
}


class ReviewExecutionContext(BaseModel):
    """Private paths plus the manifest shared by V1 and shadow capture."""

    model_config = ConfigDict(frozen=True)

    manifest: ReviewManifest
    input_set_sha256: str
    execution_sha256: str
    runtime_config: RuntimeConfigSnapshot
    components: list[ExecutionComponentRef] = Field(default_factory=list)
    snapshot_paths: dict[InputRole, str] = Field(default_factory=dict, exclude=True)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _normalise_requested_sheets(requested_sheets: Sequence[str]) -> list[str]:
    values = {
        str(value or "")
        .strip()
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        for value in requested_sheets
        if str(value or "").strip()
    }
    return sorted(values)


def _manifest_requested_sheets(requested_sheets: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in requested_sheets:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def stable_input_set_sha256(
    *, inputs: Sequence[InputFile], requested_sheets: Sequence[str]
) -> str:
    """Fingerprint the complete, content-addressed input set.

    File locations and display filenames are intentionally excluded: content,
    role, media type and size describe the snapshot used by the engine without
    leaking a local path or changing when a user renames an upload.
    """

    input_rows = sorted(
        (
            {
                "role": item.role,
                "sha256": item.sha256,
                "size": int(item.size),
                "media_type": item.media_type,
            }
            for item in inputs
        ),
        key=lambda item: (
            str(item["role"]),
            str(item["sha256"]),
            int(item["size"]),
            str(item["media_type"]),
        ),
    )
    return _sha256_json(
        {
            "schema_version": "review-input-set/1",
            "requested_sheets": _normalise_requested_sheets(requested_sheets),
            "inputs": input_rows,
        }
    )


def _pack_payload(value: PolicyPackRef | None) -> dict[str, str] | None:
    return value.model_dump(mode="json") if value is not None else None


def _sorted_components(
    components: Sequence[ExecutionComponentRef],
) -> list[dict[str, str]]:
    return [
        component.model_dump(mode="json")
        for component in sorted(
            components,
            key=lambda component: (
                component.component_id,
                component.version,
                component.sha256,
            ),
        )
    ]


def stable_execution_sha256(
    *,
    input_set_sha256: str,
    engine_version: str,
    policy_pack: PolicyPackRef | None,
    judgement_policy_pack: PolicyPackRef | None,
    components: Sequence[ExecutionComponentRef],
    runtime_config: RuntimeConfigSnapshot,
) -> str:
    """Fingerprint all non-secret choices that can change review output."""

    return _sha256_json(
        {
            "schema_version": "review-execution/1",
            "input_set_sha256": str(input_set_sha256 or ""),
            "engine_version": str(engine_version or ""),
            "policy_pack": _pack_payload(policy_pack),
            "judgement_policy_pack": _pack_payload(judgement_policy_pack),
            "components": _sorted_components(components),
            "runtime_config": runtime_config.model_dump(mode="json"),
        }
    )


def _choice(name: str, env_name: str, default: str) -> str:
    value = os.getenv(env_name, default).strip().lower()
    allowed = _CHOICE_VALUES[name]
    if value not in allowed:
        raise ValueError(f"{env_name} must be one of {', '.join(sorted(allowed))}")
    return value


def _positive_int(env_name: str, default: int) -> int:
    try:
        value = int(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else default


def _strict_positive_int(env_name: str, default: int) -> int:
    try:
        value = int(os.getenv(env_name, str(default)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{env_name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{env_name} must be greater than zero")
    return value


def _bool(env_name: str, default: bool) -> bool:
    value = os.getenv(env_name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _endpoint_sha256(raw_endpoint: str) -> str:
    """Hash a normalized endpoint without retaining credentials or query data."""

    raw_endpoint = str(raw_endpoint or "").strip()
    if not raw_endpoint:
        return hashlib.sha256(b"").hexdigest()
    try:
        parsed = urlsplit(raw_endpoint)
        if parsed.scheme and parsed.hostname:
            hostname = parsed.hostname.lower()
            port = f":{parsed.port}" if parsed.port else ""
            path = parsed.path or ""
            canonical = urlunsplit(
                (parsed.scheme.lower(), f"{hostname}{port}", path, "", "")
            )
        else:
            canonical = raw_endpoint.split("?", 1)[0].split("#", 1)[0]
    except ValueError:
        canonical = raw_endpoint.split("?", 1)[0].split("#", 1)[0]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def capture_runtime_config() -> RuntimeConfigSnapshot:
    """Capture all current output-affecting, non-secret runtime choices."""

    llm = review_llm_runtime_settings()
    return RuntimeConfigSnapshot(
        review_model=str(llm["model"] or ""),
        review_endpoint_sha256=_endpoint_sha256(str(llm["base_url"] or "")),
        review_temperature=float(llm["temperature"]),
        review_json_mode=bool(llm["json_mode"]),
        verify_ssl=bool(llm["verify_ssl"]),
        quality_mode=_choice("quality", "REVIEW_RESULT_QUALITY_MODE", "shadow"),
        deterministic_crosscheck_mode=_choice(
            "crosscheck", "REVIEW_DETERMINISTIC_CROSSCHECK_MODE", "all_findings"
        ),
        evidence_agent_mode=_choice(
            "agent", "REVIEW_EVIDENCE_AGENT_MODE", "fallback"
        ),
        evidence_snapshot_max_cells=_positive_int(
            "REVIEW_EVIDENCE_SNAPSHOT_MAX_CELLS", _DEFAULT_MAX_CELLS
        ),
        challenger_full_text=_bool("REVIEW_CHALLENGER_FULL_TEXT", True),
        mineru_ocr_mode=_choice("mineru", "MINERU_OCR_MODE", "off"),
        mineru_ocr_language=os.getenv("MINERU_OCR_LANGUAGE", "ch").strip() or "ch",
        mineru_model_version=os.getenv("MINERU_MODEL_VERSION", "vlm").strip() or "vlm",
        policy_mode=_choice("policy", "REVIEW_POLICY_MODE", "shadow"),
        judgement_mode=_choice("judgement", "REVIEW_JUDGEMENT_MODE", "off"),
        judgement_max_requests=_strict_positive_int(
            "REVIEW_JUDGEMENT_MAX_REQUESTS", _DEFAULT_JUDGEMENT_MAX_REQUESTS
        ),
        prompt_bundle_version=str(llm["prompt_bundle_version"] or ""),
    )


def component_ref_from_path(
    *, component_id: str, version: str, path: str | Path
) -> ExecutionComponentRef:
    """Return a content-addressed config component without persisting its path."""

    try:
        digest = sha256_path(path)
    except (OSError, ValueError):
        digest = hashlib.sha256(b"review-component-unavailable/1").hexdigest()
    return ExecutionComponentRef(
        component_id=str(component_id or "component"),
        version=str(version or "unknown"),
        sha256=digest,
    )


def _manifest_input(item: InputFile) -> InputFile:
    filename = Path(str(item.filename or "input")).name or "input"
    return item.model_copy(
        update={"filename": filename, "path": f"inputs/{item.role}/{filename}"}
    )


def build_review_execution_context(
    *,
    review_id: str,
    source: str,
    requested_sheets: Sequence[str],
    inputs: Sequence[InputFile],
    snapshot_paths: Mapping[InputRole, str],
    policy_pack: PolicyPackRef | None,
    judgement_policy_pack: PolicyPackRef | None,
    engine_version: str,
    components: Sequence[ExecutionComponentRef],
    runtime_config: RuntimeConfigSnapshot,
) -> ReviewExecutionContext:
    """Build the one context shared by V1 quality and the shadow artifact."""

    input_set_sha256 = stable_input_set_sha256(
        inputs=inputs, requested_sheets=requested_sheets
    )
    execution_sha256 = stable_execution_sha256(
        input_set_sha256=input_set_sha256,
        engine_version=engine_version,
        policy_pack=policy_pack,
        judgement_policy_pack=judgement_policy_pack,
        components=components,
        runtime_config=runtime_config,
    )
    ordered_components = [
        ExecutionComponentRef.model_validate(component)
        for component in sorted(
            components,
            key=lambda component: (
                component.component_id,
                component.version,
                component.sha256,
            ),
        )
    ]
    manifest = ReviewManifest(
        review_id=review_id,
        source=source,
        requested_sheets=_manifest_requested_sheets(requested_sheets),
        inputs=[_manifest_input(item) for item in inputs],
        policy_pack=policy_pack,
        judgement_policy_pack=judgement_policy_pack,
        engine_version=engine_version,
        input_set_sha256=input_set_sha256,
        execution_sha256=execution_sha256,
        runtime_config=runtime_config,
        components=ordered_components,
    )
    return ReviewExecutionContext(
        manifest=manifest,
        input_set_sha256=input_set_sha256,
        execution_sha256=execution_sha256,
        runtime_config=runtime_config,
        components=ordered_components,
        snapshot_paths={role: str(path) for role, path in snapshot_paths.items()},
    )
