import type {
  ArtifactFinding,
  ArtifactStageStatus,
  ReviewArtifactPayload,
} from "./types";

const STATUS_LABELS: Record<ArtifactStageStatus, string> = {
  completed: "已完成",
  running: "处理中",
  disabled: "未启用",
  error: "异常",
};

const STATUS_STYLES: Record<ArtifactStageStatus, string> = {
  completed: "bg-emerald-50 text-emerald-700",
  running: "bg-blue-50 text-blue-700",
  disabled: "bg-slate-100 text-slate-600",
  error: "bg-red-50 text-red-700",
};

function StageStatus({ status }: { status: ArtifactStageStatus }) {
  return (
    <span className={`rounded-md px-2 py-1 text-xs ${STATUS_STYLES[status]}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}

function evidenceLabel(finding: ArtifactFinding): string {
  const ref = finding.evidence_refs_v2?.[0];
  if (!ref) return "未提供精确证据引用";
  const location = [
    ref.sheet || finding.sheet,
    ref.cell_or_range || finding.cell,
  ]
    .filter(Boolean)
    .join("!");
  return location || ref.source_ref || ref.evidence_id || "已引用证据";
}

function FindingCard({ finding }: { finding: ArtifactFinding }) {
  const decision = finding.decision || finding.status || "unknown";
  const quote =
    finding.evidence_refs_v2?.[0]?.quote ||
    finding.evidence_refs_v2?.[0]?.excerpt;
  return (
    <article className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-slate-900">
            {finding.issue_type || "未命名判断"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {[finding.rule_id, finding.rule_version]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <span className="rounded-md bg-white px-2 py-1 text-xs text-slate-600">
          {decision}
        </span>
      </div>
      {finding.conclusion || finding.basis ? (
        <p className="mt-2 text-sm leading-6 whitespace-pre-wrap text-slate-700">
          {finding.conclusion || finding.basis}
        </p>
      ) : null}
      {finding.unknown_reason ? (
        <p className="mt-2 text-xs text-amber-700">
          未确定原因：{finding.unknown_reason}
        </p>
      ) : null}
      <p className="mt-2 text-xs text-slate-500">
        证据位置：{evidenceLabel(finding)}
      </p>
      {quote ? (
        <blockquote className="mt-2 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-600">
          “{quote}”
        </blockquote>
      ) : null}
    </article>
  );
}

function StageCard({
  title,
  detail,
  status,
}: {
  title: string;
  detail: string;
  status: ArtifactStageStatus;
}) {
  return (
    <div className="rounded-xl border bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-900">{title}</p>
        <StageStatus status={status} />
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">{detail}</p>
    </div>
  );
}

export function ReviewArtifactPanel({
  artifact,
}: {
  artifact: ReviewArtifactPayload;
}) {
  const { stage_a: stageA, stage_b: stageB, stage_c: stageC } = artifact.stages;
  const stageADetail =
    stageA.status === "completed"
      ? `${stageA.sheet_count ?? 0} 个 Sheet，已固定 ${stageA.captured_cell_count ?? 0} 个单元格${stageA.capture_status === "truncated" ? "（已截断）" : ""}`
      : "等待输入快照完成";
  const stageBDetail = (() => {
    if (!stageB.policy_pack) return "当前运行未启用策略包";
    const plan = stageB.plan;
    const planDetail = plan
      ? `，计划 ${plan.items ?? 0} 项，跳过 ${plan.skipped ?? 0} 项`
      : "，正在生成规则计划";
    return `${stageB.policy_pack.id}@${stageB.policy_pack.version}${planDetail}，${stageB.findings.length} 个规则候选`;
  })();
  const stageCDetail = stageC.policy_pack
    ? `${stageC.policy_pack.id}@${stageC.policy_pack.version}，${stageC.findings.length} 个判断结果`
    : "默认关闭，需配置 REVIEW_JUDGEMENT_MODE=shadow";

  return (
    <section
      data-testid="review-artifact-panel"
      className="rounded-2xl border border-blue-200 bg-blue-50/40 p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Evidence-First 过程
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            这里展示固定证据、规则候选和受限判断；当前审阅结论仍以 V1 结果为准。
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="rounded-md bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-700">
            V1 当前权威
          </span>
          <span className="rounded-md bg-blue-100 px-2 py-1 text-xs font-medium text-blue-700">
            Stage B/C shadow 候选
          </span>
          <StageStatus
            status={
              artifact.artifact_status === "completed"
                ? "completed"
                : artifact.artifact_status
            }
          />
        </div>
      </div>

      {artifact.artifact_error ? (
        <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">
          Shadow artifact 异常：{artifact.artifact_error}
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <StageCard
          title="阶段 A · 输入快照"
          detail={stageADetail}
          status={stageA.status}
        />
        <StageCard
          title="阶段 B · 规则试点"
          detail={stageBDetail}
          status={stageB.status}
        />
        <StageCard
          title="阶段 C · LLM 判断"
          detail={stageCDetail}
          status={stageC.status}
        />
      </div>

      {stageB.findings.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-sm font-semibold text-slate-900">
            阶段 B 规则候选
          </h3>
          <div className="mt-2 space-y-2">
            {stageB.findings.map((finding) => (
              <FindingCard
                key={finding.finding_id || finding.identity_key}
                finding={finding}
              />
            ))}
          </div>
        </div>
      ) : null}

      {stageC.findings.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-sm font-semibold text-slate-900">
            阶段 C 受限判断
          </h3>
          <div className="mt-2 space-y-2">
            {stageC.findings.map((finding) => (
              <FindingCard
                key={finding.finding_id || finding.identity_key}
                finding={finding}
              />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
