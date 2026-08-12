import { useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { Button } from "@/components/ui/button";
import type {
  AnalysisSection,
  EvidenceRef,
  Finding,
  FindingQuality,
  FindingQualityGate,
} from "./types";

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
  const qualityRefs = finding.quality?.citation_validation?.verified_refs;
  const refs = finding.quality ? qualityRefs || [] : finding.evidence_refs;
  const locations = (refs || [])
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

const CITATION_STATUS_LABELS: Record<string, string> = {
  verified: "引用可复现",
  partial: "引用部分验证",
  invalid: "引用无效",
  not_available: "引用不可用",
};

const CLAIM_SUPPORT_STATUS_LABELS: Record<string, string> = {
  supported: "结论有附件支持",
  partial: "结论支持不足",
  unsupported: "结论支持不足",
  not_required: "结论不要求附件支持",
  error: "结论支持不可用",
  not_available: "结论支持不可用",
};

const CONSISTENCY_STATUS_LABELS: Record<string, string> = {
  consistent: "结论一致",
  conflicted: "存在结论冲突",
  not_comparable: "结论不可比较",
  not_available: "结论一致性不可用",
};

const GATE_LABELS: Record<string, string> = {
  deterministic_cross_check: "确定性交叉校验",
  model_re_review: "模型复核",
  adversarial_challenge: "对抗式挑战",
};

const GATE_STATUS_LABELS: Record<string, string> = {
  passed: "已通过",
  flagged: "已标记",
  not_run: "未执行",
  error: "执行异常",
};

const CITATION_STATUS_STYLES: Record<string, string> = {
  verified: "bg-emerald-100 text-emerald-700",
  partial: "bg-amber-100 text-amber-700",
  invalid: "bg-red-100 text-red-700",
  not_available: "bg-slate-100 text-slate-600",
};

const CLAIM_SUPPORT_STATUS_STYLES: Record<string, string> = {
  supported: "bg-emerald-100 text-emerald-700",
  partial: "bg-amber-100 text-amber-700",
  unsupported: "bg-red-100 text-red-700",
  not_required: "bg-slate-100 text-slate-600",
  error: "bg-red-100 text-red-700",
  not_available: "bg-slate-100 text-slate-600",
};

const CONSISTENCY_STATUS_STYLES: Record<string, string> = {
  consistent: "bg-emerald-100 text-emerald-700",
  conflicted: "bg-red-100 text-red-700",
  not_comparable: "bg-slate-100 text-slate-600",
  not_available: "bg-slate-100 text-slate-600",
};

function safeQualityText(value: string | undefined, limit = 160): string {
  const text = value?.trim() || "";
  if (!text || text.startsWith("/") || text.includes("..")) return "";
  return text.slice(0, limit);
}

function qualityLocation(quality: FindingQuality): string {
  const location = quality.primary_location;
  if (!location) return "未定位";
  const cell = [location.sheet, location.cell_or_range]
    .map((value) => value?.trim())
    .filter(Boolean)
    .join("!");
  if (cell) return cell;
  const sourceRef = safeQualityText(location.source_ref);
  return (
    sourceRef || (location.source_kind === "attachment" ? "附件定位" : "未定位")
  );
}

function QualityGate({
  name,
  gate,
}: {
  name: string;
  gate: FindingQualityGate;
}) {
  const label = GATE_LABELS[name] || "其他质量校验";
  const status = GATE_STATUS_LABELS[gate.status] || "不可用";
  return (
    <li className="text-xs leading-5 text-slate-600">
      <span className="font-medium text-slate-700">{label}：</span>
      {status}
      {gate.status === "not_run" && gate.reason ? `（${gate.reason}）` : ""}
      {gate.status === "flagged" && gate.issues?.length
        ? `（${gate.issues.join("；")}）`
        : ""}
      {gate.status === "error" && gate.reason ? `（${gate.reason}）` : ""}
    </li>
  );
}

function FindingQualityPanel({
  finding,
  quality,
}: {
  finding: Finding;
  quality: FindingQuality;
}) {
  const citation = quality.citation_validation;
  const citationStatus = citation?.status || "not_available";
  const citationLabel =
    CITATION_STATUS_LABELS[citationStatus] ||
    CITATION_STATUS_LABELS.not_available;
  const claimSupport = quality.claim_support;
  const claimSupportStatus = claimSupport?.status || "not_available";
  const claimSupportLabel =
    CLAIM_SUPPORT_STATUS_LABELS[claimSupportStatus] ||
    CLAIM_SUPPORT_STATUS_LABELS.not_available;
  const consistency = quality.consistency;
  const consistencyStatus = consistency?.status || "not_available";
  const consistencyLabel =
    CONSISTENCY_STATUS_LABELS[consistencyStatus] ||
    CONSISTENCY_STATUS_LABELS.not_available;
  const gates = quality.gates || {};
  const grouping = quality.grouping;
  const remediation = quality.remediation;
  const inputHash = quality.provenance?.input_sha256?.trim();
  const inputSetHash = quality.provenance?.input_set_sha256?.trim();
  const executionHash = quality.provenance?.execution_sha256?.trim();
  const missingFields = remediation?.missing_fields || [];
  const requiredEvidence = remediation?.required_evidence || [];
  const acceptanceCriteria = remediation?.acceptance_criteria || [];
  const rejectionCodes = citation?.rejection_codes || [];
  const conflictIds = consistency?.conflict_ids || [];
  const supportRequirements = claimSupport?.missing_requirements || [];

  return (
    <div
      data-testid="finding-quality"
      className="mt-4 rounded-lg border border-slate-200 bg-slate-50/80 p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold text-slate-700">质量与溯源</p>
        <span
          className={`rounded-md px-2 py-1 text-xs font-medium ${CITATION_STATUS_STYLES[citationStatus] || CITATION_STATUS_STYLES.not_available}`}
        >
          {citationLabel}
        </span>
        <span
          className={`rounded-md px-2 py-1 text-xs font-medium ${CLAIM_SUPPORT_STATUS_STYLES[claimSupportStatus] || CLAIM_SUPPORT_STATUS_STYLES.not_available}`}
        >
          {claimSupportLabel}
        </span>
        <span
          className={`rounded-md px-2 py-1 text-xs font-medium ${CONSISTENCY_STATUS_STYLES[consistencyStatus] || CONSISTENCY_STATUS_STYLES.not_available}`}
        >
          {consistencyLabel}
        </span>
        <span className="text-xs text-slate-500">
          已验证 {citation?.verified_count ?? 0} · 拒绝{" "}
          {citation?.rejected_count ?? 0}
        </span>
      </div>

      <dl className="mt-2 space-y-1 text-xs leading-5 text-slate-600">
        <div>
          <dt className="inline font-medium text-slate-700">主定位：</dt>
          <dd className="inline">{qualityLocation(quality)}</dd>
        </div>
        {finding.assertion_id ? (
          <div>
            <dt className="inline font-medium text-slate-700">审阅命题：</dt>
            <dd className="inline">{finding.assertion_id}</dd>
          </div>
        ) : null}
        {finding.claim_type ? (
          <div>
            <dt className="inline font-medium text-slate-700">声明类型：</dt>
            <dd className="inline">{finding.claim_type}</dd>
          </div>
        ) : null}
        {finding.claim_subject ? (
          <div>
            <dt className="inline font-medium text-slate-700">声明对象：</dt>
            <dd className="inline">{finding.claim_subject}</dd>
          </div>
        ) : null}
        {finding.claim_value ? (
          <div>
            <dt className="inline font-medium text-slate-700">声明值：</dt>
            <dd className="inline">{finding.claim_value}</dd>
          </div>
        ) : null}
        {rejectionCodes.length > 0 ? (
          <div>
            <dt className="inline font-medium text-amber-700">
              引用拒绝原因：
            </dt>
            <dd className="inline text-amber-700">
              {rejectionCodes.join("、")}
            </dd>
          </div>
        ) : null}
        {supportRequirements.length > 0 ? (
          <div>
            <dt className="inline font-medium text-amber-700">
              结论支持缺口：
            </dt>
            <dd className="inline text-amber-700">
              {supportRequirements.join("、")}
            </dd>
          </div>
        ) : null}
        {conflictIds.length > 0 ? (
          <div>
            <dt className="inline font-medium text-red-700">冲突编号：</dt>
            <dd className="inline text-red-700">{conflictIds.join("、")}</dd>
          </div>
        ) : null}
        {Object.keys(gates).length > 0 ? (
          <div>
            <dt className="font-medium text-slate-700">复核状态：</dt>
            <dd>
              <ul className="mt-1 space-y-0.5">
                {Object.entries(gates).map(([name, gate]) => (
                  <QualityGate
                    key={name}
                    name={name}
                    gate={gate}
                  />
                ))}
              </ul>
            </dd>
          </div>
        ) : null}
        {grouping?.root_cause_id ? (
          <div>
            <dt className="inline font-medium text-slate-700">根因编号：</dt>
            <dd className="inline">{grouping.root_cause_id}</dd>
          </div>
        ) : null}
        {grouping?.duplicate_of ? (
          <div>
            <dt className="inline font-medium text-slate-700">重复于：</dt>
            <dd className="inline">{grouping.duplicate_of}</dd>
          </div>
        ) : null}
        {remediation?.status && remediation.status !== "not_available" ? (
          <div>
            <dt className="inline font-medium text-slate-700">整改状态：</dt>
            <dd className="inline">
              {remediation.status === "actionable" ? "可执行" : "需人工补全"}
            </dd>
          </div>
        ) : null}
        {remediation?.action ? (
          <div>
            <dt className="inline font-medium text-slate-700">整改动作：</dt>
            <dd className="inline">{remediation.action}</dd>
          </div>
        ) : null}
        {requiredEvidence.length > 0 ? (
          <div>
            <dt className="inline font-medium text-slate-700">所需证据：</dt>
            <dd className="inline">{requiredEvidence.join("、")}</dd>
          </div>
        ) : null}
        {acceptanceCriteria.length > 0 ? (
          <div>
            <dt className="inline font-medium text-slate-700">验收条件：</dt>
            <dd className="inline">{acceptanceCriteria.join("；")}</dd>
          </div>
        ) : null}
        {missingFields.length > 0 ? (
          <div>
            <dt className="inline font-medium text-amber-700">整改待补全：</dt>
            <dd className="inline text-amber-700">
              {missingFields.join("、")}
            </dd>
          </div>
        ) : null}
        {inputHash ? (
          <div>
            <dt className="inline font-medium text-slate-700">输入版本：</dt>
            <dd className="inline">{inputHash.slice(0, 8)}</dd>
          </div>
        ) : null}
        {inputSetHash ? (
          <div>
            <dt className="inline font-medium text-slate-700">输入集版本：</dt>
            <dd className="inline">{inputSetHash.slice(0, 12)}</dd>
          </div>
        ) : null}
        {executionHash ? (
          <div>
            <dt className="inline font-medium text-slate-700">执行版本：</dt>
            <dd className="inline">{executionHash.slice(0, 12)}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
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

      {(() => {
        const verifiedRefs =
          finding.quality?.citation_validation?.verified_refs;
        const refs = finding.quality
          ? verifiedRefs || []
          : finding.evidence_refs;
        return refs?.length ? (
          <div className="mt-4 border-t border-slate-200/80 pt-3">
            <p className="text-xs font-medium text-slate-500">证据引用</p>
            <div className="mt-2 space-y-2">
              {refs.map((ref, index) => (
                <EvidenceReference
                  key={`${evidenceLocation(ref, finding)}-${index}`}
                  ref={ref}
                  finding={finding}
                  index={index}
                />
              ))}
            </div>
          </div>
        ) : null;
      })()}
      {finding.quality ? (
        <FindingQualityPanel
          finding={finding}
          quality={finding.quality}
        />
      ) : null}
      {!finding.quality && !finding.evidence_refs?.length && finding.snippet ? (
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
  reviewId,
}: {
  sections: AnalysisSection[];
  runningMessage?: string;
  errorMessage?: string;
  reviewId?: string;
}) {
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    if (!reviewId) return;
    const backendUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:5000";
    const url = `${backendUrl}/findings/${reviewId}/export?format=xlsx`;
    const filename = `findings_${reviewId}.xlsx`;
    setExporting(true);
    try {
      const response = await fetch(url);
      if (!response.ok) {
        toast.error("导出失败，请稍后重试。");
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      try {
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      } finally {
        URL.revokeObjectURL(objectUrl);
      }
    } catch {
      toast.error("导出失败，请检查网络后重试。");
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="rounded-2xl border bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">分析结果</h2>
        {reviewId ? (
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={exporting}
          >
            <Download className="mr-1 size-4" />
            导出审阅包（含质量与溯源）
          </Button>
        ) : null}
      </div>
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
