"""Data models for the review engine (ported from analyze_excel.py)."""
from dataclasses import dataclass
from typing import Any, Dict, Optional


# Severity mapping: internal P0/P1/P2 <-> display 高/中/低
_SEVERITY_DISPLAY = {"P0": "高", "P1": "中", "P2": "低"}
_SEVERITY_FROM_CHINESE = {"高": "P0", "中": "P1", "低": "P2"}

# Maximum length for excerpt text in evidence_refs
_EXCERPT_MAX_LEN = 2000
# Marker added when an excerpt was constructed (not verbatim from a cell)
_EXCERPT_CONSTRUCTED_MARKER = "[非逐字原文]"


# Unified Finding result JSON Schema — documents the shape each LLM result
# must conform to. Validation is enforced by review.validation by hand
# (no jsonschema dependency).
_FINDING_RESULT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["status", "conclusion", "evidence_refs"],
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail", "unknown"]},
        "conclusion": {"type": "string", "minLength": 4},
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
        },
        "evidence_refs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["cell_or_range"],
                "properties": {
                    "sheet": {"type": "string"},
                    "cell_or_range": {"type": "string"},
                    "attachment": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
            },
        },
        "severity": {"type": "string", "enum": ["P0", "P1", "P2"]},
        "risk_type": {
            "type": "string",
            "enum": ["覆盖性", "一致性", "证据不足", "方法性", "逻辑性", "跨字段一致性"],
        },
        "fix_suggestion": {
            "type": "object",
            "properties": {
                "missing_field": {"type": "string"},
                "supplement_explanation": {"type": "string"},
                "required_evidence_type": {"type": "string"},
            },
        },
        "unknown_reason": {"type": "string"},
        "assertion_id": {"type": "string", "minLength": 3},
        "claim_type": {
            "type": "string",
            "enum": [
                "workpaper_text",
                "attachment_presence",
                "attachment_content",
                "period_date",
                "configuration_value",
                "population_coverage",
                "record_consistency",
            ],
        },
        "claim_subject": {"type": "string", "maxLength": 500},
        "claim_value": {"type": "string", "maxLength": 500},
    },
}


@dataclass(frozen=True)
class Finding:
    issue_type: str
    severity: str  # internal P0/P1/P2; output maps to 高/中/低
    sheet: str
    cell: Optional[str]
    snippet: str
    basis: str
    suggestion: str
    # --- extended fields (all have defaults, backward compatible) ---
    status: str = "fail"  # pass / fail / unknown
    risk_type: str = ""  # 覆盖性 / 一致性 / 证据不足 / ...
    evidence_refs: str = "[]"  # JSON string of list[dict]
    conclusion: str = ""
    reasons: str = "[]"  # JSON string of list[str]
    fix_suggestion_detail: str = "{}"  # JSON string of dict
    unknown_reason: str = ""
    needs_review: bool = False
    # Stable provenance hints used by the additive review-quality envelope.
    # They remain optional so existing rule constructors and stored V1 data
    # continue to deserialize unchanged.
    origin: str = "legacy"
    rule_hint: str = ""
    # Controlled assertion/claim fields. Defaults preserve old constructors
    # and stored V1 payloads; the taxonomy adapter fills them before export.
    assertion_id: str = ""
    claim_type: str = ""
    claim_subject: str = ""
    claim_value: str = ""


@dataclass(frozen=True)
class AttachmentFile:
    index: str
    rel_dir: str
    filename: str
    rel_path: str
    file_type: str
    description: str = ""
    status: str = ""
    size: int = 0
    extracted_text: str = ""
    extraction_status: str = ""


# Kept as an import-compatible alias for callers that only use the old data
# shape. New review inputs are indexed from an attachment directory.
AttachmentPreviewItem = AttachmentFile
