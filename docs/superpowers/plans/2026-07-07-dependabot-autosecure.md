# Dependabot 漏洞修复 + 安全更新自动合并 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 立即修复前端 critical+high 漏洞（vitest/vite），并建立 dependabot + CI 自动合并基础设施，让安全更新在测试通过后自动 squash 合并。

**Architecture:** 三件套：`.github/dependabot.yml`（npm + uv 双 ecosystem，原生 auto-merge，minor/patch 分组）+ `.github/workflows/ci.yml`（PR/push 触发，后端 pytest + 前端 vitest/lint/tsc 双 job）+ 仓库设置（手动开启 auto-merge + required checks）。立即修复通过升级 `vitest` 到 4.x 完成。

**Tech Stack:** GitHub Actions, dependabot v2 config, vitest 4.x, uv, pytest, npm

**Spec:** `docs/superpowers/specs/2026-07-07-dependabot-autosecure-design.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `frontend/package.json` | 修改 | `vitest` 升级到 `^4.1.10` |
| `frontend/package-lock.json` | 重建 | 锁定新依赖树 |
| `.github/dependabot.yml` | 新建 | npm + uv ecosystem，auto-merge，分组，schedule |
| `.github/workflows/ci.yml` | 新建 | PR/push 触发的 backend + frontend 双 job CI |
| `README.md` | 修改 | 加"首次启用自动合并"手动设置步骤 |

---

### Task 1: 升级 vitest 修复 critical+high 漏洞

**Files:**
- Modify: `frontend/package.json` (`devDependencies.vitest`)
- Modify: `frontend/package-lock.json`（由 `npm install` 重建）

- [ ] **Step 1: 升级 vitest 到 4.x**

在 `frontend/` 目录运行：

```bash
cd frontend
npm install -D vitest@^4.1.10
```

预期：`package.json` 的 `vitest` 变为 `^4.1.10`，`package-lock.json` 重建，拉入新版 `vite`/`@vitest/mocker`/`vite-node`/`esbuild`。

- [ ] **Step 2: 验证漏洞已降**

运行：

```bash
cd frontend
npm audit --json | python -c "import json,sys;d=json.load(sys.stdin);print(d.get('metadata',{}).get('vulnerabilities',{}))"
```

预期：`critical` 和 `high` 均为 `0`（原来各 1）。`total` 从 13 降到 ≤9（清掉 critical vitest + high vite + 若干 dev moderate）。

- [ ] **Step 3: 跑前端测试确认未破**

运行：

```bash
cd frontend
npx vitest run --pool=forks --poolOptions.forks.singleFork=true
```

预期：全部测试通过（既有 12 个 workbench/view-model 测试）。若 vitest 4.x API 变动导致失败，按报错调整测试代码（常见：`vi`/`expect` 导入路径、`describe`/`it` 语义未变）。`--pool=forks --poolOptions.forks.singleFork=true` 是该仓库既有要求（见 memory），必须保留。

- [ ] **Step 4: 类型检查 + lint**

运行：

```bash
cd frontend
npx tsc --noEmit
npm run lint
```

预期：`tsc` exit 0；`lint` 无新增错误（既有 3 个未使用变量警告允许）。

- [ ] **Step 5: 提交**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "fix(frontend): 升级 vitest 到 4.x 修复 critical+high 漏洞

vitest 2→4 修复 critical(vitest) + high(vite) 漏洞及若干 dev-only moderate。
dev-only 改动，测试/lint/tsc 全绿。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 新建 dependabot 配置

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 1: 创建配置文件**

写入 `.github/dependabot.yml`：

```yaml
# Dependabot 配置：前后端安全更新，原生 auto-merge（squash），
# minor/patch 合并减少噪音，major 单独 PR 人工确认 breaking。
# 前提：仓库 Settings → Pull Requests 勾选 "Allow auto-merge"，
# 且 main 分支保护已把 CI 检查设为 required（见 README 首次启用步骤）。
version: 2
auto-merge: true
updates:
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    auto-merge: true
    groups:
      minor-patch:
        update-types:
          - "minor"
          - "patch"
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    auto-merge: true
    groups:
      minor-patch:
        update-types:
          - "minor"
          - "patch"
```

- [ ] **Step 2: 校验 YAML 语法**

运行：

```bash
python -c "import yaml,sys; yaml.safe_load(open('.github/dependabot.yml',encoding='utf-8')); print('YAML valid')"
```

预期：输出 `YAML valid`。

- [ ] **Step 3: 提交**

```bash
git add .github/dependabot.yml
git commit -m "ci: 新增 dependabot 配置（npm+uv，auto-merge squash，minor/patch 分组）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 新建 CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 创建 workflow 文件**

写入 `.github/workflows/ci.yml`：

```yaml
# CI：PR/push 触发，后端 pytest + 前端 vitest/lint/tsc。
# 是 dependabot auto-merge 的判定前置——CI 通过才会自动 squash 合并。
name: CI

on:
  push:
    branches: [main]
  pull_request:

# 同一 PR 新推送时取消旧 run，省额度
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    runs-on: ubuntu-latest
    env:
      WORKSPACE_PATH: /tmp/workspace
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install uv
        run: pip install uv
      - name: Sync dependencies
        run: uv sync
      - name: Prepare workspace
        run: mkdir -p $WORKSPACE_PATH/assets/uploads $WORKSPACE_PATH/assets/results
      - name: Run backend tests
        run: uv run pytest tests/ -q

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Install dependencies
        run: npm ci
      - name: Lint
        run: npm run lint
      - name: Type check
        run: npx tsc --noEmit
      - name: Run frontend tests
        run: npx vitest run --pool=forks --poolOptions.forks.singleFork=true
```

- [ ] **Step 2: 校验 YAML 语法**

运行：

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml',encoding='utf-8')); print('YAML valid')"
```

预期：输出 `YAML valid`。

- [ ] **Step 3: 本地预演 backend job 命令**

在仓库根目录运行（模拟 CI 的后端命令）：

```bash
uv sync && mkdir -p /tmp/workspace/assets/uploads /tmp/workspace/assets/results && WORKSPACE_PATH=/tmp/workspace uv run pytest tests/ -q
```

预期：111 passed（与本地既有结果一致）。这一步确认 CI 的 backend 命令在干净环境能跑通。

- [ ] **Step 4: 本地预演 frontend job 命令**

在 `frontend/` 运行：

```bash
cd frontend && npm ci && npm run lint && npx tsc --noEmit && npx vitest run --pool=forks --poolOptions.forks.singleFork=true
```

预期：lint 无新错、tsc exit 0、vitest 全绿。`npm ci` 会按 `package-lock.json` 装干净依赖，验证锁文件一致性。

- [ ] **Step 5: 提交**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: 新增 PR/push CI（backend pytest + frontend vitest/lint/tsc）

dependabot auto-merge 的判定前置；CI 通过才会自动合并。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: README 加"首次启用自动合并"步骤

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 定位插入点**

运行：

```bash
grep -n "## 环境变量" README.md | head -1
```

预期：输出环境变量章节的行号。在其**前**插入新章节"## 安全更新自动合并"。

- [ ] **Step 2: 插入手动设置章节**

在 `## 环境变量` 之前插入：

```markdown
## 安全更新自动合并

仓库已配置 dependabot（`.github/dependabot.yml`）+ CI（`.github/workflows/ci.yml`）。dependabot 每周一检查前后端依赖安全更新，开 PR 后 CI 跑测试，通过则自动 squash 合并。

**首次启用需在 GitHub 仓库设置（一次性，手动）**：

1. Settings → General → Pull Requests → 勾选 "Allow auto-merge"，默认合并方式选 **Squash**。
2. Settings → Branches → `main` → Add branch protection rule → 勾 "Require status checks to pass before merging" → required status checks 选 `backend` 和 `frontend`（CI job 名）。
3. Settings → Code security → 确认 "Dependabot security updates" 已开启。

完成上述设置后，dependabot 开的安全更新 PR 在 CI 通过后会自动合并到 `main`。major 更新单独成 PR，CI 因 breaking 失败则停住等人工处理。

```

- [ ] **Step 3: 校验 README 未破坏**

运行：

```bash
grep -c "安全更新自动合并" README.md
```

预期：输出 `1`。

- [ ] **Step 4: 提交**

```bash
git add README.md
git commit -m "docs: README 加 dependabot 自动合并首次启用步骤

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 推送并部署后验证

**Files:** 无（部署验证）

- [ ] **Step 1: 推送所有提交**

运行：

```bash
git push origin main
```

预期：fast-forward 推送成功（含 vitest 升级、dependabot.yml、ci.yml、README 四个提交 + 之前的 spec 提交）。

- [ ] **Step 2: 确认 CI 在 main 上首次运行**

推送后，在 GitHub Actions 页面确认 `CI` workflow 在最新 push 上触发。两个 job（backend/frontend）应都绿（本地已预演）。

若失败：看日志，常见是 CI 环境差异（Python/Node 版本、`uv` 安装）。修复后补提交再推。

- [ ] **Step 3: 用户手动配置仓库设置（无法自动）**

提示用户完成 README Task 4 步骤 1-3（开启 auto-merge + required checks + dependabot security updates）。这是 dependabot auto-merge 生效的前提，只能网页操作。

- [ ] **Step 4: 部署后人工确认（无法自动验证，记录在案）**

下次 dependabot 按 schedule（每周一）开 PR 后，确认：
- PR 上 CI 两个 job 都跑且通过。
- auto-merge 在 CI 通过后触发 squash 合并。
- major 更新单独 PR，breaking 时 CI 拦住。

这一步只能在 dependabot 首次开 PR 后验证，本计划不阻塞完成——记录为部署后观察项。

---

## 验证清单（全部完成后）

- [ ] `npm audit` critical+high = 0（Task 1 Step 2）
- [ ] 前端测试/lint/tsc 全绿（Task 1 Step 3-4）
- [ ] 后端 111 passed（Task 3 Step 3）
- [ ] `.github/dependabot.yml` + `.github/workflows/ci.yml` YAML 合法（Task 2/3 Step 2）
- [ ] CI 在 push 后 GitHub Actions 跑通（Task 5 Step 2）
- [ ] 仓库设置已开 auto-merge + required checks（Task 5 Step 3，用户手动）

## 部署后观察项（非阻塞）

- dependabot 首次 schedule 开 PR 后，auto-merge 实际触发。
- major 安全更新 PR 的处理（CI 拦 breaking）。
