# Native Gmail delivery CLI

All Gmail reads and writes for this workflow go through `scripts/gmail_delivery.py`.
It calls the Gmail REST API directly (stdlib only, no MCP server, no plugin) and
reuses the OAuth token that the installed Hermes `google-workspace` skill manages
at `$HERMES_HOME/google_token.json`. Resolution order: `--hermes-home`, then
`$HERMES_HOME`, then `~/.hermes`; on a Hermes desktop install a shell without
`HERMES_HOME` exported falls back to `%LOCALAPPDATA%/hermes/google_token.json`
when a token exists there. `auth-check` always reports the path it resolved.

Required scopes: `gmail.send` and `gmail.modify`. `auth-check` fails loudly when
either is missing, so a revoked or narrowed token can never silently downgrade a
run's delivery guarantee.

## Credential check (run during preparation and as the preflight gate)

```powershell
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live
```

`auth-check` reports `status`, `token_path`, granted scopes, and `missing_scopes`.
`--live` additionally calls the Gmail profile endpoint to prove the mailbox is
reachable, and reports the authenticated address. Neither form sends anything.

## Order of operations (never reorder)

```powershell
# 1. send exactly one status email for this invocation
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py send --to me --from "<sender_name>" --subject "[<prefix>] <display-name> | <YYYY-MM-DD HH:mm>" --body-file <body-file>

# 2. write delivered history with label_status=pending
python .agents/skills/daily-literature-recommendations/scripts/history.py record-delivery --history data/<task-id>/state/recommendations.jsonl --input selected.jsonl --task-id <task-id> --run-key <run-key> --email-subject "<subject>" --gmail-label "<configured-gmail-label>" --label-status pending

# 3. apply the EXACT configured label (created when absent, verified after the write)
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py label --subject "<subject>" --label "<configured-gmail-label>"

# 4. only after verification, flip history to applied
python .agents/skills/daily-literature-recommendations/scripts/history.py mark-label-status --history data/<task-id>/state/recommendations.jsonl --task-id <task-id> --run-key <run-key> --gmail-label "<configured-gmail-label>" --status applied
```

`send` prints `{"status": "sent", "id": ..., "threadId": ..., "to": ..., "from": ..., "subject": ...}`.
The `id` is for the current process only: never write a Gmail message ID into
`run.json`, history, logs, or the email report.

## Commands

| Command | Purpose |
|---|---|
| `auth-check [--live]` | Verify token, scopes, and (with `--live`) mailbox reachability |
| `send --to <addr\|me> --subject <s> (--body <t> \| --body-file <path>) [--html] [--from <display>] [--thread-id <id>]` | Send one message. `--to me` resolves to the authenticated address |
| `label (--message-id <id> \| --subject <s> \| --run-json <path>) --label <name> [--no-create]` | Resolve the label by exact name, create it if absent, apply it, verify it |
| `verify-label (--message-id <id> \| --subject <s> \| --run-json <path>) --label <name>` | Read back label membership without writing |
| `find-message --subject <s>` | List the exact-subject matches in Sent (recovery/diagnosis only) |

`--run-json` reads the run's recorded `email_subject`; it is the retry-friendly
way to address the message a previous invocation already sent. The lookup
reduces that subject to plain words before querying Gmail — production subjects
carry `[`, `]` and `|`, which Gmail's query grammar would otherwise consume —
and then compares each candidate's decoded subject for exact equality.

`--from` takes the task's `delivery.sender_name`. A bare name (no `@`) is paired
with the authenticated address, so the inbox shows the configured name while the
real `From` address stays the authorized account — no Gmail send-as alias needed.
Anything containing `@` is passed through as an explicit sender.

## Exit codes (branch on these, not on prose)

| Code | Meaning | Required reaction |
|---|---|---|
| 0 | Success | Continue to the next step |
| 2 | Send failed | Nothing was emailed: do not write delivered history, do not mark delivered |
| 3 | Label failed (or no exact-subject message found) | Keep `delivery_status=delivered`; keep `label_status=pending`; never resend |
| 4 | Auth/config failure (no token, missing scope, unreachable mailbox) | Stop the delivery step; use the connector-preflight path |
| 5 | Usage error (missing/ambiguous argument) | Fix the invocation and retry the same step |

## Retry semantics

A label failure is retried by re-running **only** step 3 with the same exact
subject, then step 4. `label` never sends mail, and a successful retry cannot
produce a second email.

## Rules

- Match the label by its exact configured name. Never substitute a similar,
  default, or incidentally mentioned label; when the name is absent, create it
  instead of reusing a neighbour.
- One status email per invocation, always, even at zero recommendations.
- No secrets, tokens, or message IDs in the task YAML, `run.json`, history,
  logs, or the report.
- `send` returns success only after Gmail accepts the message; `label` returns
  success only after the label is verified present on that message.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Exit 4, `missing_scopes` non-empty | Re-authorize through the Hermes `google-workspace` skill so `gmail.send` and `gmail.modify` are granted |
| Exit 4, no token at `token_path` | Complete the `google-workspace` OAuth setup; the CLI does not manage credentials itself |
| Exit 4, `invalid_grant` on refresh | The refresh token was revoked or expired: re-authorize, then re-run `auth-check --live` |
| Exit 3, `no sent message with subject` | The subject in the retry does not match the sent one exactly (spacing, prefix, time format). Confirm with `find-message` |
| Exit 5, `N sent messages share subject` | Subject collision: address the message with `--message-id` instead |
