# Daily Literature Recommendations

**English** | [简体中文](README_CN.md)

A bounded literature-recommendation project driven by a scheduled agent run. A task YAML defines the research scope; the agent runs paper discovery, citation expansion, relevance screening, evidence-aware reading, and scoring, then delivers recommendations by Gmail. Scheduling is owned by the triggering platform's own scheduler; delivery is native — any Agent Skills-compatible agent (Hermes, Codex, Claude Code) runs the same workflow, and `scripts/gmail_delivery.py` talks to the Gmail REST API directly with no MCP server on any platform.

- Every trigger is an independent run and sends one status email, even with zero new papers.
- Papers are deduplicated by DOI, arXiv ID, or normalized title; delivered papers never repeat.

## Quick start

```bash
git clone https://github.com/sw-ljn/Daily-Literature-Recommendations.git
cd Daily-Literature-Recommendations
cp .env.example .env   # fill in real keys; .env is ignored by Git
uv sync                # pinned Python venv (.venv/) + pypdf, from uv.lock
npm install            # npm deps + local patch + Claude Code skill bridge
npm run doctor && npm test
```

Prerequisites: Node.js 18+, [uv](https://docs.astral.sh/uv/) (Python 3.10+ is provisioned automatically), and an agent able to trigger this project (Hermes, Codex, or Claude Code). Gmail requires a one-time OAuth: use the Hermes `google-workspace` skill so the token lands at `$HERMES_HOME/google_token.json`, then verify:

```bash
uv run python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live
```

API keys for search providers go only in `.env` (see `.env.example`).

## Run your first recommendation

**Manual** — from the project root in any supported agent session:

```text
Use the project's $daily-literature-recommendations skill to run tasks/smoke-mattergen.yaml. Follow every YAML search, reading, and recommendation limit. Complete Gmail delivery, exact-label application, read-back verification, and history update.
```

There is no `npm run recommend` — the skill orchestrates the run; the CLIs and scripts below are its internal steps.

**Scheduled** — register a trigger with your platform's scheduler (see [Multi-platform scheduling](#multi-platform-scheduling)). Every trigger is an independent run; even a zero-result run sends one status email.

## Define a task

```bash
cp tasks/_template.yaml tasks/solid-electrolyte.yaml
```

The filename is for humans; the `task_id` inside is authoritative for run directories, history, and `run_key`. Cadence is never written in the YAML — it belongs to the scheduler.

Required fields:

| Field | Meaning |
| --- | --- |
| `task_id` | Stable unique id (lowercase, digits, hyphens; don't rename an active task) |
| `display_name` | Human-readable name for email subjects and reports |
| `timezone` | IANA timezone for timestamps and `run_key` |
| `scope.research_question` | The question every invocation answers |
| `scope.target_relationship` | The direct relationship a paper must have; a keyword hit is not relevance |
| `search.keywords` | Non-empty list of English search phrases |

`scope.include` / `scope.exclude` are strongly recommended for auditable screening. All optional fields and defaults (`search.sources`, `read_limit`, `recommend_limit`, `min_score`, `delivery.*`, …) are documented in `tasks/_template.yaml`. Minimal example:

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
search:
  keywords:
    - solid-state electrolyte generative model
delivery:
  recipient: me
  gmail_label: Literature recommendations
```

## Multi-platform scheduling

The workflow is platform-neutral: skills live in `.agents/skills/` (the cross-tool Agent Skills directory), every project command is a plain `npm`/`python` call, and switching platform means re-registering the trigger — nothing else changes.

|  | Hermes | Codex | Claude Code |
| --- | --- | --- | --- |
| Skill discovery | Reads `.agents/skills/` natively; fresh clone needs `hermes skills trust` once | Scans `.agents/skills/` natively | `.claude/skills/` junctions via `npm run sync:skills` |
| Registration | `hermes cron create "0 8 * * *" "<task prompt>" --workdir <project> --deliver local` | Codex app Automations with custom cron; or schedule `codex exec --full-auto "<task prompt>"` | Task Scheduler + `claude -p "<task prompt>"` |
| Credentials | Logged-in Hermes; Gmail token shared on disk | ChatGPT login or `CODEX_API_KEY`; Gmail token shared on disk | Logged-in `claude` CLI; Gmail token shared on disk |

The Gmail OAuth token lives in the Hermes data directory (`%LOCALAPPDATA%\hermes\google_token.json` on a Hermes desktop install); `gmail_delivery.py` locates it automatically — no platform copies credentials. Register each task with exactly one scheduler: duplicate registrations send duplicate emails.

Self-contained task prompt (works verbatim on every platform — cron runs in a fresh session):

```text
Run the literature recommendation task in <project path>; run every command locally there, no cloud shell.

Step 1 — Gmail credential preflight only (no email):
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live

If the project directory is unavailable, stop immediately and say so honestly.

If the preflight fails while the project directory is usable, run from the project root and stop:
python scripts/write-preflight-failure.py --task-file tasks/<task>.yaml --stage gmail_auth --reason "Gmail credential preflight failed" --error-code "<actual-error-code>" --runtime-status ok --gmail-status unavailable
Confirm the returned run_path is under data/<task_id>/runs/<timestamp>/run.json, then stop.

When the check passes, use the project's daily-literature-recommendations skill to run tasks/<task>.yaml: honor every YAML limit and complete Gmail delivery, exact-label application, read-back verification, and the history update. 
```

For Claude Code, trigger it from Windows Task Scheduler with `claude -p "<task prompt>"` (complete an interactive `claude` login once first). Codex uses the same prompt in an automation or `codex exec --full-auto`.

## Common commands

| Command | Purpose |
| --- | --- |
| `npm run doctor` | Check search capabilities and configured providers |
| `npm test` | Full suite: skill bridge, patch, history, delivery, cleanup, mock smoke |
| `npm run smoke:live` | Live provider smoke checks (accesses external services) |
| `npm run cleanup:task -- --task-id <id> [--apply]` | Preview/delete one task's `data/<task_id>` (dry-run by default; pause its schedule first) |
| `npm run migrate:task -- --task-id <id> [--apply]` | One-time migration from the legacy scattered layout (see `docs/task-data-cleanup.md`) |
| `npm run failure:preflight -- ...` | Record a delivery-preflight failure at the canonical run path |
| `npm run sync:skills` | Rebuild the `.claude/skills/` junctions for Claude Code |

## Data and delivery semantics

- Run artifacts live in `data/<task_id>/runs/<timestamp>/` and `downloads/<timestamp>/`; delivery history in `data/<task_id>/state/recommendations.jsonl` (one task's rows only — cross-task rows are rejected).
- `run.json` must make the delivery facts auditable: `delivery_status`, `gmail_label_expected`, `gmail_label_applied`, `label_status`. Never store Gmail message IDs or secrets in run artifacts.
- Email subject: `[<subject_prefix>] <display_name> | <YYYY-MM-DD HH:mm>`.
- `delivery.gmail_label` is exact: create it if absent, apply only that label, and read the sent message back to verify.
- Send succeeded but label failed → keep `delivered` + `label_status=pending`; retry the label by exact subject, never resend the email.
- Send failed → do not write delivered history. Zero recommendations still sends a status email with counts and exclusion reasons.
- `gmail_delivery.py` exit codes: `0` success, `2` send failed, `3` label failed (retry label only), `4` credential problem, `5` bad arguments. Full command surface: `references/delivery-cli.md` in the skill.

## Going deeper

Project documentation (each in English and 简体中文):

- [Project deep dive](docs/DEEP-DIVE.md) — upstream provenance and pinning, the local patch layer, the full repository layout, the nine-stage execution workflow, data/`run.json` semantics, data cleanup, and Gmail delivery details ([简体中文](docs/DEEP-DIVE_CN.md))

Skill-internal references:

- `tasks/_template.yaml` — fully commented task configuration
- `.agents/skills/daily-literature-recommendations/SKILL.md` — the complete orchestration workflow
- `docs/task-data-cleanup.md` — data cleanup and migration details
- `scripts/patch-paper-search.mjs` — project-local compatibility patches for the pinned `paper-search-cli 0.3.4` (arXiv timeouts, managed Scholar backend, verified-`pdfUrl`-first downloads); review when upgrading

## Security and maintenance

- Secrets live only in `.env`, `paper-search` configuration, or environment variables — never in task YAML, skills, run artifacts, or Git history.
- Download-source policy is the user's decision, declared in the task prompt or task YAML; verify title and identity after every PDF download.
- Never describe abstract-only assessment as full-text reading; never fabricate bibliographic data, results, or limitations.
- Pause the schedule before cleanup, migration, or dependency upgrades; run `npm test` and `npm run doctor` afterward.
- If docs and the runtime CLI disagree, trust `npx --no-install paper-search --help` and the tests.
