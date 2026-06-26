import { describe, expect, it } from "vitest";
import { buildWorkbenchViewModel } from "../view-model";

describe("buildWorkbenchViewModel", () => {
  it("derives evidence, summary metrics, result sections, and progress state", () => {
    const model = buildWorkbenchViewModel({
      status: "completed",
      archiveUrl: "https://example.com/audit.zip",
      contentBlocks: [
        { type: "text", text: "Workbook.xlsx", metadata: { name: "Workbook.xlsx" } },
        { type: "text", text: "Evidence.pdf", metadata: { name: "Evidence.pdf" } },
      ],
      messages: [
        {
          id: "ai-1",
          type: "ai",
          content: "## 结论摘要\n存在 3 个异常点\n\n## 建议动作\n复核收入截止测试",
          tool_calls: [{ id: "tool-1", name: "analyze_worksheet", args: { file_path: "assets/uploads/a.xlsx" } }],
        },
      ],
      isLoading: false,
      elapsedSeconds: 42,
      error: null,
    });

    expect(model.evidenceItems).toHaveLength(3);
    expect(model.summaryMetrics.find((item) => item.label === "异常项")?.value).toBe("3");
    expect(model.analysisSections.map((section) => section.title)).toEqual(["结论摘要", "建议动作"]);
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
    expect(failed.progressSteps.some((step) => step.status === "failed")).toBe(true);
    expect(failed.errorMessage).toBe("分析失败，请检查输入材料后重试。");
  });
});
