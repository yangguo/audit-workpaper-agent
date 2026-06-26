import type { ReactNode } from "react";

export function WorkbenchHeader({
  title,
  subtitle,
  statusLabel,
  action,
}: {
  title: string;
  subtitle: string;
  statusLabel: string;
  action?: ReactNode;
}) {
  return (
    <header className="flex items-center justify-between border-b bg-white px-6 py-4">
      <div className="min-w-0">
        <h1 className="truncate text-2xl font-semibold tracking-tight text-slate-950">
          {title}
        </h1>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <div className="flex items-center gap-3">
        <div className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
          {statusLabel}
        </div>
        {action}
      </div>
    </header>
  );
}
