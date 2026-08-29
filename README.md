# Daily Literature Recommendations

**English** | [简体中文](README_CN.md)

A bounded literature-recommendation project designed for Codex scheduled tasks. A task YAML defines the research scope; the workflow then performs paper discovery, citation expansion, relevance screening, evidence-aware reading, scoring and ranking, Gmail delivery, exact-label filing, and recommendation-history deduplication.

This project produces recurring recommendations, not a systematic review or an exhaustive search. Every scheduled trigger is an independent invocation and sends one status email, even when no new paper qualifies. Paper content is deduplicated by DOI, arXiv ID, or normalized title; a valid trigger is never suppressed by date or email subject.

## Core boundaries

- All commands use the project-pinned local runtime. Do not fall back to a user-global `paper-search` executable.
- During a scheduled run, DevSpace performs project commands and file operations on the local machine. Do not use a cloud shell.
- Gmail is used only to read the authenticated profile, send the report, apply the exact YAML-configured label, and read the message back to verify that label.
- Never use Sci-Hub. Every `download_with_fallback` call must explicitly set `useSciHub=false`.
- If full text cannot be lawfully accessed, use `abstract_only` or `substantial_excerpt`; never claim that an abstract-only assessment is a full-text reading.
- API keys, cookies, account information, and other secrets belong only in the local `.env`, `paper-search` configuration, or environment variables. Never put them in task YAML, skills, run artifacts, or Git history.

## Upstream projects and local orchestration

| Component | Upstream | Pinned version | Role in this project |
| --- | --- | --- | --- |
| `write-literature-review` | [Zsun79/LitReviewSkill](https://github.com/Zsun79/LitReviewSkill) | commit [`a53cd419352e4dd05958f67340fde3642d84abc3`](https://github.com/Zsun79/LitReviewSkill/tree/a53cd419352e4dd05958f67340fde3642d84abc3) | Reuses stages 0–7: scope, queries, seed discovery, citation expansion, screening, ranking, and bounded full-text inspection. Its knowledge-graph and review-writing stages are intentionally omitted. |
| `paper-search-cli` | [dr-dumpling/paper-search-cli](https://github.com/dr-dumpling/paper-search-cli) | npm `0.3.4`, MIT | Multi-source metadata search, identifier verification, backward/forward citation expansion, lawful PDF discovery, and journal metrics. |
| `daily-literature-recommendations` | Project-local skill | `1.0.0` | Orchestrates the upstream workflows and adds Gmail delivery, label verification, task-local history, and run-artifact management. |

Source provenance and versions are recorded in `skills-lock.json`, `package.json`, and `package-lock.json`. DevSpace and Gmail are Codex runtime connectors; they are not vendored upstream repositories.

The project does not fork the upstream skills. After `npm install`, `scripts/patch-paper-search.mjs` applies a small compatibility layer to the pinned `paper-search-cli 0.3.4` runtime:

- a sufficient source-specific timeout for arXiv, without holding the global lock during cooldown waits;
- the managed SerpApi backend when Google Scholar is configured;
- a verified caller-provided `pdfUrl` as the first lawful download candidate.

When upgrading `paper-search-cli`, review the patch, refresh `.agents/skills/paper-search`, and rerun the full test suite.

## Requirements and setup

- Windows PowerShell;
- Node.js 18 or later;
- Python 3.10 or later;
- a working DevSpace connection to this project directory;
- an authorized Gmail connection that can run `get profile`, send, apply labels, and read messages back;
- any API keys or institutional access required by the selected literature sources.

Initial setup:

```powershell
Set-Location E:\projects-codex\daily-literature-recommendations
Copy-Item .env.example .env
npm install
npm run doctor
npm test
```

`npm install` installs pinned dependencies and reapplies the project-local patch. Put real keys only in `.env`; it is ignored by Git. `.env.example` currently documents the managed SerpApi backend and the arXiv source timeout. Other providers can be enabled through `paper-search` configuration or environment variables.

You can also run the pinned health checks directly:

```powershell
npx --no-install paper-search doctor --pretty
npx --no-install paper-search smoke --mock --pretty
```

Proceed when metadata search is available. Missing enhanced providers, publisher keys, or institutional entitlements are capability limits, not reasons to fail all independent sources.

## Repository layout

```text
daily-literature-recommendations/
├─ .agents/skills/
│  ├─ daily-literature-recommendations/  # Project orchestration skill
│  ├─ paper-search/                      # CLI routing skill
│  └─ write-literature-review/           # Pinned LitReviewSkill
├─ tasks/
│  ├─ _template.yaml                     # Fully documented production template
│  └─ smoke-mattergen.yaml               # MatterGen end-to-end smoke task
├─ data/                                 # Runtime data; ignored by Git
│  └─ <task_id>/
│     ├─ runs/<timestamp>/               # Search, screening, reading, and run.json
│     ├─ downloads/<timestamp>/          # Lawfully acquired, identity-checked papers
│     ├─ state/recommendations.jsonl      # Delivered-paper history for this task
│     └─ tmp/                            # Task-local temporary files
├─ scripts/
│  ├─ patch-paper-search.mjs             # Local paper-search compatibility patch
│  ├─ cleanup-task-data.py               # Delete one canonical task-data directory
│  ├─ migrate-task-data.py               # One-time legacy-layout migration
│  ├─ write-preflight-failure.py         # Canonical connector-preflight failure writer
│  └─ task_data_layout.py                # Shared path and safety implementation
├─ tests/                                # Patch, history, migration, and cleanup tests
├─ docs/task-data-cleanup.md             # Detailed migration and cleanup guidance
├─ .env.example                          # Secret-free environment template
├─ package.json                          # Local commands and pinned npm dependency
├─ skills-lock.json                      # Skill source and commit provenance
├─ README.md                             # English documentation
└─ README_CN.md                          # Simplified Chinese documentation
```

The four runtime subdirectories are fixed and isolated per `task_id`. Task YAML cannot override runtime paths.

## Define a task YAML

Copy the template to create a new task:

```powershell
Copy-Item tasks\_template.yaml tasks\solid-electrolyte.yaml
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
| `delivery.gmail_label` | `Literature recommendations` | Exact label that must be created/applied and verified after sending. |
| `delivery.subject_prefix` | `每日文献推荐` | Email subject prefix. |
| `delivery.signature` | `Codex` | Message signature. |
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
  gmail_label: Literature recommendations from codex
```

Use `tasks/_template.yaml` for the fully commented configuration. Cadence and execution time belong to the Codex scheduled task, not the YAML.

## Execution workflow

A normal invocation performs these stages:

1. Read the YAML and create a unique `run_key=<task_id>:<YYYY-MM-DDTHH-mm-ss>` and run directory.
2. Check the project-local `paper-search` capability and construct queries within the configured budget.
3. Search independent sources, normalize records, deduplicate by DOI/arXiv ID/title, and filter task-local delivery history.
4. Screen titles and abstracts, perform bounded backward/forward citation expansion, and rescreen.
5. Score candidates on task relevance, novelty, evidence, provenance, and accessible reading evidence.
6. Within `read_limit`, lawfully retrieve and identity-check papers and record the true reading depth.
7. Select at most `recommend_limit` papers and write `selected.jsonl`.
8. Send one Gmail status email, apply the exact configured `gmail_label`, and read the message back to verify it.
9. Update task-local recommendation history only after a successful send, then finalize `run.json`.

Inaccessible full text is not evidence that a paper is irrelevant. Record an isolated source, download, or candidate failure and continue other independent candidates.

## Manual invocation

Select this project in Codex and use a prompt such as:

```text
Use the project's $daily-literature-recommendations skill to run tasks/smoke-mattergen.yaml. Follow every YAML search, reading, and recommendation limit. Do not use Sci-Hub. Complete Gmail delivery, exact-label application, read-back verification, and history update.
```

The skill provides the orchestration, so there is no equivalent `npm run recommend` command. The CLI, Python state scripts, and file operations are project-local implementation steps within the orchestrated run.

## Scheduled-task prompt example

Configure the cadence in Codex Scheduled and use:

```text
First use @DevSpace to open E:\projects-codex\daily-literature-recommendations and use @Gmail get profile to validate both connections. Do not send an email during this check.

If DevSpace is unavailable, stop immediately and state that a local run.json could not be written. Do not use a cloud shell and do not claim that a file was written.

If Gmail get profile fails while DevSpace remains available, use @DevSpace to run this command from the project root and no other path:
python scripts/write-preflight-failure.py --task-file tasks/smoke-mattergen.yaml --stage gmail_profile --reason "Gmail connector preflight failed" --error-code "<actual-error-code>" --devspace-status ok --gmail-status unavailable
Confirm that the returned run_path is under data/smoke1-mattergen/runs/<timestamp>/run.json, then stop. Never hand-create runs/smoke1-mattergen/... or another legacy path.

When both connections work, use the project's $daily-literature-recommendations skill to run tasks/smoke-mattergen.yaml. All project commands and file operations must run locally through @DevSpace; do not use a cloud shell. Use Gmail only for sending, exact-label application, and read-back verification. Never use Sci-Hub.
```

Connection preflight must happen before retrieval and delivery. `write-preflight-failure.py` must create the failure record; the model must not construct the path itself. The script reads the authoritative `task_id` and `timezone`, writes atomically to the canonical directory, and refuses to overwrite an existing run. It fixes path consistency only; it does not repair Gmail connector permissions or session routing.

Do not change cadence from inside the skill. Every scheduled trigger sends one report, including zero-result runs. Do not search prior Gmail subjects to suppress a valid invocation.

## Data and `run.json`

Every invocation creates task-timezone-specific directories:

```text
data/<task_id>/runs/<YYYY-MM-DDTHH-mm-ss>/
data/<task_id>/downloads/<YYYY-MM-DDTHH-mm-ss>/
```

A typical run directory contains:

- raw search responses and source errors;
- normalized, merged, and history-filtered candidate JSONL;
- screening, citation-expansion, and rescreening decisions;
- reading notes, identity verification, and true reading depth;
- scores and `selected.jsonl`;
- the final `run.json` invocation record.

`run.json` should make at least these facts auditable: `task_id`, `run_key`, invocation time, task timezone, configured limits, enabled sources, stage counts, capability limits/failures, email subject and recipient, `delivery_status`, `gmail_label_expected`, `gmail_label_applied`, and `label_status`. Never store Gmail message IDs, API keys, or copyrighted full text in run artifacts.

Minimal connector-preflight failure state:

```json
{
  "task_id": "smoke1-mattergen",
  "run_key": "smoke1-mattergen:2026-08-28T09-00-00",
  "status": "failed_preflight",
  "connection_check": {
    "devspace": "ok",
    "gmail_profile": "unavailable",
    "email_sent_during_check": false
  },
  "delivery_status": "not_sent",
  "label_status": "not_attempted",
  "failures": [
    {
      "stage": "gmail_profile",
      "reason": "Gmail connector preflight failed",
      "error_code": "FORBIDDEN"
    }
  ]
}
```

Recommendation history is stored at `data/<task_id>/state/recommendations.jsonl`. It may contain rows for that task only; the history tool rejects cross-task rows to prevent contamination.

## Common commands

| Command | Purpose |
| --- | --- |
| `npm run doctor` | Check local search capabilities and configured providers. |
| `npm run smoke:mock` | Run the offline CLI smoke suite. |
| `npm run smoke:live` | Run live provider smoke checks; accesses external services. |
| `npm run patch:paper-search` | Reapply project-local compatibility patches. |
| `npm run failure:preflight -- ...` | Derive the canonical run path from YAML and record a connector-preflight failure. |
| `npm test` | Run patch, history-isolation, migration, cleanup, and mock-smoke tests. |

Example preflight-failure record:

```powershell
npm run failure:preflight -- `
  --task-file tasks/smoke-mattergen.yaml `
  --stage gmail_profile `
  --reason "Gmail connector preflight failed" `
  --error-code "FORBIDDEN" `
  --devspace-status ok `
  --gmail-status unavailable
```

The returned `run_path` is the only allowed location for that failure record.

### Clean data by `task_id`

The cleanup script handles exactly one `data/<task_id>` directory. It defaults to dry-run and never scans other tasks:

```powershell
$taskId = "smoke1-mattergen"

# Preview file count, directory count, and bytes; change nothing
npm run cleanup:task -- --task-id $taskId

# Pause the corresponding scheduled task, then delete data/<task_id>
npm run cleanup:task -- --task-id $taskId --apply
```

The task YAML is preserved by default, so a later scheduled trigger recreates empty state and may recommend previously delivered papers again. To retire a task permanently, disable its schedule first and explicitly remove the task config:

```powershell
npm run cleanup:task -- --task-id $taskId --remove-task-config --apply
```

Add `--json` for a machine-readable report. The script rejects path separators, `..`, project roots, and unsafe targets. `task-a` never matches `task-a-longer`.

### Migrate the legacy scattered layout

Older installations used root-level `runs/<task_id>`, `downloads/<task_id>`, shared `state/recommendations.jsonl`, and task-prefixed temporary paths. Only legacy installations need this one-time migration:

```powershell
# Preview
npm run migrate:task -- --task-id $taskId

# Pause the corresponding scheduled task, then apply
npm run migrate:task -- --task-id $taskId --apply
```

The migrator copies data into a staging directory and verifies file count and byte count before committing `data/<task_id>`, splitting shared history, and removing exact legacy sources. It refuses to merge into an existing destination. See `docs/task-data-cleanup.md` for details.

## Gmail delivery semantics

- `delivery.recipient` defaults to `me`; the authenticated Gmail account remains the actual sender.
- Subject format: `[<subject_prefix>] <display_name> | <YYYY-MM-DD HH:mm>`.
- `delivery.gmail_label` is exact. Create it if absent, apply only that label, and read the sent message back to verify it.
- If sending succeeds but labeling fails, preserve `delivery_status=delivered`, record `label_status=pending`, and retry labeling without resending.
- If sending fails, do not write the papers to delivered history.
- A zero-recommendation run still sends a status email with counts, scope, main exclusion reasons, and source limitations.

## Security and maintenance

- `data/`, `.env`, `node_modules/`, diagnostics, temporary artifacts, credentials, and private task YAML are ignored by Git.
- Only lawful publisher, arXiv, PMC/Europe PMC, CORE/OpenAIRE, Unpaywall, or otherwise authorized sources may be used for downloads.
- A successful PDF download is not sufficient: extract text and verify the title/identity before treating it as evidence. Reject mismatches.
- Never describe an abstract assessment as full-text reading, and never fabricate bibliographic metadata, results, or limitations.
- Pause the corresponding schedule before cleanup, migration, or dependency upgrades. Run `npm test` and `npm run doctor` afterward.
- If documentation and the runtime CLI disagree, trust `npx --no-install paper-search --help`, `tools --pretty`, and validated tests, then update the skill and both README files.
