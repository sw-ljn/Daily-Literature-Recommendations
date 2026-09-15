# Project deep dive: architecture, layout, workflow, and data

**English** | [简体中文](DEEP-DIVE_CN.md)

> This document consolidates the project's deep-dive documentation in one place. For the quick-start reading path, start at [README.md](../README.md).

## Upstream projects and local orchestration

| Component | Upstream | Pinned version | Role in this project |
| --- | --- | --- | --- |
| `write-literature-review` | [Zsun79/LitReviewSkill](https://github.com/Zsun79/LitReviewSkill) | commit [`a53cd419352e4dd05958f67340fde3642d84abc3`](https://github.com/Zsun79/LitReviewSkill/tree/a53cd419352e4dd05958f67340fde3642d84abc3) | Reuses stages 0–7: scope, queries, seed discovery, citation expansion, screening, ranking, and bounded full-text inspection. Its knowledge-graph and review-writing stages are intentionally omitted. |
| `paper-search-cli` | [dr-dumpling/paper-search-cli](https://github.com/dr-dumpling/paper-search-cli) | npm `0.3.4`, MIT | Multi-source metadata search, identifier verification, backward/forward citation expansion, lawful PDF discovery, and journal metrics. |
| `daily-literature-recommendations` | Project-local skill | `1.0.0` | Orchestrates the upstream workflows and adds native Gmail delivery, label verification, task-local history, and run-artifact management. |

Source provenance and versions are recorded in `skills-lock.json`, `package.json`, and `package-lock.json`. The scheduler (the triggering platform's built-in scheduler) and the Gmail account are runtime dependencies; they are not vendored upstream repositories.

The project does not fork the upstream skills. After `npm install`, `scripts/patch-paper-search.mjs` applies a small compatibility layer to the pinned `paper-search-cli 0.3.4` runtime:

- a sufficient source-specific timeout for arXiv, without holding the global lock during cooldown waits;
- the managed SerpApi backend when Google Scholar is configured;
- a verified caller-provided `pdfUrl` as the first lawful download candidate.

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

## Execution workflow

A normal invocation performs these stages:

1. Read the YAML and create a unique `run_key=<task_id>:<YYYY-MM-DDTHH-mm-ss>` and run directory.
2. Check the project-local `paper-search` capability and construct queries within the configured budget.
3. Search independent sources, normalize records, deduplicate by DOI/arXiv ID/title, and filter task-local delivery history.
4. Screen titles and abstracts, perform bounded backward/forward citation expansion, and rescreen.
5. Score candidates on task relevance, novelty, evidence, provenance, and accessible reading evidence.
6. Within `read_limit`, lawfully retrieve and identity-check papers and record the true reading depth.
7. Select at most `recommend_limit` papers and write `selected.jsonl`.
8. Send one Gmail status email through `scripts/gmail_delivery.py`, apply the exact configured `gmail_label`, and read the message back to verify it.
9. Update task-local recommendation history only after a successful send, then finalize `run.json`.

Inaccessible full text is not evidence that a paper is irrelevant. Record an isolated source, download, or candidate failure and continue other independent candidates.

There is no equivalent `npm run recommend` command — the skill provides the orchestration; the CLIs, Python state scripts, and file operations are project-local implementation steps within the orchestrated run.

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

Minimal delivery-credential preflight failure state:

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

Recommendation history is stored at `data/<task_id>/state/recommendations.jsonl`. It may contain rows for that task only; the history tool rejects cross-task rows to prevent contamination.

### Clean data by `task_id`

The cleanup script handles exactly one `data/<task_id>` directory. It defaults to dry-run and never scans other tasks:

```bash
taskId="smoke1-mattergen"

# Preview file count, directory count, and bytes; change nothing
npm run cleanup:task -- --task-id $taskId

# Pause the corresponding scheduled task, then delete data/<task_id>
npm run cleanup:task -- --task-id $taskId --apply
```

The task YAML is preserved by default, so a later scheduled trigger recreates empty state and may recommend previously delivered papers again. To retire a task permanently, disable its schedule first and explicitly remove the task config:

```bash
npm run cleanup:task -- --task-id $taskId --remove-task-config --apply
```

Add `--json` for a machine-readable report. The script rejects path separators, `..`, project roots, and unsafe targets. `task-a` never matches `task-a-longer`.

## Gmail delivery semantics

All Gmail reads and writes go through `.agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py`, which calls the Gmail REST API directly with the OAuth token created once by the Hermes `google-workspace` skill. No MCP server and no connector are involved.

- `delivery.recipient` defaults to `me`; the CLI resolves `me` to the authenticated Gmail account, which remains the actual sender address.
- `delivery.sender_name` is the display name shown in the inbox; pass it as `--from "<sender_name>"` and the CLI pairs the bare name with the authenticated address.
- Subject format: `[<subject_prefix>] <display_name> | <YYYY-MM-DD HH:mm>`.
- `delivery.gmail_label` is exact. Create it if absent, apply only that label, and read the sent message back to verify it. Never reuse a similar existing label.
- If sending succeeds but labeling fails, preserve `delivery_status=delivered`, record `label_status=pending`, and retry labeling without resending.
- Label retries locate the already-sent message by its exact recorded subject — never by a stored message ID, which run artifacts must not contain.
- If sending fails, do not write the papers to delivered history.
- A zero-recommendation run still sends a status email with counts, scope, main exclusion reasons, and source limitations.

Exit codes: `0` success, `2` send failed, `3` labeling failed (resend is forbidden; retry the label only), `4` credential or permission problem, `5` bad arguments. See `references/delivery-cli.md` in the skill for the full command surface.
