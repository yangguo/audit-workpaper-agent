# 检查结果报告导出功能设计

## 背景

审阅完成后，用户需要把 `findings`（发现点）导出为 Excel 报告，方便离线查看、汇总和整改跟踪。当前系统仅支持在 Web 界面中展示结果，没有导出能力。

## 目标

- 支持将一次审阅的全部发现点导出为 `.xlsx` 文件。
- 报告包含完整字段：位置、问题类型、严重级别、依据、建议、证据引用等。
- 导出入口放在「分析结果」面板右上角，操作直观。

## 非目标

- 不支持 PDF/Word 导出（后续可扩展）。
- 不支持自定义字段选择（后续可扩展）。
- 不导出原始审阅日志或附件文件。

## 方案

### 后端

新增 `GET /findings/{review_id}/export?format=xlsx` 接口：

- 从 `storage.findings_store.load_findings(review_id)` 读取现有 findings JSON。
- 使用 `openpyxl` 生成 Excel 工作簿。
- 单工作表「审阅发现汇总」，表头固定，每行一个发现点。
- 响应头：
  - `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  - `Content-Disposition: attachment; filename="findings_{review_id}.xlsx"`

导出字段：

| 列名 | 来源字段 | 说明 |
|---|---|---|
| 序号 | 行号 | 从 1 开始 |
| Sheet | `sheet` | |
| 单元格 | `cell` | 可为空 |
| 问题类型 | `issue_type` | |
| 严重级别 | `severity` + `severity_display` | 如 `P0 / 高` |
| 风险类型 | `risk_type` | |
| 状态 | `status` | fail / unknown / pass |
| 结论 | `conclusion` 或 `llm_conclusion` | |
| 判定依据 | `basis` | 多行文本 |
| 整改建议 | `suggestion` | 多行文本 |
| 证据引用 | `evidence_refs` | JSON 文本，含 sheet/cell/attachment/excerpt |
| 交叉校验问题 | `cross_validate_issues` | 数组拼接为文本 |
| LLM 复核状态 | `llm_status` | 可为空 |
| LLM 复核说明 | `llm_comment` | 可为空 |
| 不确定原因 | `unknown_reason` | 可为空 |

### 前端

- 在 `AnalysisResultPanel` 右上角新增「导出 Excel 报告」按钮。
- 按钮仅在 `findings` 存在且非空时显示。
- 点击后发起下载请求，使用隐藏 `<a>` 或 `window.open` 触发浏览器保存。
- 下载过程中按钮显示 loading，失败时通过 toast 提示用户重试。

### 错误处理

- review_id 不存在或 findings 为空 → 后端返回 404。
- 生成失败 → 后端返回 500，前端 toast 提示。
- 网络错误 → 前端 toast 提示。

### 测试

- 后端：`tests/review/test_export.py` 验证：
  - 正常生成 Excel 且字段完整。
  - 不存在的 review_id 返回 404。
  - 空 findings 返回 404。
- 前端：在 `AnalysisResultPanel` 测试中补充导出按钮渲染断言。

## 依赖

- 后端：已有 `openpyxl`。
- 前端：无需新增依赖。

## 接口变更

新增一个 GET 端点：

```
GET /findings/{review_id}/export?format=xlsx
```

无破坏性变更。
