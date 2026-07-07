import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { WorkbenchShell } from "../WorkbenchShell";
import { ReviewIntakePanel } from "../ReviewIntakePanel";

describe("WorkbenchShell", () => {
  it("renders the audit workbench regions", () => {
    render(
      <WorkbenchShell
        header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "系统正常" }}
        summaryMetrics={[{ label: "异常项", value: "3" }]}
        analysisSections={[{ title: "结论摘要", body: "存在 3 个异常项" }]}
        evidenceItems={[{ id: "1", name: "Workbook.xlsx", source: "upload", status: "ready" }]}
        progressSteps={[{ label: "分析底稿", status: "active" }]}
        toolTraces={[{ id: "t1", name: "analyze_worksheet", argsSummary: '{"file_path":"assets/uploads/a.xlsx"}' }]}
        isEmpty={false}
      />,
    );

    expect(screen.getByRole("heading", { name: "审计底稿审阅" })).toBeInTheDocument();
    expect(screen.getByText("证据列表")).toBeInTheDocument();
    expect(screen.getByText("分析结果")).toBeInTheDocument();
    expect(screen.getByText("进度状态")).toBeInTheDocument();
    expect(screen.getByText("调用追踪")).toBeInTheDocument();
  });

  it("shows the empty workbench call to action when no evidence or result exists", () => {
    render(
      <WorkbenchShell
        header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "系统正常" }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        isEmpty
      />,
    );

    expect(screen.getByText("开始一次审阅任务")).toBeInTheDocument();
  });

  it("shows failed progress state and recovery copy", () => {
    render(
      <WorkbenchShell
        header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "处理失败" }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[{ label: "分析底稿", status: "failed" }]}
        toolTraces={[]}
        isEmpty={false}
        errorMessage="分析失败，请检查输入材料后重试。"
      />,
    );

    expect(screen.getByText("分析失败，请检查输入材料后重试。")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("uses ellipsis glyphs in loading copy", () => {
    render(
      <WorkbenchShell
        header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "处理中" }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        isEmpty={false}
        runningMessage="正在分析底稿… 已运行 8s"
      />,
    );

    expect(screen.getByText("正在分析底稿… 已运行 8s")).toBeInTheDocument();
  });

  it("renders the understood-requirement card with scope and files when provided", () => {
    render(
      <WorkbenchShell
        header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "处理中" }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        isEmpty={false}
        understoodRequirement={{
          review_id: "rid1",
          status: "running",
          scope: "PE-6",
          sheets_raw: "pe6",
          workpaper: "C22 IT一般控制测试2025v5.xlsx",
          checkpoints: "检查要点.xlsx",
          attachments_preview: null,
          summary: "将审阅 PE-6（底稿：C22 IT一般控制测试2025v5.xlsx，含检查要点：检查要点.xlsx）",
        }}
      />,
    );

    const card = screen.getByTestId("understood-requirement");
    expect(card).toBeInTheDocument();
    expect(screen.getByText("PE-6")).toBeInTheDocument();
    expect(screen.getByText("C22 IT一般控制测试2025v5.xlsx")).toBeInTheDocument();
    expect(screen.getByText("检查要点.xlsx")).toBeInTheDocument();
  });

  it("does not render the understood-requirement card when absent", () => {
    render(
      <WorkbenchShell
        header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "系统正常" }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        isEmpty
      />,
    );

    expect(screen.queryByTestId("understood-requirement")).not.toBeInTheDocument();
  });
});

describe("ReviewIntakePanel", () => {
  it("renders labeled intake controls with an accessible submit button", async () => {
    const user = userEvent.setup();

    render(
      <ReviewIntakePanel
        archiveUrl=""
        input=""
        showUrlInput
        isLoading={false}
        onArchiveUrlChange={() => {}}
        onInputChange={() => {}}
        onToggleUrlInput={() => {}}
        onSubmit={(event) => event.preventDefault()}
        onFileUpload={() => {}}
        onPaste={() => {}}
      />,
    );

    expect(screen.getByLabelText("文件下载链接")).toBeInTheDocument();
    expect(screen.getByLabelText("审阅要求")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始分析" })).toBeInTheDocument();
    await user.tab();
  });
});
