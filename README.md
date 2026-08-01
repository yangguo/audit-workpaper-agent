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
- 参数：`files`（可重复传多个文件）
- 限制：最多 10 个文件；单文件最大 100MB

示例：

```bash
curl -X POST "http://localhost:5000/upload" \
  -F "files=@/path/to/a.pdf" \
  -F "files=@/path/to/b.png"
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
- 返回的 `path` 为相对路径（从 `assets/` 起）
- 前端默认通过 `POST /api/upload` 代理到后端 `POST /upload`（读取 `NEXT_PUBLIC_BACKEND_URL`）

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
