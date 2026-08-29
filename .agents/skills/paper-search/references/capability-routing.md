# Capability Routing Reference

Use this reference when mapping a user literature request to one of the five main `paper-search` workflow capabilities.

## Functional Map

| User Intent | Capability | Preferred Entrypoint | Boundary |
|---|---|---|---|
| Search papers, find related work, verify DOI/PMID, screen literature | `metadata_search` | `paper-search search` integrated entrypoint / `paper-search run search_*` precise tool entrypoint | Returns and verifies paper metadata only; Sci-Hub is not a search source |
| Expand citation graph for a known paper | `citation_expansion` | `paper-search run get_paper_citations` / `paper-search run get_paper_references` | Requires a known `paperId`, DOI, or arXiv ID; returns citing papers or cited references, not general keyword search |
| Query impact factor, JCR/SSCI/CAS quartiles, JCI, ESI, warnings, journal rank | `journal_metrics` | `paper-search journal-metrics` / `paper-search run query_journal_metrics` | Journal-level lookup, not paper search; requires `EASYSCHOLAR_KEY` |
| Get or download a verified paper PDF | `pdf_discovery` | `paper-search download` / `paper-search run download_with_fallback` | Verify identity before download; Sci-Hub is the default enabled final fallback |
| Find Methods text, parameters, software, models, or statistical wording in body snippets | `body_snippet_search` | `paper-search run search_semantic_snippets` | Searches Semantic Scholar OA snippet index; requires `SEMANTIC_SCHOLAR_API_KEY`; not full-text parsing |

## Workflow Boundaries

Open-ended literature tasks use the Two-Stage Paper Workflow:

1. Run `metadata_search`: build and verify a paper list with title, authors, year, journal/source, DOI, PMID/PMCID, URL, abstract clues, and relevance.
2. Run `pdf_discovery` only after the user confirms selected papers or the task explicitly requires PDFs. Record failed downloads without blocking other items.

Direct Paper Requests may skip broad discovery when the user provides a DOI, PMID, PMCID, arXiv ID, or already verified paper list. The target identity still needs verification before download.

Do not fabricate PMID, DOI, title, author, journal, or year from model memory. Important citations should include the supported claim, title, authors, journal/source, year, DOI or PMID when available, and a stable URL.

## Metadata Search

Use `metadata_search` for finding papers, expanding keywords, literature screening, and verifying DOI/PMID/PMCID/arXiv ID.

`paper-search search` is the integrated metadata entrypoint:

- use `--platform NAME` for one source
- use `--sources a,b,c` for explicit multi-source search
- use `--platform all` or `--sources all` only when broad recall matters more than precision

It does not call `citation_expansion`, `journal_metrics`, `pdf_discovery`, or `body_snippet_search`.

```bash
paper-search search "machine learning" --platform crossref --max-results 5 --pretty
paper-search search "osteoarthritis occupational exposure" --platform pubmed --max-results 10 --pretty
paper-search search "transformer attention mechanism" --sources arxiv,semantic,crossref --max-results 5 --pretty
paper-search search "causal inference target trial emulation" --sources all --max-results 5 --pretty
```

Precise tool entrypoints:

```bash
paper-search run search_pubmed --arg query="osteoarthritis occupational exposure" --arg maxResults=10 --pretty
paper-search run search_openalex --arg query="causal inference target trial emulation" --arg maxResults=5 --pretty
paper-search run get_paper_by_doi --arg doi="10.xxxx/xxxxx" --pretty
```

Do not treat `search_scihub` as a search source. It is DOI/URL-targeted lookup, not `metadata_search`.

## Citation Expansion

Use `citation_expansion` when the user has a known paper and asks which papers cite it or which references it cites.

```bash
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --arg limit=5 --pretty
paper-search run get_paper_references --arg doi="10.1038/nature12373" --arg limit=5 --pretty
```

Target priority is `paperId` > `doi` > `arxivId`. This capability uses Semantic Scholar Graph API and is separate from keyword-based `metadata_search`.

## Journal Metrics

Use `journal_metrics` for journal-level metrics: impact factor, JCR/SSCI quartiles, CAS quartiles, JCI, ESI, warnings, and rank.

```bash
paper-search journal-metrics "Nature" "BMJ" --pretty
paper-search journal-metrics --file journals.txt --include-raw --pretty
paper-search run query_journal_metrics --json-args '{"journals":["Nature"],"includeRaw":true}' --pretty
```

`journal_metrics` requires `EASYSCHOLAR_KEY`. If missing, tell the user to configure it locally:

```bash
paper-search setup EASYSCHOLAR_KEY
```

For batch journal lookups, prefer one `journal-metrics` call with multiple journal names or `--file`; do not run parallel EasyScholar requests.

## PDF Discovery

Use `pdf_discovery` to get an already verified paper PDF. For open-ended literature tasks, do not begin with batch downloads.

```bash
paper-search download 2301.12345 --platform arxiv --save-path ./downloads --pretty
paper-search run download_paper --arg paperId="10.xxxx/xxxxx" --arg platform=springer --arg savePath="./downloads" --pretty
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title","pdfUrl":"https://example.org/paper.pdf","savePath":"./downloads"}' --pretty
```

`download_with_fallback` order:

1. caller-supplied `pdfUrl`, when provided
2. source-native download
3. metadata PDF URL
4. repository discovery through PMC, Europe PMC, CORE, OpenAIRE
5. Unpaywall DOI resolution
6. Sci-Hub as the final fallback

Sci-Hub Fallback is enabled by default. To suppress that final stage for one request:

```bash
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title","pdfUrl":"https://example.org/paper.pdf","savePath":"./downloads","useSciHub":false}' --pretty
```

PDF source groups:

- `open_access_sources`: arXiv, bioRxiv, medRxiv, PMC, Europe PMC, CORE, OpenAIRE, Unpaywall, OpenAlex OA metadata, Semantic Scholar openAccessPdf, publisher open-access modes, IACR
- `entitled_access_sources`: Web of Science, ScienceDirect, Scopus, Springer, IEEE, Wiley TDM, or other sources requiring user keys, subscriptions, TDM tokens, or institutional entitlements
- `scihub_sources`: Sci-Hub, separately identified as the default enabled final fallback; not OA and not entitled access

## Body Snippet Search

Use `body_snippet_search` to find Methods wording, parameters, software names, model descriptions, statistical analysis text, or similar body-snippet clues.

```bash
paper-search run search_semantic_snippets --arg query="comparative risk assessment methods uncertainty propagation" --arg limit=5 --arg fieldsOfStudy=Medicine --pretty
```

`search_semantic_snippets` requires `SEMANTIC_SCHOLAR_API_KEY` and uses `limit`, not `maxResults`.

Only results with `snippetKind="body"` can be used as body-snippet evidence. Results from `title` or `abstract` are clues only. Before quoting or relying on a snippet, verify title, authors, year, journal/source, DOI or PMID.

## Platform Selection

| Task | First Choice | Supplements |
|---|---|---|
| Biomedical, clinical, pharmaceutical, public health | `pubmed` | `pmc`, `europepmc`, `semantic`, `crossref` |
| Methods/body snippet clues | `search_semantic_snippets` | Use `pubmed`/`semantic` first for titles and synonyms |
| Citation graph expansion | `get_paper_citations`, `get_paper_references` | Use only after a target paper identifier is known |
| Computer science, AI, math, physics | `arxiv` | `semantic`, `crossref`, `openalex` |
| CS bibliographies and conference metadata | `dblp` | `acm`, `usenix`, `openreview`, `ieee` requires key |
| Cross-disciplinary coverage | `crossref` | `openalex`, `semantic` |
| Open-access full-text discovery | `pmc`, `europepmc`, `core`, `openaire`, `unpaywall` | `download_with_fallback` |
| Journal IF/quartiles/rank | `journal-metrics` | `query_journal_metrics` |
| Cryptography | `iacr` | `arxiv` |
| Citation-count sorting | `semantic`, `crossref`, `openalex` | `webofscience`, `scopus` require keys |
| Exact Google Scholar results in scheduled runs | `googlescholar` with `SERPAPI_API_KEY` | Without a managed key, prefer `openalex`; direct Scholar HTML is best-effort only |
| Publisher or paid databases | `webofscience`, `ieee`, `scopus`, `sciencedirect`, `springer`/`springerlink`, `wiley` | Use only when key is configured |

For this project-local runtime, `googlescholar` automatically uses the managed SerpApi Google Scholar backend when `SERPAPI_API_KEY` is configured. Set `PAPER_SEARCH_GOOGLE_SCHOLAR_BACKEND=serpapi` for scheduled runs to disable direct-HTML fallback and fail clearly when the key is missing. Store both values only in local environment/configuration, never in task YAML or run artifacts.

## Query Construction

- Translate Chinese research questions into English keywords by default.
- Use 3-8 core concept terms rather than long sentences.
- For medical topics, include MeSH or standard terminology when useful.
- For method details, include software names, parameter names, model names, or section words such as `methods`, `statistical analysis`, `adjusted for`, `bootstrap`, `sensitivity analysis`.
