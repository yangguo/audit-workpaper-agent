import { FileCheck2, Layers, Paperclip } from "lucide-react";
import type { UnderstoodRequirement } from "./types";

/**
 * Shows what the agent understood the review requirement to be — the scope
 * (sheets) and files it selected — surfaced as soon as review_workpaper is
 * called, so the user can immediately spot a misunderstanding (e.g. wrong
 * control point, or empty scope = all sheets when one was requested).
 *
 * Passive display: does not block the background review.
 */
export function UnderstoodRequirementPanel(props: {
  requirement: UnderstoodRequirement;
}) {
  const { requirement: r } = props;
  const files: Array<{ icon: typeof Layers; label: string; value: string }> = [
    { icon: FileCheck2, label: "底稿", value: r.workpaper },
  ];
  if (r.checkpoints) files.push({ icon: Layers, label: "检查要点", value: r.checkpoints });
  if (r.attachments_preview)
    files.push({ icon: Paperclip, label: "附件预览", value: r.attachments_preview });

  return (
    <section
      className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4"
      aria-label="审阅理解"
      data-testid="understood-requirement"
    >
      <div className="flex items-center gap-2">
        <FileCheck2 className="size-4 text-blue-600" />
        <h2 className="text-sm font-semibold text-blue-900">审阅理解（请确认范围是否正确）</h2>
      </div>
      <p className="mt-2 text-sm text-slate-800">{r.summary}</p>
      <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1 text-xs text-slate-600 sm:grid-cols-2">
        <div className="flex items-center gap-1.5">
          <Layers className="size-3.5 shrink-0 text-slate-400" />
          <dt className="font-medium text-slate-500">审阅范围：</dt>
          <dd className="truncate font-medium text-slate-800">{r.scope}</dd>
        </div>
        {files.map((f) => (
          <div key={f.label} className="flex items-center gap-1.5">
            <f.icon className="size-3.5 shrink-0 text-slate-400" />
            <dt className="font-medium text-slate-500">{f.label}：</dt>
            <dd className="truncate font-medium text-slate-800" title={f.value}>
              {f.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
