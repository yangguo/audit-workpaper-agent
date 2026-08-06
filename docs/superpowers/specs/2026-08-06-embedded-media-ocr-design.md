# 文档嵌入图片自动 OCR 设计

## 背景

`src/review/attachments.py:_read_docx_file`、`_read_pptx_file`、`_read_pdf_file` 只提取文本内容，完全忽略文档内嵌的图片（DOCX/PPTX 里的截图、PDF 里的嵌入图、扫描件 PDF 的文本层图）。受限于此：

- 审批截图、流程图、签字页等「证据在图片里、文字只是上下文」的凭证，审阅时图片部分完全失明
- 受限证据 Agent 看不到这些内嵌图，不会触发 `ocr_attachment`
- LLM 只能基于残缺的「文字」部分做判定，evidence 不足/不充分的 finding 比例被低估

## 目标

- 把 DOCX/PPTX/PDF 中嵌入的图片提取出来，**并入现有的图片 OCR 流水线**
- 受限 Agent 能识别这些「虚拟附件」并按需调 `ocr_attachment`（走 MinerU）
- finding 的 `evidence_refs.attachment` 字段能正确记录「来自 my.docx 的第 N 张图」
- 复用现有的 OCR 缓存（`ocr_by_path`）和逐字校验机制

## 非目标

- 不解决 PDF 扫描件（无文本层的整页图）—— 已有路径
- 不解决 DOCX 中的 OLE 嵌入对象
- 不改变 MinerU 的使用方式或配额控制
- 不重写 OCR 工具本身

## 方案

### 后端

**新增** `src/review/embedded_media.py`：

```python
def extract_embedded_media(attachments_dir: str) -> List[VirtualAttachment]:
    """遍历 attachments_dir 下所有 .docx/.pptx/.pdf，解出嵌入图片。

    返回虚拟附件列表，每项含：
    - rel_path: <原文件名>::<嵌入图文件名>，避免与真实附件冲突
    - source_rel_path: 原始 .docx/.pptx/.pdf 的相对路径
    - source_kind: "docx|pptx|pdf"
    - media_index: 在源文档中的序号（从 1 开始）
    - bytes: 图片内容
    - file_type: png/jpg/jpeg/jp2/webp/gif/bmp
    """
```

具体解压逻辑：
- **DOCX**: 用 `zipfile` 解 `word/media/*`（图片通常在 `word/media/`）
- **PPTX**: 用 `zipfile` 解 `ppt/media/*`
- **PDF**: 优先用 `pypdf.PdfReader.pages[i].images`（pypdf ≥ 3.0 支持）；若失败或未安装，回退到 shell `pdfimages -all <pdf> <prefix>` 抽到临时目录

**修改** `src/review/attachments.py:build_attachment_index`：

- 在原文档索引完成后调用 `extract_embedded_media(attachments_dir)`
- 把每张虚拟图片写入 `<attachments_dir>/.embedded_media/<source>::<media_index>.<ext>`（写入磁盘以便后续路径解析和缓存命中）
- 创建一个新的 `AttachmentFile`，`rel_path` 指向写入的虚拟文件路径
- 加入 `items / by_filename / by_rel_path / by_index` 索引（与真实附件一致）
- `status = "binary"`（未经 OCR），让受限 Agent 在需要时调 `ocr_attachment`

**修改** `src/review/evidence_steps.py:_extract_attachment_refs`（可选）：

- 当前解析 `<C22.SA-12-4>` 形式。增加一种「嵌入图引用」格式如 `见 my.docx 截图1`、`my.docx 图2`，解析后能命中 `by_filename` 中以 `my.docx::` 开头的虚拟文件。

实际上**只要虚拟文件在 `by_rel_path` 索引中**，执行描述写「见 `my.docx` 截图1」时 `rel_path` 大概率能命中，无需额外修改解析器——这是要测试的点。

### 成本控制

- 单次审阅最多提取 `MAX_EMBEDDED_PER_REVIEW=200` 张图（防止恶意超大文档）
- 单张图 > `MAX_EMBEDDED_IMAGE_BYTES=10MB` 跳过
- MinerU OCR 缓存按 `rel_path` 索引，重复审阅不重复计费

### 错误处理

- 单个文档的解压失败不阻塞其他文档（用 try/except 包住单文档循环）
- 抽出的临时文件保留在 `.embedded_media/`，加 `.gitignore` 忽略
- `by_filename`/`by_rel_path` 加虚拟文件不影响现有匹配（路径以 `::` 分隔，无冲突）

### 测试

`tests/review/test_embedded_media.py`：
- DOCX 内置图（用 `zipfile` 构造包含 `word/media/` 的 mock）→ 提取正确
- PPTX 内置图 → 提取正确
- PDF 嵌入图（用 `pypdf` mock 或小型 PDF fixture）→ 提取正确
- 单文档解压失败不影响其他文档
- 超大图跳过
- 虚拟附件出现在 `build_attachment_index` 的 `items` 中
- 受限 Agent 能匹配「见 my.docx 截图1」到虚拟附件

### 受限 Agent 提示词

`src/review/evidence_agent.py` 中的 system prompt 已经包含「对图片或扫描件先调用 `ocr_attachment`」指引。虚拟附件因为 `rel_path` 在索引内、status 为 binary，会被 Agent 识别为可 OCR 的图片。无需修改提示词。

## 风险

- **DOCX 嵌入图位置识别**: 用户在执行描述里写「见 `my.docx` 第二张截图」时，能否命中虚拟文件取决于 `by_rel_path` 的 key 设计。计划用 `<原文件名>::<嵌入图文件名>` 格式，让用户写 `见 my.docx::image1.png` 时能直接命中；普通写法「见 my.docx 截图1」需要 `by_filename` 的子串匹配——这超出了本次改动范围，列入后续。
- **临时目录污染**: 重复审阅可能产生大量 `.embedded_media/` 文件。snapshot 阶段已复制 `attachments_dir`，所以 pinned snapshot 也会包含这些虚拟文件。需要确认 `pinned_attachments_dir` 是「attachments 父目录」还是「attachments 本身」——看代码确认。

## 接口变更

- 新增 `src/review/embedded_media.py` 模块
- 修改 `src/review/attachments.py:build_attachment_index`
- `.gitignore` 增加 `**/.embedded_media/`
- 无对外 API 变更