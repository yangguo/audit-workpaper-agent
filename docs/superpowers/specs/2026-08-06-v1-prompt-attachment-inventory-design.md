# V1 主审阅 prompt 注入附件清单设计

## 背景

发现于 `8d4c753d3ebc4861a65573d9fe032d6f` SA-10 review：finding「SAP 系统密码策略证据不足」

- **附件目录里有** `sap系统数据库密码策略.docx` 含 2 张嵌入图 + `sap应用系统密码策略.docx` 1 张 + `操作系统密码策略.docx` 1 张
- **V1 主审阅却判「证据不足」**——它没看到这些图，只能读工作底稿 cell 文字
- **Agent 在 always 模式下跑了 OCR 命中这些图**（`e1a5ceaca7c5460685c1bf776eb48e0d` review：8+ 次 OCR 命中 SA-10 嵌入图，全部 success）
- **Agent 结果没回填到 finding**——V1 finding 写盘时，Agent OCR 数据丢失

**结论**：V1 主审阅的 LLM 不知道有哪些证据可用 → 误判「证据不足」。受限 Agent 知道证据但太晚 → finding 已落地。

## 目标

让 V1 主审阅的 LLM 在判定前知道：
- 附件目录里有哪些真实文件
- 哪些 DOCX/PPTX/PDF 里有什么嵌入图（具体路径）
- 提取出的文本片段
- **可用 evidence_refs 候选**

这样 V1 能基于实际证据下结论：
- ✅ 看到附件里有「SAP 密码策略.docx 含 2 张图」→ 不再判「证据不足」→ 引用具体图
- ❌ 真正没有附件的 → 仍然判「证据不足」

## 非目标

- 不修改 Agent 自身（已经能 OCR）
- 不改变 V1 findings 数量或严重级别的逻辑
- 不替代 Agent（Agent 仍是后置证据验证）
- 不修改 review pipeline 控制流

## 方案

### 后端

**新增 helper** `src/review/attachments.py:build_evidence_inventory`：

```python
@dataclass
class EvidenceEntry:
    rel_path: str
    file_type: str
    status: str  # "ok" | "binary" | "unsupported"
    excerpt: str  # 文本前 200 字
    source_document: Optional[str] = None  # 嵌入图才有
    is_embedded: bool = False


def build_evidence_inventory(
    attachments: Dict[str, object],
    *,
    max_entries: int = 30,
    max_embedded: int = 12,
    max_excerpt_chars: int = 200,
) -> str:
    """Build a compact human-readable evidence inventory string for LLM prompts.

    Returns a multi-line string listing:
    - Real attachment files (top max_entries by relevance, prefer "ok" status)
    - Embedded media images (top max_embedded, grouped by source document)

    Capped to keep prompt size bounded. Used by V1 prompt builders.
    """
```

**Inventory 格式示例**：
```
[证据清单（仅展示前 30 个附件 + 12 张嵌入图，附件目录实际有 N 项）]

== 真实附件（27 项有文本内容） ==
[ok] 审计证据/SA-10/sap系统数据库密码策略.docx — 文本前 200 字：...
[ok] 审计证据/SA-10/sap应用系统密码策略.docx — 文本前 200 字：...
[binary] 审计证据/SA-10/某扫描件.pdf（无文本层，需 OCR）

== 嵌入图（共 153 张，DOCX/PPTX/PDF 中抽取） ==
[image1.png] 来自 sap系统数据库密码策略.docx
[image2.png] 来自 sap系统数据库密码策略.docx
[image1.png] 来自 sap应用系统密码策略.docx
[image1.png] 来自 操作系统密码策略.docx
...
引用示例：evidence_refs.attachment = ".embedded_media/sap系统数据库密码策略.docx::image2.png"
```

**修改 4 个 prompt builder 注入 inventory**：

| 文件 | 函数 | 现有 prompt 注入点 |
|---|---|---|
| `src/review/checkpoints.py` | `_llm_check_sheet_by_checkpoints` | `system_prompt` 末尾加 `"\n\n[证据清单]\n" + inventory` |
| `src/review/evidence_steps.py` | `_llm_check_evidence_vs_steps` | user_prompt payload 加 `available_evidence` 字段 |
| `src/review/procedure_pairs.py` | `_llm_judge_procedure_pair` | user_prompt 末尾加 inventory |
| `src/review/pipeline.py` | `run_review` → `_check_sheet_scope` | system_prompt 注入（次要） |

每个注入点用统一函数调用：
```python
from review.attachments import build_evidence_inventory
inventory = build_evidence_inventory(attachments, max_entries=30, max_embedded=12)
```

**修改 LLM prompt 末尾的指示语**：
```
"如执行描述引用了附件（如「《SAP系统密码策略》」），可从 [证据清单] 中找到真实路径和嵌入图，"
"若附件含嵌入图且需要核对界面截图，应在 evidence_refs.attachment 字段填 .embedded_media/ 路径。"
```

### 关键 LLM 引导文本

```python
EVIDENCE_GUIDANCE = """
重要：[证据清单] 段列出了本sheet附件目录中真实可用的文件及其嵌入图。\n
- 若执行描述引用了「《某文档》」，从清单中找出实际路径作为 evidence_refs.attachment\n
- 若证据是截图（密码策略截图、系统参数界面），DOCX/PPTX 中抽取的嵌入图位于 .embedded_media/ 路径\n
- 不要把没有 [证据清单] 中实际存在的文件写进 evidence_refs\n
- 不要因为「执行描述里没明说截图」就判证据不足——先看 [证据清单] 中是否真的缺\n
"""
```

## 接口变更

- 新增 `review.attachments.build_evidence_inventory` 函数
- 修改 4 个 prompt builder：增加 `attachments` 参数 + inventory 注入
- 修改 system_prompt 末尾增加 EVIDENCE_GUIDANCE
- 无破坏性变更：现有字段保留

## 错误处理

| 情况 | 行为 |
|---|
| `attachments` 为 None/空 | inventory 字符串为空，不影响现有逻辑 |
| 附件数 > 30 | 截断到 30 个，提示「实际有 N 项」 |
| 嵌入图 > 12 | 截断到 12 张 |
| LLM 误用路径 | 现有 evidence_refs 校验会失败 → 降级 unknown |

## 测试

`tests/review/test_attachments.py` 新增：
- `build_evidence_inventory` 基础输出
- 空 attachments 返回 ""
- 超过 max_entries 截断
- 嵌入图分组
- 中文不破坏（excerpt 截断在字符边界）

`tests/review/test_checkpoints.py`、`test_evidence_steps.py`、`test_procedure_pairs.py`：
- inventory 字符串出现在 mock LLM 收到的 prompt 中
- EVIDENCE_GUIDANCE 文本出现在 system_prompt 中

## 风险

- **prompt 体积**：4 个 prompt 都加 inventory，体积增大 1-2KB。靠 max_entries/max_embedded 截断。
- **LLM 行为变化**：原本「没看到附件就判证据不足」的习惯会被打破，finding 数量/严重级别可能变化。
- **缓存**：每次 review 都构建 inventory，消耗 ~10ms（无 IO）。

## 预期效果

**修复前**（SA-10 review 现状）：
> 证据类型缺失 —「底稿仅以《SAP系统密码策略》为依据，未提供系统参数界面截图」

**修复后**（理想 finding）：
> 证据类型缺失 —「执行描述引用了《SAP系统密码策略》，附件目录中存在该文件含 2 张嵌入图（…::image1.png, …::image2.png），建议补充 AD 层密码策略的独立证据」

差异：原 finding 是「没有」，新 finding 是「有但不全」——更准确，审计经理能针对性补充。