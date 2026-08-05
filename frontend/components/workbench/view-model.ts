import type {
  AnalysisSection,
  EvidenceItem,
  Finding,
  FindingsPayload,
  ProgressStep,
  ReviewProgress,
  ToolTrace,
  UnderstoodRequirement,
  WorkbenchStatus,
  WorkbenchViewModel,
} from "./types";

type Input = {
  status: WorkbenchStatus;
  archiveUrl: string;
  contentBlocks: Array<{
    type: string;
    text?: string;
    metadata?: { name?: string };
  }>;
  messages: Array<{
    id: string;
    type: string;
    content: string;
    tool_calls?: Array<{
      id: string;
      name: string;
      args: Record<string, unknown>;
    }>;
  }>;
  isLoading: boolean;
  elapsedSeconds: number;
  error: unknown;
  findings?: FindingsPayload | null;
  reviewStatus?: "idle" | "running" | "completed" | "error";
  reviewElapsedSeconds?: number;
  reviewProgress?: ReviewProgress | null;
  understoodRequirement?: UnderstoodRequirement | null;
};

function splitSections(content: string): AnalysisSection[] {
  const matches = content
    .split(/^## /m)
    .map((item) => item.trim())
    .filter(Boolean);
  if (matches.length <= 1)
    return [{ title: "分析结果", body: content.trim() }].filter((s) => s.body);
  return matches.map((item) => {
    const [title, ...body] = item.split("\n");
    return { title: title.trim(), body: body.join("\n").trim() };
  });
}

function extractAnomalyCount(content: string): string {
  const patterns = [
    /(\d+)\s*个异常点?/,
    /(\d+)\s*处异常/,
    /异常[:：]\s*(\d+)/,
    /异常数(?:量)?[:：]\s*(\d+)/,
    /发现\s*(\d+)\s*个?异常/,
    /存在\s*(\d+)\s*个?异常/,
    /共\s*(\d+)\s*个?异常/,
  ];
  for (const pattern of patterns) {
    const match = content.match(pattern);
    if (match) return match[1];
  }
  return "0";
}

function uploadedEvidence(input: Input): EvidenceItem[] {
  const items = input.contentBlocks
    .filter((block) => block.metadata?.name)
    .map((block, index): EvidenceItem => ({
      id: `${block.metadata?.name}-${index}`,
      name: block.metadata?.name ?? "未命名文件",
      source: "upload",
      status: "ready",
    }));
  if (input.archiveUrl) {
    items.push({
      id: "archive-url",
      name: input.archiveUrl,
      source: "link",
      status: "ready",
    });
  }
  return items;
}

const SEVERITY_TITLES: Record<string, string> = {
  P0: "P0 高风险问题",
  P1: "P1 中风险问题",
  P2: "P2 低风险问题",
};

function findingsToSections(findings: Finding[]): AnalysisSection[] {
  const groups: Record<string, Finding[]> = {};
  for (const f of findings) {
    const sev = (f.severity || "P2") as string;
    if (!groups[sev]) groups[sev] = [];
    groups[sev].push(f);
  }
  const sections: AnalysisSection[] = [];
  for (const sev of ["P0", "P1", "P2"]) {
    const list = groups[sev];
    if (!list || list.length === 0) continue;
    sections.push({
      title: `${SEVERITY_TITLES[sev] || sev}（${list.length}）`,
      body: "",
      findings: list,
    });
  }
  return sections;
}

function findingsToEvidence(findings: Finding[]): EvidenceItem[] {
  const items: EvidenceItem[] = [];
  const seen = new Map<string, number>();
  for (const f of findings) {
    for (const r of f.evidence_refs || []) {
      const name = r.attachment || r.cell_or_range || "";
      if (!name) continue;
      const baseId = `f-${f.sheet || ""}-${name}`;
      const count = seen.get(baseId) ?? 0;
      seen.set(baseId, count + 1);
      const loc = f.sheet ? `${f.sheet}!${name}` : name;
      items.push({
        id: count === 0 ? baseId : `${baseId}-${count}`,
        name: loc,
        source: "link",
        status: "ready",
      });
    }
  }
  return items;
}

export function buildWorkbenchViewModel(input: Input): WorkbenchViewModel {
  const uploaded = uploadedEvidence(input);
  const totalElapsed = input.elapsedSeconds + (input.reviewElapsedSeconds ?? 0);
  const liveProgress =
    input.reviewStatus === "running" && input.reviewProgress
      ? input.reviewProgress
      : undefined;
  const latestAi = [...input.messages]
    .reverse()
    .find((message) => message.type === "ai" && message.content);

  const reviewRunning = input.reviewStatus === "running";
  const errorMessage =
    input.error instanceof Error
      ? "分析失败，请检查输入材料后重试。"
      : typeof input.error === "string"
        ? "分析失败，请检查输入材料后重试。"
        : undefined;
  const runningMessage = input.isLoading
    ? `正在分析底稿… 已运行 ${input.elapsedSeconds}s`
    : reviewRunning
      ? `审阅进行中… 已运行 ${input.reviewElapsedSeconds ?? 0}s（大底稿可能需要数十分钟，完成后自动展示结果）`
      : undefined;

  const status: WorkbenchStatus = input.error
    ? "failed"
    : input.isLoading || reviewRunning
      ? "running"
      : input.status;

  const progressSteps: ProgressStep[] = [
    { label: "准备材料", status: "completed" },
    {
      label: "分析底稿",
      status: input.isLoading ? "active" : input.error ? "failed" : "completed",
    },
    {
      label: "生成结论",
      status: reviewRunning
        ? "active"
        : input.isLoading
          ? "pending"
          : input.error
            ? "failed"
            : "completed",
    },
  ];

  const lastUpdatedLabel =
    input.elapsedSeconds > 0 ? `${input.elapsedSeconds}s 前更新` : "刚刚更新";

  // Structured-findings path (preferred when review_workpaper ran)
  if (input.findings && input.findings.findings) {
    const bySev = input.findings.stats.by_severity || {};
    const summaryMetrics = [
      { label: "P0", value: String(bySev.P0 || 0) },
      { label: "P1", value: String(bySev.P1 || 0) },
      { label: "P2", value: String(bySev.P2 || 0) },
      { label: "总计", value: String(input.findings.stats.total_findings) },
      { label: "处理耗时", value: `${totalElapsed}s` },
    ];
    const analysisSections = findingsToSections(input.findings.findings);
    const toolTraces: ToolTrace[] = Object.entries(
      input.findings.stats.llm_call_stats || {},
    ).map(([stage, counts], i) => ({
      id: `stage-${i}`,
      name: stage,
      argsSummary: JSON.stringify(counts),
    }));
    return {
      status,
      evidenceItems: uploaded.concat(
        findingsToEvidence(input.findings.findings),
      ),
      summaryMetrics,
      analysisSections,
      progressSteps,
      toolTraces,
      liveProgress,
      understoodRequirement: input.understoodRequirement ?? null,
      lastUpdatedLabel,
      errorMessage,
      runningMessage,
    };
  }

  // Markdown fallback (no structured findings)
  const analysisSections = latestAi?.content
    ? splitSections(latestAi.content)
    : [];
  const anomalyCount = latestAi?.content
    ? extractAnomalyCount(latestAi.content)
    : "0";
  const toolTraces: ToolTrace[] = (latestAi?.tool_calls ?? []).map((call) => ({
    id: call.id,
    name: call.name,
    argsSummary: JSON.stringify(call.args),
  }));
  const summaryMetrics = [
    {
      label: "风险等级",
      value: latestAi?.content.includes("高风险") ? "高" : "中",
    },
    { label: "异常项", value: anomalyCount },
    { label: "处理耗时", value: `${totalElapsed}s` },
  ];

  return {
    status,
    evidenceItems: uploaded,
    summaryMetrics,
    analysisSections,
    progressSteps,
    toolTraces,
    liveProgress,
    understoodRequirement: input.understoodRequirement ?? null,
    lastUpdatedLabel,
    errorMessage,
    runningMessage,
  };
}
