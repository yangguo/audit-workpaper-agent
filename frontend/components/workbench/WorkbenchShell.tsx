import type { ReactNode } from "react";
import { WorkbenchHeader } from "./WorkbenchHeader";
import { EmptyStatePanel } from "./EmptyStatePanel";
import { EvidenceListPanel } from "./EvidenceListPanel";
import { ResultSummaryCards } from "./ResultSummaryCards";
import { AnalysisResultPanel } from "./AnalysisResultPanel";
import { ProgressStatusPanel } from "./ProgressStatusPanel";
import { ToolTracePanel } from "./ToolTracePanel";
import type {
  AnalysisSection,
  EvidenceItem,
  ProgressStep,
  SummaryMetric,
  ToolTrace,
} from "./types";

export function WorkbenchShell(props: {
  header: {
    title: string;
    subtitle: string;
    statusLabel: string;
    action?: ReactNode;
  };
  summaryMetrics: SummaryMetric[];
  analysisSections: AnalysisSection[];
  evidenceItems: EvidenceItem[];
  progressSteps: ProgressStep[];
  toolTraces: ToolTrace[];
  isEmpty: boolean;
  errorMessage?: string;
  runningMessage?: string;
  intake?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <WorkbenchHeader
        title={props.header.title}
        subtitle={props.header.subtitle}
        statusLabel={props.header.statusLabel}
        action={props.header.action}
      />
      <div className="mx-auto grid w-full max-w-[1320px] min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 lg:grid-cols-[320px_minmax(0,1fr)_320px]">
        <aside className="space-y-4">
          {props.intake ?? (
            <section className="rounded-2xl border bg-white p-4">
              <h2 className="text-base font-semibold">输入面板</h2>
            </section>
          )}
          <EvidenceListPanel items={props.evidenceItems} />
        </aside>
        <main className="space-y-4">
          <ResultSummaryCards items={props.summaryMetrics} />
          {props.isEmpty ? (
            <EmptyStatePanel />
          ) : (
            <AnalysisResultPanel
              sections={props.analysisSections}
              runningMessage={props.runningMessage}
              errorMessage={props.errorMessage}
            />
          )}
        </main>
        <aside className="space-y-4">
          <ProgressStatusPanel steps={props.progressSteps} />
          <ToolTracePanel traces={props.toolTraces} />
        </aside>
      </div>
    </div>
  );
}
