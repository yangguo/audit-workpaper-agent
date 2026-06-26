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

export type WorkbenchViewModel = {
  status: WorkbenchStatus;
  evidenceItems: EvidenceItem[];
  summaryMetrics: SummaryMetric[];
  analysisSections: AnalysisSection[];
  progressSteps: ProgressStep[];
  toolTraces: ToolTrace[];
  lastUpdatedLabel: string;
  errorMessage?: string;
  runningMessage?: string;
};
