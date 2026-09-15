# 架构：上游项目与本地编排

> 本文档展开 README 中的上游溯源、版本锁定与本地补丁说明。阅读路径从 [README_CN.md](../README_CN.md) 开始。

## 上游项目与本地编排

| 组件 | 上游来源 | 当前锁定版本 | 在本项目中的用途 |
| --- | --- | --- | --- |
| `write-literature-review` | [Zsun79/LitReviewSkill](https://github.com/Zsun79/LitReviewSkill) | commit [`a53cd419352e4dd05958f67340fde3642d84abc3`](https://github.com/Zsun79/LitReviewSkill/tree/a53cd419352e4dd05958f67340fde3642d84abc3) | 复用步骤 0–7：范围定义、关键词、种子集、引文扩展、筛选、排序和受限全文阅读；不执行其知识图谱与综述成文阶段。 |
| `paper-search-cli` | [dr-dumpling/paper-search-cli](https://github.com/dr-dumpling/paper-search-cli) | npm `0.3.4`，MIT | 多来源元数据检索、DOI/标识核验、参考文献与施引文献扩展、合法 PDF 发现及期刊指标查询。 |
| `daily-literature-recommendations` | 本项目本地 Skill | `1.0.0` | 将上述两个上游能力编排为定期推荐流程，并增加 Gmail 投递、标签验证、任务本地历史和运行产物管理。 |

来源和版本记录在 `skills-lock.json`、`package.json` 与 `package-lock.json` 中。调度器（触发平台自带的定时功能）和 Gmail 账号属于运行时依赖，不是复制到本仓库的上游代码依赖。

项目不 fork 上游 Skill。`scripts/patch-paper-search.mjs` 会在 `npm install` 后对锁定的 `paper-search-cli 0.3.4` 应用少量项目兼容补丁：

- 为 arXiv 使用足够的来源级超时，并在冷却等待期间释放全局锁；
- 在配置 SerpApi 时使用托管的 Google Scholar 后端；
- 允许把已经核验的 `pdfUrl` 作为合法下载回退的第一候选。

升级 `paper-search-cli` 时必须同步检查补丁、刷新 `.agents/skills/paper-search`，然后重新运行完整测试。

## 运行时环境（背景）

- Node.js 18+ 与 [uv](https://docs.astral.sh/uv/)（Python 3.10+ 由 `uv sync` 自动装好）；
- 可触发本项目的 agent：Hermes、Codex 或 Claude Code（Claude Code 需 `npm run sync:skills` 桥接，`npm install` 会自动执行）；
- 已授权的 Gmail 账号：先通过 Hermes 的 `google-workspace` skill 完成一次性 OAuth，使 token 落到 `$HERMES_HOME/google_token.json`，再用 `uv run python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live` 验证；
- 按需配置检索源所需的 API key 或机构访问权限。

`uv sync` 依据 `pyproject.toml` 与 `uv.lock` 创建锁定的项目虚拟环境（`.venv/`，Python 3.10+）——当前钉住 `pypdf`，用于 PDF 文本提取；所有 Python 步骤请通过 `uv run python ...` 执行，确保始终命中锁定环境。`.env.example` 当前包含 SerpApi 后端和 arXiv 来源超时的示例设置，其他来源可通过 `paper-search` 配置或环境变量启用。

健康检查也可以直接使用固定的项目本地 CLI：

```bash
npx --no-install paper-search doctor --pretty
npx --no-install paper-search smoke --mock --pretty
```

元数据检索可用时即可继续运行。缺少增强检索源、出版商密钥或机构权限应记录为能力限制，不应让所有独立来源一起失败。

## 核心边界

- 所有命令使用项目锁定的本地运行时，不使用用户全局安装的 `paper-search`。
- 每次运行的项目命令和文件操作都在本机执行，不使用云端 shell。
- Gmail 只负责读取已授权账号信息、发送邮件、应用 YAML 中配置的精确标签，以及回读验证标签。这四项都通过 `scripts/gmail_delivery.py` 完成，不涉及 Gmail MCP 服务或连接器。
- 无法获得全文时必须标记为 `abstract_only` 或 `substantial_excerpt`，不得假装完成全文阅读。
- API key、cookie、账号信息和其他秘密只保存在本地 `.env`、`paper-search` 配置或环境变量中，不得写入任务 YAML、Skill、运行日志或 Git 历史。
- 下载来源合规策略（包括是否允许 Sci-Hub）由使用者按任务在任务 YAML 或触发提示词中定义；项目本身不做约束。
