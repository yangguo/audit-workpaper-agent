# 项目结构说明

- 后端（FastAPI）：`src/`
- 前端（Next.js）：`frontend/`

# 本地运行（后端）

## 运行流程

```bash
bash scripts/local_run.sh -m flow
```

## 运行节点

```bash
bash scripts/local_run.sh -m node -n node_name
```

## 启动 HTTP 服务

```bash
bash scripts/http_run.sh -p 5000
```

## 本地配置 LLM

后端使用 OpenAI-compatible 接口。Agent 对话和 Excel 审阅共用同一个 API key/base URL，但可以通过两个模型变量分别指定模型。

```bash
cp .env.example .env
# 编辑 .env，至少填写 LLM_API_KEY、LLM_BASE_URL，
# 并将 AGENT_LLM_MODEL、REVIEW_LLM_MODEL 改成服务商实际可用的模型名
```

`LLM_BASE_URL` 填服务商的 API 根地址（通常以 `/v1` 结尾），不要填写具体的 `/chat/completions` 路径。启动方式会自动读取项目根目录的 `.env`：

```bash
bash scripts/http_run.sh -p 5000
# 或
bash scripts/local_run.sh -m flow
```

完整变量示例见 [.env.example](/Users/vyang/Desktop/spaces/audit-workpaper-agent/.env.example)。

## 阶段 B 策略包试点

审阅完成后，后端会在 `assets/reviews/<review_id>/` 中异步生成 Evidence-First shadow artifact。阶段 B 默认使用仓库内版本化的 `itgc-core/1.0.0` 策略包执行三条确定性规则，并写入：

- `review-plan.json`：本次实际匹配的 Sheet、事实、规则和证据 ID；显式指定但不存在的 Sheet 会记录 `scope_validation_failed`，不会回退到全部 Sheet。
- `policy-findings.json`：带规则版本、稳定 `identity_key`、`evidence_id`、逐字引用、偏移和内容哈希的阶段 B 候选。

试点规则包括“仅访谈且缺少实质性证据”“标准要求的证据类型未在执行描述中体现”和“特权账号范围未覆盖 OS/DB 管理员”。这些结果暂不合并到 `findings.json` 或现有 `/findings/{review_id}` 响应，V1 结果仍是用户侧权威结果。

相关配置：`REVIEW_POLICY_MODE=shadow|off`（默认 `shadow`）、`REVIEW_POLICY_PACK_ID`、`REVIEW_POLICY_PACK_VERSION`、`REVIEW_POLICY_PACK_ROOT` 和可选的 `REVIEW_ENGINE_VERSION`。策略包加载或执行失败只会将 shadow artifact 标记为 error，不会回滚或修改已完成的 V1 审阅。

# Docker 部署（后端）

## 构建镜像

```bash
docker build -t audit-workpaper-agent .
```

## 运行容器

```bash
# 提前创建挂载目录（避免容器内目录被遮盖）
mkdir -p logs assets/uploads

docker run -d \
  --name audit-agent \
  -p 5000:5000 \
  -e LLM_API_KEY=<your-api-key> \
  -e LLM_BASE_URL=<your-llm-base-url> \
  -e FRONTEND_ORIGINS=http://localhost:3000 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/assets/uploads:/app/assets/uploads \
  audit-workpaper-agent
```

## 安全更新自动合并

仓库已配置 dependabot（`.github/dependabot.yml`）+ CI（`.github/workflows/ci.yml`）。dependabot 每周一检查前后端依赖安全更新，开 PR 后 CI 跑测试，通过则自动 squash 合并。

**首次启用需在 GitHub 仓库设置（一次性，手动）**：

1. Settings → General → Pull Requests → 勾选 "Allow auto-merge"，默认合并方式选 **Squash**。
2. Settings → Branches → `main` → Add branch protection rule → 勾 "Require status checks to pass before merging" → required status checks 选 `backend` 和 `frontend`（CI job 名）。
3. Settings → Code security → 确认 "Dependabot security updates" 已开启。

完成上述设置后，dependabot 开的安全更新 PR 在 CI 通过后会自动合并到 `main`。major 更新单独成 PR，CI 因 breaking 失败则停住等人工处理。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `LLM_API_KEY` | 是 | LLM API 密钥 |
| `LLM_BASE_URL` | 是 | LLM 接口地址 |
| `FRONTEND_ORIGINS` | 否 | CORS 允许的前端 Origin，默认 `http://localhost:3000` |
| `WORKSPACE_PATH` | 否 | 工作目录根路径，默认 `/app` |
| `APP_ENV` | 否 | 设为 `DEV` 开启开发模式（热重载） |
| `AGENT_LLM_MODEL` | 否 | Agent LLM 模型，默认 `doubao-seed-2-0-pro-260215` |
| `AGENT_LLM_TEMPERATURE` | 否 | Agent LLM 温度，默认 `0.7` |
| `AGENT_LLM_MAX_TOKENS` | 否 | Agent LLM 最大 token 数，默认 `10000` |
| `AGENT_LLM_TIMEOUT` | 否 | Agent LLM 超时（秒），默认 `600` |
| `REVIEW_LLM_MODEL` | 否 | 审阅引擎 LLM 模型，默认 `doubao-seed-1-6-251015` |
| `REVIEW_EVIDENCE_AGENT_MODE` | 否 | 受限证据调查 Agent：`off`、`fallback`、`always`；默认 `fallback` |
| `REVIEW_EVIDENCE_AGENT_MAX_STEPS` | 否 | 单个 Sheet 的证据调查最大 Agent 步数，默认 `8` |
| `REVIEW_POLICY_MODE` | 否 | 阶段 B 策略 shadow：`shadow` 或 `off`；默认 `shadow` |
| `REVIEW_POLICY_PACK_ID` | 否 | 策略包 ID，默认 `itgc-core` |
| `REVIEW_POLICY_PACK_VERSION` | 否 | 策略包版本，默认 `1.0.0` |
| `REVIEW_POLICY_PACK_ROOT` | 否 | 策略包根目录；不设置时使用仓库内 `policy_packs/` |
| `REVIEW_ENGINE_VERSION` | 否 | artifact 中记录的执行器版本，默认 `stage-b-policy-shadow` |
| `MINERU_OCR_MODE` | 否 | OCR 模式：`off`（默认）、`auto`、`lightweight`、`precise`；远程处理附件前需明确开启 |
| `MINERU_TOKEN` | `precise/auto` 时 | MinerU 精确解析 API Token；`auto` 有 Token 时优先走精确 API |
| `MINERU_MODEL_VERSION` | 否 | 精确 API 模型，默认 `vlm` |
| `MINERU_OCR_LANGUAGE` | 否 | OCR 语言，默认 `ch` |
| `MINERU_OCR_MAX_WAIT_SECONDS` | 否 | 单个 OCR 任务最长等待时间，默认 `300` 秒 |
| `MINERU_OCR_POLL_INTERVAL_SECONDS` | 否 | OCR 轮询间隔，默认 `2` 秒 |
| `MINERU_OCR_MAX_TEXT_CHARS` | 否 | 单个附件纳入证据上下文的 OCR 文本上限，默认 `12000` |
| `S3_ENDPOINT_URL` | 否 | S3 兼容存储端点（启用对象存储时必填） |
| `S3_BUCKET_NAME` | 否 | S3 桶名 |
| `S3_STORAGE_TOKEN` | 否 | S3 代理签名 token |
| `PGDATABASE_URL` | 否 | PostgreSQL 连接串，不设置则使用内存存储 |

## 后端环境变量（本地开发）

- `FRONTEND_ORIGINS`：CORS 允许的前端 Origin 列表，使用英文逗号分隔；未设置时默认 `http://localhost:3000`
  - 示例：`FRONTEND_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`
  - 若前端开发端口或域名有变化，需要同步更新该值
- `WORKSPACE_PATH`：工作目录根路径（影响上传文件落盘位置）；未设置时默认当前工作目录

## 上传接口（后端）

- Method：`POST`
- Path：`/upload`
- Content-Type：`multipart/form-data`
- 普通文件参数：`files`（可重复传多个文件）
- 附件目录参数：`upload_mode=attachments_dir`、`files`、与文件一一对应的 `relative_paths`
- 普通文件限制：最多 10 个文件；单文件最大 100MB
- 附件目录限制：最多 500 个文件；单文件最大 100MB；目录总大小最大 1GB

示例：

```bash
curl -X POST "http://localhost:5000/upload" \
  -F "files=@/path/to/a.pdf" \
  -F "files=@/path/to/b.png"
```

附件目录上传示例（每个 `relative_paths` 与同位置的 `files` 对应）：

```bash
curl -X POST "http://localhost:5000/upload" \
  -F "upload_mode=attachments_dir" \
  -F "relative_paths=SA-4c/evidence.txt" \
  -F "files=@/path/to/attachments/evidence.txt"
```

响应示例：

```json
{
  "files": [
    {
      "original_name": "a.pdf",
      "path": "assets/uploads/<uuid>_a.pdf",
      "size": 123
    }
  ]
}
```

落盘位置：

- `${WORKSPACE_PATH}/assets/uploads/`
- 附件目录落盘到 `${WORKSPACE_PATH}/assets/uploads/attachments/<batch-id>/`，并保留目录层级
- 返回的 `path` 为相对路径（从 `assets/` 起）
- 前端默认通过 `POST /api/upload` 代理到后端 `POST /upload`（读取 `NEXT_PUBLIC_BACKEND_URL`）

前端的“上传附件目录”会自动发送 `upload_mode=attachments_dir`。审阅 Agent 收到返回的
`directory` 路径后，将其作为 `review_workpaper(..., attachments_dir=...)`；审阅器会递归定位底稿引用的实际证据文件，并读取可解析文本参与分析。

审阅器默认采用“确定性索引 + 受限证据 Agent + 规则/LLM 校验”的混合方式：先快照目录并建立索引；只有附件引用未匹配、文件无法解析或需要进一步交叉查找时，才启动证据 Agent。该 Agent 只能列出、搜索和读取快照内已索引的相对路径，不能执行命令、写文件或访问其他目录。Agent 返回的路径和摘录会经过服务端校验，调查状态、工具调用、来源和未解决事项会写入审阅统计。

### OCR 附件证据

当 `MINERU_OCR_MODE` 不是 `off` 时，受限证据 Agent 会额外获得 `ocr_attachment` 工具。它只能对当前审阅快照中已索引的相对路径调用 MinerU，适用于图片、扫描 PDF 及其他普通解析器无法读取的支持格式；OCR 结果会回到同一个 `ocr_by_path` 缓存，再经过路径和逐字摘录校验后进入审阅上下文。

- `auto`：配置 `MINERU_TOKEN` 时走精确 API（本地签名上传、批量结果轮询、ZIP 中的 `full.md`）；未配置 Token 时走免 Token 的轻量文件上传 API。
- `lightweight`：免 Token，单文件、10MB/20 页限制，仅返回 Markdown；适合低敏感、较小的图片或扫描件，但受 IP 限频影响。
- `precise`：需要 `MINERU_TOKEN`，单文件支持至 200MB/200 页，返回 ZIP 结果并读取 `full.md`；更适合正式审阅。
- 默认关闭是为了避免审计附件未经批准被发送到外部服务。OCR 失败、超限或不支持时只记录 `unresolved`，不会把模型猜测当作证据。

接口实现依据 [MinerU 文档解析接口文档](https://mineru.net/apiManage/docs) 的签名上传、异步轮询和两种 API 模式。

# 前端运行（frontend/）

1. 进入前端目录：

```bash
cd frontend
```

2. 配置环境变量（推荐复制示例文件）：

```bash
cp .env.example .env.local
```

其中：

- `NEXT_PUBLIC_BACKEND_URL`：后端 FastAPI 服务地址（默认 `http://localhost:5000`）

3. 安装依赖并启动开发服务器：

```bash
npm install
npm run dev
```

默认访问地址：`http://localhost:3000`
