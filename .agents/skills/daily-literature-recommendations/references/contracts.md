# Data and state contracts

## Normalized paper record

Required fields after normalization:

```json
{
  "canonical_id": "doi:10.xxxx/example",
  "title": "Paper title",
  "normalized_title": "paper title",
  "authors": ["First Author"],
  "year": 2026,
  "venue": "Journal or repository",
  "doi": "10.xxxx/example",
  "arxiv_id": "",
  "url": "https://doi.org/10.xxxx/example",
  "pdf_url": "",
  "abstract": "...",
  "sources": ["crossref", "openalex"],
  "cited_by_count": 0,
  "screening": {"status": "unscreened", "reason": ""}
}
```

The normalizer also emits LitReview-compatible aliases such as `id`, `author_count`, `publisher`, `referenced_works`, `related_works`, `source_stage`, and `source_query`.

## Selected recommendation fields

Before email delivery, add:

```json
{
  "score": {
    "relevance": 0,
    "novelty": 0,
    "evidence": 0,
    "provenance": 0,
    "access": 0,
    "total": 0
  },
  "reading_depth": "full_text|substantial_excerpt|abstract_only",
  "task_relationship": "...",
  "research_question": "...",
  "method_and_data": "...",
  "key_findings": "...",
  "recommendation_reason": "...",
  "limitations": "..."
}
```

## Recommendation history

`data/<task-id>/state/recommendations.jsonl` contains one row per delivered paper for that task:

```json
{
  "task_id": "task-name",
  "run_key": "task-name:2026-08-19T09-00-00",
  "canonical_id": "doi:10.xxxx/example",
  "normalized_title": "paper title",
  "title": "Paper title",
  "recommended_at": "2026-08-19T09:00:00-07:00",
  "email_subject": "[每日文献推荐] ... | 2026-08-19 09:00",
  "delivery_status": "delivered",
  "gmail_label": "Literature recommendations",
  "label_status": "pending|applied|failed"
}
```

Keep the `task_id` field even though the file is task-local, and reject rows belonging to a different task as a layout error. Treat either matching canonical ID or matching normalized title as already delivered. A later paper version may be recommended again only when the task enables updates and the agent documents a material change.

## Failure states

- Search/source failure: log it and continue independent sources.
- Paper access failure: set reading depth honestly; do not infer full-text evidence.
- Gmail send failure: do not append delivered paper history.
- Gmail send success plus label failure: append history with `delivery_status=delivered` and `label_status=pending`; retry labeling without resending.
- Every scheduled-task trigger is an independent invocation. Never inspect existing Gmail subjects to suppress it; send a zero-result report when there are no new recommendations.

## Delivery-state transitions

`send → record-delivery (pending) → label → verify-label → mark-label-status (applied)`.

`mark-label-status` is the only command allowed to update an already delivered row,
and it refuses to run when no delivered row matches the `--task-id`, `--run-key`,
and `--gmail-label` triple. Use it only after the exact label is verified present
on the sent message; a failed or skipped verification leaves `pending`.

The retry for a `pending` row addresses the already-sent message by its exact
recorded `email_subject` (`gmail_delivery.py label --run-json <run.json>` or
`--subject "<subject>"`), so Gmail message IDs never have to be persisted. A
retry must not send a second email.

See `references/delivery-cli.md` for commands, exit codes, and troubleshooting.
