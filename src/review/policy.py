"""Strict, declarative policy-pack loading for Stage-B shadow execution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# This is an allowlist, not an import hook. Policy JSON can select only
# evaluator functions that are registered and reviewed in repository code.
TRUSTED_EVALUATOR_IDS = frozenset(
    {
        "procedure.interview_only",
        "procedure.required_evidence",
        "scope.os_db_admin",
    }
)


class PolicyPackError(ValueError):
    """Raised when a policy pack is missing, unsafe, or schema-invalid."""


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=3)
    version: str = Field(min_length=5)
    title: str = Field(min_length=1, max_length=200)
    evaluator_id: str = Field(min_length=1, max_length=120)
    applies_to: dict[str, object] = Field(default_factory=dict)
    severity: Literal["P0", "P1", "P2"]
    risk_type: Literal["覆盖性", "一致性", "证据不足", "方法性", "逻辑性", "跨字段一致性"]
    required_evidence_types: list[str] = Field(default_factory=list, max_length=20)
    remediation_template: str = Field(min_length=1, max_length=2000)
    enabled: bool = True

    @field_validator("rule_id", "evaluator_id")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char in value for char in ("/", "\\", "\n", "\r")):
            raise ValueError("identifier must be a single safe value")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        value = value.strip()
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("version must use MAJOR.MINOR.PATCH")
        return value


class PolicyPackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=5)
    title: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=80)
    engine_compatibility: str = Field(min_length=1, max_length=120)
    rules: list[str] = Field(min_length=1, max_length=100)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        value = value.strip()
        if not _COMPONENT_RE.fullmatch(value):
            raise ValueError("id must be a safe path component")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        value = value.strip()
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("version must use MAJOR.MINOR.PATCH")
        return value


class PolicyPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: PolicyPackManifest
    rules: list[PolicyRule] = Field(min_length=1)

    def rule(self, rule_id: str) -> PolicyRule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise KeyError(rule_id)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    def model_dump_jsonable(self) -> dict[str, object]:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.manifest.title,
            "rules": [rule.model_dump(mode="json") for rule in self.rules],
        }


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2] / "policy_packs"


def _safe_component(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not _COMPONENT_RE.fullmatch(value):
        raise PolicyPackError(f"unsafe {label} path component")
    return value


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyPackError(f"missing policy file: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyPackError(f"invalid policy JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PolicyPackError(f"policy JSON must be an object: {path}")
    return value


def load_policy_pack(
    *,
    pack_id: str = "itgc-core",
    version: str = "1.0.0",
    root: str | Path | None = None,
) -> PolicyPack:
    """Load one repository-owned, versioned policy pack safely."""
    safe_id = _safe_component(pack_id, "policy pack")
    safe_version = _safe_component(version, "policy version")
    if not _VERSION_RE.fullmatch(safe_version):
        raise PolicyPackError("policy version must use MAJOR.MINOR.PATCH")

    root_path = Path(root).expanduser() if root is not None else _default_root()
    root_resolved = root_path.resolve()
    pack_root = (root_resolved / safe_id / safe_version).resolve()
    if not pack_root.is_relative_to(root_resolved):
        raise PolicyPackError("policy pack path escapes root")

    manifest_path = pack_root / "manifest.json"
    raw_manifest = _read_json(manifest_path)
    try:
        manifest = PolicyPackManifest.model_validate(raw_manifest)
    except Exception as exc:
        raise PolicyPackError(f"invalid policy manifest: {manifest_path}") from exc
    if manifest.id != safe_id or manifest.version != safe_version:
        raise PolicyPackError("policy manifest id/version does not match requested pack")

    rules: list[PolicyRule] = []
    seen_ids: set[str] = set()
    for relative_name in manifest.rules:
        relative_path = Path(str(relative_name).replace("\\", "/"))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PolicyPackError(f"unsafe policy rule path: {relative_name}")
        rule_path = (pack_root / relative_path).resolve()
        if not rule_path.is_relative_to(pack_root):
            raise PolicyPackError(f"policy rule path escapes pack: {relative_name}")
        raw_rule = _read_json(rule_path)
        try:
            rule = PolicyRule.model_validate(raw_rule)
        except Exception as exc:
            raise PolicyPackError(f"invalid policy rule: {rule_path}") from exc
        if rule.rule_id in seen_ids:
            raise PolicyPackError(f"duplicate rule_id: {rule.rule_id}")
        if rule.evaluator_id not in TRUSTED_EVALUATOR_IDS:
            raise PolicyPackError(f"unknown evaluator_id: {rule.evaluator_id}")
        if rule.version != manifest.version:
            raise PolicyPackError(f"rule version mismatch: {rule.rule_id}")
        seen_ids.add(rule.rule_id)
        rules.append(rule)

    if not rules:
        raise PolicyPackError("policy pack has no rules")
    return PolicyPack(manifest=manifest, rules=sorted(rules, key=lambda item: item.rule_id))
