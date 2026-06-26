import type { EvidenceItem } from "./types";

export function EvidenceListPanel({ items }: { items: EvidenceItem[] }) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">证据列表</h2>
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          暂无证据材料，上传文件或粘贴链接后将显示在此处。
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex items-center justify-between rounded-xl border px-3 py-2 text-sm"
            >
              <span className="truncate" title={item.name}>
                {item.name}
              </span>
              <span className="ml-2 shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                {item.source === "link" ? "链接" : "文件"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
