import json
import re

import openpyxl
import pytest
from langchain_core.messages import AIMessage

from review.pipeline import run_review, _parse_sheet_filter, _finding_to_dict, _backfill_embedded_evidence_refs
from review.models import Finding


def test_backfill_embedded_evidence_refs_adds_missing_paths():
    finding = {
        "sheet": "SA-10",
        "basis": "底稿引用了《SAP系统密码策略》<C22.SA-10-1>。截图 .embedded_media/sap密码策略.docx::image1.png 显示密码长度5。",
        "evidence_refs": [
            {"sheet": "SA-10", "cell_or_range": "C14", "attachment": "", "excerpt": "通过检查《SAP系统密码策略》"}
        ],
    }
    out = _backfill_embedded_evidence_refs([finding])
    atts = [r["attachment"] for r in out[0]["evidence_refs"]]
    assert ".embedded_media/sap密码策略.docx::image1.png" in atts


def test_backfill_embedded_evidence_refs_no_duplicate():
    finding = {
        "sheet": "SA-10",
        "basis": ".embedded_media/foo.docx::image1.png 已有。",
        "evidence_refs": [
            {"sheet": "SA-10", "cell_or_range": "", "attachment": ".embedded_media/foo.docx::image1.png", "excerpt": "x"}
        ],
    }
    out = _backfill_embedded_evidence_refs([finding])
    assert len(out[0]["evidence_refs"]) == 1


def test_backfill_embedded_evidence_refs_handles_real_attachments():
    finding = {
        "sheet": "PE-6",
        "basis": "见 审计证据/PE-6/C10-演练记录.pdf（含截图）。",
        "evidence_refs": [],
    }
    out = _backfill_embedded_evidence_refs([finding])
    atts = [r["attachment"] for r in out[0]["evidence_refs"]]
    assert "审计证据/PE-6/C10-演练记录.pdf" in atts


class _FakeRunnable:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        return AIMessage(content=self.content)


class _FakeLLM:
    """Returns a canned review result for any LLM call (used by _llm_review_findings)."""
    def __init__(self, content):
        self.content = content

    def bind(self, **kwargs):
        return _FakeRunnable(self.content)


def _pass_review_payload():
    return json.dumps({
        "results": [{
            "id": 1,
            "status": "pass",
            "conclusion": "该发现经复核不成立结论",
            "evidence_refs": [],
            "llm_validity": "不成立",
            "llm_severity": "低",
            "severity": "P2",
            "reasons": ["理由"],
            "risk_type": "证据不足",
        }]
    }, ensure_ascii=False)


def test_parse_sheet_filter():
    assert _parse_sheet_filter(None) is None
    assert _parse_sheet_filter("all") is None
    assert _parse_sheet_filter("SA-4c,SA-5") == ["SA-4c", "SA-5"]
    assert _parse_sheet_filter("SA-4c，SA-5") == ["SA-4c", "SA-5"]


def test_finding_to_dict_parses_json_fields():
    f = Finding(
        issue_type="t", severity="P0", sheet="SA-1", cell="A1",
        snippet="s", basis="b", suggestion="sug",
        evidence_refs='[{"cell_or_range":"A1"}]', reasons='["理由"]',
        fix_suggestion_detail='{"supplement_explanation":"补充"}',
    )
    d = _finding_to_dict(f)
    assert d["evidence_refs"] == [{"cell_or_range": "A1"}]
    assert d["reasons"] == ["理由"]
    assert d["fix_suggestion_detail"] == {"supplement_explanation": "补充"}
    assert d["severity_display"] == "高"


@pytest.mark.asyncio
async def test_run_review_scope_finding_only(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SA-4c"
    ws["A1"] = "管理员账号识别情况"
    # no layout, no checkpoints, no preview -> only _check_sheet_scope fires
    llm = _FakeLLM(_pass_review_payload())

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
    )

    assert len(findings) == 1
    f0 = findings[0]
    assert f0["issue_type"] == "特权账号识别范围可能不完整"
    assert f0["severity"] == "P1"
    assert f0["severity_display"] == "中"
    assert f0["llm_status"] == "pass"
    assert f0["cross_validate_issues"] == []
    assert f0["challenge_verdict"] is None
    assert stats["total_findings"] == 1
    assert stats["by_severity"]["P1"] == 1


@pytest.mark.asyncio
async def test_run_review_empty_workbook(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    wb.active.title = "Empty"
    llm = _FakeLLM('{"results": []}')
    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
    )
    assert findings == []
    assert stats["total_findings"] == 0


@pytest.mark.asyncio
async def test_run_review_falls_back_when_specified_sheet_not_reviewable(monkeypatch):
    """If `sheets` selects a sheet with no layout/checkpoints, fall back to all sheets."""
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    import openpyxl as _ox
    wb = _ox.Workbook()
    cover = wb.active
    cover.title = "Cover"
    cover["A1"] = "封面内容，无审计程序布局"
    ws = wb.create_sheet("SA-4c")
    ws["A1"] = "标准审计程序"
    ws["B1"] = "执行审计程序"
    ws["A5"] = "审计期间获取系统用户清单并检查权限分配情况。"
    ws["B5"] = "我们导出了系统用户清单并进行了权限核查与记录。"
    llm = _FakeLLM('{"status":"pass","reason":"符合","evidence_refs":[]}')

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets="Cover", llm=llm,
    )
    # fell back to all sheets -> SA-4c was reviewed -> procedure_pair LLM call attempted
    assert stats.get("warning"), "expected a fallback warning"
    assert stats["llm_call_stats"].get("procedure_pair", {}).get("calls", 0) >= 1


@pytest.mark.asyncio
async def test_run_review_honors_reviewable_sheet_scope(monkeypatch):
    """A reviewable named sheet is reviewed ALONE — never expanded to all sheets.

    Regression guard for the scoping contract: when the caller passes
    `sheets="SA-4c"` and SA-4c has a detectable layout, the pipeline must
    review only SA-4c (no fallback). The agent relies on this to honor a
    user request to review a single control point.
    """
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    import openpyxl as _ox
    import review.pipeline as _pipe

    def _add_layout(ws, std, exe):
        ws["A1"] = "标准审计程序"
        ws["B1"] = "执行审计程序"
        ws["A5"] = std
        ws["B5"] = exe

    wb = _ox.Workbook()
    ws1 = wb.active
    ws1.title = "SA-4c"
    _add_layout(ws1, "审计期间获取系统用户清单并检查权限分配情况。",
                "我们导出了系统用户清单并进行了权限核查与记录。")
    ws2 = wb.create_sheet("SA-5")
    _add_layout(ws2, "抽样核查账号创建审批。", "我们抽样核查了账号创建审批记录。")
    llm = _FakeLLM('{"results": []}')

    reviewed: list = []

    async def _spy(llm, wb, target_sheets, attachments=None):
        reviewed.extend(target_sheets)
        return {}, []

    monkeypatch.setattr(_pipe, "_llm_check_procedure_pairs", _spy)

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets="SA-4c", llm=llm,
    )

    assert stats.get("warning", "") == "", "should not fall back to all sheets"
    assert reviewed == ["SA-4c"], (
        f"expected only SA-4c reviewed, got {reviewed} (scope was expanded?)"
    )


@pytest.mark.asyncio
async def test_run_review_resolves_loose_sheet_name(monkeypatch):
    """A loose sheet name (case/dash variant an LLM produces) resolves to the
    actual tab and is reviewed alone — no fallback to all sheets.

    Regression guard for the user-reported bug: agent passed `sheets='pe6'`
    but the actual tab is `PE-6`; the exact-match filter rejected it and fell
    back to all 34 sheets. The filter must normalize-match (PE-6, pe6, pe-6
    all resolve to the same tab).
    """
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    import openpyxl as _ox
    import review.pipeline as _pipe

    def _add_layout(ws, std, exe):
        ws["A1"] = "标准审计程序"
        ws["B1"] = "执行审计程序"
        ws["A5"] = std
        ws["B5"] = exe

    wb = _ox.Workbook()
    ws1 = wb.active
    ws1.title = "PE-6"  # actual tab: uppercase, dash
    _add_layout(ws1, "审计期间获取批处理作业清单。", "我们导出了批处理作业清单。")
    ws2 = wb.create_sheet("SA-4c")
    _add_layout(ws2, "获取系统用户清单并检查权限。", "我们导出用户清单，截图保存。")
    llm = _FakeLLM('{"results": []}')

    reviewed: list = []

    async def _spy(llm, wb, target_sheets, attachments=None):
        reviewed.extend(target_sheets)
        return {}, []

    monkeypatch.setattr(_pipe, "_llm_check_procedure_pairs", _spy)

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets="pe6", llm=llm,
    )

    assert stats.get("warning", "") == "", (
        f"loose name 'pe6' should resolve to PE-6, not fall back; warning={stats.get('warning')!r}"
    )
    assert reviewed == ["PE-6"], (
        f"expected only PE-6 reviewed (resolved from 'pe6'), got {reviewed}"
    )


@pytest.mark.asyncio
async def test_run_review_uses_constrained_evidence_agent_and_records_stats(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    monkeypatch.setenv("REVIEW_EVIDENCE_AGENT_MODE", "always")
    import review.pipeline as _pipe
    from review.models import AttachmentFile

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SA-4c"
    ws["A1"] = "标准审计程序"
    ws["B1"] = "执行审计程序"
    ws["A5"] = "获取系统用户清单并检查权限。"
    ws["B5"] = "我们核验用户清单，见附件1。"
    item = AttachmentFile(
        index="1", rel_dir="SA-4c", filename="users.txt",
        rel_path="SA-4c/users.txt", file_type="txt", status="ok",
        extraction_status="ok", extracted_text="admin,administrator", size=19,
    )
    attachments = {
        "source_type": "directory",
        "path": "/pinned/attachments",
        "items": [item],
        "by_filename": {"users.txt": [item]},
        "by_rel_path": {"sa-4c/users.txt": [item]},
        "by_index": {"1": [item]},
        "by_sheet_norm": {"SA4C": [item]},
        "status_counts": {"ok": 1},
    }
    captured = {}

    async def _fake_agent(**kwargs):
        captured["sheet"] = kwargs["ws"].title
        return {
            "status": "completed",
            "evidence": [{
                "path": "SA-4c/users.txt",
                "file_type": "txt",
                "extraction_status": "ok",
                "excerpt": "admin,administrator",
                "supports": "用户清单中的管理员权限",
                "confidence": "high",
            }],
            "unresolved": [],
            "tool_trace": [{"tool": "search_attachment_text"}],
            "tool_calls": 1,
        }

    async def _fake_evidence_steps(**kwargs):
        captured["agent_evidence"] = kwargs["attachments"].get("agent_evidence_by_sheet")
        return []

    monkeypatch.setattr(_pipe, "investigate_sheet", _fake_agent)
    monkeypatch.setattr(_pipe, "_llm_check_evidence_vs_steps", _fake_evidence_steps)

    findings, stats = await _pipe.run_review(
        wb=wb, checkpoints={}, attachments=attachments, sheets=None,
        llm=_FakeLLM('{"results": []}'),
    )

    assert findings == []
    assert captured["sheet"] == "SA-4c"
    assert captured["agent_evidence"]["SA4C"][0]["excerpt"] == "admin,administrator"
    assert stats["evidence_agent"]["runs"] == 1
    assert stats["evidence_agent"]["accepted_evidence"] == 1
    assert stats["evidence_agent"]["tool_calls"] == 1


@pytest.mark.asyncio
async def test_run_review_partial_match_warns_but_does_not_fall_back(monkeypatch):
    """Some requested names resolve (one reviewable, one not), some don't.

    The reviewable one is reviewed alone (no fallback to all sheets); the
    unresolvable name is surfaced in a warning. Regression guard for the
    mixed case, which the all-resolve / none-resolve tests don't cover.
    """
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    import openpyxl as _ox
    import review.pipeline as _pipe

    def _add_layout(ws, std, exe):
        ws["A1"] = "标准审计程序"
        ws["B1"] = "执行审计程序"
        ws["A5"] = std
        ws["B5"] = exe

    wb = _ox.Workbook()
    ws1 = wb.active
    ws1.title = "PE-6"
    _add_layout(ws1, "审计期间获取批处理作业清单。", "我们导出了批处理作业清单。")
    ws2 = wb.create_sheet("Cover")
    ws2["A1"] = "封面，无审计程序布局"  # resolves but not reviewable (no layout/checkpoints)
    llm = _FakeLLM('{"results": []}')

    reviewed: list = []

    async def _spy(llm, wb, target_sheets, attachments=None):
        reviewed.append(list(target_sheets))
        return {}, []

    monkeypatch.setattr(_pipe, "_llm_check_procedure_pairs", _spy)

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets="pe6,ZZZ", llm=llm,
    )

    # PE-6 resolved + reviewable -> reviewed; ZZZ unresolvable -> warned, not fatal
    assert reviewed == [["PE-6"]], f"expected only PE-6 reviewed, got {reviewed}"
    warning = stats.get("warning", "")
    assert warning, "expected a partial-match warning"
    assert "ZZZ" in warning, f"warning should mention unmatched ZZZ: {warning!r}"
    assert "全部 Sheet" not in warning, (
        f"should NOT fall back to all sheets: {warning!r}"
    )


@pytest.mark.asyncio
async def test_run_review_emits_progress_at_stages(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    wb.active.title = "Empty"
    llm = _FakeLLM('{"results": []}')
    recorded: list[dict] = []
    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
        on_progress=lambda p: recorded.append(p),
    )
    stages = [p["stage"] for p in recorded]
    assert "starting" in stages
    assert "done" in stages
    assert recorded[-1]["stage"] == "done"
    assert recorded[-1]["findings_so_far"]["total"] == len(findings)
    for p in recorded:
        assert {"stage", "current_sheet", "llm_calls", "findings_so_far", "msg"} <= set(p.keys())
        assert isinstance(p["llm_calls"], dict)
        assert isinstance(p["findings_so_far"]["total"], int)


@pytest.mark.asyncio
async def test_run_review_ignores_on_progress_exceptions(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    wb.active.title = "Empty"
    llm = _FakeLLM('{"results": []}')

    def boom(p):
        raise RuntimeError("progress callback broken")

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
        on_progress=boom,
    )
    # review still completed despite the callback throwing
    assert stats["total_findings"] == len(findings)


@pytest.mark.asyncio
async def test_intra_chunk_progress_emitted_during_long_checkpoints_stage(monkeypatch):
    """A sheet with many checkpoints must emit progress between chunks, not only
    at the stage boundary. Otherwise long checkpoint reviews look frozen for
    many minutes.

    Regression guard for: 1 sheet with 11 checkpoints at batch_size=6 should
    emit at least 2 intra-chunk progress events (one per processed chunk).
    """
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    import openpyxl as _ox
    import review.pipeline as _pipe
    import review.checkpoints as _ckp

    wb = _ox.Workbook()
    ws = wb.active
    ws.title = "SA-12"

    # 11 checkpoints to drive >1 chunk with batch_size=6
    many_ckpts = [f"检查要点 {i}：核查对应证据并形成结论。" for i in range(1, 12)]
    llm = _FakeLLM('{"results": []}')

    intra_events: list[str] = []

    # Spy on the intra-chunk callback to capture messages emitted between chunks.
    import review.checkpoints as _ckp_mod

    async def _spy(llm, ws_title, ws, checkpoints, attachments=None,
                   batch_size=6, sleep_seconds=0, attachments_preview=None,
                   on_progress=None):
        # Mirror the real implementation's chunk loop just enough to invoke the
        # intra-chunk callback the way the real code does.
        for start in range(0, len(checkpoints), max(1, int(batch_size))):
            end = min(start + max(1, int(batch_size)), len(checkpoints))
            if on_progress is not None:
                on_progress(f"checkpoints:{ws_title}",
                            f"已处理 {end} / {len(checkpoints)} 个检查要点")
        return []

    monkeypatch.setattr(_pipe, "_llm_check_sheet_by_checkpoints", _spy)

    def collect(p):
        if p["current_sheet"] == "SA-12" and "已处理" in p["msg"]:
            intra_events.append(p["msg"])

    findings, stats = await run_review(
        wb=wb, checkpoints={"SA-12": many_ckpts}, attachments_preview={},
        sheets=None, llm=llm, on_progress=collect,
    )
    assert len(intra_events) >= 2, (
        f"expected >=2 intra-chunk events for 11 checkpoints, got {intra_events}"
    )
    assert intra_events[-1].endswith("/ 11 个检查要点"), (
        f"final intra-chunk event should report total 11, got {intra_events[-1]!r}"
    )
