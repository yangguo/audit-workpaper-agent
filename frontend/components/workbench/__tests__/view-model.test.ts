import { describe, expect, it } from "vitest";
import { buildWorkbenchViewModel } from "../view-model";

const buildInput = (
  overrides: Partial<Parameters<typeof buildWorkbenchViewModel>[0]>,
) => ({
  status: "completed" as const,
  archiveUrl: "",
  contentBlocks: [],
  messages: [],
  isLoading: false,
  elapsedSeconds: 0,
  error: null,
  ...overrides,
});

describe("buildWorkbenchViewModel", () => {
  it("derives evidence, summary metrics, result sections, and progress state", () => {
    const model = buildWorkbenchViewModel({
      status: "completed",
      archiveUrl: "https://example.com/audit.zip",
      contentBlocks: [
        {
          type: "text",
          text: "Workbook.xlsx",
          metadata: { name: "Workbook.xlsx" },
        },
        {
          type: "text",
          text: "Evidence.pdf",
          metadata: { name: "Evidence.pdf" },
        },
      ],
      messages: [
        {
          id: "ai-1",
          type: "ai",
          content:
            "## 结论摘要\n存在 3 个异常点\n\n## 建议动作\n复核收入截止测试",
          tool_calls: [
            {
              id: "tool-1",
              name: "analyze_worksheet",
              args: { file_path: "assets/uploads/a.xlsx" },
            },
          ],
        },
      ],
      isLoading: false,
      elapsedSeconds: 42,
      error: null,
    });

    expect(model.evidenceItems).toHaveLength(3);
    expect(
      model.summaryMetrics.find((item) => item.label === "异常项")?.value,
    ).toBe("3");
    expect(model.analysisSections.map((section) => section.title)).toEqual([
      "结论摘要",
      "建议动作",
    ]);
    expect(model.progressSteps.at(-1)?.status).toBe("completed");
    expect(model.toolTraces[0]?.name).toBe("analyze_worksheet");
  });

  it("marks failure and timeout states for the status rail", () => {
    const failed = buildWorkbenchViewModel({
      status: "failed",
      archiveUrl: "",
      contentBlocks: [],
      messages: [],
      isLoading: false,
      elapsedSeconds: 180,
      error: new Error("timeout"),
    });

    expect(failed.status).toBe("failed");
    expect(failed.progressSteps.some((step) => step.status === "failed")).toBe(
      true,
    );
    expect(failed.errorMessage).toBe("分析失败，请检查输入材料后重试。");
  });

  it("exposes reviewId from findings payload", () => {
    const input = buildInput({
      findings: {
        review_id: "r123",
        created_at: "",
        source: "test.xlsx",
        stats: {
          total_findings: 1,
          by_severity: { P0: 1, P1: 0, P2: 0 },
          by_status: {},
          by_risk_type: {},
          llm_call_stats: {},
        },
        findings: [
          {
            issue_type: "问题",
            severity: "P0",
            sheet: "SA-1",
            cell: "C5",
            snippet: "",
            basis: "",
            suggestion: "",
            status: "fail",
            risk_type: "一致性",
          },
        ],
      },
    });
    const model = buildWorkbenchViewModel(input);
    expect(model.reviewId).toBe("r123");
  });

  it("builds metrics and sections from structured findings when provided", () => {
    const model = buildWorkbenchViewModel({
      status: "completed",
      archiveUrl: "",
      contentBlocks: [],
      messages: [{ id: "ai-1", type: "ai", content: "## 审阅报告\n..." }],
      isLoading: false,
      elapsedSeconds: 12,
      error: null,
      findings: {
        review_id: "rid",
        stats: {
          total_findings: 2,
          by_severity: { P0: 1, P1: 1, P2: 0 },
          by_status: { fail: 2 },
          by_risk_type: { 证据不足: 2 },
          llm_call_stats: { "checkpoints:SA-1": { calls: 3, ok: 3 } },
        },
        findings: [
          {
            issue_type: "特权账号识别范围可能不完整",
            severity: "P1",
            severity_display: "中",
            sheet: "SA-4c",
            cell: null,
            basis: "依据",
            suggestion: "建议",
            evidence_refs: [{ sheet: "SA-4c", cell_or_range: "A1" }],
            conclusion: "结论",
          },
          {
            issue_type: "执行列疑似未替换模板",
            severity: "P0",
            severity_display: "高",
            sheet: "SA-1",
            cell: "B5",
            basis: "依据2",
            suggestion: "建议2",
            evidence_refs: [],
            conclusion: "结论2",
          },
        ],
      },
    });

    expect(model.summaryMetrics.find((m) => m.label === "P0")?.value).toBe("1");
    expect(model.summaryMetrics.find((m) => m.label === "P1")?.value).toBe("1");
    expect(model.summaryMetrics.find((m) => m.label === "总计")?.value).toBe(
      "2",
    );
    const titles = model.analysisSections.map((s) => s.title);
    expect(titles).toContain("P0 高风险问题（1）");
    expect(titles).toContain("P1 中风险问题（1）");
    expect(
      model.analysisSections.find((section) => section.title.startsWith("P0"))
        ?.findings?.[0]?.issue_type,
    ).toBe("执行列疑似未替换模板");
    // evidence_ref surfaced in the evidence list
    expect(model.evidenceItems.some((e) => e.name.includes("SA-4c"))).toBe(
      true,
    );
    // llm_call_stats surfaced as tool traces
    expect(model.toolTraces.some((t) => t.name.startsWith("checkpoints"))).toBe(
      true,
    );
  });

  it("passes the understood requirement through to the view model", () => {
    const understood = {
      review_id: "rid1",
      status: "running",
      scope: "PE-6",
      sheets_raw: "pe6",
      workpaper: "C22 IT一般控制测试2025v5.xlsx",
      checkpoints: "检查要点.xlsx",
      attachments_dir: "dir-1",
      attachments_preview: null,
      summary:
        "将审阅 PE-6（底稿：C22 IT一般控制测试2025v5.xlsx，含检查要点：检查要点.xlsx）",
    };
    const model = buildWorkbenchViewModel({
      status: "running",
      archiveUrl: "",
      contentBlocks: [],
      messages: [],
      isLoading: false,
      elapsedSeconds: 3,
      error: null,
      understoodRequirement: understood,
    });

    expect(model.understoodRequirement).toEqual(understood);
  });

  it("defaults understood requirement to null when not provided", () => {
    const model = buildWorkbenchViewModel({
      status: "idle",
      archiveUrl: "",
      contentBlocks: [],
      messages: [],
      isLoading: false,
      elapsedSeconds: 0,
      error: null,
    });
    expect(model.understoodRequirement).toBeNull();
  });

  it("shows total elapsed time and live progress while review is running", () => {
    const model = buildWorkbenchViewModel({
      status: "running",
      archiveUrl: "",
      contentBlocks: [],
      messages: [],
      isLoading: false,
      elapsedSeconds: 6,
      reviewStatus: "running",
      reviewElapsedSeconds: 120,
      reviewProgress: {
        stage: "checkpoints",
        current_sheet: "SA-9",
        llm_calls: { checkpoints: 3 },
        findings_so_far: { P0: 0, P1: 1, P2: 2, total: 3 },
        recent_events: [{ t: "10:00:00", msg: "完成 SA-9 checkpoint 评审" }],
        updated_at: "2026-08-05T10:00:00",
      },
      error: null,
    });
    const metric = model.summaryMetrics.find((m) => m.label === "处理耗时");
    expect(metric?.value).toBe("126s");
    expect(model.liveProgress?.stage).toBe("checkpoints");
    expect(model.liveProgress?.findings_so_far.total).toBe(3);
  });

  it("does not surface live progress when review is not running", () => {
    const model = buildWorkbenchViewModel({
      status: "completed",
      archiveUrl: "",
      contentBlocks: [],
      messages: [],
      isLoading: false,
      elapsedSeconds: 42,
      error: null,
    });
    expect(model.liveProgress).toBeUndefined();
  });
});
