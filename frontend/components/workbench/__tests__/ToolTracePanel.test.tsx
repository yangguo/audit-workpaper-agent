import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ToolTracePanel } from "../ToolTracePanel";
import type { ReviewProgress } from "../types";

const progress: ReviewProgress = {
  stage: "checkpoints",
  current_sheet: "SA-9 用户权限",
  llm_calls: { checkpoints: 3, evidence_steps: 1 },
  findings_so_far: { P0: 0, P1: 1, P2: 2, total: 3 },
  recent_events: [
    { t: "10:00:02", msg: "完成 SA-9 checkpoint 评审" },
    { t: "10:00:01", msg: "开始处理 SA-9" },
  ],
  updated_at: "2026-08-05T10:00:02",
};

describe("ToolTracePanel", () => {
  it("renders live progress when provided", () => {
    render(<ToolTracePanel traces={[]} liveProgress={progress} />);
    // `checkpoints` appears in both the stage label and the LLM call summary,
    // so use getAllByText to verify it is rendered (verbatim brief impl renders
    // it in two distinct elements).
    expect(screen.getAllByText(/checkpoints/).length).toBeGreaterThan(0);
    expect(screen.getByText(/SA-9 用户权限/)).toBeInTheDocument();
    expect(screen.getByText(/checkpoints.*3|3.*checkpoints/)).toBeInTheDocument();
    expect(screen.getByText(/共\s*3/)).toBeInTheDocument();
    expect(screen.getByText(/完成 SA-9 checkpoint 评审/)).toBeInTheDocument();
  });

  it("renders traces when no live progress", () => {
    render(
      <ToolTracePanel
        traces={[{ id: "t1", name: "analyze_worksheet", argsSummary: "{}" }]}
      />,
    );
    expect(screen.getByText("analyze_worksheet")).toBeInTheDocument();
  });

  it("renders placeholder when empty", () => {
    render(<ToolTracePanel traces={[]} />);
    expect(screen.getByText(/工具调用将显示在此处/)).toBeInTheDocument();
  });

  it("does not crash on missing progress fields", () => {
    render(
      <ToolTracePanel
        traces={[]}
        liveProgress={
          { stage: "checkpoints" } as unknown as ReviewProgress
        }
      />,
    );
    expect(screen.getByText(/checkpoints/)).toBeInTheDocument();
  });
});
