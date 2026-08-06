# 受限 Agent 主动 OCR 嵌入图设计

## 背景

`src/review/evidence_agent.py` 现在能跑通（commit `f19a80e` 修了 OpenAI strict 模式），但 Agent 调用 `ocr_attachment(".../xxx.docx")` 时拿到的是**整份文件的已抽取文本**，不是真正的 OCR 结果。

更糟的是：DOCX/PPTX/PDF 里的嵌入图（截图、流程图、扫描页）才是关键证据，但 Agent 不知道 `.embedded_media/` 路径存在，也不主动去 OCR 单张图。

## 目标

让 Agent 在审阅含嵌入图的 DOCX/PPTX 时，**主动 OCR 单张图**而非整份文档，产出可追溯到具体图的 evidence：

- `list_attachment_files` 输出标记嵌入图（`source_document` 字段）
- Agent system prompt 明确指引：DOCX/PPTX 嵌入图通过 `.embedded_media/` 暴露，应逐张 OCR
- `ocr_attachment` 调用针对**单张图**而非整份文档

## 非目标

- 不修改 OCR backend 本身
- 不改变 PDF/PPT 嵌入图提取逻辑（Tasks 1-3 已完成）
- 不修改 finding 生成或 LLM 评估流程
- 不替代人工审计（仍是 Agent 辅助）

## 方案

### 后端改动 1：`list_attachment_files` 输出加 `source_document` 字段

`src/review/evidence_agent.py:_item_summary` 增加：

```python
def _item_summary(item: AttachmentFile) -> Dict[str, object]:
    summary = {
        "rel_path": item.rel_path,
        "filename": item.filename,
        "file_type": item.file_type,
        "status": item.status,
        "size": item.size,
    }
    # 嵌入图项：标记来自哪个原始文档
    if item.rel_path.startswith(".embedded_media/"):
        # rel_path = ".embedded_media/<docx>::<image>.png"
        # source = 父文档名（"<docx>::<image>.png" 前的部分）
        parts = item.rel_path.split("/", 1)[1]
        if "::" in parts:
            source_doc, media_name = parts.split("::", 1)
            summary["source_document"] = source_doc
            summary["media_name"] = media_name
    return summary
```

效果：Agent 调用 `list_attachment_files` 后，能看到：

```json
{
  "rel_path": ".embedded_media/2-备份日志.docx::image1.png",
  "filename": "2-备份日志.docx::image1.png",
  "file_type": "png",
  "status": "binary",
  "source_document": "2-备份日志.docx",
  "media_name": "image1.png"
}
```

### 后端改动 2：Agent system prompt 增加引导

`src/review/evidence_agent.py` 中传给 `create_agent` 的 system_prompt：

```python
system_prompt=(
    "你是受限的审计证据调查 Agent。你只能通过工具查看审阅快照中的附件索引和已提取文本。"
    "你不可以执行命令、写文件、访问工具返回之外的路径或编造证据。"
    + ("如果附件是图片或扫描件，可先使用 ocr_attachment 获取 OCR 原文；OCR 失败时必须保留 unresolved。" if ocr_client else "")
    + "关键指引：DOCX/PPTX/PDF 中提取出的嵌入图位于 .embedded_media/ 虚拟目录，"
    + "路径形如 .embedded_media/<原文档名>::<图名>.<ext>。"
    + "若需要核对该文档内的截图、流程图、扫描页证据，应直接对 .embedded_media/ 中的具体图调用 ocr_attachment，"
    + "而非对整份 DOCX/PDF 调用（整份调用只会返回文字）。"
    + "在 list_attachment_files 返回中中查看 source_document 字段可定位图来源。"
    + "你只负责定位候选证据，不负责给出审阅结论。最后必须返回约定 JSON。"
)
```

### 后端改动 3：`_build_investigation_prompt` 增加上下文

把 `.embedded_media/` 条目单独列出，提醒 Agent 优先考虑：

```python
embedded = [it for it in attachments["items"] if it.rel_path.startswith(".embedded_media/")]
payload = {
    "sheet": str(getattr(ws, "title", "") or ""),
    "cells": relevant_cells,
    "attachment_status_counts": attachments.get("status_counts", {}),
    "embedded_media_count": len(embedded),
    "embedded_media_examples": [
        {
            "source_document": it.rel_path.split("::")[0].split("/", 1)[1],
            "media_filename": it.rel_path.split("::")[1] if "::" in it.rel_path else "",
        }
        for it in embedded[:10]
    ] if embedded else [],
}
```

效果：Agent 在 prompt 里看到 `embedded_media_examples` 列出的具体图，能直接 OCR。

### 改动 4：可观测性 — Agent prompt 增加字数预算

`_DEFAULT_MAX_PROMPT_CHARS = 16000` 已够；但 embedded_media_examples 要限长：

```python
"embedded_media_examples": [...][:10],  # 限前 10 张
"embedded_media_count": len(embedded),  # 总数
"embedded_media_more": len(embedded) > 10,  # 是否还有更多
```

## 接口变更

- `list_attachment_files` 返回的每个 item dict 多 2 个字段：`source_document` 和 `media_name`（仅嵌入图项）
- Agent system_prompt 文案扩展
- `_build_investigation_prompt` payload 多 3 个字段

无破坏性变更：现有字段保留；新增字段默认 None 或空列表。

## 错误处理

| 情况 | 行为 |
|---|
| `.embedded_media/` 不存在 | `embedded_media_examples` 为空，Agent 退回原行为 |
| Agent 不响应 `.embedded_media/` 路径 | OCR 失败返回 `unresolved`，不报错 |
| Agent OCR `.embedded_media/` 路径但图片格式不支持 | MinerU 返回错误，OCR 计数 +1 |

## 测试

`tests/review/test_evidence_agent.py` 新增：
- `_item_summary` 在虚拟嵌入图项上输出 `source_document` 和 `media_name`
- `_build_investigation_prompt` 在有嵌入图时填充 `embedded_media_examples`
- 列表字段截断在 10 个

不端到端测试 Agent prompt 改动（LLM 行为不稳定），但通过单元测试确保数据和 prompt 结构正确。

## 风险

- **Agent 行为不稳**：提示词调整需要实际跑几次才能确认效果。可能要1-2 轮微调。
- **prompt 体积**：增加 3 个字段，prompt 增大。控制示例在 10 个内。
- **OCR 成本**：Agent 现在会调更多次 OCR（每张图一次），成本上升。可通过 `_DEFAULT_MAX_AGENT_STEPS` 限制步数。