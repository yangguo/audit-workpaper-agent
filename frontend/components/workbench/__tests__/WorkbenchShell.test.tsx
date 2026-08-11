import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchShell } from "../WorkbenchShell";
import { ReviewIntakePanel } from "../ReviewIntakePanel";

// Mock sonner's toast so tests can assert that error notifications are
// dispatched on export failures without rendering the real Toaster.
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

import { toast } from "sonner";

const baseWorkbenchProps = {
  header: {
    title: "审计底稿审阅",
    subtitle: "会话 A",
    statusLabel: "已完成",
  },
  summaryMetrics: [],
  analysisSections: [],
  evidenceItems: [],
  progressSteps: [],
  toolTraces: [],
  isEmpty: false,
};

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

  it("shows evidence-agent analysis, OCR outcome, excerpts, and unresolved evidence", () => {
    render(
      <WorkbenchShell
        {...baseWorkbenchProps}
        evidenceAnalysis={{
          mode: "always",
          runs: 1,
          toolCalls: 3,
          acceptedEvidence: 1,
          unresolved: 1,
          errors: 0,
          ocr: { calls: 1, success: 1, errors: 0, timeouts: 0 },
          details: [
            {
              sheet: "SA-1",
              status: "completed",
              toolCalls: 3,
              ocr: { calls: 1, success: 1, errors: 0, timeouts: 0 },
              evidence: [
                {
                  path: ".embedded_media/password-policy.docx::image1.png",
                  fileType: "png",
                  extractionStatus: "ocr",
                  excerpt: "Password age must not exceed 90 days.",
                  supports: "supports password-policy control",
                  confidence: "high",
                },
              ],
              unresolved: [{ request: "管理员截图", reason: "未提供截图" }],
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId("evidence-analysis")).toBeInTheDocument();
    expect(screen.getByText("证据分析")).toBeInTheDocument();
    expect(
      screen.getByText("MinerU OCR：调用 1 · 成功 1 · 失败 0 · 超时 0"),
    ).toBeInTheDocument();
    expect(
      screen.getByTitle(".embedded_media/password-policy.docx::image1.png"),
    ).toHaveTextContent(".embedded_media/password-policy.docx::image1.png");
    expect(
      screen.getByText("“Password age must not exceed 90 days.”"),
    ).toBeInTheDocument();
    expect(screen.getByText(/未提供截图/)).toBeInTheDocument();
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
                  {
                    attachment:
                      ".embedded_media/password-policy.docx::image1.png",
                    excerpt: "密码最小长度为 12 个字符",
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
    expect(
      screen.getByText(
        "附件：.embedded_media/password-policy.docx::image1.png",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("“密码最小长度为 12 个字符”")).toBeInTheDocument();
  });

  it("renders quality provenance, truthful gate states, grouping, and open remediation items", () => {
    render(
      <WorkbenchShell
        {...baseWorkbenchProps}
        analysisSections={[
          {
            title: "P1 中风险问题（1）",
            body: "",
            findings: [
              {
                issue_type: "证据类型缺失",
                severity: "P1",
                status: "unknown",
                sheet: "SA-4c",
                evidence_refs: [
                  { attachment: "foreign.txt", excerpt: "不得显示的拒绝引用" },
                  { sheet: "SA-4c", cell_or_range: "D12", excerpt: "已验证引用" },
                ],
                quality: {
                  schema_version: "review-quality/1",
                  finding_id: "legacy:quality-1",
                  primary_location: {
                    source_kind: "cell",
                    sheet: "SA-4c",
                    cell_or_range: "D12",
                    source_ref: "workpaper:SA-4c!D12",
                    evidence_id: "cell:12",
                  },
                  citation_validation: {
                    status: "partial",
                    verified_count: 1,
                    rejected_count: 1,
                    rejection_codes: ["out_of_scope_source"],
                    verified_refs: [
                      {
                        source_kind: "cell",
                        sheet: "SA-4c",
                        cell_or_range: "D12",
                        evidence_id: "cell:12",
                        excerpt: "已验证引用",
                      },
                    ],
                  },
                  gates: {
                    deterministic_cross_check: {
                      status: "passed",
                      reason: "已执行确定性交叉校验",
                    },
                    model_re_review: {
                      status: "not_run",
                      reason: "同一 V1 模型来源，未进行独立复核",
                    },
                    adversarial_challenge: {
                      status: "not_run",
                      reason: "仅对 P0 或升级项执行",
                    },
                  },
                  provenance: {
                    input_sha256: "abcdef1234567890",
                    engine_version: "stage-a-quality-shadow",
                  },
                  grouping: {
                    root_cause_id: "root:abc123",
                    duplicate_of: null,
                    related_finding_ids: [],
                  },
                  remediation: {
                    status: "needs_human_refinement",
                    action: "补充抽样依据",
                    required_evidence: ["用户权限导出清单"],
                    acceptance_criteria: ["可由复核人按清单复现"],
                    missing_fields: ["责任范围"],
                  },
                },
              },
            ],
          },
        ]}
      />,
    );

    const findingCard = screen.getByTestId("finding-card");
    expect(findingCard).toHaveTextContent("引用部分验证");
    expect(findingCard).toHaveTextContent("主定位：SA-4c!D12");
    expect(findingCard).toHaveTextContent("确定性交叉校验：已通过");
    expect(findingCard).toHaveTextContent("模型复核：未执行");
    expect(findingCard).toHaveTextContent("同一 V1 模型来源，未进行独立复核");
    expect(findingCard).toHaveTextContent("对抗式挑战：未执行");
    expect(findingCard).toHaveTextContent("根因编号：root:abc123");
    expect(findingCard).toHaveTextContent("整改待补全：责任范围");
    expect(findingCard).toHaveTextContent("输入版本：abcdef12");
    expect(findingCard).not.toHaveTextContent("foreign.txt");
  });

  it("renders export button when reviewId is provided", () => {
    render(<WorkbenchShell {...baseWorkbenchProps} reviewId="r123" />);
    expect(screen.getByText("导出审阅包（含质量与溯源）")).toBeInTheDocument();
  });

  it("hides export button when reviewId is absent", () => {
    render(<WorkbenchShell {...baseWorkbenchProps} />);
    expect(screen.queryByText("导出审阅包（含质量与溯源）")).not.toBeInTheDocument();
  });

  describe("export click behaviour", () => {
    let fetchMock: ReturnType<typeof vi.fn>;
    let createObjectURLMock: ReturnType<typeof vi.fn>;
    let revokeObjectURLMock: ReturnType<typeof vi.fn>;
    let originalFetch: typeof fetch | undefined;
    let originalCreate: typeof URL.createObjectURL | undefined;
    let originalRevoke: typeof URL.revokeObjectURL | undefined;

    beforeEach(() => {
      vi.mocked(toast.error).mockClear();
      originalFetch = globalThis.fetch;
      originalCreate = URL.createObjectURL;
      originalRevoke = URL.revokeObjectURL;
      fetchMock = vi.fn();
      globalThis.fetch = fetchMock as unknown as typeof fetch;
      createObjectURLMock = vi.fn(() => "blob:mock-url");
      revokeObjectURLMock = vi.fn();
      URL.createObjectURL = createObjectURLMock as unknown as typeof URL.createObjectURL;
      URL.revokeObjectURL = revokeObjectURLMock as unknown as typeof URL.revokeObjectURL;
    });

    afterEach(() => {
      if (originalFetch) globalThis.fetch = originalFetch;
      else delete (globalThis as { fetch?: typeof fetch }).fetch;
      if (originalCreate) URL.createObjectURL = originalCreate;
      if (originalRevoke) URL.revokeObjectURL = originalRevoke;
    });

    it("fetches the export URL and triggers a blob download on success", async () => {
      const user = userEvent.setup();
      fetchMock.mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(new Blob(["xlsx-bytes"])),
      });

      render(<WorkbenchShell {...baseWorkbenchProps} reviewId="r123" />);

      const button = screen.getByRole("button", { name: "导出审阅包（含质量与溯源）" });
      expect(button).not.toBeDisabled();
      await user.click(button);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const calledUrl = fetchMock.mock.calls[0][0];
      expect(String(calledUrl)).toContain("/findings/r123/export?format=xlsx");

      // Allow microtask queue to flush (response.blob() is async).
      await vi.waitFor(() => {
        expect(createObjectURLMock).toHaveBeenCalledTimes(1);
      });
      expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);
      expect(toast.error).not.toHaveBeenCalled();
    });

    it("disables the button while the export fetch is in flight", async () => {
      const user = userEvent.setup();
      let resolveResponse: (value: unknown) => void = () => {};
      fetchMock.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveResponse = resolve;
          }),
      );

      render(<WorkbenchShell {...baseWorkbenchProps} reviewId="r123" />);

      const button = screen.getByRole("button", { name: "导出审阅包（含质量与溯源）" });
      await user.click(button);

      // While the promise is pending the button must reflect the loading state.
      expect(button).toBeDisabled();

      resolveResponse({
        ok: true,
        blob: () => Promise.resolve(new Blob(["xlsx"])),
      });

      await vi.waitFor(() => {
        expect(button).not.toBeDisabled();
      });
    });

    it("shows a toast when the server responds with a non-OK status", async () => {
      const user = userEvent.setup();
      fetchMock.mockResolvedValue({
        ok: false,
        blob: () => Promise.resolve(new Blob()),
      });

      render(<WorkbenchShell {...baseWorkbenchProps} reviewId="r123" />);
      await user.click(screen.getByRole("button", { name: "导出审阅包（含质量与溯源）" }));

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalledTimes(1);
      });
      expect(createObjectURLMock).not.toHaveBeenCalled();
    });

    it("shows a toast when the network request rejects", async () => {
      const user = userEvent.setup();
      fetchMock.mockRejectedValue(new Error("network down"));

      render(<WorkbenchShell {...baseWorkbenchProps} reviewId="r123" />);
      await user.click(screen.getByRole("button", { name: "导出审阅包（含质量与溯源）" }));

      await vi.waitFor(() => {
        expect(toast.error).toHaveBeenCalledTimes(1);
      });
    });
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
