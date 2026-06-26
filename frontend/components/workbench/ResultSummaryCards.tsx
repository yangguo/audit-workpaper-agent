import type { SummaryMetric } from "./types";

export function ResultSummaryCards({ items }: { items: SummaryMetric[] }) {
  if (items.length === 0) return null;
  return (
    <section className="grid grid-cols-3 gap-3">
      {items.map((item) => (
        <div key={item.label} className="rounded-2xl border bg-white p-4">
          <p className="text-sm text-muted-foreground">{item.label}</p>
          <p className="mt-2 text-2xl font-semibold">{item.value}</p>
        </div>
      ))}
    </section>
  );
}
