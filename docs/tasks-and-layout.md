# Repository layout and task configuration

> This document expands on the README: the full directory tree, all task YAML fields with defaults, and the per-task data directories. For the reading path, start at [README.md](README.md).

## Repository layout

```text
daily-literature-recommendations/
├─ .agents/skills/
│  ├─ daily-literature-recommendations/  # Project orchestration skill
│  │  ├─ scripts/gmail_delivery.py       # Native Gmail REST delivery: send, label, verify
│  │  ├─ scripts/history.py              # Recommendation-history reader/writer
│  │  ├─ scripts/normalize_papers.py     # Normalized paper-record helpers
│  │  └─ references/                     # Email template, contracts, delivery CLI, config schema
│  ├─ paper-search/                      # CLI routing skill (bundled from paper-search-cli)
│  └─ write-literature-review/           # Pinned LitReviewSkill
├─ .claude/skills/                       # Generated junctions into .agents/skills (Git-ignored; rebuilt by npm run sync:skills)
├─ tasks/
│  ├─ _template.yaml                                  # Fully documented production template
│  ├─ smoke-mattergen.yaml                            # MatterGen end-to-end smoke task
│  └─ structure-action-property-applications.yaml     # Production example task
├─ data/                                 # Runtime data; ignored by Git
│  └─ <task_id>/
│     ├─ runs/<timestamp>/               # Search, screening, reading, and run.json
│     ├─ downloads/<timestamp>/          # Lawfully acquired, identity-checked papers
│     ├─ state/recommendations.jsonl     # Delivered-paper history for this task
│     └─ tmp/                            # Task-local temporary files
├─ scripts/
│  ├─ patch-paper-search.mjs             # Local paper-search compatibility patch
│  ├─ sync-claude-skills.mjs             # Mirror .agents/skills into .claude/skills for Claude Code
│  ├─ cleanup-task-data.py               # Delete one canonical task-data directory
│  ├─ migrate-task-data.py               # One-time legacy-layout migration
│  ├─ write-preflight-failure.py         # Canonical delivery-preflight failure writer
│  └─ task_data_layout.py                # Shared path and safety implementation
├─ tests/                                # Patch, sync, history, delivery, migration, and cleanup tests
├─ docs/                                 # This documentation set
├─ .env.example                          # Secret-free environment template
├─ package.json                          # Local commands and pinned npm dependency
├─ pyproject.toml / uv.lock              # Pinned Python environment (pypdf)
├─ skills-lock.json                      # Skill source and commit provenance
├─ README.md / README_CN.md              # Entry documentation (English / 简体中文)
└─ IDEA.md                               # Private notes (Git-ignored)
```

The four runtime subdirectories are fixed and isolated per `task_id`. Task YAML cannot override runtime paths.

## Define a task YAML

Copy the template to create a new task:

```bash
cp tasks/_template.yaml tasks/solid-electrolyte.yaml
```

The YAML filename is for human organization only. The `task_id` inside the file is authoritative for data directories, history, and the `run_key` namespace. For example, `tasks/smoke-mattergen.yaml` currently declares `task_id: smoke1-mattergen`.

### Required production fields

| Field | Meaning |
| --- | --- |
| `task_id` | Stable unique identifier. Lowercase letters, digits, and hyphens are recommended. Do not rename an active task casually. |
| `display_name` | Human-readable name used in email subjects and run reports. |
| `timezone` | IANA timezone used for invocation timestamps, `run_key`, and email subject time. |
| `scope.domain` | Research domain used to choose terminology and sensible source defaults. |
| `scope.research_question` | The explicit question every invocation continues to answer. |
| `scope.target_relationship` | The direct relationship a paper must have to the task. A keyword hit alone is not relevance. |
| `search.keywords` | Non-empty list of initial English search phrases. |

Defining `scope.include` and `scope.exclude` is strongly recommended so screening remains stable and auditable across runs.

### Optional fields and defaults

| Field | Default | Purpose |
| --- | --- | --- |
| `search.sources` | `crossref, openalex, semantic, arxiv` | Sources this task is allowed to query. Do not enable every provider indiscriminately. |
| `search.date_window_days` | `30` | Search window relative to the invocation date. |
| `search.max_queries` | `10` | Maximum generated or executed queries. |
| `search.search_limit` | `40` | Overall merged-candidate budget. |
| `search.citation_expansion.enabled` | `true` | Expand references and citing papers. |
| `search.citation_expansion.rounds` | `1` | Maximum expansion rounds. |
| `search.citation_expansion.frontier_limit` | `5` | Maximum frontier papers per round. |
| `search.citation_expansion.references_per_seed` | `5` | Maximum references per frontier paper. |
| `search.citation_expansion.citations_per_seed` | `5` | Maximum citing papers per frontier paper. |
| `screening.read_limit` | `15` | Maximum candidates actually read. |
| `screening.recommend_limit` | `5` | Maximum recommendations per email; never pad with weak papers. |
| `screening.min_score` | `65` | Minimum recommendation score, from 0 to 100. |
| `screening.allowed_reading_depth` | all three | `full_text`, `substantial_excerpt`, and `abstract_only`. |
| `screening.allow_preprints` | `true` | Allow relevant preprints. |
| `screening.allow_updates` | `false` | Allow a materially changed version of a delivered paper to be recommended again. |
| `delivery.recipient` | `me` | Gmail recipient. |
| `delivery.sender_name` | `daily-lit` | Display name shown in the recipient's inbox; passed to the CLI as `--from`. |
| `delivery.gmail_label` | `Literature recommendations` | Exact label that must be created/applied and verified after sending. |
| `delivery.subject_prefix` | `每日文献推荐` | Email subject prefix. |
| `delivery.signature` | `daily-lit` | Message signature. |
| `delivery.language` | `zh-CN` | Message language. |

Minimal example:

```yaml
task_id: solid-electrolyte-generative-design
display_name: Solid-electrolyte generative design
timezone: America/Los_Angeles

scope:
  domain: materials science
  research_question: How are generative models used for structure- or property-guided solid-electrolyte design?
  target_relationship: The method must directly target solid electrolytes or justify a transferable relationship to inorganic crystal generation.
  include:
    - Generative or inverse design of inorganic crystal structures
    - Validation of ionic conductivity, stability, or synthesizability
  exclude:
    - Generic large-language-model discussions
    - Work unrelated to inorganic crystals or solid ionic conductors

search:
  keywords:
    - solid-state electrolyte generative model
    - lithium ion conductor inverse design

delivery:
  recipient: me
  gmail_label: Literature recommendations
```

Use `tasks/_template.yaml` for the fully commented configuration. Cadence and execution time belong to the scheduler (a `hermes cron` job, a Codex automation, or Task Scheduler), not the YAML. Download-source policy (including whether Sci-Hub may be used) is likewise the user's decision, declared in the task YAML or the triggering prompt.
