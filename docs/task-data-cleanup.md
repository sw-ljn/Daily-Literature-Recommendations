# 任务数据统一布局、迁移与清理

## 固定布局

所有增长型运行数据统一放在一个任务专属目录中：

```text
data/
  <task_id>/
    runs/
      <timestamp>/
    downloads/
      <timestamp>/
    state/
      recommendations.jsonl
    tmp/
```

每个 `task_id` 的四个子目录结构相同、彼此平行隔离。任务 YAML 仍放在 `tasks/`，因为它是可复用配置而不是运行时积累数据。YAML 中的 `task_id` 是唯一依据，配置文件名可以不同。

运行路径不再允许由单个任务覆盖，避免任务数据重新分散到项目其他位置。外部 Gmail 邮件和 Codex 调度器执行状态不属于项目运行数据，也不会被迁移或清理。

## 一次性迁移旧布局

旧版本分别使用 `runs/<task_id>`、`downloads/<task_id>`、共享的 `state/recommendations.jsonl` 和带任务前缀的 `tmp/` 路径。先暂停对应定时任务并预览迁移：

```powershell
$taskId = "在这里填写任务 YAML 中的 task_id"
python scripts/migrate-task-data.py --task-id $taskId
```

迁移器会：

- 将旧运行目录复制到 `data/<task_id>/runs/`；
- 将旧下载目录复制到 `data/<task_id>/downloads/`；
- 从共享历史中精确抽取该 `task_id` 的行，写入任务本地历史；
- 将旧 `tmp/` 中名称精确等于 `<task_id>`，或符合 `<task_id>-<ISO时间戳>` 的路径放入任务本地 `tmp/`；这种收紧可避免把 `task-a-longer` 误归给 `task-a`；
- 先核对复制后的文件数和字节数，再提交新目录并删除对应旧源；
- 保留共享历史中其他任务的行。

确认 dry-run 后应用：

```powershell
python scripts/migrate-task-data.py --task-id $taskId --apply
```

非标准旧文件不会被猜测归属。确认后可显式迁入 `tmp/legacy/`：

```powershell
python scripts/migrate-task-data.py --task-id $taskId --extra-path 12 --apply
```

迁移目标已存在时工具会拒绝合并，防止覆盖新旧运行。如果迁移被意外中断并留下目标目录，应先核对目标与旧源，再人工处理或恢复，而不是强制合并。

## 日常清理

迁移完成后，清理脚本只计算并处理一个精确目录，不扫描 `runs/`、`downloads/`、`state/` 或 `tmp/`：

```powershell
python scripts/cleanup-task-data.py --task-id $taskId
```

确认报告后实际删除：

```powershell
python scripts/cleanup-task-data.py --task-id $taskId --apply
```

默认保留任务 YAML，方便任务从空历史重新运行。永久退役任务时才同时删除配置：

```powershell
python scripts/cleanup-task-data.py --task-id $taskId --remove-task-config --apply
```

两个工具都支持 `--json`。所有删除均要求 `--apply`；默认模式只读。`task_id` 必须是安全的单个路径段，最终目标必须严格等于项目内的 `data/<task_id>`，不会使用模糊匹配，因此 `task-a` 与 `task-a-longer` 相互隔离。
