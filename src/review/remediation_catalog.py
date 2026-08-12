"""Versioned, non-executable remediation templates bound to assertions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from review.finding_taxonomy import (
    AssertionCatalog,
    AssertionPackManifest,
    assertion_catalog_directory,
)


_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ASSERTION_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_TEMPLATE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)*$")


class RemediationCatalogError(ValueError):
    """Raised when repository-owned remediation declarations are unsafe."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _static_texts(values: Iterable[Any], *, label: str) -> list[str]:
    result = [_text(value) for value in values]
    if not result or not all(result):
        raise ValueError(f"{label} must contain non-empty static text")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must not contain duplicates")
    return result


class RemediationTemplate(BaseModel):
    """A static, audited remediation prescription for controlled assertions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template_id: str = Field(min_length=3, max_length=120)
    assertion_ids: list[str] = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=2_000)
    required_evidence: list[str] = Field(min_length=1, max_length=50)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=50)

    @field_validator("template_id")
    @classmethod
    def _safe_template_id(cls, value: str) -> str:
        value = _text(value)
        if not _TEMPLATE_RE.fullmatch(value):
            raise ValueError("template_id must be a controlled identifier")
        return value

    @field_validator("assertion_ids")
    @classmethod
    def _safe_assertion_ids(cls, values: list[str]) -> list[str]:
        result = [_text(value) for value in values]
        if not result or not all(_ASSERTION_RE.fullmatch(value) for value in result):
            raise ValueError("assertion_ids must contain controlled assertion identifiers")
        if len(set(result)) != len(result):
            raise ValueError("assertion_ids must not contain duplicates")
        return result

    @field_validator("action")
    @classmethod
    def _static_action(cls, value: str) -> str:
        value = _text(value)
        if not value:
            raise ValueError("action must be non-empty static text")
        # Templates are copied verbatim; no Python/Jinja/string formatting is
        # evaluated anywhere in this module.
        return value

    @field_validator("required_evidence", "acceptance_criteria")
    @classmethod
    def _static_lists(cls, values: list[str], info) -> list[str]:
        return _static_texts(values, label=info.field_name)


class RemediationCatalog(BaseModel):
    """A strict catalog stored beside the assertion catalog version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=5, max_length=40)
    templates: list[RemediationTemplate] = Field(default_factory=list, max_length=300)

    @field_validator("id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        value = _text(value)
        if not _COMPONENT_RE.fullmatch(value):
            raise ValueError("id must be a safe path component")
        return value

    @field_validator("version")
    @classmethod
    def _safe_version(cls, value: str) -> str:
        value = _text(value)
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("version must use MAJOR.MINOR.PATCH")
        return value

    def template_for_assertion(self, assertion_id: str) -> RemediationTemplate | None:
        normalized = _text(assertion_id)
        for template in self.templates:
            if normalized in template.assertion_ids:
                return template
        return None


def _read_json(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RemediationCatalogError(f"missing remediation catalog file: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationCatalogError(f"invalid remediation catalog JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise RemediationCatalogError(f"remediation catalog JSON must be an object: {path}")
    return raw


def remediation_catalog_directory(
    *,
    pack_id: str = "review-quality",
    version: str = "1.0.0",
    root: str | Path | None = None,
) -> Path:
    """Return the safe shared directory for one assertion/remediation version."""

    return assertion_catalog_directory(pack_id=pack_id, version=version, root=root)


def load_remediation_catalog(
    *,
    pack_id: str = "review-quality",
    version: str = "1.0.0",
    root: str | Path | None = None,
) -> RemediationCatalog:
    """Load static remediation declarations without loading assertion bindings."""

    catalog_root = remediation_catalog_directory(
        pack_id=pack_id, version=version, root=root
    )
    try:
        manifest = AssertionPackManifest.model_validate(
            _read_json(catalog_root / "manifest.json")
        )
    except RemediationCatalogError:
        raise
    except Exception as exc:
        raise RemediationCatalogError("invalid remediation catalog manifest") from exc
    if manifest.id != pack_id or manifest.version != version:
        raise RemediationCatalogError("remediation catalog manifest id/version mismatch")
    templates_path = (catalog_root / manifest.remediation_templates_file).resolve()
    if not templates_path.is_relative_to(catalog_root):
        raise RemediationCatalogError("remediation catalog path escapes root")
    try:
        catalog = RemediationCatalog.model_validate(_read_json(templates_path))
    except RemediationCatalogError:
        raise
    except Exception as exc:
        raise RemediationCatalogError("invalid remediation catalog") from exc
    if catalog.id != manifest.id or catalog.version != manifest.version:
        raise RemediationCatalogError("remediation catalog id/version mismatch")
    template_ids = [template.template_id for template in catalog.templates]
    if len(set(template_ids)) != len(template_ids):
        raise RemediationCatalogError("duplicate template_id")
    return RemediationCatalog(
        id=catalog.id,
        version=catalog.version,
        templates=sorted(catalog.templates, key=lambda template: template.template_id),
    )


def validate_remediation_bindings(
    assertions: AssertionCatalog, remediation: RemediationCatalog
) -> None:
    """Ensure every trusted assertion maps to exactly its declared template."""

    if assertions.id != remediation.id or assertions.version != remediation.version:
        raise RemediationCatalogError("assertion/remediation catalog id/version mismatch")
    bound: dict[str, str] = {}
    for template in remediation.templates:
        for assertion_id in template.assertion_ids:
            assertion = assertions.maybe_assertion(assertion_id)
            if assertion is None:
                raise RemediationCatalogError(
                    f"remediation template references unknown assertion: {assertion_id}"
                )
            if assertion_id in bound:
                raise RemediationCatalogError(
                    f"assertion has multiple remediation templates: {assertion_id}"
                )
            if assertion.remediation_template_id != template.template_id:
                raise RemediationCatalogError(
                    "remediation template does not match assertion binding: "
                    f"{assertion_id} -> {template.template_id}"
                )
            bound[assertion_id] = template.template_id
    for assertion in assertions.assertions:
        expected = assertion.remediation_template_id
        if expected == "human_refinement":
            continue
        if bound.get(assertion.assertion_id) != expected:
            raise RemediationCatalogError(
                "assertion is missing its trusted remediation template: "
                f"{assertion.assertion_id}"
            )
