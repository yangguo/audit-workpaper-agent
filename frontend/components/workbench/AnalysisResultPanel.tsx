import type { AnalysisSection } from "./types";

export function AnalysisResultPanel({
  sections,
  runningMessage,
  errorMessage,
}: {
  sections: AnalysisSection[];
  runningMessage?: string;
  errorMessage?: string;
}) {
  return (
    <section className="rounded-2xl border bg-white p-5">
      <h2 className="text-base font-semibold">分析结果</h2>
      {errorMessage ? (
        <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {errorMessage}
          <p className="mt-2 text-muted-foreground">
            可重试当前任务，或修改输入材料后重新发起。
          </p>
        </div>
      ) : null}
      {runningMessage ? (
        <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-700">
          {runningMessage}
        </div>
      ) : null}
      <div className="mt-4 space-y-5">
        {sections.map((section) => (
          <article key={section.title}>
            <h3 className="text-sm font-semibold text-slate-900">
              {section.title}
            </h3>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">
              {section.body}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
