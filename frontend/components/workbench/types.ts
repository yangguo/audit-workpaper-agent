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

export type UnderstoodRequirement = {
  review_id?: string | null;
  status?: string | null;
  scope: string;
  sheets_raw: string;
  workpaper: string;
  checkpoints?: string | null;
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
  llm_conclusion?: string;
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
