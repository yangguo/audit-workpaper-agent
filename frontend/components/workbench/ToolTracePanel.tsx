import type { ToolTrace } from "./types";

export function ToolTracePanel({ traces }: { traces: ToolTrace[] }) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">调用追踪</h2>
      {traces.length === 0 ? (
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
