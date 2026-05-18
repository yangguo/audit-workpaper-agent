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
  -e COZE_WORKLOAD_IDENTITY_API_KEY=<your-api-key> \
  -e COZE_INTEGRATION_MODEL_BASE_URL=<your-llm-base-url> \
  -e FRONTEND_ORIGINS=http://localhost:3000 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/assets/uploads:/app/assets/uploads \
  audit-workpaper-agent
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `COZE_WORKLOAD_IDENTITY_API_KEY` | 是 | LLM API 密钥 |
| `COZE_INTEGRATION_MODEL_BASE_URL` | 是 | LLM 接口地址 |
| `FRONTEND_ORIGINS` | 否 | CORS 允许的前端 Origin，默认 `http://localhost:3000` |
| `COZE_WORKSPACE_PATH` | 否 | 工作目录根路径，默认 `/app` |
| `COZE_PROJECT_ENV` | 否 | 设为 `DEV` 开启开发模式（热重载） |
| `PGDATABASE_URL` | 否 | PostgreSQL 连接串，不设置则使用内存存储 |

## 后端环境变量（本地开发）

- `FRONTEND_ORIGINS`：CORS 允许的前端 Origin 列表，使用英文逗号分隔；未设置时默认 `http://localhost:3000`
  - 示例：`FRONTEND_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`
  - 若前端开发端口或域名有变化，需要同步更新该值
- `COZE_WORKSPACE_PATH`：工作目录根路径（影响上传文件落盘位置）；未设置时默认当前工作目录

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

- `${COZE_WORKSPACE_PATH}/assets/uploads/`
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

