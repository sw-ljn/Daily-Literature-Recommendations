# 目录结构与任务配置

> 本文档展开 README 中的完整目录树、任务 YAML 全部字段与默认值。阅读路径从 [README_CN.md](../README_CN.md) 开始。

## 目录结构

```text
daily-literature-recommendations/
├─ .agents/skills/
│  ├─ daily-literature-recommendations/  # 本项目编排 Skill
│  │  ├─ scripts/gmail_delivery.py       # 原生 Gmail 投递：发送、加标签、回读验证
│  │  ├─ scripts/history.py              # 推荐历史的读写
│  │  ├─ scripts/normalize_papers.py     # 规范化论文记录读写
│  │  └─ references/                     # 邮件模板、契约、投递 CLI、配置 schema
│  ├─ paper-search/                      # CLI 路由 Skill（paper-search-cli 捆绑）
│  └─ write-literature-review/           # 锁定的 LitReviewSkill
├─ .claude/skills/                       # 指向 .agents/skills 的生成 junction（Git 忽略；npm run sync:skills 重建）
├─ tasks/
│  ├─ _template.yaml                                  # 完整生产任务模板
│  ├─ smoke-mattergen.yaml                            # MatterGen 端到端样例任务
│  └─ structure-action-property-applications.yaml     # 生产示例任务
├─ data/                                 # 运行时数据；Git 忽略
│  └─ <task_id>/
│     ├─ runs/<timestamp>/               # 每次运行的检索、筛选、阅读和 run.json
│     ├─ downloads/<timestamp>/          # 合法获取并核验身份的论文文件
│     ├─ state/recommendations.jsonl     # 该任务已投递论文历史
│     └─ tmp/                            # 该任务临时文件
├─ scripts/
│  ├─ patch-paper-search.mjs             # paper-search-cli 本地兼容补丁
│  ├─ sync-claude-skills.mjs             # 将 .agents/skills 镜像为 .claude/skills 供 Claude Code 使用
│  ├─ cleanup-task-data.py               # 按 task_id 清理统一数据目录
│  ├─ migrate-task-data.py               # 旧分散布局的一次性迁移器
│  ├─ write-preflight-failure.py         # 将投递凭据预检失败写入规范运行目录
│  └─ task_data_layout.py                # 数据路径与安全校验公共实现
├─ tests/                                # 补丁、桥接、历史、投递、迁移和清理测试
├─ docs/                                 # 本文档集
├─ .env.example                          # 无密钥的环境变量模板
├─ package.json                          # 本地命令和固定 npm 依赖
├─ pyproject.toml / uv.lock              # 锁定 Python 环境（pypdf）
├─ skills-lock.json                      # 上游 Skill 来源与固定提交
├─ README.md / README_CN.md              # 英文 / 简体中文入口文档
└─ IDEA.md                               # 私人笔记（Git 忽略）
```

`task_id` 对应的四个数据子目录结构固定且相互隔离。任务 YAML 不允许覆盖运行数据路径。

## 定义任务 YAML

复制模板创建新任务：

```bash
cp tasks/_template.yaml tasks/solid-electrolyte.yaml
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

完整注释版请直接使用 `tasks/_template.yaml`。调度频率和执行时间不写在 YAML 中，由调度器（`hermes cron` 任务、Codex Automations 或 Windows 任务计划程序）单独控制。下载来源合规策略（包括是否允许 Sci-Hub）同样由使用者在任务 YAML 或触发提示词中定义。
