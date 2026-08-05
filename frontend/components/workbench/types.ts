export type WorkbenchStatus =
  "idle" | "uploading" | "running" | "completed" | "failed" | "timeout";

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
  status: WorkbenchStatus;
  evidenceItems: EvidenceItem[];
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
};

export type Finding = {
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
  };
  findings: Finding[];
};

export type ArtifactStageStatus =
  "completed" | "running" | "disabled" | "error";

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

export type ReviewArtifactPayload = {
  review_id: string;
  artifact_status: "running" | "completed" | "error";
  artifact_error?: string | null;
  engine_version?: string;
  created_at?: string;
  source_sha256?: string;
  requested_sheets?: string[];
  inputs?: ArtifactInput[];
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
