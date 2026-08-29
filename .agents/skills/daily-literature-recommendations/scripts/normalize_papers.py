#!/usr/bin/env python3
"""Normalize paper-search CLI JSON into deduplicated LitReview-compatible JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.rstrip(".,; ")


def normalize_arxiv(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text)
    text = re.sub(r"^arxiv:", "", text)
    text = re.sub(r"\.pdf$", "", text)
    return re.sub(r"v\d+$", "", text)


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def parse_extra(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def parse_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        authors = []
        for item in value:
            if isinstance(item, dict):
                author = item.get("name") or item.get("display_name") or (item.get("author") or {}).get("display_name")
                if author:
                    authors.append(str(author).strip())
            elif str(item).strip():
                authors.append(str(item).strip())
        return authors
    text = str(value or "").strip()
    if not text:
        return []
    separator = ";" if ";" in text else None
    return [part.strip() for part in text.split(separator) if part.strip()] if separator else [text]


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("papers", "results", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def canonical_id(doi: str, arxiv_id: str, title_key: str) -> str:
    if doi.startswith("10.48550/arxiv."):
        return f"arxiv:{normalize_arxiv(doi.split('arxiv.', 1)[1])}"
    if doi:
        return f"doi:{doi}"
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    digest = hashlib.sha256(title_key.encode("utf-8")).hexdigest()[:20]
    return f"title:{digest}"


def normalize_row(row: dict[str, Any], query: str, default_source: str = "") -> dict[str, Any] | None:
    title = str(row.get("title") or row.get("display_name") or "").strip()
    title_key = normalize_title(title)
    if not title_key:
        return None
    extra = parse_extra(row.get("extra"))
    doi = normalize_doi(row.get("doi"))
    paper_id = str(row.get("paper_id") or row.get("paperId") or row.get("id") or "").strip()
    if not doi and paper_id.lower().startswith("10."):
        doi = normalize_doi(paper_id)
    arxiv_id = normalize_arxiv(extra.get("arxivId") or row.get("arxiv_id") or "")
    if not arxiv_id and re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", paper_id.lower()):
        arxiv_id = normalize_arxiv(paper_id)
    if not arxiv_id and doi.startswith("10.48550/arxiv."):
        arxiv_id = normalize_arxiv(doi.split("arxiv.", 1)[1])
    source = str(row.get("source") or default_source or "unknown").strip().lower()
    authors = parse_authors(row.get("authors"))
    year = row.get("year")
    if year in (None, ""):
        match = re.match(r"(\d{4})", str(row.get("published_date") or ""))
        year = int(match.group(1)) if match else None
    venue = str(row.get("journal") or row.get("venue") or "").strip()
    publisher = str(extra.get("publisher") or row.get("publisher") or "").strip()
    url = str(row.get("url") or "").strip()
    if doi and not doi.startswith("10.48550/arxiv."):
        url = f"https://doi.org/{doi}"
    pdf_url = str(row.get("pdf_url") or row.get("pdfUrl") or "").strip()
    openalex_id = str(extra.get("openAlexId") or row.get("openalex_id") or "").strip()
    identifier = canonical_id(doi, arxiv_id, title_key)
    return {
        "canonical_id": identifier,
        "id": openalex_id or paper_id or identifier,
        "paper_id": paper_id,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "openalex_id": openalex_id,
        "title": title,
        "normalized_title": title_key,
        "year": year,
        "authors": authors,
        "author_count": len(authors),
        "venue": venue,
        "publisher": publisher,
        "abstract": str(row.get("abstract") or "").strip(),
        "url": url,
        "pdf_url": pdf_url,
        "sources": [source],
        "source_records": [{"source": source, "paper_id": paper_id, "url": str(row.get("url") or "").strip()}],
        "open_access": {"oa_url": pdf_url or url if pdf_url else ""},
        "referenced_works": row.get("referenced_works") or [],
        "related_works": row.get("related_works") or [],
        "cited_by_count": int(row.get("citation_count") or row.get("cited_by_count") or row.get("citationCount") or 0),
        "source_stage": "seed",
        "source_query": query,
        "parent_id": "",
        "screening": {"status": "unscreened", "reason": ""},
    }


def rank_identity(row: dict[str, Any]) -> tuple[int, int, int]:
    doi = str(row.get("doi") or "")
    published_doi = int(bool(doi) and not doi.startswith("10.48550/arxiv."))
    has_venue = int(bool(row.get("venue") or row.get("publisher")))
    has_abstract = int(bool(row.get("abstract")))
    return published_doi, has_venue, has_abstract


def merge_record(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    primary, secondary = (right, left) if rank_identity(right) > rank_identity(left) else (left, right)
    merged = dict(primary)
    for field in ("abstract", "doi", "arxiv_id", "openalex_id", "venue", "publisher", "url", "pdf_url"):
        if not merged.get(field) and secondary.get(field):
            merged[field] = secondary[field]
    if len(str(secondary.get("abstract") or "")) > len(str(merged.get("abstract") or "")):
        merged["abstract"] = secondary["abstract"]
    merged["authors"] = merged.get("authors") or secondary.get("authors") or []
    merged["author_count"] = len(merged["authors"])
    merged["sources"] = sorted(set((left.get("sources") or []) + (right.get("sources") or [])))
    seen_records: set[tuple[str, str, str]] = set()
    source_records = []
    for item in (left.get("source_records") or []) + (right.get("source_records") or []):
        key = (str(item.get("source") or ""), str(item.get("paper_id") or ""), str(item.get("url") or ""))
        if key not in seen_records:
            seen_records.add(key)
            source_records.append(item)
    merged["source_records"] = source_records
    merged["cited_by_count"] = max(int(left.get("cited_by_count") or 0), int(right.get("cited_by_count") or 0))
    merged["canonical_id"] = canonical_id(str(merged.get("doi") or ""), str(merged.get("arxiv_id") or ""), merged["normalized_title"])
    if merged.get("doi") and not str(merged["doi"]).startswith("10.48550/arxiv."):
        merged["url"] = f"https://doi.org/{merged['doi']}"
    return merged


def dedupe(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_title: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["normalized_title"]
        by_title[key] = merge_record(by_title[key], row) if key in by_title else row
    return sorted(by_title.values(), key=lambda item: (item.get("year") or 0, item.get("cited_by_count") or 0), reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--query", default="")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    default_source = ""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            default_source = str(data.get("provider") or "")
        default_source = default_source or str(payload.get("tool") or "")
    normalized = [item for raw in extract_rows(payload) if (item := normalize_row(raw, args.query, default_source))]
    unique = dedupe(normalized)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in unique:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"input_records": len(normalized), "unique_records": len(unique), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
