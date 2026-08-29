# Workflow Logging Guide

## Purpose

Use `logs/workflow_log.md` as the running audit trail for the full literature-review workflow.

The log should make it possible for another reviewer to answer:

- what the agent did
- in what order it happened
- what files or commands were used
- what each step produced
- what was learned
- why the next decision was made

## Required File

Write the log to:

- `logs/workflow_log.md`

Create the file near the beginning of the workflow and keep appending to it as work happens.

## Logging Rules

- Log every major workflow step.
- Log every expansion or screening round separately.
- Record counts whenever a step changes the candidate set.
- Record failures, retries, unavailable full text, and scope changes explicitly.
- Keep the log factual and auditable.
- Do not replace the log with a polished summary only. It should remain step-by-step.

## Minimum Fields Per Entry

Each entry should include:

- step number or stage name
- timestamp or round identifier when available
- action taken
- inputs used
- output files updated
- key result or counts
- decision or next action

## Suggested Template

```md
# Workflow Log

## Step 1 - Scope Setup
- Action: clarified review scope and created `plan/review_plan.md`
- Inputs: user topic, inclusion criteria, time window
- Outputs: `plan/review_plan.md`
- Result: finalized scope for the review
- Next: draft keyword list

## Step 2 - Keyword Drafting
- Action: drafted search keywords
- Inputs: topic statement and synonyms
- Outputs: `search/seed_keywords.json`
- Result: selected 8 keywords with high recall focus
- Notes: dropped 2 overly broad keywords because they caused topic drift
- Next: run seed search

## Step 3 - Seed Search
- Action: searched OpenAlex title and abstract fields
- Inputs: keyword set from `search/seed_keywords.json`
- Outputs: `search/seed_candidates.jsonl`, `search/candidates.jsonl`
- Result: 184 seed records retrieved, 161 unique after dedupe
- Next: screen seed set

## Step 4 - Screening Round 1
- Action: screened title and abstract of seed set
- Inputs: `search/seed_candidates.jsonl`
- Outputs: `screening/filtered_candidates.jsonl`, `screening/visited_titles.jsonl`
- Result: 161 screened, 54 included, 107 excluded
- Notes: common exclusion reasons were wrong domain and non-scholarly publication type
- Next: expand from filtered set

## Step 5 - Expansion Round 1
- Action: expanded by backward and forward citations
- Inputs: `screening/filtered_candidates.jsonl`
- Outputs: `expansion/expanded_candidates.jsonl`, `screening/screening_queue.jsonl`
- Result: 420 expanded records, 233 new unvisited candidates after dedupe
- Next: screen expansion queue
```

## End-of-Workflow Summary

End the log with a short final section containing:

- total number of search or expansion rounds
- total number of unique screened candidates
- final included reference count
- number of full texts actually read
- main themes discovered
- key limitations or blind spots

## Relationship to Final Outputs

The log is not the literature review itself.

Keep these separate:

- `logs/workflow_log.md`: operational audit trail
- `review/literature_review.md`: editable review draft
- `literature_review.pdf`: final root deliverable
