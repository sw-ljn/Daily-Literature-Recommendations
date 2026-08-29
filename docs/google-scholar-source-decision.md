# Google Scholar source decision

## Decision

Direct Google Scholar HTML scraping is not suitable as the primary unattended source. Google Scholar does not provide an official bulk-search API and explicitly tells automated clients that are blocked to respect `robots.txt`. The current `paper-search-cli` adapter fetches Scholar HTML directly, so HTTP 429 and CAPTCHA/anti-bot failures remain expected even with delays.

If exact Google Scholar results and ranking are required, use a managed Google Scholar SERP provider behind the existing logical `googlescholar` source name. SerpApi is the preferred candidate for this project because it exposes a dedicated `engine=google_scholar` endpoint, structured JSON organic results, pagination, caching, and a free tier that currently covers 250 successful searches per month. The current smoke task uses two queries per run, so that tier is sufficient for one daily task with headroom.

The project-local compatibility patch now supports SerpApi behind the existing logical `googlescholar` source name. It activates only when the user creates an account, accepts its terms, and configures a private `SERPAPI_API_KEY` locally. Never place that key in task YAML, Skill files, logs, or recommendation history. Setting `PAPER_SEARCH_GOOGLE_SCHOLAR_BACKEND=serpapi` disables direct-HTML fallback for scheduled runs.

If a third-party SERP service is not desired, use OpenAlex as the primary programmatic discovery source and retain Crossref, Scopus, arXiv, and repository sources for corroboration. OpenAlex is stable and structured but is not an exact substitute for Google Scholar ranking or coverage.

## Candidate comparison

| Candidate | Exact Google Scholar results | Structured API | Current low-volume fit | Decision |
|---|---:|---:|---:|---|
| Direct Scholar HTML | Yes | No | Poor; recurring 429 risk | Reject for unattended primary use |
| SerpApi Google Scholar API | Yes | Yes | Good; 250 searches/month free tier | Preferred exact-result backend |
| Bright Data SERP API | Not clearly documented for Scholar-specific results | Yes | More infrastructure than this task needs | Secondary candidate |
| OpenAlex | No | Yes | Excellent and open | Preferred no-SERP alternative |

## Integration contract

`googlescholar` selects the managed backend only when `SERPAPI_API_KEY` is configured. The adapter returns the existing normalized paper fields, preserves the logical source name, redacts the key from errors, uses provider caching, and fails clearly without falling back to direct HTML scraping when scheduled runs set the managed-only backend flag.
