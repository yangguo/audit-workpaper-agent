# Dependabot 漏洞修复 + 安全更新自动合并 — 设计文档

**日期**：2026-07-07
**状态**：已确认，待实现

## 背景与目标

推送代码后 GitHub 报告默认分支有 46 个 dependabot 漏洞（1 critical / 14 high / 24 moderate / 7 low）。本地 `npm audit` 实际为 13 个（1 critical `vitest` / 1 high `vite` / 10 moderate / 1 low）——差异是 GitHub 按传递依赖展开计数。

两个目标：
1. **立即修复** critical + high 漏洞（用户确认范围）。
2. **建立自动合并基础设施**，让安全更新定期、安全地自动合并（测试通过为门槛）。

仓库现状：无 `.github/` 目录（无 dependabot 配置、无任何 CI workflow）。前端 npm（`frontend/package.json` + `package-lock.json`），后端 uv（`pyproject.toml` + `uv.lock`）。

## 范围决策（用户确认）

- 立即修复：**仅 critical + high**（`vitest`/`vite`，dev-only）。moderate 留给自动 workflow。
- 自动合并门槛：**测试通过才合**（需先建 CI）。
- 覆盖范围：**前后端都纳入**（npm + uv 两个 ecosystem）。
- 合并方式：**Squash merge**（与仓库现有单行提交风格一致）。

## 架构总览

两部分互为依赖：

**(A) 立即修复 critical+high**：前端 `vitest` 从 `^2.1.8` 升到 `^4.1.10`，拉新版 `vite`，修掉 critical `vitest` + high `vite` + 若干 dev moderate。dev-only 改动，跑测试验证不破。

**(B) 自动合并基础设施**（三件套）：
1. `.github/dependabot.yml` — 两个 ecosystem（`npm`/`frontend`、`uv`/根），`auto-merge: true`，按语义版本分组（major 单独 PR，minor+patch 合并），每周一 schedule。
2. `.github/workflows/ci.yml` — PR/push 触发，并行跑后端 `uv sync && uv run pytest` + 前端 `npm ci && npm run lint && npx vitest run`。这是"测试通过才合"的判定来源。
3. **仓库设置（手动，一次性）**：开启 "Allow auto-merge: squash"，把 CI 检查设为 `main` 的 required status check。

**数据流**：dependabot 按 schedule 开 PR → CI workflow 在 PR 上跑测试 → CI 通过 → dependabot 的 auto-merge 请求触发 squash 合并 → main 更新。CI 不通过则不合，人工介入。

## 组件细节

### (A) 立即修复 — `frontend/package.json`

- `vitest`: `^2.1.8` → `^4.1.10`（SemVer major）。拉 `vite` 6/7、`@vitest/mocker`、`vite-node` 新版，修掉 critical `vitest` + high `vite` + moderate `@vitest/mocker`/`vite-node`/`esbuild`。
- `npm install` 重建 `package-lock.json`。
- 验证：`npx vitest run --pool=forks --poolOptions.forks.singleFork=true`（沿用既有 pool 配置）+ `npx tsc --noEmit` + `npm run lint`。
- vitest 4.x API 变动（`expect`/`vi` 接口）需留意，若测试挂了按迁移指南调整。
- **不动运行时 moderate 漏洞**（`prismjs`/`next`/`nuqs` 等）——留给自动 workflow。

### (B1) `.github/dependabot.yml`

```yaml
version: 2
auto-merge: true
updates:
  - package-ecosystem: npm
    directory: /frontend
    schedule: { interval: weekly, day: monday }
    open-pull-requests-limit: 5
    auto-merge: true
    groups:
      minor-patch:
        update-types: [minor, patch]
  - package-ecosystem: uv
    directory: /
    schedule: { interval: weekly, day: monday }
    open-pull-requests-limit: 5
    auto-merge: true
    groups:
      minor-patch:
        update-types: [minor, patch]
```

- major 更新单独成 PR（不合组），需人工确认 breaking；minor/patch 合并减少噪音。
- `auto-merge: true` 让 dependabot 创建 PR 时即请求 auto-merge。

### (B2) `.github/workflows/ci.yml`

- 触发：`pull_request`（含 dependabot）+ `push` 到 `main`。
- 两个 job 并行：
  - **backend**：`actions/setup-python@v5` + `uv sync` + `uv run pytest tests/`（设 `WORKSPACE_PATH` 临时目录避免污染）。
  - **frontend**：`actions/setup-node@v4` + `npm ci` + `npm run lint` + `npx vitest run --pool=forks --poolOptions.forks.singleFork=true` + `npx tsc --noEmit`。
- 失败则 PR 红，auto-merge 不触发。

### (B3) 仓库设置（手动，文档化）

在 README 加一节"首次启用自动合并"步骤：
1. Settings → General → Pull Requests → 勾 "Allow auto-merge" + 默认 squash。
2. Settings → Branches → `main` protection → required status checks 选 CI job。
3. Settings → Code security → 确认 dependabot security updates 开启。

## 错误处理与边界

- **CI 在 dependabot PR 上失败**：PR 红，auto-merge 不触发。dependabot 不无限重试——人工看日志修（通常 breaking API 变动），或 `/dependabot reopen` 重跑。预期行为，不需额外代码。
- **major 更新**：不合组、单独 PR。`auto-merge: true` 仍请求合并，若 CI 因 breaking 失败则停住；若 CI 恰好过（非破坏性 major）也会自动合。**决策**：保持 auto-merge 对 major 生效（YAGNI，CI 是唯一门槛，与确认策略一致）。日后想拦 major 再加 workflow 过滤。
- **后端 `uv` ecosystem**：dependabot 更新 `pyproject.toml` + `uv.lock`。锁文件冲突或 `uv sync` 失败 → CI 红即拦。
- **仓库未开 auto-merge 设置**：`auto-merge: true` 静默无效，PR 停住等手动合——文档(B3)覆盖，部署后确认设置已开。
- **vitest 4.x 迁移破坏**：若测试挂到无法快速修，回退 `vitest` 到 `^2.1.9` 并改用 `npm audit fix` 非 major 路径（若存在），或单独提 issue。不硬塞坏掉的升级。

## 测试与验证

### (A) 立即修复验证（本地，新鲜证据）
- `npm audit --json` vuln 数从 13 降到 ≤7（清掉 critical+high+4 个 dev moderate）。
- `npx vitest run`（带 pool 配置）全绿。
- `npx tsc --noEmit` exit 0。
- `npm run lint` 无新增错误。

### (B2) CI workflow 验证
- 本地 `act` 跑不了（Windows + 依赖），改为推送后看 GitHub Actions 在 PR 上实际运行。
- workflow 语法用 `actionlint` 校验（若可用）或人工核对 schema。

### 部署后人工确认项（无法自动验证）
- 仓库设置 auto-merge 已开启、required status check 已设。
- dependabot 首次按 schedule 开 PR 后，CI 跑通 + auto-merge 实际触发。

## 备选方案（已否决）

- **方案 B（自写 `gh pr merge --auto` workflow）**：不依赖 dependabot 原生 auto-merge，但需自写合并脚本、token 权限、`pull_request_target` 安全考量，复杂度高且功能等价于 A。
- **方案 C（定时扫描合并 workflow）**：cron 主动扫 dependabot PR 合并。实时性差、重复 CI 成本、逻辑最复杂，仅 A/B 不可用时考虑。

## 不在本次范围

- 运行时 moderate 漏洞（`prismjs`/`next`/`nuqs`/`js-yaml`）的立即修复——交由自动 workflow 按周期处理。
- 后端 Python 漏洞扫描（`pip-audit`）——本次靠 dependabot `uv` ecosystem 发现，不额外引入扫描工具。
- 完整移除 Coze 平台耦合（`load_env.py` 的 `coze_workload_identity`）——独立工作。
