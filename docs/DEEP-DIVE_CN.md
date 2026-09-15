# 项目深入说明：架构、目录、执行流程与数据

[English](DEEP-DIVE.md) | **简体中文**

> 本文档把项目的深入说明合并为一篇。快速上手阅读路径从 [README_CN.md](../README_CN.md) 开始。

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

无法获得全文不是"不相关"的证据。单个来源、下载或候选失败时记录失败并继续其他独立候选。

Skill 负责完整编排，因此不存在一个等价的 `npm run recommend` 命令。底层检索 CLI、Python 状态脚本和文件读写只是编排过程中的项目本地步骤。

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

### 按 `task_id` 清理数据

清理器只处理一个精确目录 `data/<task_id>`，默认 dry-run，不扫描其他任务：

```bash
taskId="smoke1-mattergen"

# 预览文件数、目录数和字节数，不修改数据
npm run cleanup:task -- --task-id $taskId

# 暂停对应计划任务后实际删除 data/<task_id>
npm run cleanup:task -- --task-id $taskId --apply
```

默认保留 `tasks/*.yaml`，因此下一次计划触发会从空历史重新创建数据并可能重新推荐既有论文。永久退役任务时，应先停用计划任务，再显式删除任务配置：

```bash
npm run cleanup:task -- --task-id $taskId --remove-task-config --apply
```

添加 `--json` 可输出机器可读报告。脚本拒绝路径分隔符、`..`、项目根目录和其他不安全目标；`task-a` 不会匹配 `task-a-longer`。

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
