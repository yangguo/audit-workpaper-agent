# 审计底稿 Agent 前端（对话式）集成设计

## 目标

- 为 audit-workpaper-agent 增加一个对话式 Web 前端，复用 doc-convert 的 Next.js 聊天 UI。
- 支持与后端 OpenAI 兼容接口进行流式对话（POST `/v1/chat/completions`）。
- 支持文件上传到后端落盘，并将可引用的相对路径注入到对话上下文，便于工具调用（如 `analyze_worksheet`、`verify_attachments`）。
- 前后端分离部署：前端独立运行/部署，通过环境变量配置后端地址。

## 非目标

- 不在本次范围内新增“工作流运行控制台”（`/run`、`/stream_run`、`/cancel`、`/graph_parameter` 的表单化 UI）。
- 不在本次范围内新增对象存储上传链路（S3/OSS）。
- 不做复杂的用户体系与权限控制（如需将以网关/反向代理层接入鉴权）。

## 当前后端能力（摘要）

- OpenAI 兼容对话：POST `/v1/chat/completions`（支持流式）
- 健康检查：GET `/health`
- 工作流相关：`/run`、`/stream_run`、`/cancel/{run_id}`、`/node_run/{node_id}`
- 与文件相关的工具默认使用 `COZE_WORKSPACE_PATH`（默认 `/workspace/projects`）作为工作目录，并在 `assets` 中查找相对路径文件。

## 推荐方案

- 在本项目新增 `frontend/`，整体复用 doc-convert 的 Next.js 前端工程（App Router + Tailwind），仅做必要的后端对接适配。
- 后端新增 `/upload` 文件上传接口，并加 CORS 允许前端域名访问（至少 dev 环境）。

## 前端设计

### 目录

- `frontend/`：Next.js 应用
  - `app/`：页面与 API routes
  - `providers/Stream.tsx`：流式对话状态管理与增量渲染
  - `components/thread/`：聊天 UI（输入、消息渲染、Markdown 展示）
  - `hooks/use-file-upload.tsx`：拖拽/粘贴/选择文件，调用 `/api/upload`

### 环境变量

- `NEXT_PUBLIC_BACKEND_URL`
  - 默认：`http://localhost:5000`
  - 用途：浏览器侧请求后端 `/v1/chat/completions`、以及 Next API Route 转发后端 `/upload`

### 与后端对话

- 入口：`providers/Stream.tsx` 以 OpenAI Chat Completions 流式协议消费后端返回
- 请求：
  - URL：`${NEXT_PUBLIC_BACKEND_URL}/v1/chat/completions`
  - Method：POST
  - Body：OpenAI 兼容 payload（包含 `messages`、`stream: true` 等）
- 解析：
  - 按 `data:` 行解析 JSON
  - 拼接 `choices[0].delta.content`
  - 完成事件以 `[DONE]` 结束

### 文件上传（通过 Next API Route 转发）

- 前端调用：POST `/api/upload`
  - 表单：`files`（支持多文件）
  - `/api/upload` 在服务端读取 FormData，并转发到后端 `${BACKEND_URL}/upload`
- 约束：
  - 前端限制文件类型与大小（先延用 doc-convert 的策略，必要时再调整）

### 将上传结果注入对话上下文

- 后端返回的每个文件路径使用相对路径（相对 `COZE_WORKSPACE_PATH`），例如：
  - `assets/uploads/<uuid>_<original_filename>`
- 前端在用户消息末尾追加一段可读、可复制的路径清单：
  - `已上传文件路径：`
  - `- assets/uploads/...`

## 后端设计

### 新增接口：POST /upload

- 功能：接收 multipart 文件并保存到 `${COZE_WORKSPACE_PATH}/assets/uploads/`
- 返回：JSON
  - `files`: `[{ "original_name": string, "path": string, "size": number }]`
  - `path` 为相对路径（例如 `assets/uploads/...`）
- 命名：
  - 保存文件名建议加前缀以避免冲突（如 `<uuid>_<original_filename>`）

### CORS

- 前后端分离时，浏览器需要对后端开启 CORS
- 策略：
  - `allow_origins` 使用环境变量配置（dev 默认允许 `http://localhost:3000`）
  - 允许方法：POST/GET/OPTIONS
  - 允许 header：`Content-Type`、以及 `x-run-id` 等自定义 header（如未来需要）
  - 允许凭证：按需开启（默认关闭）

## 数据流（端到端）

1. 用户在前端选择/拖拽文件
2. 前端 POST `/api/upload`（Next 服务端）→ 转发后端 POST `/upload`
3. 后端将文件写入 `COZE_WORKSPACE_PATH/assets/uploads/` 并返回相对路径列表
4. 前端将路径列表注入用户消息后，调用后端 `/v1/chat/completions`（流式）
5. 模型在需要读取底稿时，使用相对路径调用工具（如 `analyze_worksheet(file_path="assets/uploads/xxx.xlsx")`）

## 错误处理

- 上传失败：
  - 前端显示错误提示，保留已选择文件，允许重试
  - 后端返回 `400`（非法文件）或 `500`（写入失败）
- 对话失败/中断：
  - 前端对当前 AI 消息标记失败并提示
  - 允许用户重试发送

## 安全与限制

- 后端写入目录固定为 `assets/uploads/`，不允许客户端传入任意路径
- 文件名需做基础清理（去除路径分隔符等），避免路径穿越
- 单文件/总大小限制建议在后端也做校验，防止绕过前端限制

## 验证方式

- 本地 smoke：
  - 上传接口可写入文件并返回相对路径
  - 前端能够展示上传列表并把路径注入对话
  - `/v1/chat/completions` 流式输出在 UI 中可增量渲染

