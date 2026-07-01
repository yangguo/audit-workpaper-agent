import type {
  AnalysisSection,
  EvidenceItem,
  ToolTrace,
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

export function buildWorkbenchViewModel(input: Input): WorkbenchViewModel {
  const latestAi = [...input.messages]
    .reverse()
    .find((message) => message.type === "ai" && message.content);
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

  const errorMessage =
    input.error instanceof Error
      ? "分析失败，请检查输入材料后重试。"
      : typeof input.error === "string"
        ? "分析失败，请检查输入材料后重试。"
        : undefined;

  const runningMessage = input.isLoading
    ? `正在分析底稿… 已运行 ${input.elapsedSeconds}s`
    : undefined;

  const status: WorkbenchStatus = input.error
    ? "failed"
    : input.isLoading
      ? "running"
      : input.status;

  return {
    status,
    evidenceItems: (input.contentBlocks
      .filter((block) => block.metadata?.name)
      .map((block, index): EvidenceItem => ({
        id: `${block.metadata?.name}-${index}`,
        name: block.metadata?.name ?? "未命名文件",
        source: "upload",
        status: "ready",
      })) as EvidenceItem[]).concat(
      input.archiveUrl
        ? [
            {
              id: "archive-url",
              name: input.archiveUrl,
              source: "link",
              status: "ready",
            },
          ]
        : [],
    ),
    summaryMetrics: [
      {
        label: "风险等级",
        value: latestAi?.content.includes("高风险") ? "高" : "中",
      },
      { label: "异常项", value: anomalyCount },
      { label: "处理耗时", value: `${input.elapsedSeconds}s` },
    ],
    analysisSections,
    progressSteps: [
      { label: "准备材料", status: "completed" },
      {
        label: "分析底稿",
        status: input.isLoading ? "active" : input.error ? "failed" : "completed",
      },
      {
        label: "生成结论",
        status: input.isLoading ? "pending" : input.error ? "failed" : "completed",
      },
    ],
    toolTraces,
    lastUpdatedLabel:
      input.elapsedSeconds > 0 ? `${input.elapsedSeconds}s 前更新` : "刚刚更新",
    errorMessage,
    runningMessage,
  };
}
