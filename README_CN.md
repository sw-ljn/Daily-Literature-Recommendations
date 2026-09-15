# 每日文献推荐系统

[English](README.md) | **简体中文**

面向自动化计划任务的有界文献推荐项目：由计划任务触发，按任务 YAML 定义研究范围，完成文献检索、引文扩展、相关性筛选、证据阅读、评分排序、Gmail 投递、精确标签归档和推荐历史排重。调度由触发平台自带的定时功能负责，投递为原生实现：任何兼容 Agent Skills 的 agent（Hermes、Codex、Claude Code）都可以用各自的调度器触发同一条工作流（见[多平台调度](#多平台调度)）；`scripts/gmail_delivery.py` 直连 Gmail REST API —— 任何平台都不依赖 MCP 服务。

本项目生成的是周期性推荐，不是系统综述或穷尽性检索。每次计划任务触发都是一次独立运行：即使没有新论文，也会发送一封状态邮件；论文内容按 DOI、arXiv ID 或规范化题名去重，但不会按日期或邮件主题跳过一次合法触发。

## 核心边界

- 所有命令使用项目锁定的本地运行时，不使用用户全局安装的 `paper-search`。
- 每次运行的项目命令和文件操作都在本机执行，不使用云端 shell。
- Gmail 只负责读取已授权账号信息、发送邮件、应用 YAML 中配置的精确标签，以及回读验证标签。这四项都通过 `scripts/gmail_delivery.py` 完成，不涉及 Gmail MCP 服务或连接器。
- 不得使用 Sci-Hub；调用下载回退工具时必须显式设置 `useSciHub=false`。
- 无法获得全文时必须标记为 `abstract_only` 或 `substantial_excerpt`，不得假装完成全文阅读。
- API key、cookie、账号信息和其他秘密只能保存在本地 `.env`、`paper-search` 配置或环境变量中，不得写入任务 YAML、Skill、运行日志或 Git 历史。

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

## 环境要求与初始化

- Windows PowerShell；
- Node.js 18 或更高版本；
- [uv](https://docs.astral.sh/uv/)（Python 3.10+ 由 `uv sync` 自动装好）；
- 可触发本项目目录、兼容 Agent Skills 的 agent：Hermes、Codex 或 Claude Code（Claude Code 还需 `npm run sync:skills` 桥接，`npm install` 会自动执行）；
- 已授权的 Gmail 账号：先通过 Hermes 的 `google-workspace` skill 完成一次性 OAuth，使 token 落到 `$HERMES_HOME/google_token.json`，再用 `python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live` 验证；
- 按需配置检索源所需的 API key 或机构访问权限。

首次初始化：

```powershell
Set-Location E:\project-claude\daily-literature-recommendations
Copy-Item .env.example .env
uv sync
npm install
npm run doctor
npm test
```

`uv sync` 依据 `pyproject.toml` 与 `uv.lock` 创建锁定的项目虚拟环境（`.venv/`，Python 3.10+）——当前钉住 `pypdf`，用于工作流第 5 步的 PDF 文本提取；所有 Python 步骤请通过 `uv run python ...` 执行，确保始终命中锁定环境。`npm install` 会安装锁定依赖并自动应用本地补丁。请只在 `.env` 中填写真实密钥；`.env` 已被 Git 忽略。`.env.example` 当前包含 SerpApi 后端和 arXiv 来源超时的示例设置，其他来源可通过 `paper-search` 配置或环境变量启用。

健康检查也可以直接使用固定的项目本地 CLI：

```powershell
npx --no-install paper-search doctor --pretty
npx --no-install paper-search smoke --mock --pretty
```

元数据检索可用时即可继续运行。缺少增强检索源、出版商密钥或机构权限应记录为能力限制，不应让所有独立来源一起失败。

## 目录结构

```text
daily-literature-recommendations/
├─ .agents/skills/
│  ├─ daily-literature-recommendations/  # 本项目编排 Skill
│  │  ├─ scripts/gmail_delivery.py       # 原生 Gmail 投递：发送、加标签、回读验证
│  │  ├─ scripts/history.py              # 推荐历史的读写
│  │  └─ references/                     # 邮件模板、契约、投递 CLI、配置 schema
│  ├─ paper-search/                      # CLI 路由 Skill
│  └─ write-literature-review/           # 锁定的 LitReviewSkill
├─ .claude/skills/                       # 指向 .agents/skills 的生成 junction（Git 忽略；npm run sync:skills 重建）
├─ tasks/
│  ├─ _template.yaml                     # 完整生产任务模板
│  └─ smoke-mattergen.yaml               # MatterGen 端到端样例任务
├─ data/                                 # 运行时数据；Git 忽略
│  └─ <task_id>/
│     ├─ runs/<timestamp>/               # 每次运行的检索、筛选、阅读和 run.json
│     ├─ downloads/<timestamp>/          # 合法获取并核验身份的论文文件
│     ├─ state/recommendations.jsonl      # 该任务已投递论文历史
│     └─ tmp/                            # 该任务临时文件
├─ scripts/
│  ├─ patch-paper-search.mjs             # paper-search-cli 本地兼容补丁
│  ├─ sync-claude-skills.mjs             # 将 .agents/skills 镜像为 .claude/skills 供 Claude Code 使用
│  ├─ cleanup-task-data.py               # 按 task_id 清理统一数据目录
│  ├─ migrate-task-data.py               # 旧分散布局的一次性迁移器
│  ├─ write-preflight-failure.py         # 将投递凭据预检失败写入规范运行目录
│  └─ task_data_layout.py                # 数据路径与安全校验公共实现
├─ tests/                                # 补丁、历史、迁移和清理测试
├─ docs/task-data-cleanup.md             # 数据迁移与清理细节
├─ .env.example                          # 无密钥的环境变量模板
├─ package.json                          # 本地命令和固定 npm 依赖
└─ skills-lock.json                      # 上游 Skill 来源与固定提交
```

`task_id` 对应的四个数据子目录结构固定且相互隔离。任务 YAML 不允许覆盖运行数据路径。

## 定义任务 YAML

复制模板创建新任务：

```powershell
Copy-Item tasks\_template.yaml tasks\solid-electrolyte.yaml
```

YAML 文件名只用于人类管理，文件内部的 `task_id` 才是运行目录、历史文件和 `run_key` 的权威标识。例如当前 `tasks/smoke-mattergen.yaml` 的真实 `task_id` 是 `smoke1-mattergen`。

### 必填或生产运行必须明确的字段

| 字段 | 说明 |
| --- | --- |
| `task_id` | 稳定唯一标识。建议只使用小写字母、数字和连字符，启用后不要随意更名。 |
| `display_name` | 邮件主题和运行报告中的可读名称。 |
| `timezone` | IANA 时区，用于调用时间、`run_key` 和邮件主题时间。 |
| `scope.domain` | 研究领域，用于术语和默认来源选择。 |
| `scope.research_question` | 每次运行持续回答的明确研究问题。 |
| `scope.target_relationship` | 论文必须与研究问题建立的直接关系；关键词命中本身不等于相关。 |
| `search.keywords` | 初始英文检索短语列表，不能为空。 |

强烈建议同时写出 `scope.include` 和 `scope.exclude`，使每次筛选采用稳定、可审计的纳入排除标准。

### 可选字段与默认值

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| `search.sources` | `crossref, openalex, semantic, arxiv` | 本任务允许使用的来源；不要无条件启用所有数据库。 |
| `search.date_window_days` | `30` | 相对运行日期的检索时间窗。 |
| `search.max_queries` | `10` | 最多生成或执行的查询数。 |
| `search.search_limit` | `40` | 多查询合并后的候选预算。 |
| `search.citation_expansion.enabled` | `true` | 是否扩展参考文献和施引文献。 |
| `search.citation_expansion.rounds` | `1` | 最多扩展轮数。 |
| `search.citation_expansion.frontier_limit` | `5` | 每轮最多扩展的前沿论文数。 |
| `search.citation_expansion.references_per_seed` | `5` | 每篇种子最多获取的参考文献数。 |
| `search.citation_expansion.citations_per_seed` | `5` | 每篇种子最多获取的施引文献数。 |
| `screening.read_limit` | `15` | 最多实际阅读的候选数。 |
| `screening.recommend_limit` | `5` | 单次最多推荐数；不得用弱相关论文凑数。 |
| `screening.min_score` | `65` | 进入推荐的最低总分，范围 0–100。 |
| `screening.allowed_reading_depth` | 三种深度均允许 | `full_text`、`substantial_excerpt`、`abstract_only`。 |
| `screening.allow_preprints` | `true` | 是否允许预印本。 |
| `screening.allow_updates` | `false` | 是否允许有实质更新的已推荐论文再次进入推荐。 |
| `delivery.recipient` | `me` | Gmail 收件人。 |
| `delivery.sender_name` | `daily-lit` | 收件箱中显示的发件人名称，作为 `--from` 传给 CLI。 |
| `delivery.gmail_label` | `Literature recommendations` | 发送后必须创建/应用/回读验证的精确标签名。 |
| `delivery.subject_prefix` | `每日文献推荐` | 邮件主题前缀。 |
| `delivery.signature` | `daily-lit` | 邮件正文署名。 |
| `delivery.language` | `zh-CN` | 邮件正文语言。 |

最小示例：

```yaml
task_id: solid-electrolyte-generative-design
display_name: 固态电解质生成式设计
timezone: America/Los_Angeles

scope:
  domain: materials science
  research_question: 生成式模型如何用于固态电解质的结构或性能导向设计？
  target_relationship: 方法必须直接用于固态电解质，或具有可论证的无机晶体生成迁移关系
  include:
    - 生成或逆向设计无机晶体结构
    - 验证离子电导率、稳定性或可合成性
  exclude:
    - 仅讨论通用大语言模型
    - 与无机晶体或固态离子导体无关

search:
  keywords:
    - solid-state electrolyte generative model
    - lithium ion conductor inverse design

delivery:
  recipient: me
  gmail_label: Literature recommendations
```

完整注释版请直接使用 `tasks/_template.yaml`。调度频率和执行时间不写在 YAML 中，由调度器（`hermes cron` 任务、Codex Automations 或 Windows 任务计划程序）单独控制。

## 执行流程

一次正常调用依次完成：

1. 读取 YAML，建立唯一 `run_key=<task_id>:<YYYY-MM-DDTHH-mm-ss>` 和运行目录；
2. 检查项目本地 `paper-search` 能力，构造不超过预算的查询；
3. 多来源检索、规范化、按 DOI/arXiv ID/题名去重，并过滤本任务历史；
4. 按题名与摘要筛选，受限扩展参考文献和施引文献，再次筛选；
5. 按相关性、创新性、证据、来源可靠性和可读证据进行 100 分制排序；
6. 在 `read_limit` 内合法获取并核验论文身份，记录真实阅读深度；
7. 选择不超过 `recommend_limit` 的论文，生成 `selected.jsonl`；
8. 通过 `scripts/gmail_delivery.py` 发送一封状态邮件，应用 YAML 中的精确 `gmail_label` 并回读验证；
9. 仅在发送成功后更新任务本地推荐历史，最后完善 `run.json`。

无法获得全文不是“不相关”的证据。单个来源、下载或候选失败时记录失败并继续其他独立候选。

## 手动调用

在任一受支持 agent 的项目根目录会话（Hermes、Codex 或 Claude Code）中使用：

```text
使用项目的 $daily-literature-recommendations 执行 tasks/smoke-mattergen.yaml。严格遵守 YAML 的检索、阅读和推荐上限；不得使用 Sci-Hub；完成 Gmail 发送、精确标签应用、回读验证和历史更新。
```

Skill 负责完整编排，因此不存在一个等价的 `npm run recommend` 命令。底层检索 CLI、Python 状态脚本和文件读写只是编排过程中的项目本地步骤。

## 多平台调度

工作流本身与平台无关：技能位于 `.agents/skills/`（Agent Skills 跨工具标准目录），所有项目命令都是普通的 `npm`/`python` 调用，任务 YAML 不包含任何调度字段。各平台只有触发方式不同。Claude Code 只读取 `.claude/skills/`；`npm install` 和 `npm run sync:skills` 会把该目录重建为指向 `.agents/skills/` 的 junction，因此所有平台执行的是同一份技能文件。

|  | Hermes 定时任务 | Codex Automations | Windows 任务计划程序（Claude Code） |
| --- | --- | --- | --- |
| 技能发现 | 原生识别 `.agents/skills/`；新 clone 需执行一次 `hermes skills trust` | 原生扫描 `.agents/skills/`，含 `agents/openai.yaml` | `npm run sync:skills` 生成的 `.claude/skills/` junction |
| 定时能力 | 内置定时任务，cron 表达式 | 内置 Automations，自定义 cron（也可把 `codex exec` 交给任意外部调度器） | 任务计划程序触发器；agent 经 `claude -p` 运行 |
| 注册方式 | `hermes cron create`（见下节） | Codex 应用内创建独立自动化：自定义 cron + 同一段任务提示词；或调度 `codex exec --full-auto "<任务提示词>"` | `Register-ScheduledTask`（见下方示例） |
| 凭据要求 | 已登录 Hermes；Gmail OAuth token 磁盘共享 | ChatGPT 登录或 `CODEX_API_KEY`（`codex exec`）；Gmail OAuth token 磁盘共享 | 已登录 `claude` CLI；Gmail OAuth token 磁盘共享 |
| 运行产物 | 一封状态邮件；`--deliver local` 使结果不进聊天 | 一封状态邮件；自动化运行记录进入 Codex 收件箱 | 一封状态邮件；stdout 写入任务历史 |

说明：

- Gmail OAuth token 位于 Hermes 数据目录（本机为 `%LOCALAPPDATA%\hermes\google_token.json`）；`gmail_delivery.py` 会自动定位，无需为其他平台复制凭据。
- 每个任务只在一个调度器注册一条定时项；不要把同一任务同时注册到两个调度器——每次触发都是一次独立运行，会各自发送邮件。
- 调度频率属于调度器，绝不写入任务 YAML；切换平台只是重新注册触发器，不改动工作流本身。

Claude Code 注册示例（PowerShell，当前用户，无需管理员；需先完成一次交互式 `claude` 登录）：

```powershell
Register-ScheduledTask -TaskName "daily-literature-claude" `
  -Action (New-ScheduledTaskAction -Execute "cmd.exe" -Argument '/c cd /d E:\project-claude\daily-literature-recommendations && claude -p "使用项目的 daily-literature-recommendations 技能执行 tasks/smoke-mattergen.yaml。严格遵守全部 YAML 上限，完成 Gmail 发送、精确标签应用和历史更新。"') `
  -Trigger (New-ScheduledTaskTrigger -Daily -At 08:00)
```

下节 Hermes 部分展示的「先预检后运行」任务提示词在所有平台原样可用。

## 用 Hermes cron 定时运行

每个任务注册一个内置 cron 任务，并把工作目录固定到项目目录，确保每次运行都从正确的位置开始：

```bash
hermes cron create "0 8 * * *" \
  "运行本项目的文献推荐任务。" \
  --name daily-literature \
  --workdir E:/project-claude/daily-literature-recommendations \
  --deliver local
```

`--workdir` 会注入项目上下文文件，并把终端、文件与代码执行工具的工作目录设为该路径；`--deliver local` 表示运行结果不进入聊天。`0 8 * * *` 表示按宿主时区每天 08:00 执行。用 `hermes cron list` / `hermes cron delete` 查看或删除任务。

任务提示词保持简短：

```text
先在不发信的前提下验证 Gmail 凭据：在项目根目录执行 `python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live`。

如果项目目录不可用，立即停止，明确说明无法写入本地 run.json；不要使用云端 shell，也不要声称已经写入文件。

如果凭据检查失败但项目目录仍可写，只能在项目根目录执行：
python scripts/write-preflight-failure.py --task-file tasks/smoke-mattergen.yaml --stage gmail_auth --reason "Gmail credential preflight failed" --error-code "<实际错误码>" --runtime-status ok --gmail-status unavailable
确认脚本返回的 run_path 位于 data/smoke1-mattergen/runs/<timestamp>/run.json 后停止。不要手工创建 runs/smoke1-mattergen/... 或其他旧路径。

凭据检查通过后，用项目的 $daily-literature-recommendations 执行 tasks/smoke-mattergen.yaml。所有项目命令和文件操作都在本机完成；不要使用云端 shell。Gmail 仅用于发送、精确加标签及回读验证。不得使用 Sci-Hub。
```

凭据预检必须发生在检索和发送之前。失败文件必须由 `write-preflight-failure.py` 生成，不能由模型拼接路径。该脚本从 YAML 读取真实 `task_id` 与 `timezone`，原子写入规范目录，并拒绝覆盖已有运行。它只解决失败记录的路径一致性，不修复缺失、过期或被撤销的 Gmail 凭据。

不要在 Skill 内修改计划频率。每次计划触发都发送一封报告，包括零结果运行；不要通过搜索 Gmail 已发送主题来压制本次触发。

## 数据与 `run.json`

每次运行使用任务时区生成独立目录：

```text
data/<task_id>/runs/<YYYY-MM-DDTHH-mm-ss>/
data/<task_id>/downloads/<YYYY-MM-DDTHH-mm-ss>/
```

典型运行目录包含：

- 原始检索响应和来源错误；
- 规范化、合并和历史过滤后的候选 JSONL；
- 初筛、引文扩展和复筛决定；
- 阅读笔记、论文身份核验和真实阅读深度；
- 评分结果与 `selected.jsonl`；
- 汇总调用状态的 `run.json`。

`run.json` 至少应能审计 `task_id`、`run_key`、调用时间、任务时区、配置上限、启用来源、各阶段计数、能力限制/失败、邮件主题与收件人、`delivery_status`、`gmail_label_expected`、`gmail_label_applied` 和 `label_status`。不要记录 Gmail message ID、API key 或受版权保护的全文。

投递凭据预检失败时可采用如下最小状态：

```json
{
  "task_id": "smoke1-mattergen",
  "run_key": "smoke1-mattergen:2026-08-28T09-00-00",
  "status": "failed_preflight",
  "connection_check": {
    "local_runtime": "ok",
    "gmail_credential": "unavailable",
    "email_sent_during_check": false
  },
  "delivery_status": "not_sent",
  "label_status": "not_attempted",
  "failures": [
    {
      "stage": "gmail_auth",
      "reason": "Gmail credential preflight failed",
      "error_code": "FORBIDDEN"
    }
  ]
}
```

推荐历史位于 `data/<task_id>/state/recommendations.jsonl`。该文件只允许出现对应任务的行；混入其他 `task_id` 时历史脚本会报错，避免跨任务污染。

## 常用脚本

| 命令 | 用途 |
| --- | --- |
| `npm run doctor` | 检查本地检索能力和已配置来源。 |
| `npm run smoke:mock` | 执行不依赖实时网络的 CLI 冒烟测试。 |
| `npm run smoke:live` | 执行实时来源冒烟测试；会访问外部服务。 |
| `npm run patch:paper-search` | 重新应用项目本地兼容补丁。 |
| `npm run sync:skills` | 重建 Claude Code 使用的 `.claude/skills/` junction。 |
| `npm run failure:preflight -- ...` | 由 YAML 派生规范目录并记录投递凭据预检失败。 |
| `npm test` | 运行技能桥接、补丁、历史隔离、投递、清理和 mock smoke 测试。 |

预检失败记录示例：

```powershell
npm run failure:preflight -- `
  --task-file tasks/smoke-mattergen.yaml `
  --stage gmail_auth `
  --reason "Gmail credential preflight failed" `
  --error-code "FORBIDDEN" `
  --runtime-status ok `
  --gmail-status unavailable
```

输出中的 `run_path` 是唯一允许使用的失败记录路径。

### 按 `task_id` 清理数据

清理器只处理一个精确目录 `data/<task_id>`，默认 dry-run，不扫描其他任务：

```powershell
$taskId = "smoke1-mattergen"

# 预览文件数、目录数和字节数，不修改数据
npm run cleanup:task -- --task-id $taskId

# 暂停对应计划任务后实际删除 data/<task_id>
npm run cleanup:task -- --task-id $taskId --apply
```

默认保留 `tasks/*.yaml`，因此下一次计划触发会从空历史重新创建数据并可能重新推荐既有论文。永久退役任务时，应先停用计划任务，再显式删除任务配置：

```powershell
npm run cleanup:task -- --task-id $taskId --remove-task-config --apply
```

添加 `--json` 可输出机器可读报告。脚本拒绝路径分隔符、`..`、项目根目录和其他不安全目标；`task-a` 不会匹配 `task-a-longer`。

### 迁移旧版分散数据

旧版使用根目录下的 `runs/<task_id>`、`downloads/<task_id>`、共享 `state/recommendations.jsonl` 和任务前缀临时目录。仅旧安装需要执行一次：

```powershell
# 先预览
npm run migrate:task -- --task-id $taskId

# 暂停对应计划任务后应用
npm run migrate:task -- --task-id $taskId --apply
```

迁移器先复制到暂存目录并核对文件数和字节数，再提交 `data/<task_id>`、拆分共享历史并移除精确旧源。目标目录已存在时会拒绝合并。详细说明见 `docs/task-data-cleanup.md`。

## Gmail 投递语义

Gmail 的读取与写入全部由 `.agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py` 完成：它使用 Hermes `google-workspace` skill 一次性创建的 OAuth token 直接调用 Gmail REST API，不涉及任何 MCP 服务或连接器。

- `delivery.recipient` 默认为 `me`，CLI 会把 `me` 解析为已授权账号；真实发件地址始终是该账号。
- `delivery.sender_name` 是收件箱中显示的发件人名称；用 `--from "<sender_name>"` 传入，CLI 会把该名称与已授权地址配成 `"名称" <地址>`。
- 邮件主题格式为 `[<subject_prefix>] <display_name> | <YYYY-MM-DD HH:mm>`。
- `delivery.gmail_label` 是精确值。标签不存在时应创建，只应用这个标签，并在写入后回读目标邮件验证；不得复用名称相近的既有标签。
- Gmail 发送成功但标签失败时，保留 `delivery_status=delivered`，记录 `label_status=pending`，重试标签时不得重发邮件。
- 标签重试按运行记录中的精确主题定位那封已发邮件，不保存 message ID（运行产物禁止包含该 ID）。
- Gmail 发送失败时，不得把论文写入已投递历史。
- 零篇推荐仍需发送包含检索计数、范围、主要排除原因和来源限制的状态邮件。

退出码：`0` 成功；`2` 发送失败；`3` 标签失败（禁止重发，只重试标签）；`4` 凭据或权限问题；`5` 参数错误。完整命令面见 Skill 内的 `references/delivery-cli.md`。

## 安全与维护

- `data/`、`.env` 和 `node_modules/` 均为本地运行内容，不应提交到 Git。
- 下载仅使用出版商、arXiv、PMC/Europe PMC、CORE/OpenAIRE、Unpaywall 或其他合法开放/授权来源。
- PDF 下载成功后仍需从正文核验题名与论文身份；错误 PDF 必须丢弃。
- 不要把摘要评估描述为全文阅读，不要编造书目信息、结果或局限。
- 在清理、迁移或升级依赖前暂停对应计划任务；完成后运行 `npm test` 和 `npm run doctor`。
- 文档与实际 CLI 冲突时，以项目根目录执行的 `npx --no-install paper-search --help`、`tools --pretty` 和测试结果为准，并同步更新 Skill/README。
