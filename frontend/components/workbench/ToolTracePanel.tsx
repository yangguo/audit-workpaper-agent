import type { ReviewProgress, ToolTrace } from "./types";

export function ToolTracePanel({
  traces,
  liveProgress,
}: {
  traces: ToolTrace[];
  liveProgress?: ReviewProgress | null;
}) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">调用追踪</h2>
      {liveProgress ? (
        <LiveProgressView progress={liveProgress} />
      ) : traces.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          任务运行后，工具调用将显示在此处。
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {traces.map((trace) => (
            <li
              key={trace.id}
              className="rounded-xl border px-3 py-2 text-sm"
            >
              <p className="font-medium">{trace.name}</p>
              <p className="mt-1 break-all text-xs text-muted-foreground">
                {trace.argsSummary}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LiveProgressView({ progress }: { progress: ReviewProgress }) {
  const fs = progress.findings_so_far ?? { P0: 0, P1: 0, P2: 0, total: 0 };
  const calls = progress.llm_calls ?? {};
  const events = progress.recent_events ?? [];
  return (
    <div className="mt-3 space-y-3 text-sm">
      <div className="rounded-xl border px-3 py-2">
        <p className="font-medium">
          {progress.stage || "运行中"}
          {progress.current_sheet ? ` · ${progress.current_sheet}` : ""}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          LLM 调用：{Object.keys(calls).length === 0
            ? "0"
            : Object.entries(calls).map(([k, v]) => `${k} ${v}`).join("，")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          已发现：P0 {fs.P0 ?? 0} / P1 {fs.P1 ?? 0} / P2 {fs.P2 ?? 0} / 共 {fs.total ?? 0}
        </p>
      </div>
      {events.length > 0 && (
        <ul className="space-y-1">
          {[...events].reverse().map((e, i) => (
            <li key={`${e.t}-${i}`} className="break-all text-xs text-muted-foreground">
              <span className="font-mono">{e.t}</span> {e.msg}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
