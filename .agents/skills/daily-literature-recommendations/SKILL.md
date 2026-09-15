---
name: daily-literature-recommendations
description: Orchestrate bounded recurring academic-paper discovery, screening, citation expansion, reading, ranking, Gmail delivery, label filing, and recommendation-history updates. Use for scheduled or manual daily/weekly literature recommendation tasks driven by a task YAML file, especially when an agent should combine the installed write-literature-review workflow, paper-search CLI, and the native Gmail delivery CLI without producing a full literature-review article.
---

# Daily Literature Recommendations

Run a repeatable recommendation pipeline. Reuse upstream skills unchanged: apply steps 0-7 of `write-literature-review`, use `paper-search` as the search, citation, verification, and lawful PDF-discovery engine, then replace the upstream graph/review stages with Gmail delivery and persistent history.

## Required preparation

1. Read the task YAML and `references/task-config-schema.md`. Do not invent a missing research scope or target relationship.
2. Read `../write-literature-review/SKILL.md` and its authoritative `references/workflow.md` completely. Use only steps 0-7; do not build its knowledge graph, review Markdown, or PDF.
3. Read `../paper-search/SKILL.md` and the relevant routing/CLI references completely before calling the CLI.
4. Read `references/delivery-cli.md` before the first Gmail call. All Gmail reads and writes go through the project-local native delivery CLI (`scripts/gmail_delivery.py`); it talks to the Gmail REST API directly and shares the OAuth token managed by the installed `google-workspace` skill. Do not add a Gmail MCP server or a Gmail plugin for this workflow. Confirm the credential with `python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check` (add `--live` to also confirm the mailbox is reachable).
5. Run every CLI command from the project root through the pinned local runtime: `npx --no-install paper-search ...`. Never fall back to a user-global `paper-search` executable.
6. Run `npx --no-install paper-search doctor --pretty`. Continue when metadata search is available; treat missing enhanced or publisher keys as capability limits, not fatal errors.

Never store secrets in this skill, the task YAML, logs, or project history. Download-source policy (including whether Sci-Hub may be used) is the user's decision, made per task in the task YAML or the triggering prompt; this project imposes none.

## Project contract

Resolve paths relative to the scheduled task's selected project directory:

```text
tasks/<task-config-name>.yaml
data/<task-id>/
  runs/<YYYY-MM-DDTHH-mm-ss>/
  downloads/<YYYY-MM-DDTHH-mm-ss>/
  state/recommendations.jsonl
  tmp/
```

The `task_id` field inside the YAML is authoritative; do not derive it from the config filename. Runtime data paths are fixed and must not be overridden per task. Create the four parallel subdirectories when needed. A run directory should contain the raw search JSON, normalized candidates, screening decisions, reading notes, selected recommendations, and `run.json`. Use the matching task-local `tmp/` directory for transient files. Do not place API keys or full copyrighted text in these artifacts.

### Connector-preflight failures

Do not hand-build a path when a connector check fails before the normal workflow establishes its run directory. The Gmail check is `python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live`; when it fails (no token, missing `gmail.send`/`gmail.modify` scope, or unreachable mailbox) while the project directory itself is writable, run this project-local command from the project root:

```powershell
python scripts/write-preflight-failure.py --task-file tasks/<task-config-name>.yaml --stage gmail_auth --reason "Gmail credential preflight failed" --error-code "<auth-check status or provider error code>" --runtime-status ok --gmail-status unavailable
```

The script reads the YAML's authoritative `task_id` and `timezone`, creates a unique `data/<task-id>/runs/<timestamp>/run.json`, refuses to overwrite an existing run, and never creates legacy `runs/`, `downloads/`, or shared `state/` roots. Use the returned `run_path`; do not substitute another path. If the project directory itself is unavailable, a project-local failure file cannot be written honestly: stop and report that boundary without using a cloud shell.

## Workflow

### 0. Establish the invocation

- Derive the invocation timestamp from the task timezone and set a unique `run_key=<task-id>:<YYYY-MM-DDTHH-mm-ss>`.
- Use `data/<task-id>/runs/<YYYY-MM-DDTHH-mm-ss>/` and the matching `data/<task-id>/downloads/<YYYY-MM-DDTHH-mm-ss>/` directory so separate invocations never overwrite one another.
- Set the subject to `[<subject-prefix>] <display-name> | <YYYY-MM-DD HH:mm>`.
- Do not search Gmail Sent to suppress an invocation. Do not skip because an earlier email has the same task, date, or subject. The scheduled task owns cadence and each trigger is an authorized independent run.
- Record limits, enabled sources, invocation timestamp, and `run_key` in `run.json`.

### 1. Define scope and queries (LitReview 0-1)

- Translate the configured research relationship into explicit inclusion and exclusion tests.
- Draft no more than the configured maximum queries (default 10). Prefer concise English noun phrases, synonyms, method names, materials/entities, and domain variants.
- Preserve the user's target relationship. A keyword match alone is not relevance.

### 2. Build the bounded seed set (LitReview 2)

- Use `npx --no-install paper-search search`; choose sources by field or use the configured list.
- On Windows PowerShell, quote a source CSV: `--sources "crossref,openalex,arxiv"`.
- Split the total search budget across queries. Do not treat `--max-results` as a global cap when invoking several queries; stop once the merged unique count reaches `search_limit`.
- Save every raw CLI JSON response. Normalize and deduplicate with:

```powershell
python .agents/skills/daily-literature-recommendations/scripts/normalize_papers.py --input <raw.json> --output <normalized.jsonl> --query "<query>"
```

- Merge normalized batches by canonical DOI/arXiv ID and normalized title. Prefer a published DOI record over its preprint while preserving all source URLs.
- Filter previously delivered papers with `scripts/history.py filter-new`.

### 3. Screen, expand, and rescreen (LitReview 3-5)

- Screen title and abstract against the configured relationship. Prefer recall in the first pass and precision in the final pass.
- For the most relevant frontier papers with DOI, Semantic Scholar paper ID, or arXiv ID, use `get_paper_references` and `get_paper_citations` when citation expansion is enabled.
- Citation-graph results may omit abstracts. Enrich each new record through DOI lookup or title search before applying title-and-abstract screening; do not include an unverified graph edge as a recommendation.
- Apply the configured expansion round and per-seed caps. Stop when no new paper survives, saturation is reached, or the configured bound is reached.
- Deduplicate each round. Record include/exclude/borderline, a short reason, reading priority, and discovery route.
- Never classify an inaccessible full text as irrelevant solely because it is inaccessible.

### 4. Rank the final candidates (LitReview 6)

Do not use citation count as the main score for a current-literature feed. Score each candidate on a 100-point rubric:

- task and relationship relevance: 0-40
- methodological or scientific novelty: 0-20
- evidence quality and validation: 0-20
- metadata/provenance reliability: 0-10
- accessible reading evidence: 0-10

Use citation count only as a weak tie-breaker. Record component scores and the final score. Exclude candidates below `min_score`.

### 5. Read the bounded set (LitReview 7)

- Read at most `read_limit`, in rank order.
- Verify identity and canonical publication before downloading.
- Prefer publisher HTML, arXiv, PMC/Europe PMC, CORE/OpenAIRE, Unpaywall, or another lawful open-access source, within the task's download-source policy.
- If the normalized candidate already contains a verified `pdf_url`, pass it to `download_with_fallback` as `pdfUrl`; the project-local patch tries that URL before source-native and repository fallback stages.
- For a downloaded PDF, extract text with the pinned project environment: `uv run python <extraction-script-or-inline-code>` from the project root (the project venv pins `pypdf`; `uv run` inside the project root always resolves it — do not use `uv run --with`, ad-hoc installs, or ad-hoc dependency downloads). Read methods, data, findings, limitations, and the exact connection to the configured task.
- Mark `reading_depth` as `full_text`, `substantial_excerpt`, or `abstract_only`. Never present abstract-only assessment as full-text reading.
- Drop or rerank a candidate if deeper reading disproves relevance or quality.

### 6. Select recommendations

- Select no more than `recommend_limit` (default 5).
- Do not pad the email with weak or duplicate papers. Sending fewer, including zero, is valid.
- Verify title, authors, year, venue/status, DOI or stable URL, and publication/preprint status.
- Write `selected.jsonl` in normalized paper-record format with screening, score, reading depth, and concise recommendation fields.

### 7. Deliver through Gmail

Read `references/delivery-cli.md` for the exact commands, exit codes, and `run.json` fields. Ship this order and never reorder it: **send → record history as `pending` → label → verify → mark `applied`.**

- Read `references/email-template.md` and compose one plain-text or simple HTML email.
- Send to `me` unless the task specifies an exact recipient. The CLI resolves `me` to the authenticated account itself.
- Pass `--from "<delivery.sender_name>"` so the inbox shows the configured name; the authenticated Gmail account remains the actual sender address.
- Sign with `delivery.signature`; the authenticated Gmail account remains the actual sender address.
- Send exactly one status email for every invocation, including when zero papers survive screening or all candidates were previously recommended. Never suppress the email because a prior invocation already sent one.
- Include the run scope and counts, then structured entries for every selected paper.
- Send with `scripts/gmail_delivery.py send`. A non-zero exit means nothing was emailed: do not mark recommendations delivered and do not write history rows.
- After a successful send, immediately write delivered recommendation history with `scripts/history.py record-delivery` and `--label-status pending`.
- Resolve the post-send label only from the parsed `delivery.gmail_label` value (default `Literature recommendations`). Treat that value as exact: never substitute an existing, similar, default, or user-mentioned label name.
- Apply that exact configured label to the sent message with `scripts/gmail_delivery.py label`, which matches the name exactly, creates the label when absent, and verifies the write. Do not apply an additional fallback label.
- Record both `gmail_label_expected` and `gmail_label_applied` in `run.json`; do not infer success merely from a generic label-write response or from the CLI's own success line.
- Only after exact-label verification succeeds, flip the run/history record to `label_status=applied` with `scripts/history.py mark-label-status`. If creation, application, or verification fails, preserve `delivery_status=delivered`, keep `label_status=pending`, and do not resend the email on retry: re-run only the label step (see `references/contracts.md`).
- If sending fails, do not mark recommendations delivered.

### 8. Finish the run

- Save counts for searched, deduplicated, screened, expanded, read by depth, selected, delivered, and failures.
- Report completed delivery, exact subject, recipient, label status, and capability limitations without exposing message IDs, secrets, or private configuration.

## State commands

Filter already delivered recommendations:

```powershell
python .agents/skills/daily-literature-recommendations/scripts/history.py filter-new --history data/<task-id>/state/recommendations.jsonl --input candidates.jsonl --output new-candidates.jsonl --task-id <task-id>
```

Record a successful delivery:

```powershell
python .agents/skills/daily-literature-recommendations/scripts/history.py record-delivery --history data/<task-id>/state/recommendations.jsonl --input selected.jsonl --task-id <task-id> --run-key <run-key> --email-subject "<subject>" --gmail-label "<configured-gmail-label>" --label-status pending
```

Flip a delivery to `label_status=applied` once the label is verified (this is the only command that may update a delivered row, and it never resends):

```powershell
python .agents/skills/daily-literature-recommendations/scripts/history.py mark-label-status --history data/<task-id>/state/recommendations.jsonl --task-id <task-id> --run-key <run-key> --gmail-label "<configured-gmail-label>" --status applied
```

Send and file the email through the native delivery CLI:

```powershell
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py send --to me --from "<sender_name>" --subject "<subject>" --body-file <body-file>
python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py label --subject "<subject>" --label "<configured-gmail-label>"
```

Use `references/delivery-cli.md` for the full command set and exit codes, and `references/contracts.md` for paper/state fields and failure-state semantics.

## Hard boundaries

- Treat every scheduled-task trigger as a new run and send one report for it; do not implement email-level or calendar-day idempotency inside this skill.
- Do not send an email before completing the configured screening and reading work.
- Do not claim exhaustive or systematic coverage from a bounded recurring run.
- Do not recommend a paper only because it is highly cited or keyword-matched.
- Do not repeat a delivered paper unless the task explicitly enables update recommendations and the new version materially changes the evidence.
- Do not fabricate bibliographic data, access status, reading depth, findings, or limitations.
- Do not let one failed source or PDF block independent candidates; log the failure and continue.
