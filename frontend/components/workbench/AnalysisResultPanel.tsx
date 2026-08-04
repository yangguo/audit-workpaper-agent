import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import type { AnalysisSection, EvidenceRef, Finding } from "./types";

const markdownComponents: any = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mt-2 text-sm leading-7 text-slate-700">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
      {children}
    </ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-700">
      {children}
    </ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => <li>{children}</li>,
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h4 className="mt-4 text-base font-semibold text-slate-900">{children}</h4>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h4 className="mt-4 text-base font-semibold text-slate-900">{children}</h4>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h5 className="mt-3 text-sm font-semibold text-slate-900">{children}</h5>
  ),
  h4: ({ children }: { children?: React.ReactNode }) => (
    <h6 className="mt-3 text-sm font-semibold text-slate-900">{children}</h6>
  ),
  code: ({
    className,
    children,
  }: {
    className?: string;
    children?: React.ReactNode;
  }) => {
    const isCodeBlock = /language-/.test(className || "");
    return (
      <code
        className={
          isCodeBlock
            ? "font-mono text-xs text-white"
            : "rounded bg-slate-100 px-1 py-0.5 text-xs font-medium text-slate-800"
        }
      >
        {children}
      </code>
    );
  },
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3">
      {children}
    </pre>
  ),
  table: ({ children }: { children?: React.ReactNode }) => (
    <table className="mt-2 w-full border-collapse text-sm text-slate-700">
      {children}
    </table>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="border bg-slate-100 px-2 py-1 text-left font-semibold">
      {children}
    </th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="border px-2 py-1">{children}</td>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="mt-2 border-l-4 border-slate-300 pl-3 text-sm text-slate-600 italic">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-slate-200" />,
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      className="text-primary text-sm underline underline-offset-2"
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
};

const SEVERITY_STYLES: Record<string, string> = {
  P0: "border-red-300 bg-red-50 text-red-700",
  P1: "border-amber-300 bg-amber-50 text-amber-700",
  P2: "border-slate-300 bg-slate-50 text-slate-700",
};

const STATUS_LABELS: Record<string, string> = {
  fail: "发现问题",
  pass: "通过",
  unknown: "待确认",
  成立: "发现问题",
  不成立: "通过",
  不确定: "待确认",
};

const STATUS_STYLES: Record<string, string> = {
  fail: "bg-red-100 text-red-700",
  pass: "bg-emerald-100 text-emerald-700",
  unknown: "bg-amber-100 text-amber-700",
};

const FIX_DETAIL_LABELS: Record<string, string> = {
  missing_field: "缺失字段",
  supplement_explanation: "补充说明",
  required_evidence_type: "所需证据类型",
};

function findingLocation(finding: Finding): string {
  const locations = (finding.evidence_refs || [])
    .map((ref) => evidenceLocation(ref, finding))
    .filter(Boolean);
  if (locations.length > 0) return [...new Set(locations)].join("、");
  return [finding.sheet, finding.cell].filter(Boolean).join("!") || "未定位";
}

function evidenceLocation(ref: EvidenceRef, finding: Finding): string {
  if (ref.attachment) return `附件：${ref.attachment}`;
  return [ref.sheet || finding.sheet, ref.cell_or_range || finding.cell]
    .filter(Boolean)
    .join("!");
}

function parseJsonValue(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!text) return "";
  try {
    return JSON.parse(text);
  } catch {
    return value;
  }
}

function stringList(value: unknown): string[] {
  const parsed = parseJsonValue(value);
  if (Array.isArray(parsed)) {
    return parsed
      .filter((item): item is string => typeof item === "string")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return typeof parsed === "string" && parsed.trim() ? [parsed.trim()] : [];
}

function evidenceList(value: unknown): EvidenceRef[] {
  const parsed = parseJsonValue(value);
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(
    (item): item is EvidenceRef =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item),
  );
}

function formatFixDetails(value: unknown): string {
  const parsed = parseJsonValue(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return "";
  }
  return Object.entries(parsed)
    .filter(([, item]) => typeof item === "string" && item.trim())
    .map(
      ([key, item]) =>
        `${FIX_DETAIL_LABELS[key] || key}：${String(item).trim()}`,
    )
    .join("\n");
}

function FindingField({ label, value }: { label: string; value?: string }) {
  if (!value?.trim()) return null;
  return (
    <div className="mt-3">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm leading-6 whitespace-pre-wrap text-slate-700">
        {value}
      </dd>
    </div>
  );
}

function FindingListField({
  label,
  values,
}: {
  label: string;
  values?: string[];
}) {
  const items = (values || []).filter((value) => value?.trim());
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">
          {items.map((value, index) => (
            <li key={`${value}-${index}`}>{value}</li>
          ))}
        </ul>
      </dd>
    </div>
  );
}

function EvidenceReference({
  ref,
  finding,
  index,
}: {
  ref: EvidenceRef;
  finding: Finding;
  index: number;
}) {
  const location = evidenceLocation(ref, finding) || "未提供位置";
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-slate-500">
          证据 {index + 1}
        </span>
        <span className="text-xs font-medium text-slate-700">{location}</span>
      </div>
      {ref.excerpt ? (
        <blockquote className="mt-2 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-600">
          “{ref.excerpt}”
        </blockquote>
      ) : (
        <p className="mt-2 text-xs text-amber-700">
          未提供逐字摘录，证据需要人工补充。
        </p>
      )}
    </div>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  const severity = finding.severity || "P2";
  const status = finding.status || "unknown";
  const severityLabel = finding.severity_display || severity;
  const statusLabel = STATUS_LABELS[status] || status;
  const fixDetails = formatFixDetails(finding.fix_suggestion_detail);
  const llmFixDetails = formatFixDetails(finding.llm_fix_suggestion);
  const llmReasons = stringList(finding.llm_reasons);
  const llmMissingEvidence = stringList(finding.llm_missing_evidence);
  const llmNextActions = stringList(finding.llm_next_actions);
  const llmEvidenceRefs = evidenceList(finding.llm_evidence_refs);

  return (
    <article
      data-testid="finding-card"
      className={`rounded-xl border border-l-4 p-4 ${SEVERITY_STYLES[severity] || SEVERITY_STYLES.P2}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-slate-900">
            {finding.issue_type || "未命名问题"}
          </h4>
          <p className="mt-1 text-xs text-slate-500">
            {finding.risk_type ? `风险类型：${finding.risk_type} · ` : ""}
            位置：{findingLocation(finding)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-medium">
          <span className="rounded-md bg-white/80 px-2 py-1">
            {severity} · {severityLabel}
          </span>
          <span
            className={`rounded-md px-2 py-1 ${STATUS_STYLES[status] || STATUS_STYLES.unknown}`}
          >
            {statusLabel}
          </span>
        </div>
      </div>

      <dl className="mt-3 border-t border-slate-200/80 pt-1">
        <FindingField
          label="结论"
          value={
            finding.llm_conclusion || finding.conclusion || finding.issue_type
          }
        />
        <FindingField
          label="判定依据"
          value={finding.basis}
        />
        <FindingListField
          label="判定要点"
          values={finding.reasons}
        />
        <FindingField
          label="整改建议"
          value={finding.suggestion}
        />
        <FindingField
          label="补充整改信息"
          value={fixDetails}
        />
        <FindingField
          label="不确定原因"
          value={finding.unknown_reason}
        />
        {finding.llm_status ? (
          <FindingField
            label="LLM 复核状态"
            value={STATUS_LABELS[finding.llm_status] || finding.llm_status}
          />
        ) : null}
        <FindingField
          label="LLM 风险类型"
          value={finding.llm_risk_type}
        />
        {finding.llm_comment ? (
          <FindingField
            label="LLM 复核说明"
            value={finding.llm_comment}
          />
        ) : null}
        <FindingListField
          label="LLM 复核要点"
          values={llmReasons}
        />
        <FindingListField
          label="需要补充的证据"
          values={llmMissingEvidence}
        />
        <FindingListField
          label="后续动作"
          values={llmNextActions}
        />
        <FindingField
          label="LLM 整改补充"
          value={llmFixDetails}
        />
        <FindingField
          label="LLM 不确定原因"
          value={finding.llm_unknown_reason}
        />
        {finding.cross_validate_issues?.length ? (
          <FindingListField
            label="交叉校验"
            values={finding.cross_validate_issues}
          />
        ) : null}
        {finding.challenge_verdict ? (
          <FindingField
            label="对抗式质疑"
            value={finding.challenge_verdict}
          />
        ) : null}
      </dl>

      {finding.evidence_refs?.length ? (
        <div className="mt-4 border-t border-slate-200/80 pt-3">
          <p className="text-xs font-medium text-slate-500">证据引用</p>
          <div className="mt-2 space-y-2">
            {finding.evidence_refs.map((ref, index) => (
              <EvidenceReference
                key={`${evidenceLocation(ref, finding)}-${index}`}
                ref={ref}
                finding={finding}
                index={index}
              />
            ))}
          </div>
        </div>
      ) : finding.snippet ? (
        <FindingField
          label="原文摘录"
          value={finding.snippet}
        />
      ) : null}
      {llmEvidenceRefs.length ? (
        <div className="mt-4 border-t border-slate-200/80 pt-3">
          <p className="text-xs font-medium text-slate-500">LLM 证据引用</p>
          <div className="mt-2 space-y-2">
            {llmEvidenceRefs.map((ref, index) => (
              <EvidenceReference
                key={`llm-${evidenceLocation(ref, finding)}-${index}`}
                ref={ref}
                finding={finding}
                index={index}
              />
            ))}
          </div>
        </div>
      ) : null}
    </article>
  );
}

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
        <div className="border-destructive/30 bg-destructive/5 text-destructive mt-4 rounded-xl border p-4 text-sm">
          {errorMessage}
          <p className="text-muted-foreground mt-2">
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
            {section.findings?.length ? (
              <div className="mt-3 space-y-3">
                {section.findings.map((finding, index) => (
                  <FindingCard
                    key={`${finding.issue_type}-${finding.sheet || ""}-${finding.cell || index}`}
                    finding={finding}
                  />
                ))}
              </div>
            ) : section.body ? (
              <div className="markdown-body">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={markdownComponents}
                >
                  {section.body}
                </ReactMarkdown>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
