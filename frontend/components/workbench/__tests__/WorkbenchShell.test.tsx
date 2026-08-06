import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { WorkbenchShell } from "../WorkbenchShell";
import { ReviewIntakePanel } from "../ReviewIntakePanel";

describe("WorkbenchShell", () => {
  it("renders the audit workbench regions", () => {
    render(
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "系统正常",
        }}
        summaryMetrics={[{ label: "异常项", value: "3" }]}
        analysisSections={[{ title: "结论摘要", body: "存在 3 个异常项" }]}
        evidenceItems={[
          { id: "1", name: "Workbook.xlsx", source: "upload", status: "ready" },
        ]}
        progressSteps={[{ label: "分析底稿", status: "active" }]}
        toolTraces={[
          {
            id: "t1",
            name: "analyze_worksheet",
            argsSummary: '{"file_path":"assets/uploads/a.xlsx"}',
          },
        ]}
        isEmpty={false}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "审计底稿审阅" }),
    ).toBeInTheDocument();
    expect(screen.getByText("证据列表")).toBeInTheDocument();
    expect(screen.getByText("分析结果")).toBeInTheDocument();
    expect(screen.getByText("进度状态")).toBeInTheDocument();
    expect(screen.getByText("调用追踪")).toBeInTheDocument();
  });

  it("shows the empty workbench call to action when no evidence or result exists", () => {
    render(
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "系统正常",
        }}
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
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "处理失败",
        }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[{ label: "分析底稿", status: "failed" }]}
        toolTraces={[]}
        isEmpty={false}
        errorMessage="分析失败，请检查输入材料后重试。"
      />,
    );

    expect(
      screen.getByText("分析失败，请检查输入材料后重试。"),
    ).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("uses ellipsis glyphs in loading copy", () => {
    render(
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "处理中",
        }}
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
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "处理中",
        }}
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
          attachments_dir: "dir-1",
          attachments_preview: null,
          summary:
            "将审阅 PE-6（底稿：C22 IT一般控制测试2025v5.xlsx，含检查要点：检查要点.xlsx）",
        }}
      />,
    );

    const card = screen.getByTestId("understood-requirement");
    expect(card).toBeInTheDocument();
    expect(screen.getByText("PE-6")).toBeInTheDocument();
    expect(
      screen.getByText("C22 IT一般控制测试2025v5.xlsx"),
    ).toBeInTheDocument();
    expect(screen.getByText("检查要点.xlsx")).toBeInTheDocument();
    expect(screen.getByText("dir-1")).toBeInTheDocument();
  });

  it("does not render the understood-requirement card when absent", () => {
    render(
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "系统正常",
        }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        isEmpty
      />,
    );

    expect(
      screen.queryByTestId("understood-requirement"),
    ).not.toBeInTheDocument();
  });

  it("renders the Evidence-First stage artifact without replacing V1 results", () => {
    render(
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "已完成",
        }}
        summaryMetrics={[{ label: "异常项", value: "1" }]}
        analysisSections={[{ title: "结论摘要", body: "V1 结果" }]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        isEmpty={false}
        artifact={{
          review_id: "rid-artifact",
          artifact_status: "completed",
          stages: {
            stage_a: {
              status: "completed",
              capture_status: "complete",
              captured_cell_count: 12,
              sheet_count: 1,
            },
            stage_b: {
              status: "completed",
              policy_pack: { id: "itgc-core", version: "1.0.0" },
              findings: [
                {
                  finding_id: "finding-b",
                  issue_type: "证据类型缺失",
                  rule_id: "procedure.required_evidence",
                  decision: "unknown",
                  evidence_refs_v2: [
                    { sheet: "SA-4c", cell_or_range: "D12", quote: "执行描述" },
                  ],
                },
              ],
            },
            stage_c: {
              status: "disabled",
              findings: [],
            },
          },
        }}
      />,
    );

    expect(screen.getByTestId("review-artifact-panel")).toBeInTheDocument();
    expect(screen.getByText("Evidence-First 过程")).toBeInTheDocument();
    expect(screen.getByText("阶段 B 规则候选")).toBeInTheDocument();
    expect(screen.getByText("证据位置：SA-4c!D12")).toBeInTheDocument();
    expect(screen.getByText("V1 结果")).toBeInTheDocument();
  });

  it("renders structured finding fields as readable blocks", () => {
    render(
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "已完成",
        }}
        summaryMetrics={[]}
        analysisSections={[
          {
            title: "P1 中风险问题（1）",
            body: "",
            findings: [
              {
                issue_type: "证据类型缺失",
                severity: "P1",
                severity_display: "中",
                status: "fail",
                risk_type: "证据不足",
                sheet: "SA-4c",
                cell: "D12",
                conclusion: "执行描述没有体现证据检查。",
                basis: "标准程序要求检查证据。",
                reasons: ["没有记录抽样范围"],
                suggestion: "补充证据清单和抽样依据。",
                fix_suggestion_detail: {
                  required_evidence_type: "系统导出清单",
                },
                llm_status: "unknown",
                llm_reasons: '["需要确认抽样总体"]',
                llm_missing_evidence: '["用户权限导出清单"]',
                llm_next_actions: '["补充抽样依据"]',
                llm_evidence_refs: JSON.stringify([
                  {
                    sheet: "SA-4c",
                    cell_or_range: "E13",
                    excerpt: "权限清单原文",
                  },
                ]),
                evidence_refs: [
                  {
                    sheet: "SA-4c",
                    cell_or_range: "D12",
                    excerpt: "执行描述原文",
                  },
                ],
              },
            ],
          },
        ]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        isEmpty={false}
      />,
    );

    const findingCard = screen.getByTestId("finding-card");
    expect(findingCard).toBeInTheDocument();
    expect(screen.getByText("证据类型缺失")).toBeInTheDocument();
    expect(findingCard).toHaveTextContent("位置：SA-4c!D12");
    expect(screen.getByText("结论")).toBeInTheDocument();
    expect(screen.getByText("判定依据")).toBeInTheDocument();
    expect(screen.getByText("没有记录抽样范围")).toBeInTheDocument();
    expect(screen.getByText("整改建议")).toBeInTheDocument();
    expect(screen.getByText("所需证据类型：系统导出清单")).toBeInTheDocument();
    expect(screen.getByText("LLM 复核状态")).toBeInTheDocument();
    expect(screen.getByText("待确认")).toBeInTheDocument();
    expect(screen.getByText("需要确认抽样总体")).toBeInTheDocument();
    expect(screen.getByText("用户权限导出清单")).toBeInTheDocument();
    expect(screen.getByText("补充抽样依据")).toBeInTheDocument();
    expect(screen.getByText("LLM 证据引用")).toBeInTheDocument();
    expect(screen.getByText("“权限清单原文”")).toBeInTheDocument();
    expect(screen.getAllByText("证据 1")).toHaveLength(2);
    expect(screen.getByText("“执行描述原文”")).toBeInTheDocument();
  });

  it("renders export button when reviewId is provided", () => {
    render(
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: "会话 A",
          statusLabel: "已完成",
        }}
        summaryMetrics={[]}
        analysisSections={[]}
        evidenceItems={[]}
        progressSteps={[]}
        toolTraces={[]}
        reviewId="r123"
        isEmpty={false}
      />,
    );

    expect(screen.getByText("导出 Excel 报告")).toBeInTheDocument();
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
        onAttachmentDirectoryUpload={() => {}}
        attachmentDirectoryFileCount={0}
        onPaste={() => {}}
      />,
    );

    expect(screen.getByLabelText("文件下载链接")).toBeInTheDocument();
    expect(screen.getByLabelText("审阅要求")).toBeInTheDocument();
    expect(screen.getByLabelText("上传附件目录")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "开始分析" }),
    ).toBeInTheDocument();
    await user.tab();
  });
});
