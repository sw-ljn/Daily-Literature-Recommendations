# Execution workflow, scheduling details, and data/run.json

> This document expands on the README: the stage-by-stage execution workflow, the Hermes cron walkthrough, and the full data/`run.json` contract. For the reading path, start at [README.md](README.md).

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

## Scheduling the run with Hermes cron

Register one cron job per task with the built-in scheduler, pinned to the project directory so every run starts from the right working directory:

```bash
hermes cron create "0 8 * * *" \
  "Run the project's daily literature recommendation task." \
  --name daily-literature \
  --workdir /path/to/Daily-Literature-Recommendations \
  --deliver local
```

`--workdir` injects the project context files and sets the working directory for terminal, file, and code-execution tools; `--deliver local` keeps the run out of chat. `0 8 * * *` means 08:00 daily in the host timezone. Inspect, pause, or remove jobs with `hermes cron list`, `hermes cron pause`, `hermes cron resume`, and `hermes cron delete`.

The job prompt itself stays small:

```text
First validate the Gmail credential without sending email: run `python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live` from the project root.

If the project directory is unavailable, stop immediately and state that a local run.json could not be written. Do not use a cloud shell and do not claim that a file was written.

If the credential check fails while the project directory remains usable, run this command from the project root and no other path:
python scripts/write-preflight-failure.py --task-file tasks/<task>.yaml --stage gmail_auth --reason "Gmail credential preflight failed" --error-code "<actual-error-code>" --runtime-status ok --gmail-status unavailable
Confirm that the returned run_path is under data/<task_id>/runs/<timestamp>/run.json, then stop. Never hand-create runs/<task_id>/... or another legacy path.

When the check passes, use the project's $daily-literature-recommendations skill to run tasks/<task>.yaml. Keep every project command and file operation local; do not use a cloud shell. Use Gmail only for sending, exact-label application, and read-back verification.
```

Connection preflight must happen before retrieval and delivery. `write-preflight-failure.py` must create the failure record; the model must not construct the path itself. The script reads the authoritative `task_id` and `timezone`, writes atomically to the canonical directory, and refuses to overwrite an existing run. It fixes path consistency only; it does not repair a missing, expired, or revoked Gmail credential.

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

## Preflight failure recording

`write-preflight-failure.py` derives the canonical run path from the task YAML and writes the failure record there; the returned `run_path` is the only allowed location for that record:

```bash
npm run failure:preflight -- \
  --task-file tasks/smoke-mattergen.yaml \
  --stage gmail_auth \
  --reason "Gmail credential preflight failed" \
  --error-code "FORBIDDEN" \
  --runtime-status ok \
  --gmail-status unavailable
```

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

### Migrate the legacy scattered layout

Older installations used root-level `runs/<task_id>`, `downloads/<task_id>`, shared `state/recommendations.jsonl`, and task-prefixed temporary paths. Only legacy installations need this one-time migration:

```bash
# Preview
npm run migrate:task -- --task-id $taskId

# Pause the corresponding scheduled task, then apply
npm run migrate:task -- --task-id $taskId --apply
```

The migrator copies data into a staging directory and verifies file count and byte count before committing `data/<task_id>`, splitting shared history, and removing exact legacy sources. It refuses to merge into an existing destination. See `docs/task-data-cleanup.md` for details.

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
