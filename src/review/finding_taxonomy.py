"""Versioned, declarative finding assertions and safe legacy classification."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ASSERTION_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_GATE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")

ClaimType = Literal[
    "workpaper_text",
    "attachment_presence",
    "attachment_content",
    "period_date",
    "configuration_value",
    "population_coverage",
    "record_consistency",
]


class AssertionCatalogError(ValueError):
    """Raised when a repository-owned assertion catalog is unsafe or invalid."""


class AssertionPackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=5, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    assertions_file: str = Field(min_length=1, max_length=160)
    remediation_templates_file: str = Field(
        default="remediation-templates.json", min_length=1, max_length=160
    )

    @field_validator("id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        value = value.strip()
        if not _COMPONENT_RE.fullmatch(value):
            raise ValueError("id must be a safe path component")
        return value

    @field_validator("version")
    @classmethod
    def _safe_version(cls, value: str) -> str:
        value = value.strip()
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("version must use MAJOR.MINOR.PATCH")
        return value

    @field_validator("assertions_file")
    @classmethod
    def _safe_assertions_file(cls, value: str) -> str:
        path = Path(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or path.name != "assertions.json":
            raise ValueError("assertions_file must be the local assertions.json")
        return path.as_posix()

    @field_validator("remediation_templates_file")
    @classmethod
    def _safe_remediation_templates_file(cls, value: str) -> str:
        path = Path(value.replace("\\", "/"))
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.name != "remediation-templates.json"
        ):
            raise ValueError(
                "remediation_templates_file must be the local remediation-templates.json"
            )
        return path.as_posix()


class AssertionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_id: str = Field(min_length=3, max_length=160)
    version: str = Field(min_length=5, max_length=40)
    claim_type: ClaimType
    allowed_origins: list[str] = Field(min_length=1, max_length=30)
    requires_attachment_support: bool
    exclusive_claim: bool
    deterministic_gate_ids: list[str] = Field(default_factory=list, max_length=20)
    remediation_template_id: str = Field(min_length=1, max_length=120)
    root_family: str = Field(default="", max_length=120)

    @field_validator("assertion_id")
    @classmethod
    def _safe_assertion_id(cls, value: str) -> str:
        value = value.strip()
        if not _ASSERTION_RE.fullmatch(value):
            raise ValueError("assertion_id must be a dotted controlled identifier")
        return value

    @field_validator("version")
    @classmethod
    def _safe_version(cls, value: str) -> str:
        value = value.strip()
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("version must use MAJOR.MINOR.PATCH")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _safe_origins(cls, values: list[str]) -> list[str]:
        result = [str(value or "").strip() for value in values]
        if not all(_GATE_RE.fullmatch(value) for value in result):
            raise ValueError("allowed_origins must contain controlled identifiers")
        if len(set(result)) != len(result):
            raise ValueError("allowed_origins must not contain duplicates")
        return result

    @field_validator("deterministic_gate_ids")
    @classmethod
    def _safe_gates(cls, values: list[str]) -> list[str]:
        result = [str(value or "").strip() for value in values]
        if not all(_GATE_RE.fullmatch(value) for value in result):
            raise ValueError("deterministic_gate_ids must contain controlled identifiers")
        if len(set(result)) != len(result):
            raise ValueError("deterministic_gate_ids must not contain duplicates")
        return result

    @field_validator("remediation_template_id", "root_family")
    @classmethod
    def _safe_template_id(cls, value: str) -> str:
        value = value.strip()
        if value and not _GATE_RE.fullmatch(value.replace("-", "_")):
            raise ValueError("template/root identifier must be controlled")
        return value


class AssertionCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=5, max_length=40)
    assertions: list[AssertionSpec] = Field(min_length=1, max_length=200)

    def assertion(self, assertion_id: str) -> AssertionSpec:
        for assertion in self.assertions:
            if assertion.assertion_id == assertion_id:
                return assertion
        raise KeyError(assertion_id)

    def maybe_assertion(self, assertion_id: str) -> AssertionSpec | None:
        try:
            return self.assertion(assertion_id)
        except KeyError:
            return None


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2] / "policy_packs"


def _safe_component(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not _COMPONENT_RE.fullmatch(value):
        raise AssertionCatalogError(f"unsafe {label} path component")
    return value


def assertion_catalog_directory(
    *,
    pack_id: str = "review-quality",
    version: str = "1.0.0",
    root: str | Path | None = None,
) -> Path:
    safe_id = _safe_component(pack_id, "assertion catalog")
    safe_version = _safe_component(version, "assertion catalog version")
    if not _VERSION_RE.fullmatch(safe_version):
        raise AssertionCatalogError("assertion catalog version must use MAJOR.MINOR.PATCH")
    root_path = Path(root).expanduser() if root is not None else _default_root()
    root_resolved = root_path.resolve()
    catalog_root = (root_resolved / safe_id / safe_version).resolve()
    if not catalog_root.is_relative_to(root_resolved):
        raise AssertionCatalogError("assertion catalog path escapes root")
    return catalog_root


def _read_json(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AssertionCatalogError(f"missing assertion catalog file: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionCatalogError(f"invalid assertion catalog JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise AssertionCatalogError(f"assertion catalog JSON must be an object: {path}")
    return raw


def load_assertion_catalog(
    *,
    pack_id: str = "review-quality",
    version: str = "1.0.0",
    root: str | Path | None = None,
) -> AssertionCatalog:
    """Load a strict, non-executable assertion catalog from a safe path."""

    catalog_root = assertion_catalog_directory(
        pack_id=pack_id, version=version, root=root
    )
    raw_manifest = _read_json(catalog_root / "manifest.json")
    try:
        manifest = AssertionPackManifest.model_validate(raw_manifest)
    except Exception as exc:
        raise AssertionCatalogError("invalid assertion catalog manifest") from exc
    if manifest.id != pack_id or manifest.version != version:
        raise AssertionCatalogError("assertion catalog manifest id/version mismatch")

    assertions_path = (catalog_root / manifest.assertions_file).resolve()
    if not assertions_path.is_relative_to(catalog_root):
        raise AssertionCatalogError("assertion catalog assertions path escapes root")
    raw_catalog = _read_json(assertions_path)
    try:
        catalog = AssertionCatalog.model_validate(raw_catalog)
    except Exception as exc:
        raise AssertionCatalogError("invalid assertion catalog") from exc
    if catalog.id != manifest.id or catalog.version != manifest.version:
        raise AssertionCatalogError("assertion catalog id/version mismatch")
    assertion_ids = [assertion.assertion_id for assertion in catalog.assertions]
    if len(set(assertion_ids)) != len(assertion_ids):
        raise AssertionCatalogError("duplicate assertion_id")
    if "finding.unclassified" not in assertion_ids:
        raise AssertionCatalogError(
            "assertion catalog must include finding.unclassified"
        )
    return AssertionCatalog(
        id=catalog.id,
        version=catalog.version,
        assertions=sorted(catalog.assertions, key=lambda item: item.assertion_id),
    )


@lru_cache(maxsize=1)
def default_assertion_catalog() -> AssertionCatalog:
    return load_assertion_catalog()


def fallback_assertion_catalog() -> AssertionCatalog:
    """Return only the human-review assertion when the catalog is unavailable."""

    return AssertionCatalog(
        id="review-quality-fallback",
        version="1.0.0",
        assertions=[
            AssertionSpec(
                assertion_id="finding.unclassified",
                version="1.0.0",
                claim_type="workpaper_text",
                allowed_origins=[
                    "legacy",
                    "llm",
                    "checkpoint",
                    "procedure_pairs",
                    "sheet_scope",
                    "attachment_reference",
                    "evidence_steps",
                    "procedure_pair_llm",
                    "configuration",
                    "record",
                ],
                requires_attachment_support=False,
                exclusive_claim=False,
                deterministic_gate_ids=[],
                remediation_template_id="human_refinement",
            )
        ],
    )


# Exact, migration-only mappings for V1 producers that predate controlled
# assertion fields. They use origin/rule IDs after a narrow legacy adapter;
# title similarity is never used for semantic classification.
LEGACY_ORIGIN_RULE_HINTS: dict[str, tuple[str, str]] = {
    "执行列疑似未替换模板/未按要求填列": (
        "procedure_pairs", "execution_column_template"
    ),
    "程序执行不到位/仅依赖访谈": (
        "procedure_pairs", "interview_only_execution"
    ),
    "证据类型缺失": ("procedure_pairs", "required_evidence_missing"),
    "账号新增样本总量基准可能有误": (
        "procedure_pairs", "account_creation_population"
    ),
    "离职账号禁用检查方法可能有误": (
        "procedure_pairs", "terminated_account_disable_method"
    ),
    "未覆盖调岗权限变更/禁用测试": (
        "procedure_pairs", "transfer_access_change_coverage"
    ),
    "设计有效性证据不足（密码策略）": (
        "procedure_pairs", "password_policy_design_evidence"
    ),
    "密码策略证据有效性不足": (
        "procedure_pairs", "password_policy_effectiveness_evidence"
    ),
    "批处理作业证据不足/范围可能未覆盖": (
        "procedure_pairs", "batch_job_evidence_scope"
    ),
    "系统变更证据不足/样本框定可能有误": (
        "procedure_pairs", "change_population_evidence"
    ),
    "特权账号识别范围可能不完整": (
        "sheet_scope", "privileged_account_scope"
    ),
    "供应商托管场景证据可能不足": (
        "sheet_scope", "vendor_hosting_evidence"
    ),
    "附件证据引用未匹配到附件目录": (
        "attachment_reference", "attachment_reference_missing"
    ),
    "附件证据内容未解析": (
        "attachment_reference", "attachment_text_unavailable"
    ),
    "附件证据编号/文件未匹配（可能引用错误）": (
        "evidence_steps", "attachment_reference_mismatch"
    ),
    "证据-步骤一致性抽样复核（为控制LLM调用规模）": (
        "evidence_steps", "sampling_limited"
    ),
    "A-C对应性：LLM调用失败（需人工复核）": ("procedure_pair_llm", ""),
    "A-C对应性：LLM无法判定（需人工确认）": ("procedure_pair_llm", ""),
}

_LEGACY_ASSERTION_MAPPINGS: dict[tuple[str, str], tuple[str, str]] = {
    ("checkpoint", "evidence_number_mismatch"): (
        "attachment.reference.mapping", "reference_mismatch"
    ),
    ("checkpoint", "record_date_mismatch"): (
        "record.period_date.consistency", "date_mismatch"
    ),
    ("record", "field_mismatch"): ("record.field.consistency", "field_mismatch"),
    ("configuration", "asset_coverage"): (
        "configuration.asset_coverage.support", "coverage_insufficient"
    ),
    ("procedure_pairs", "execution_column_template"): (
        "procedure.execution.correspondence", "execution_template_unreplaced"
    ),
    ("procedure_pairs", "interview_only_execution"): (
        "procedure.execution.correspondence", "interview_only"
    ),
    ("procedure_pairs", "required_evidence_missing"): (
        "procedure.required_evidence", "required_evidence_missing"
    ),
    ("procedure_pairs", "account_creation_population"): (
        "population.sample_size.present", "population_basis_uncertain"
    ),
    ("procedure_pairs", "terminated_account_disable_method"): (
        "procedure.execution.correspondence", "method_insufficient"
    ),
    ("procedure_pairs", "transfer_access_change_coverage"): (
        "population.sample_size.present", "coverage_insufficient"
    ),
    ("procedure_pairs", "password_policy_design_evidence"): (
        "procedure.required_evidence", "design_evidence_missing"
    ),
    ("procedure_pairs", "password_policy_effectiveness_evidence"): (
        "procedure.required_evidence", "effectiveness_evidence_missing"
    ),
    ("procedure_pairs", "batch_job_evidence_scope"): (
        "population.sample_size.present", "coverage_insufficient"
    ),
    ("procedure_pairs", "change_population_evidence"): (
        "population.sample_size.present", "population_basis_uncertain"
    ),
    ("sheet_scope", "privileged_account_scope"): (
        "scope.privileged_account.coverage", "coverage_insufficient"
    ),
    ("sheet_scope", "vendor_hosting_evidence"): (
        "scope.vendor_hosting.evidence", "evidence_insufficient"
    ),
    ("attachment_reference", "attachment_reference_missing"): (
        "attachment.inventory.presence", "absent"
    ),
    ("attachment_reference", "attachment_text_unavailable"): (
        "attachment.content.support", "unavailable"
    ),
    ("evidence_steps", "attachment_reference_mismatch"): (
        "attachment.reference.mapping", "reference_mismatch"
    ),
    ("evidence_steps", "sampling_limited"): (
        "population.sample_size.present", "sampling_limited"
    ),
    ("procedure_pair_llm", ""): (
        "procedure.execution.correspondence", "unknown"
    ),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def apply_legacy_taxonomy(finding: Mapping[str, Any]) -> dict[str, Any]:
    """Add only exact legacy origin/rule IDs; do not infer semantic content."""

    output = dict(finding)
    origin = _text(output.get("origin"))
    rule_hint = _text(output.get("rule_hint"))
    if rule_hint or origin not in {"", "legacy"}:
        return output
    issue_type = _text(output.get("issue_type"))
    taxonomy = LEGACY_ORIGIN_RULE_HINTS.get(issue_type)
    if taxonomy is not None:
        output["origin"], output["rule_hint"] = taxonomy
    elif issue_type.startswith("LLM判定："):
        # This is a legacy structural marker, not a semantic mapping. The
        # actual assertion remains unclassified unless it is supplied by a
        # future constrained LLM request.
        output["origin"] = "llm"
    return output


def _evidence_attachment(finding: Mapping[str, Any]) -> str:
    refs = finding.get("evidence_refs") or []
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except json.JSONDecodeError:
            refs = []
    if not isinstance(refs, list):
        return ""
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        attachment = _text(ref.get("attachment")) or _text(ref.get("source_ref"))
        if attachment:
            return attachment.replace("\\", "/")
    return ""


def _claim_subject(finding: Mapping[str, Any], assertion: AssertionSpec) -> str:
    supplied = _text(finding.get("claim_subject"))
    if supplied:
        return supplied
    sheet = _text(finding.get("sheet")) or "unknown-sheet"
    rule_hint = _text(finding.get("rule_hint"))
    if assertion.requires_attachment_support:
        attachment = _evidence_attachment(finding) or "unresolved"
        return f"{sheet}|attachment:{attachment}"
    if assertion.assertion_id.startswith("scope.") and rule_hint:
        return f"{sheet}|scope:{rule_hint}"
    cell = _text(finding.get("cell"))
    if cell:
        return f"{sheet}|cell:{cell}"
    if rule_hint:
        return f"{sheet}|scope:{rule_hint}"
    return f"{sheet}|scope:unresolved"


def _assertion_for_finding(
    finding: Mapping[str, Any], catalog: AssertionCatalog
) -> tuple[AssertionSpec | None, str]:
    origin = _text(finding.get("origin")) or "legacy"
    supplied_id = _text(finding.get("assertion_id"))
    supplied = catalog.maybe_assertion(supplied_id) if supplied_id else None
    if supplied is not None and origin in supplied.allowed_origins:
        return supplied, _text(finding.get("claim_value"))
    mapped = _LEGACY_ASSERTION_MAPPINGS.get((origin, _text(finding.get("rule_hint"))))
    if mapped is not None:
        assertion = catalog.maybe_assertion(mapped[0])
        if assertion is not None and origin in assertion.allowed_origins:
            return assertion, mapped[1]
    return None, ""


def allowed_assertion_ids(
    catalog: AssertionCatalog, *, origin: str
) -> list[str]:
    """Return the catalog-controlled assertions a producer may emit."""

    normalized_origin = _text(origin)
    return sorted(
        assertion.assertion_id
        for assertion in catalog.assertions
        if normalized_origin in assertion.allowed_origins
    )


def deterministic_finding_fields(
    *,
    origin: str,
    rule_hint: str,
    assertion_id: str,
    sheet: str,
    cell: str | None = None,
    claim_value: str = "",
    claim_subject: str = "",
    catalog: AssertionCatalog | None = None,
) -> dict[str, Any]:
    """Build controlled metadata for a deterministic producer.

    This is deliberately keyed by producer-owned identifiers rather than issue
    text. It fails closed when a producer tries to emit an assertion not
    permitted by the active repository catalog.
    """

    active_catalog = catalog or default_assertion_catalog()
    normalized_origin = _text(origin)
    normalized_rule_hint = _text(rule_hint)
    assertion = active_catalog.maybe_assertion(_text(assertion_id))
    if assertion is None:
        raise AssertionCatalogError(f"unknown deterministic assertion: {assertion_id}")
    if normalized_origin not in assertion.allowed_origins:
        raise AssertionCatalogError(
            f"origin {normalized_origin!r} is not allowed for {assertion.assertion_id}"
        )
    subject = _text(claim_subject) or _claim_subject(
        {
            "sheet": sheet,
            "cell": cell or "",
            "rule_hint": normalized_rule_hint,
        },
        assertion,
    )
    return {
        "origin": normalized_origin,
        "rule_hint": normalized_rule_hint,
        "assertion_id": assertion.assertion_id,
        "claim_type": assertion.claim_type,
        "claim_subject": subject,
        "claim_value": _text(claim_value),
    }


def validated_llm_assertion_fields(
    *,
    sheet: str,
    cell: str | None = None,
    supplied_assertion_id: str = "",
    claim_subject: str = "",
    claim_value: str = "",
    catalog: AssertionCatalog | None = None,
) -> dict[str, Any]:
    """Validate an LLM assertion selection against its explicit whitelist.

    Free-text models are not allowed to create semantic categories. A missing
    or unapproved identifier is represented as the catalog's explicitly
    unclassified assertion and requires human review.
    """

    active_catalog = catalog or default_assertion_catalog()
    allowed = set(allowed_assertion_ids(active_catalog, origin="llm"))
    requested = _text(supplied_assertion_id)
    assertion_id = requested if requested in allowed else "finding.unclassified"
    assertion = active_catalog.maybe_assertion(assertion_id)
    if assertion is None:
        raise AssertionCatalogError("catalog must include finding.unclassified")
    subject = _text(claim_subject) or _claim_subject(
        {"sheet": sheet, "cell": cell or ""}, assertion
    )
    return {
        "origin": "llm",
        "rule_hint": "",
        "assertion_id": assertion.assertion_id,
        "claim_type": assertion.claim_type,
        "claim_subject": subject,
        "claim_value": _text(claim_value),
        "needs_review": True,
    }


def classify_finding(
    finding: Mapping[str, Any], catalog: AssertionCatalog
) -> dict[str, Any]:
    """Attach controlled assertion/claim fields without title-based guessing."""

    output = apply_legacy_taxonomy(finding)
    origin = _text(output.get("origin")) or "legacy"
    output["origin"] = origin
    output["rule_hint"] = _text(output.get("rule_hint"))
    assertion, default_value = _assertion_for_finding(output, catalog)
    if assertion is None:
        assertion = catalog.maybe_assertion("finding.unclassified")
        if assertion is None:
            raise AssertionCatalogError("catalog must contain finding.unclassified")
        output["needs_review"] = True
    else:
        output["needs_review"] = bool(output.get("needs_review")) or (
            assertion.assertion_id == "finding.unclassified"
        )
    output["assertion_id"] = assertion.assertion_id
    output["claim_type"] = assertion.claim_type
    output["claim_subject"] = _claim_subject(output, assertion)
    output["claim_value"] = _text(output.get("claim_value")) or default_value
    return output
