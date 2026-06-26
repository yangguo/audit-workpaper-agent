import type { ProgressStep } from "./types";

const STATUS_LABEL: Record<ProgressStep["status"], string> = {
  pending: "pending",
  active: "active",
  completed: "completed",
  failed: "failed",
};

export function ProgressStatusPanel({ steps }: { steps: ProgressStep[] }) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">进度状态</h2>
      <ul className="mt-3 space-y-2">
        {steps.map((step) => (
          <li
            key={step.label}
            className="flex items-center justify-between text-sm"
          >
            <span>{step.label}</span>
            <span>{STATUS_LABEL[step.status]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
