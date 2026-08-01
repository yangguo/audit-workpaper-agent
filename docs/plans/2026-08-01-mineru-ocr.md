# MinerU OCR 证据工具实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在附件目录审阅链路中增加可配置的 MinerU OCR 能力，让受限证据 Agent 能对已快照的图片/扫描件按需取证，并对 OCR 结果执行和普通附件相同的路径、摘录校验。

**Architecture:** `ReviewArtifactStore` 先固定附件目录；`evidence_agent` 只允许 `ocr_attachment` 接收索引中的相对路径，并由 `MinerUClient` 读取固定文件。客户端使用 MinerU 官方签名上传和异步轮询协议：`auto` 在有 Token 时使用精确 `/api/v4/file-urls/batch` + `/api/v4/extract-results/batch/{batch_id}`，无 Token 时使用轻量 `/api/v1/agent/parse/file` + `/api/v1/agent/parse/{task_id}`。结果只保留有上限的 Markdown 文本，签名 URL 不返回给 Agent；OCR 文本缓存按相对路径绑定，只有逐字摘录命中缓存才进入 Finding。

**Tech Stack:** Python 3.12, `requests`, MinerU API v1/v4, LangChain constrained tools, pytest/pytest-asyncio.

### Task 1: Define provider client contract

**Files:**
- Create: `src/review/mineru_client.py`
- Test: `tests/review/test_mineru_client.py`

Implement lightweight and precise signed-upload workflows, bounded polling, result download, ZIP `full.md` extraction, file/type/size limits, and structured error/timeout results. Never expose signed URLs in returned result objects.

### Task 2: Add OCR as a constrained evidence tool

**Files:**
- Modify: `src/review/evidence_agent.py`
- Modify: `src/review/attachments.py`
- Modify: `src/review/pipeline.py`
- Tests: `tests/review/test_evidence_agent.py`, `tests/review/test_attachment_directory.py`

Expose OCR only when `MINERU_OCR_MODE` is enabled (or an injected client is used in tests). Resolve the indexed path beneath the pinned directory, cache successful text, let search/read consume the cache, and validate OCR excerpts before using them as evidence. Aggregate OCR call/success/error/timeout counts in review stats.

### Task 3: Configuration and operational documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `config/agent_llm_config.json`

Document opt-in privacy behavior, precise/lightweight limits, Token/model/language/poll settings, and the official MinerU API reference.

### Task 4: Verification

Run focused OCR/evidence tests, the complete Python suite, frontend tests, TypeScript checking, and the production frontend build. Report the exact provider behavior and any existing warnings separately from failures.
