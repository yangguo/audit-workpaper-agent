import type { EvidenceAnalysis } from "./types";

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  error: "分析失败",
  skipped: "未触发",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status || "未知";
}

function extractionLabel(status?: string): string {
  if (status === "ocr") return "MinerU OCR";
  if (status === "text") return "文本提取";
  return status ? `提取：${status}` : "已验证摘录";
}

export function EvidenceAnalysisPanel({
  analysis,
}: {
  analysis: EvidenceAnalysis;
}) {
  const hasDetails = analysis.details.length > 0;
  return (
    <section
      data-testid="evidence-analysis"
      className="rounded-2xl border bg-white p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">证据分析</h2>
        {analysis.mode ? (
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
            {analysis.mode}
          </span>
        ) : null}
      </div>
      <p className="text-muted-foreground mt-2 text-xs">
        调查 {analysis.runs} 次 · 工具调用 {analysis.toolCalls} 次 · 已确认{" "}
        {analysis.acceptedEvidence} 条 · 待补充 {analysis.unresolved} 项
        {analysis.errors > 0 ? ` · 失败 ${analysis.errors} 次` : ""}
      </p>
      <p className="text-muted-foreground mt-1 text-xs">
        MinerU OCR：调用 {analysis.ocr.calls} · 成功 {analysis.ocr.success} ·
        失败 {analysis.ocr.errors} · 超时 {analysis.ocr.timeouts}
      </p>

      {!hasDetails ? (
        <p className="text-muted-foreground mt-3 text-sm">
          本次审阅未触发附件证据调查。
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          {analysis.details.slice(0, 8).map((detail, detailIndex) => (
            <article
              key={`${detail.sheet}-${detailIndex}`}
              className="rounded-xl border border-slate-200 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium">{detail.sheet}</h3>
                <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                  {statusLabel(detail.status)}
                </span>
              </div>
              <p className="text-muted-foreground mt-1 text-xs">
                工具调用 {detail.toolCalls} 次 · OCR 成功 {detail.ocr.success}/
                {detail.ocr.calls}
              </p>

              {detail.evidence.length > 0 ? (
                <ul className="mt-3 space-y-2">
                  {detail.evidence
                    .slice(0, 5)
                    .map((evidence, evidenceIndex) => (
                      <li
                        key={`${evidence.path}-${evidenceIndex}`}
                        className="rounded-lg bg-slate-50 p-2"
                      >
                        <p
                          className="text-xs font-medium break-all text-slate-700"
                          title={evidence.path}
                        >
                          {extractionLabel(evidence.extractionStatus)} ·{" "}
                          {evidence.path}
                        </p>
                        <blockquote className="mt-1 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-600">
                          “{evidence.excerpt}”
                        </blockquote>
                        {evidence.supports ? (
                          <p className="mt-1 text-xs text-slate-500">
                            支持：{evidence.supports}
                          </p>
                        ) : null}
                      </li>
                    ))}
                </ul>
              ) : null}

              {detail.unresolved.length > 0 ? (
                <ul className="mt-3 space-y-1 text-xs text-amber-800">
                  {detail.unresolved
                    .slice(0, 5)
                    .map((item, unresolvedIndex) => (
                      <li
                        key={`${item.request}-${item.reason}-${unresolvedIndex}`}
                      >
                        待补充{item.request ? `：${item.request}` : ""}
                        {item.reason ? `（${item.reason}）` : ""}
                      </li>
                    ))}
                </ul>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
