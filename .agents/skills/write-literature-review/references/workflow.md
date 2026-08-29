# Iterative Literature Review Workflow

## Intent

This workflow is optimized for topic-centered literature review, not one-shot keyword search. The goal is to keep expanding and screening until the relevant graph of papers stabilizes.

Keep a separate running log at `logs/workflow_log.md` from the beginning of the review. This is not optional bookkeeping. It is the audit trail for what the agent actually did, what the agent found, and why the next decision was made.

For the expected log structure, use `references/workflow_logging.md`.

## Step 0: Clarify Scope

Before searching, define the review scope and write it to `plan/review_plan.md`.

Record:

- topic
- research questions
- target field, venue, or domain if known
- time window, if constrained
- inclusion criteria
- exclusion criteria
- desired review type
- output directory or workspace path

Also clarify which citation format the user wants for the final review.

Supported options:

- APA
- MLA
- Chicago Author-Date
- Harvard
- IEEE
- Vancouver

If the user does not choose one of these supported formats, default to APA.

Log after this step:

- scope assumptions
- chosen citation format, or that APA was selected as the default
- any missing constraints supplied by judgment rather than the user
- the practical search boundary implied by the scope

## Step 1: Draft Search Keywords

Draft no more than 10 keywords from the user's topic.

Guidelines:

- Prefer short noun phrases.
- Include synonyms, method terms, and domain variants only when they materially increase recall.
- Avoid full question sentences.
- Avoid padding the list just to reach 10.

Good keyword list properties:

- High recall.
- Low redundancy.
- Faithful to the user's actual topic rather than a nearby trend.

Log after this step:

- the final keyword list
- discarded keyword ideas if they materially affected the search strategy
- why the final list is expected to give high recall

## Step 2: Build the Seed Set

Use `scripts/lit_review_pipeline.py search`.

The intended query behavior is:

- search OpenAlex works
- constrain matching to title and abstract
- keep the union across all drafted keywords
- retain metadata needed for later expansion and ranking

Operational notes:

- `--openalex-api-key` is recommended for reliable OpenAlex usage.
- `--email` is recommended for contactability and courteous API usage.
- Save the drafted keywords in `search/seed_keywords.json`.
- Save the initial result set in `search/seed_candidates.jsonl`.

Log after this step:

- exact search command or parameter pattern used
- number of seed records retrieved
- any year or scope filters applied
- any API failure, retry, or limitation encountered

## Step 3: Expand by Backward and Forward Citations

Use `scripts/lit_review_pipeline.py expand`.

Expansion behavior:

- backward: include all works referenced by each filtered frontier paper
- forward: include all works that cite each filtered frontier paper
- keep only title-and-abstract level metadata at this stage

Important:

- Expansion is driven from `screening/filtered_candidates.jsonl`, not from every candidate ever seen.
- New records should land in `screening/screening_queue.jsonl`.
- Already visited titles should be blocked by `screening/visited_titles.jsonl`.

Log after each expansion round:

- which filtered frontier file was used
- how many backward candidates were added
- how many forward candidates were added
- how many duplicates or already-visited titles were removed
- how many new records entered the screening queue

## Step 4: Deduplicate

Use `scripts/lit_review_pipeline.py dedupe` when needed, though `search` and `expand` already deduplicate their outputs.

Deduplication priority:

1. DOI
2. normalized title
3. metadata enrichment from duplicates, when present

The objective is a unique article list, not a perfect entity-resolution system.

Log after deduplication:

- input count
- output unique count
- approximate number removed as duplicates
- any obvious data-quality problems discovered

## Step 5: Screen with the LLM

At this stage, only use title and abstract.

The LLM should:

- review every record in `screening/screening_queue.jsonl`
- keep only papers relevant to the review scope
- update or produce `screening/filtered_candidates.jsonl`
- preserve a separate visited-title memory through `screening/visited_titles.jsonl`

Suggested screening prompt:

```text
You are screening candidate papers for a literature review.
Use only the review scope, title, and abstract.
For each paper, classify it as include or exclude.
Include papers that are clearly relevant or plausibly important to the topic.
Exclude only when the mismatch is clear.
Do not rely on outside knowledge not present in the candidate metadata.
```

When to stop:

- no new records appear in `screening/screening_queue.jsonl`, or
- a new round adds records but none survive screening

This is the saturation condition for the iterative search loop.

Log after each screening round:

- queue size reviewed
- number included
- number excluded
- common exclusion patterns
- notable borderline or difficult calls

## Step 6: Rank the Final Filtered Set

Use `scripts/lit_review_pipeline.py rank`.

The ranking is heuristic and should support prioritization, not replace scholarly judgment.

Current ranking signals:

- citation count
- source or publisher presence
- author count

Use the rank to decide:

- which papers are core references
- which papers deserve full-text reading first
- which papers are likely background rather than central evidence

Log after ranking:

- final filtered set size
- top-ranked papers selected for deeper reading
- any ranking caveats or adjustments made by judgment

## Step 7: Read Up to 30 Full Texts

Use `scripts/lit_review_pipeline.py fulltext`.

Rules:

- inspect no more than 30 full texts unless the user explicitly asks for more
- prioritize top-ranked papers
- be honest about access gaps
- summarize only the concepts, claims, methods, and limitations most relevant to the user's topic

This stage converts the filtered metadata set into a grounded reference list.

Log after full-text reading:

- which papers were actually accessed
- which papers were unavailable
- the main concepts, methods, claims, or limitations extracted
- any papers dropped or deprioritized after deeper reading

## Step 8: Build the Knowledge Graph

Produce two layers:

1. `graph/knowledge_graph.md`
2. `graph/knowledge_graph.json`

Then build the rendered graph artifact with:

```bash
python /path/to/write-literature-review/scripts/build_knowledge_graph.py \
  --workspace review_workspace
```

The text version should be readable by a human reviewer and should explicitly connect:

- concepts
- methods
- datasets
- claims
- limitations
- gaps
- supporting reference IDs

The structured JSON should be suitable for downstream visualization.

Log after graph construction:

- number of paper nodes
- number of concept nodes
- number of edges
- the most central concepts or clusters

## Step 9: Write the Literature Review

Use `references/review_writing.md`.

The review must:

- cite only the final included references
- distinguish evidence from synthesis
- organize by themes, mechanisms, evidence, and disagreements
- explicitly state limits and blind spots

Use the citation format selected in Step 0. If no supported format was chosen, use APA. Follow the examples in `references/citation format/`.

After the markdown draft in `review/literature_review.md` is ready, render the root delivery file `literature_review.pdf` with `scripts/lit_review_pipeline.py render-review`.

Log after writing:

- which sections were completed
- which claims required the strongest evidence
- unresolved weaknesses or missing evidence
- final corpus size cited in the review

## Expected Workspace Files

- `literature_review.pdf`
- `references.md`
- `knowledge_graph.png`
- `plan/review_plan.md`
- `logs/workflow_log.md`
- `search/seed_keywords.json`
- `search/seed_candidates.jsonl`
- `search/candidates.jsonl`
- `search/deduped_candidates.jsonl`
- `expansion/expanded_candidates.jsonl`
- `screening/screening_queue.jsonl`
- `screening/visited_titles.jsonl`
- `screening/filtered_candidates.jsonl`
- `screening/screening_log.csv`
- `references/ranked_references.jsonl`
- `references/ranked_references.md`
- `fulltext/fulltext_hits.json`
- `review/literature_review.md`
- `graph/knowledge_graph.md`
- `graph/knowledge_graph.json`
- `graph/knowledge_graph.dot`

## Iteration Rules

- Use `screening/screening_queue.jsonl` as the next batch to screen.
- Use `screening/filtered_candidates.jsonl` as the current relevant frontier and cumulative included set for expansion.
- Keep `screening/visited_titles.jsonl` as the visited-title boundary across all rounds.
- Do not cite or rely on papers outside the final filtered set.
- Stop expansion when a new round produces no newly relevant papers.
