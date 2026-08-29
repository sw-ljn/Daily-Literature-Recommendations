# Task configuration schema

Use one YAML file per recommendation task at `tasks/<task-id>.yaml`. The scheduler controls cadence; this file controls research and delivery behavior.

## Required fields

```yaml
task_id: solid-electrolyte-generative-design
display_name: 固态电解质的生成式材料设计
timezone: America/Los_Angeles

scope:
  domain: materials science
  research_question: 生成式模型如何用于固态电解质的结构或性能导向设计？
  target_relationship: 方法必须直接用于固态电解质，或具有可论证的无机晶体生成迁移关系
  include:
    - 生成或逆向设计无机晶体结构
    - 对离子电导率、稳定性或可合成性进行条件控制或验证
  exclude:
    - 仅讨论通用大语言模型
    - 与无机晶体结构或固态离子导体无关

search:
  keywords:
    - solid-state electrolyte generative model
    - lithium ion conductor inverse design
    - crystal diffusion ionic conductivity
```

Do not proceed when `task_id`, `display_name`, `scope.research_question`, `scope.target_relationship`, or `search.keywords` is absent or empty.

## Optional fields and defaults

```yaml
search:
  sources:
    - crossref
    - openalex
    - semantic
    - arxiv
  date_window_days: 30
  max_queries: 10
  search_limit: 40
  citation_expansion:
    enabled: true
    rounds: 1
    frontier_limit: 5
    references_per_seed: 5
    citations_per_seed: 5

screening:
  read_limit: 15
  recommend_limit: 5
  min_score: 65
  allowed_reading_depth:
    - full_text
    - substantial_excerpt
    - abstract_only
  allow_preprints: true
  allow_updates: false

delivery:
  recipient: me
  gmail_label: Literature recommendations
  subject_prefix: 每日文献推荐
  signature: Codex
  language: zh-CN

```

Defaults apply only to optional fields. Preserve user-specified sources, limits, dates, publication types, and relationship rules exactly.

Runtime paths are deliberately not configurable per task. Derive them from the required `task_id` using the fixed parallel layout:

```text
data/<task-id>/runs/
data/<task-id>/downloads/
data/<task-id>/state/recommendations.jsonl
data/<task-id>/tmp/
```

The YAML filename is not authoritative and may differ from `task_id`.

`delivery.gmail_label` is the exact post-send Gmail label name. The workflow must use that parsed value without substituting a similar existing label. Gmail should create the exact label when it is absent, apply it to the delivered message, and verify it before recording `label_status=applied`.

## Source routing defaults

- Materials science, physics, chemistry, AI: `crossref,openalex,semantic,arxiv`; add `core,openaire` for open-access discovery.
- Biomedical or clinical: `pubmed,pmc,europepmc,semantic,crossref`.
- Computer science: `arxiv,semantic,dblp,openreview,crossref`; add ACM/USENIX when useful.
- Cross-disciplinary: `crossref,openalex,semantic` plus the most relevant domain source.

Use entitled publisher/database sources only when the corresponding key or institutional entitlement is configured. Do not silently broaden to every source.

## Scheduled-task prompt

Keep the scheduled prompt small:

```text
Open the selected project through DevSpace and validate the Gmail profile without sending email. If Gmail validation fails while DevSpace remains writable, run `python scripts/write-preflight-failure.py --task-file tasks/<task-id>.yaml --stage gmail_profile --reason "Gmail connector preflight failed" --error-code "<error-code>" --devspace-status ok --gmail-status unavailable` from the project root, then stop. Use only the returned `data/<task-id>/runs/<timestamp>/run.json` path; never write a legacy `runs/<task-id>/...` path. If DevSpace is unavailable, stop without claiming a local file was written.
When both connections work, use $daily-literature-recommendations to run tasks/<task-id>.yaml from the selected project. Follow the configured limits, send the result by Gmail, file it under the configured label, and update recommendation history. Do not change the schedule from inside the skill.
Treat every scheduled trigger as a new invocation and send one report even when there are zero new recommendations. Do not suppress a run by searching prior Gmail subjects; cadence and duplicate triggers are controlled by the scheduled task.
```
