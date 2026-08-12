export type WorkbenchStatus =
  | "idle"
  | "uploading"
  | "running"
  | "completed"
  | "failed"
  | "timeout";

export type EvidenceItem = {
  id: string;
  name: string;
  source: "upload" | "link";
  status: "ready" | "uploading" | "failed";
};

export type SummaryMetric = {
  label: string;
  value: string;
};

export type AnalysisSection = {
  title: string;
  body: string;
  findings?: Finding[];
};

export type ProgressStep = {
  label: string;
  status: "pending" | "active" | "completed" | "failed";
};

export type ToolTrace = {
  id: string;
  name: string;
  argsSummary: string;
};

export type ReviewProgress = {
  stage: string;
  current_sheet: string;
  llm_calls: Record<string, number>;
  findings_so_far: { P0: number; P1: number; P2: number; total: number };
  recent_events: { t: string; msg: string }[];
  updated_at: string;
};

export type UnderstoodRequirement = {
  review_id?: string | null;
  status?: string | null;
  scope: string;
  sheets_raw: string;
  workpaper: string;
  checkpoints?: string | null;
  attachments_dir?: string | null;
  attachments_preview?: string | null;
  summary: string;
};

export type WorkbenchViewModel = {
  reviewId?: string;
  status: WorkbenchStatus;
  evidenceItems: EvidenceItem[];
  evidenceAnalysis?: EvidenceAnalysis;
  summaryMetrics: SummaryMetric[];
  analysisSections: AnalysisSection[];
  progressSteps: ProgressStep[];
  toolTraces: ToolTrace[];
  liveProgress?: ReviewProgress | null;
  understoodRequirement?: UnderstoodRequirement | null;
  lastUpdatedLabel: string;
  errorMessage?: string;
  runningMessage?: string;
};

export type EvidenceRef = {
  sheet?: string;
  cell_or_range?: string;
  attachment?: string;
  excerpt?: string;
  quote?: string;
  source_kind?: string;
  source_ref?: string;
  evidence_id?: string;
  source_sha256?: string;
  content_hash?: string;
  start_offset?: number;
  end_offset?: number;
};

export type FindingQualityGateStatus =
  | "passed"
  | "flagged"
  | "not_run"
  | "error";

export type FindingQualityGate = {
  status: FindingQualityGateStatus;
  reason?: string;
  issues?: string[];
  duration_ms?: number | null;
};

export type ClaimSupportStatus =
  | "supported"
  | "partial"
  | "unsupported"
  | "not_required"
  | "error";

export type FindingConsistencyStatus =
  | "consistent"
  | "conflicted"
  | "not_comparable";

export type FindingQuality = {
  schema_version?: string;
  finding_id?: string;
  primary_location?: {
    source_kind?: "cell" | "attachment" | "unknown";
    sheet?: string;
    cell_or_range?: string;
    source_ref?: string;
    evidence_id?: string | null;
  } | null;
  citation_validation?: {
    status?: "verified" | "partial" | "invalid" | "not_available";
    verified_count?: number;
    rejected_count?: number;
    rejection_codes?: string[];
    evidence_ids?: string[];
    verified_refs?: EvidenceRef[];
  };
  gates?: Record<string, FindingQualityGate>;
  disposition?: {
    original_status?: string;
    effective_status?: string;
    original_severity?: string;
    reason_codes?: string[];
  };
  claim_support?: {
    status?: ClaimSupportStatus;
    supporting_evidence_ids?: string[];
    missing_requirements?: string[];
    reason_codes?: string[];
  };
  consistency?: {
    status?: FindingConsistencyStatus;
    conflict_ids?: string[];
    related_finding_ids?: string[];
    reason_codes?: string[];
  };
  provenance?: {
    input_sha256?: string;
    input_set_sha256?: string;
    execution_sha256?: string;
    engine_version?: string;
    policy_pack?: { id?: string; version?: string } | null;
    assertion_catalog?: { id?: string; version?: string } | null;
  };
  grouping?: {
    root_cause_id?: string | null;
    duplicate_of?: string | null;
    related_finding_ids?: string[];
  };
  remediation?: {
    status?: "actionable" | "needs_human_refinement" | "not_available";
    action?: string;
    required_evidence?: string[];
    acceptance_criteria?: string[];
    missing_fields?: string[];
  };
};

export type OcrStats = {
  calls: number;
  success: number;
  errors: number;
  timeouts: number;
};

export type EvidenceAnalysisEvidence = {
  path: string;
  fileType?: string;
  extractionStatus?: string;
  excerpt: string;
  supports?: string;
  confidence?: string;
};

export type EvidenceAnalysisUnresolved = {
  request: string;
  reason: string;
};

export type EvidenceAnalysisDetail = {
  sheet: string;
  status: string;
  toolCalls: number;
  ocr: OcrStats;
  evidence: EvidenceAnalysisEvidence[];
  unresolved: EvidenceAnalysisUnresolved[];
};

/** UI-safe, normalized form of the evidence-agent diagnostics. */
export type EvidenceAnalysis = {
  mode?: string;
  runs: number;
  toolCalls: number;
  acceptedEvidence: number;
  unresolved: number;
  errors: number;
  ocr: OcrStats;
  details: EvidenceAnalysisDetail[];
};

/** Raw shape emitted by the review API (kept in snake_case for compatibility). */
export type EvidenceAgentStatsPayload = {
  mode?: string;
  runs?: number;
  tool_calls?: number;
  accepted_evidence?: number;
  unresolved?: number;
  errors?: number;
  ocr?: Partial<OcrStats>;
  details?: Array<{
    sheet?: string;
    status?: string;
    tool_calls?: number;
    ocr?: Partial<OcrStats>;
    evidence?: Array<{
      path?: string;
      file_type?: string;
      extraction_status?: string;
      excerpt?: string;
      supports?: string;
      confidence?: string;
    }>;
    unresolved?: Array<{ request?: string; reason?: string }>;
  }>;
};

export type Finding = {
  finding_id?: string;
  assertion_id?: string;
  claim_type?: string;
  claim_subject?: string;
  claim_value?: string;
  issue_type: string;
  severity?: string;
  severity_display?: string;
  sheet?: string;
  cell?: string | null;
  snippet?: string;
  basis?: string;
  suggestion?: string;
  status?: string;
  risk_type?: string;
  evidence_refs?: EvidenceRef[];
  conclusion?: string;
  llm_status?: string;
  llm_validity?: string;
  llm_severity?: string;
  llm_conclusion?: string;
  llm_comment?: string;
  llm_reasons?: string | string[];
  llm_missing_evidence?: string | string[];
  llm_next_actions?: string | string[];
  llm_evidence_refs?: string | EvidenceRef[];
  llm_risk_type?: string;
  llm_fix_suggestion?: string | Record<string, string>;
  llm_unknown_reason?: string;
  reasons?: string[];
  fix_suggestion_detail?: Record<string, string>;
  unknown_reason?: string;
  cross_validate_issues?: string[];
  challenge_verdict?: string | null;
  quality?: FindingQuality;
};

export type FindingsPayload = {
  review_id: string;
  created_at?: string;
  source?: string;
  stats: {
    total_findings: number;
    by_severity: Record<string, number>;
    by_status?: Record<string, number>;
    by_risk_type?: Record<string, number>;
    llm_call_stats?: Record<string, Record<string, number>>;
    evidence_agent?: EvidenceAgentStatsPayload;
  };
  findings: Finding[];
};

export type ArtifactStageStatus =
  | "completed"
  | "running"
  | "disabled"
  | "error";

export type ArtifactInput = {
  role?: string;
  filename?: string;
  sha256?: string;
  size?: number;
  media_type?: string;
};

export type ArtifactFinding = {
  finding_id?: string;
  identity_key?: string;
  rule_id?: string;
  rule_version?: string;
  issue_type?: string;
  severity?: string;
  risk_type?: string;
  sheet?: string;
  cell?: string | null;
  status?: string;
  decision?: string;
  verification_status?: string;
  conclusion?: string;
  basis?: string;
  suggestion?: string;
  reasons?: string[];
  unknown_reason?: string;
  resolution?: string;
  evidence_refs_v2?: Array<{
    evidence_id?: string;
    source_kind?: string;
    source_ref?: string;
    sheet?: string;
    cell_or_range?: string;
    quote?: string;
    excerpt?: string;
    start_offset?: number;
    end_offset?: number;
    content_hash?: string;
    role?: string;
  }>;
};

export type ArtifactRuntimeConfig = {
  review_model?: string;
  review_endpoint_sha256?: string;
  review_temperature?: number;
  review_json_mode?: boolean;
  verify_ssl?: boolean;
  quality_mode?: "off" | "shadow" | "on";
  deterministic_crosscheck_mode?: "all_findings" | "p0_only" | "off";
  evidence_agent_mode?: string;
  policy_mode?: "shadow" | "off";
  judgement_mode?: "shadow" | "off";
  prompt_bundle_version?: string;
};

export type ArtifactComponentRef = {
  component_id?: string;
  version?: string;
  sha256?: string;
};

export type ReviewArtifactPayload = {
  review_id: string;
  artifact_status: "running" | "completed" | "error";
  artifact_error?: string | null;
  engine_version?: string;
  input_set_sha256?: string;
  execution_sha256?: string;
  runtime_config?: ArtifactRuntimeConfig;
  components?: ArtifactComponentRef[];
  created_at?: string;
  source_sha256?: string;
  requested_sheets?: string[];
  inputs?: ArtifactInput[];
  comparison?: {
    status: "available" | "not_available";
    authority: "v1";
    candidate_source: "stage_c_shadow";
    counts: Record<string, number>;
    items?: Array<{
      category?: string;
      legacy_finding_id?: string | null;
      shadow_finding_id?: string | null;
      v1_status?: string | null;
      v2_status?: string | null;
      reason_code?: string;
    }>;
  };
  stages: {
    stage_a: {
      status: ArtifactStageStatus;
      capture_status?: string;
      captured_cell_count?: number;
      omitted_cell_count?: number;
      sheet_count?: number;
    };
    stage_b: {
      status: ArtifactStageStatus;
      policy_pack?: { id: string; version: string };
      plan?: {
        plan_id?: string;
        target_sheets?: string[];
        scope_status?: string;
        items?: number;
        skipped?: number;
      } | null;
      stats?: Record<string, unknown>;
      findings: ArtifactFinding[];
    };
    stage_c: {
      status: ArtifactStageStatus;
      policy_pack?: { id: string; version: string };
      stats?: Record<string, unknown>;
      findings: ArtifactFinding[];
    };
  };
};
