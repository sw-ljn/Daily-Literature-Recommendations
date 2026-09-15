# Architecture: upstream projects and local orchestration

> This document expands on the README: upstream provenance, version pinning, and the local compatibility layer. For the reading path, start at [README.md](README.md).

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

When upgrading `paper-search-cli`, review the patch, refresh `.agents/skills/paper-search`, and rerun the full test suite.

## Runtime prerequisites (context)

- Node.js 18+ and [uv](https://docs.astral.sh/uv/) (Python 3.10+ is provisioned by `uv sync`);
- an Agent Skills-compatible agent able to trigger this project directory: Hermes, Codex, or Claude Code (Claude Code additionally uses the `npm run sync:skills` bridge, run automatically by `npm install`);
- an authorized Gmail account: complete the one-time OAuth setup once through the Hermes `google-workspace` skill so the token lands at `$HERMES_HOME/google_token.json`, then confirm it with `uv run python .agents/skills/daily-literature-recommendations/scripts/gmail_delivery.py auth-check --live`;
- any API keys or institutional access required by the selected literature sources.

`uv sync` creates the pinned project venv (`.venv/`, Python 3.10+) from `pyproject.toml` and `uv.lock` — currently `pypdf` for PDF text extraction; run every Python step through `uv run python ...` so the pinned environment always resolves. `.env.example` currently documents the managed SerpApi backend and the arXiv source timeout. Other providers can be enabled through `paper-search` configuration or environment variables.

You can also run the pinned health checks directly:

```bash
npx --no-install paper-search doctor --pretty
npx --no-install paper-search smoke --mock --pretty
```

Proceed when metadata search is available. Missing enhanced providers, publisher keys, or institutional entitlements are capability limits, not reasons to fail all independent sources.

## Core boundaries

- All commands use the project-pinned local runtime. Do not fall back to a user-global `paper-search` executable.
- Every run performs project commands and file operations on the local machine. Do not use a cloud shell.
- Gmail is used only to read the authenticated profile, send the report, apply the exact YAML-configured label, and read the message back to verify that label. All four go through `scripts/gmail_delivery.py`; no Gmail MCP server or connector is involved.
- If full text cannot be lawfully accessed, use `abstract_only` or `substantial_excerpt`; never claim that an abstract-only assessment is a full-text reading.
- API keys, cookies, account information, and other secrets belong only in the local `.env`, `paper-search` configuration, or environment variables. Never put them in task YAML, skills, run artifacts, or Git history.
- Download-source policy (including whether Sci-Hub may be used) is the user's decision, declared per task in the task YAML or the triggering prompt; this project imposes none.
