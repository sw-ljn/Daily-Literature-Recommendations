# 每日文献推荐系统

**简体中文** | [English](README.md)

由 agent 定时任务驱动的文献推荐项目：任务 YAML 定义研究范围，agent 按 YAML 完成检索、筛选、阅读、评分，并把推荐邮件发到你的 Gmail。调度由触发平台的定时功能负责（Hermes / Codex / Claude Code 任一），Gmail 投递直连 REST API，不依赖 MCP。

- 每次触发都是一次独立运行，即使没有新论文也会发送一封状态邮件
- 论文按 DOI / arXiv ID / 规范化题名去重，已推荐过的不会重复出现

## 快速开始

```bash
git clone https://github.com/sw-ljn/Daily-Literature-Recommendations.git
cd Daily-Literature-Recommendations
cp .env.example .env          # 填入真实密钥；.env 已被 Git 忽略
uv sync                       # 创建锁定 Python 环境（需 uv；Python 3.10+ 自动装好）
npm install                   # 安装 npm 依赖并应用本地补丁
npm run doctor && npm test    # 健康检查
```

前置条件：

- Node.js 18+ 与 [uv](https://docs.astral.sh/uv/)；
- 一个可触发本项目的 agent：Hermes / Codex / Claude Code；
- 已授权的 Gmail 账号：通过 Hermes 的 `google-workspace` skill 完成一次性 OAuth（token 落到 `$HERMES_HOME/google_token.json`），再验证：

```bash
uv run python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live
```

缺少增强检索源、出版商密钥或机构权限属于能力限制，不应让所有独立来源一起失败。

## 运行第一次推荐

**手动触发**——在项目根目录的 agent 会话中：

```text
使用项目的 $daily-literature-recommendations 执行 tasks/smoke-mattergen.yaml。严格遵守 YAML 的检索、阅读和推荐上限；完成 Gmail 发送、精确标签应用、回读验证和历史更新。
```

**定时触发**：见[多平台调度](#多平台调度)——每个平台用自己的调度器注册，工作流本身不变。Skill 负责完整编排，因此没有等价的 `npm run recommend` 命令。

## 定义任务 YAML

```bash
cp tasks/_template.yaml tasks/solid-electrolyte.yaml
```

文件名只用于人类管理；文件内部的 `task_id` 才是运行目录、历史和 `run_key` 的权威标识。调度频率不写在 YAML 里，由调度器单独控制。

必填字段：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 稳定唯一标识（小写字母、数字、连字符；启用后不要更名） |
| `display_name` | 邮件主题和运行报告中的可读名称 |
| `timezone` | IANA 时区 |
| `scope.research_question` | 每次运行持续回答的研究问题 |
| `scope.target_relationship` | 论文必须满足的直接关系；关键词命中 ≠ 相关 |
| `search.keywords` | 初始英文检索短语，不能为空 |

完整字段与默认值见 `tasks/_template.yaml`（全注释模板）。最小示例：

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

## 执行流程

每次触发依次完成：读取 YAML 建立运行目录 → 多来源检索并去重 → 过滤本任务历史 → 题名/摘要筛选 → 引文扩展与复筛 → 100 分制评分排序 → 在 `read_limit` 内合法获取全文并核验身份 → 选出不超过 `recommend_limit` 篇 → 经 `gmail_delivery.py` 发送状态邮件并应用精确标签 → 发送成功后更新历史。

单个来源或候选失败只记录、不中断；无法获得全文不是"不相关"的证据。

## 多平台调度

工作流与平台无关：技能位于 `.agents/skills/`（Agent Skills 跨工具标准目录），任务 YAML 不含调度字段，切换平台只需重新注册触发器。Claude Code 只读 `.claude/skills/`；`npm install` 会自动把它建为指向 `.agents/skills/` 的 junction，所有平台执行同一份技能文件。

|  | Hermes | Codex | Claude Code |
| --- | --- | --- | --- |
| 技能发现 | 原生识别 `.agents/skills/`（新 clone 需 `hermes skills trust` 一次） | 原生扫描 `.agents/skills/` | junction 生成 `.claude/skills/` |
| 注册方式 | `hermes cron create "0 8 * * *" "<任务提示词>" --workdir <项目路径> --deliver local` | Codex 应用内 Automations，或外部调度器跑 `codex exec --full-auto "<任务提示词>"` | Windows 任务计划程序 + `claude -p "<任务提示词>"` |
| 凭据 | 已登录 Hermes；Gmail token 磁盘共享 | ChatGPT 登录或 `CODEX_API_KEY`；token 磁盘共享 | 已登录 `claude` CLI；token 磁盘共享 |

任务提示词模板（自包含，所有平台通用）：

```text
在项目目录 <项目路径> 执行文献推荐任务。先只做 Gmail 凭据预检（不发邮件）：
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live
项目目录不可用则立即停止并如实说明。预检失败时，在项目根目录执行
python scripts/write-preflight-failure.py --task-file tasks/<任务>.yaml --stage gmail_auth --reason "Gmail credential preflight failed" --error-code "<实际错误码>" --runtime-status ok --gmail-status unavailable
确认返回的 run_path 位于 data/<task_id>/runs/<时间戳>/run.json 后停止。
预检通过后，用项目的 daily-literature-recommendations 技能执行 tasks/<任务>.yaml，严格遵守全部上限，完成 Gmail 发送、精确标签应用、回读验证和历史更新。全文获取来源约束（如是否允许 Sci-Hub）由使用者在提示词或任务 YAML 中自行声明。
```

注意：每个任务只在一个调度器注册一条定时项（重复注册会重复发邮件）；Gmail OAuth token 位于 Hermes 数据目录（本机 `%LOCALAPPDATA%\hermes\google_token.json`），`gmail_delivery.py` 自动定位，其他平台无需复制凭据。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `npm run doctor` | 检查检索能力和已配置来源 |
| `npm test` | 全量测试（技能桥接、补丁、历史、投递、mock smoke） |
| `npm run smoke:live` | 实时来源冒烟测试（访问外部服务） |
| `npm run cleanup:task -- --task-id <id> [--apply]` | 预览/删除一个任务的 `data/<task_id>`（默认 dry-run；先暂停对应调度） |
| `npm run migrate:task -- --task-id <id> [--apply]` | 旧版分散数据布局的一次性迁移（见 `docs/task-data-cleanup.md`） |
| `npm run failure:preflight -- ...` | 记录投递凭据预检失败到规范运行目录 |
| `npm run sync:skills` | 重建 Claude Code 的 `.claude/skills/` junction |

## 数据与投递语义

- 运行产物：`data/<task_id>/runs/<时间戳>/`（检索、筛选、阅读、评分、`run.json`）与 `downloads/<时间戳>/`；历史在 `data/<task_id>/state/recommendations.jsonl`，只允许本任务的行。
- `run.json` 需可审计 `delivery_status`、`gmail_label_expected`、`gmail_label_applied`、`label_status` 等投递事实；不记录 Gmail message ID 或密钥。
- 邮件主题：`[<subject_prefix>] <display_name> | <YYYY-MM-DD HH:mm>`；`delivery.gmail_label` 是精确值，不存在则创建，只应用这一个标签并回读验证。
- 发送成功但标签失败：保留 `delivered` + `label_status=pending`，重试标签、不重发；标签重试按精确主题定位邮件。
- 发送失败不写已投递历史；零篇推荐也发一封含计数与排除原因的状态邮件。
- `gmail_delivery.py` 退出码：`0` 成功；`2` 发送失败；`3` 标签失败（只重试标签）；`4` 凭据问题；`5` 参数错误。详见 Skill 内 `references/delivery-cli.md`。

## 深入了解

项目文档（每篇均有英文与简体中文版）：

- [项目深入说明](docs/DEEP-DIVE_CN.md)——上游来源与版本锁定、本地补丁层、完整目录树、九步执行流程、数据 / run.json 语义、数据清理与 Gmail 投递细节（[English](docs/DEEP-DIVE.md)）

Skill 内部参考：

- `tasks/_template.yaml` —— 任务配置全字段说明
- `.agents/skills/daily-literature-recommendations/` —— 编排工作流全文（SKILL.md 与 references/）
- `docs/task-data-cleanup.md` —— 数据清理与迁移细节
- `scripts/patch-paper-search.mjs` —— 对锁定 `paper-search-cli 0.3.4` 的本地补丁（arXiv 超时、托管 Scholar 后端、pdfUrl 优先下载）；升级依赖时需同步检查

## 安全与维护

- 秘密只存于本地 `.env` / 环境变量 / `paper-search` 配置；`data/`、`node_modules/`、私有任务 YAML 均被 Git 忽略。
- 下载来源合规策略由使用者定义（写入提示词或任务 YAML）；无论来源如何，PDF 下载后都需核验题名与身份，无法获得全文时如实标记 `abstract_only`。
- 清理、迁移或升级依赖前先暂停对应调度任务，完成后跑 `npm test` 与 `npm run doctor`。
- 文档与实际 CLI 冲突时，以 `npx --no-install paper-search --help` 和测试结果为准。
