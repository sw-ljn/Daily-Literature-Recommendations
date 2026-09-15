# 执行流程、定时运行与数据 / run.json

> 本文档展开 README 中的分步执行流程、Hermes cron 定时详解与数据 / run.json 语义。阅读路径从 [README_CN.md](../README_CN.md) 开始。

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

## 用 Hermes cron 定时运行

每个任务注册一个内置 cron 任务，并把工作目录固定到项目目录，确保每次运行都从正确的位置开始：

```bash
hermes cron create "0 8 * * *" \
  "运行本项目的文献推荐任务。" \
  --name daily-literature \
  --workdir /path/to/Daily-Literature-Recommendations \
  --deliver local
```

`--workdir` 会注入项目上下文文件，并把终端、文件与代码执行工具的工作目录设为该路径；`--deliver local` 表示运行结果不进入聊天。`0 8 * * *` 表示按宿主时区每天 08:00 执行。用 `hermes cron list`、`hermes cron pause`、`hermes cron resume`、`hermes cron delete` 查看或管理任务。

任务提示词保持简短：

```text
先在不发信的前提下验证 Gmail 凭据：在项目根目录执行 `python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live`。

如果项目目录不可用，立即停止，明确说明无法写入本地 run.json；不要使用云端 shell，也不要声称已经写入文件。

如果凭据检查失败但项目目录仍可写，只能在项目根目录执行：
python scripts/write-preflight-failure.py --task-file tasks/<任务>.yaml --stage gmail_auth --reason "Gmail credential preflight failed" --error-code "<实际错误码>" --runtime-status ok --gmail-status unavailable
确认脚本返回的 run_path 位于 data/<task_id>/runs/<timestamp>/run.json 后停止。不要手工创建 runs/<task_id>/... 或其他旧路径。

凭据检查通过后，用项目的 $daily-literature-recommendations 执行 tasks/<任务>.yaml。所有项目命令和文件操作都在本机完成；不要使用云端 shell。Gmail 仅用于发送、精确加标签及回读验证。
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

## 投递凭据预检失败记录

`write-preflight-failure.py` 从任务 YAML 派生规范运行路径并在那里写入失败记录；返回的 `run_path` 是唯一允许使用的路径：

```bash
npm run failure:preflight -- \
  --task-file tasks/smoke-mattergen.yaml \
  --stage gmail_auth \
  --reason "Gmail credential preflight failed" \
  --error-code "FORBIDDEN" \
  --runtime-status ok \
  --gmail-status unavailable
```

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

### 迁移旧版分散数据

旧版使用根目录下的 `runs/<task_id>`、`downloads/<task_id>`、共享 `state/recommendations.jsonl` 和任务前缀临时目录。仅旧安装需要执行一次：

```bash
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
