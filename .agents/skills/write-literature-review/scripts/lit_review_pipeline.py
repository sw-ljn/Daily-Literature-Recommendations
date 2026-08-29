#!/usr/bin/env python3
"""Search, expand, rank, and retrieve literature-review candidate corpora."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


OPENALEX_WORKS = "https://api.openalex.org/works"
CORE_SEARCH = "https://api.core.ac.uk/v3/search/works/"


def workspace_path(workspace: Path, *parts: str) -> Path:
    return workspace.joinpath(*parts)


def request_json(url: str, headers: dict[str, str] | None = None, retries: int = 3) -> dict[str, Any]:
    headers = headers or {}
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": "write-literature-review-skill", **headers})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            words.append((position, word))
    return " ".join(word for _, word in sorted(words))


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def normalize_work(raw: dict[str, Any], source_stage: str, source_query: str = "", parent_id: str = "") -> dict[str, Any]:
    authors = []
    for item in raw.get("authorships") or []:
        author = item.get("author") or {}
        if author.get("display_name"):
            authors.append(author["display_name"])
    primary_location = raw.get("primary_location") or {}
    source = (primary_location.get("source") or {}).get("display_name") or raw.get("host_venue", {}).get("display_name") or ""
    publisher = (
        (primary_location.get("source") or {}).get("host_organization_name")
        or (primary_location.get("source") or {}).get("host_organization_lineage_names", [""])[0]
        or ""
    )
    concepts = [c.get("display_name") for c in raw.get("concepts", []) if c.get("display_name")]
    keywords = [k.get("display_name") for k in raw.get("keywords", []) if k.get("display_name")]
    return {
        "id": raw.get("id", ""),
        "doi": raw.get("doi", ""),
        "title": raw.get("title") or raw.get("display_name") or "",
        "normalized_title": normalize_title(raw.get("title") or raw.get("display_name") or ""),
        "year": raw.get("publication_year"),
        "authors": authors,
        "author_count": len(authors),
        "venue": source,
        "publisher": publisher,
        "abstract": abstract_from_inverted_index(raw.get("abstract_inverted_index")),
        "concepts": concepts,
        "keywords": keywords,
        "open_access": raw.get("open_access") or {},
        "referenced_works": raw.get("referenced_works") or [],
        "related_works": raw.get("related_works") or [],
        "cited_by_count": raw.get("cited_by_count"),
        "source_stage": source_stage,
        "source_query": source_query,
        "parent_id": parent_id,
        "screening": {"status": "unscreened", "reason": ""},
    }


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def resolve_path(workspace: Path, path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else workspace / path


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def strip_markdown_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def markdown_to_pdf_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            blocks.append({"type": "spacer", "text": ""})
            continue
        header_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if header_match:
            level = len(header_match.group(1))
            text = strip_markdown_inline(header_match.group(2))
            blocks.append({"type": "heading", "level": level, "text": text})
            continue
        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet_match:
            blocks.append({"type": "bullet", "text": strip_markdown_inline(bullet_match.group(1))})
            continue
        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered_match:
            blocks.append({"type": "bullet", "text": strip_markdown_inline(ordered_match.group(1))})
            continue
        if re.fullmatch(r"-{3,}", stripped):
            blocks.append({"type": "spacer", "text": ""})
            continue
        blocks.append({"type": "paragraph", "text": strip_markdown_inline(stripped)})
    return blocks


def wrap_text_for_pdf(text: str, width: int) -> list[str]:
    wrapped: list[str] = []
    current = ""
    for word in text.split():
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                wrapped.append(current)
            current = word
    if current:
        wrapped.append(current)
    return wrapped or [""]


def layout_pdf_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    laid_out: list[dict[str, Any]] = []
    for block in blocks:
        block_type = block["type"]
        if block_type == "spacer":
            laid_out.append({"text": "", "font": "F1", "size": 11, "leading": 10})
            continue
        if block_type == "heading":
            level = block.get("level", 2)
            font_size = {1: 22, 2: 18, 3: 15, 4: 13}.get(level, 12)
            width = max(30, int(100 - level * 6))
            wrapped = wrap_text_for_pdf(block["text"], width)
            for index, line in enumerate(wrapped):
                laid_out.append(
                    {
                        "text": line,
                        "font": "F2",
                        "size": font_size,
                        "leading": font_size + (8 if index == len(wrapped) - 1 else 4),
                    }
                )
            continue
        if block_type == "bullet":
            wrapped = wrap_text_for_pdf(block["text"], 84)
            for index, line in enumerate(wrapped):
                prefix = "• " if index == 0 else "  "
                laid_out.append({"text": prefix + line, "font": "F1", "size": 11, "leading": 15})
            continue
        wrapped = wrap_text_for_pdf(block["text"], 92)
        for index, line in enumerate(wrapped):
            laid_out.append({"text": line, "font": "F1", "size": 11, "leading": 15 if index == len(wrapped) - 1 else 13})
    return laid_out


def paginate_pdf_lines(lines: list[dict[str, Any]], page_height: int, top_margin: int, bottom_margin: int) -> list[list[dict[str, Any]]]:
    pages: list[list[dict[str, Any]]] = []
    current_page: list[dict[str, Any]] = []
    used_height = 0
    available_height = top_margin - bottom_margin
    for line in lines:
        needed = line["leading"]
        if current_page and used_height + needed > available_height:
            pages.append(current_page)
            current_page = []
            used_height = 0
        current_page.append(line)
        used_height += needed
    if current_page:
        pages.append(current_page)
    if not pages:
        pages.append([{"text": "(empty document)", "font": "F1", "size": 11, "leading": 15}])
    return pages


def write_simple_pdf(path: Path, title: str, blocks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page_width = 612
    page_height = 792
    left_margin = 54
    top_margin = 738
    bottom_margin = 54
    laid_out_lines = layout_pdf_blocks(blocks)
    pages = paginate_pdf_lines(laid_out_lines, page_height, top_margin, bottom_margin)

    objects: list[bytes] = []

    def add_object(body: str) -> int:
        objects.append(body.encode("latin-1", errors="replace"))
        return len(objects)

    font_regular = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    page_ids: list[int] = []
    content_ids: list[int] = []

    for page_lines in pages:
        y = top_margin
        stream_lines = ["BT"]
        first = True
        for line in page_lines:
            escaped = pdf_escape(line["text"] or " ")
            font_ref = "/F2" if line["font"] == "F2" else "/F1"
            if first:
                stream_lines.append(f"{font_ref} {line['size']} Tf")
                stream_lines.append(f"1 0 0 1 {left_margin} {y} Tm")
                stream_lines.append(f"({escaped}) Tj")
                first = False
            else:
                y -= line["leading"]
                stream_lines.append(f"{font_ref} {line['size']} Tf")
                stream_lines.append(f"1 0 0 1 {left_margin} {y} Tm")
                stream_lines.append(f"({escaped}) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines)
        content_id = add_object(f"<< /Length {len(stream.encode('latin-1', errors='replace'))} >>\nstream\n{stream}\nendstream")
        content_ids.append(content_id)
        page_ids.append(0)

    pages_obj_index = len(objects) + 1
    for idx, content_id in enumerate(content_ids):
        page_body = (
            f"<< /Type /Page /Parent {pages_obj_index} 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        page_ids[idx] = add_object(page_body)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    pages_obj = add_object(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>")
    catalog_obj = add_object(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>")
    info_obj = add_object(f"<< /Title ({pdf_escape(title)}) /Producer (LitReviewAI) >>")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("latin-1"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_obj} 0 R /Info {info_obj} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")
    )
    path.write_bytes(pdf)


def build_openalex_url(params: dict[str, str], email: str, api_key: str) -> str:
    params = dict(params)
    if email:
        params["mailto"] = email
    if api_key:
        params["api_key"] = api_key
    return OPENALEX_WORKS + "?" + urllib.parse.urlencode(params)


def title_key(row: dict[str, Any]) -> str:
    return normalize_title(row.get("title", "")) or row.get("normalized_title", "")


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        doi = (row.get("doi") or "").lower().replace("https://doi.org/", "").strip()
        title = title_key(row)
        row["normalized_title"] = title
        key = f"doi:{doi}" if doi else f"title:{title}"
        if key.endswith(":"):
            continue
        if key in seen:
            seen[key].setdefault("duplicate_sources", []).append(
                {"source_stage": row.get("source_stage"), "source_query": row.get("source_query"), "parent_id": row.get("parent_id")}
            )
            for field in ("abstract", "doi", "venue", "publisher"):
                if not seen[key].get(field) and row.get(field):
                    seen[key][field] = row[field]
            seen[key]["cited_by_count"] = max(seen[key].get("cited_by_count") or 0, row.get("cited_by_count") or 0)
            if row.get("authors") and not seen[key].get("authors"):
                seen[key]["authors"] = row["authors"]
                seen[key]["author_count"] = row.get("author_count", len(row["authors"]))
        else:
            seen[key] = row
    return list(seen.values())


def write_screening_csv(workspace: Path, rows: list[dict[str, Any]]) -> None:
    path = workspace_path(workspace, "screening", "screening_log.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "title", "year", "status", "reason", "source_stage", "source_query", "parent_id", "doi"],
        )
        writer.writeheader()
        for row in rows:
            screening = row.get("screening") or {}
            writer.writerow(
                {
                    "id": row.get("id", ""),
                    "title": row.get("title", ""),
                    "year": row.get("year", ""),
                    "status": screening.get("status", "unscreened"),
                    "reason": screening.get("reason", ""),
                    "source_stage": row.get("source_stage", ""),
                    "source_query": row.get("source_query", ""),
                    "parent_id": row.get("parent_id", ""),
                    "doi": row.get("doi", ""),
                }
            )


def write_visited_titles(workspace: Path, rows: list[dict[str, Any]]) -> None:
    title_rows = []
    seen = set()
    for row in rows:
        normalized = title_key(row)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        title_rows.append({"normalized_title": normalized, "title": row.get("title", "")})
    write_jsonl(workspace_path(workspace, "screening", "visited_titles.jsonl"), title_rows)


def load_keyword_list(args: argparse.Namespace) -> list[str]:
    keywords: list[str] = []
    if args.keyword:
        keywords.extend(args.keyword)
    if getattr(args, "keywords_file", ""):
        path = Path(args.keywords_file)
        keywords.extend([line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
    if not keywords and getattr(args, "topic", ""):
        keywords.append(args.topic)
    cleaned = []
    seen = set()
    for keyword in keywords:
        value = keyword.strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(value)
    return cleaned[:10]


def search_openalex_keywords(
    keywords: list[str],
    email: str,
    api_key: str,
    per_page: int,
    from_year: int | None,
    to_year: int | None,
    max_results_per_keyword: int,
) -> list[dict[str, Any]]:
    rows = []
    filters = []
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    if to_year:
        filters.append(f"to_publication_date:{to_year}-12-31")
    for keyword in keywords:
        cursor = "*"
        collected = 0
        while True:
            query_filters = list(filters)
            query_filters.append(f"title_and_abstract.search:{keyword}")
            params = {"filter": ",".join(query_filters), "per-page": str(per_page), "cursor": cursor, "sort": "cited_by_count:desc"}
            data = request_json(build_openalex_url(params, email, api_key))
            result_batch = data.get("results", [])
            for raw in result_batch:
                rows.append(normalize_work(raw, "seed", keyword))
                collected += 1
                if max_results_per_keyword and collected >= max_results_per_keyword:
                    break
            if max_results_per_keyword and collected >= max_results_per_keyword:
                break
            cursor = (data.get("meta") or {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(0.15)
    return rows


def fetch_openalex_ids(ids: list[str], email: str, api_key: str, stage: str, parent_id: str = "", max_results: int = 0) -> list[dict[str, Any]]:
    cleaned = [i.rsplit("/", 1)[-1] for i in ids if i]
    if max_results:
        cleaned = cleaned[:max_results]
    rows = []
    for chunk_start in range(0, len(cleaned), 100):
        chunk = cleaned[chunk_start : chunk_start + 100]
        params = {"filter": "openalex:" + "|".join(chunk), "per-page": str(len(chunk))}
        data = request_json(build_openalex_url(params, email, api_key))
        rows.extend(normalize_work(raw, stage, parent_id, parent_id) for raw in data.get("results", []))
        time.sleep(0.15)
    return rows


def forward_citations(openalex_id: str, email: str, api_key: str, max_results: int = 0, per_page: int = 100) -> list[dict[str, Any]]:
    work_id = openalex_id.rsplit("/", 1)[-1]
    rows = []
    cursor = "*"
    while True:
        params = {"filter": f"cites:{work_id}", "per-page": str(min(per_page, 100)), "cursor": cursor, "sort": "cited_by_count:desc"}
        data = request_json(build_openalex_url(params, email, api_key))
        result_batch = data.get("results", [])
        for raw in result_batch:
            rows.append(normalize_work(raw, "forward", openalex_id, openalex_id))
            if max_results and len(rows) >= max_results:
                return rows
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(0.15)
    return rows


def merge_unique_rows(existing_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return dedupe_rows(existing_rows + new_rows)


def heuristic_rank(row: dict[str, Any]) -> dict[str, Any]:
    citation_count = int(row.get("cited_by_count") or 0)
    author_count = int(row.get("author_count") or len(row.get("authors") or []))
    publisher_signal = 1 if row.get("publisher") or row.get("venue") else 0
    score = round((math.log1p(citation_count) * 10.0) + min(author_count, 10) + (publisher_signal * 3.0), 3)
    ranking = {
        "importance_score": score,
        "citation_count": citation_count,
        "author_count": author_count,
        "publisher_signal": publisher_signal,
    }
    enriched = dict(row)
    enriched["ranking"] = ranking
    return enriched


def write_ranked_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Ranked References", "", "| Rank | Title | Year | Citations | Authors | Venue | Publisher | Score |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for index, row in enumerate(rows, start=1):
        ranking = row.get("ranking") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    row.get("title", "").replace("|", "\\|"),
                    str(row.get("year", "")),
                    str(ranking.get("citation_count", 0)),
                    str(ranking.get("author_count", 0)),
                    row.get("venue", "").replace("|", "\\|"),
                    row.get("publisher", "").replace("|", "\\|"),
                    str(ranking.get("importance_score", "")),
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_search(args: argparse.Namespace) -> None:
    workspace = Path(args.out)
    keywords = load_keyword_list(args)
    if not keywords:
        raise SystemExit("Provide at least one --keyword, --keywords-file, or --topic.")
    workspace.mkdir(parents=True, exist_ok=True)
    workspace_path(workspace, "search").mkdir(parents=True, exist_ok=True)
    workspace_path(workspace, "screening").mkdir(parents=True, exist_ok=True)
    workspace_path(workspace, "search", "seed_keywords.json").write_text(
        json.dumps({"topic": args.topic, "keywords": keywords}, indent=2), encoding="utf-8"
    )
    seed_rows = dedupe_rows(
        search_openalex_keywords(
            keywords,
            args.email,
            args.openalex_api_key,
            args.per_page,
            args.from_year,
            args.to_year,
            args.max_results_per_keyword,
        )
    )
    merged = merge_unique_rows(iter_jsonl(workspace_path(workspace, "search", "candidates.jsonl")), seed_rows)
    write_jsonl(workspace_path(workspace, "search", "seed_candidates.jsonl"), seed_rows)
    write_jsonl(workspace_path(workspace, "screening", "screening_queue.jsonl"), seed_rows)
    write_jsonl(workspace_path(workspace, "search", "candidates.jsonl"), merged)
    write_jsonl(workspace_path(workspace, "search", "deduped_candidates.jsonl"), merged)
    write_visited_titles(workspace, merged)
    write_screening_csv(workspace, merged)
    print(f"wrote {len(seed_rows)} seed records from {len(keywords)} keywords; {len(merged)} unique records total")


def cmd_expand(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    input_path = resolve_path(workspace, args.input)
    frontier = dedupe_rows(iter_jsonl(input_path))
    workspace_path(workspace, "expansion").mkdir(parents=True, exist_ok=True)
    workspace_path(workspace, "screening").mkdir(parents=True, exist_ok=True)
    existing = dedupe_rows(
        iter_jsonl(workspace_path(workspace, "search", "deduped_candidates.jsonl"))
        or iter_jsonl(workspace_path(workspace, "search", "candidates.jsonl"))
    )
    visited_before = {
        row.get("normalized_title", "") for row in iter_jsonl(workspace_path(workspace, "screening", "visited_titles.jsonl"))
    }
    visited_before.update(title_key(row) for row in existing)
    expanded: list[dict[str, Any]] = []
    for seed in frontier:
        if args.backward:
            expanded.extend(
                fetch_openalex_ids(
                    seed.get("referenced_works", []),
                    args.email,
                    args.openalex_api_key,
                    "backward",
                    seed.get("id", ""),
                    args.backward_max_results,
                )
            )
        if args.forward and seed.get("id"):
            expanded.extend(
                forward_citations(
                    seed["id"],
                    args.email,
                    args.openalex_api_key,
                    max_results=args.forward_max_results,
                    per_page=args.per_page,
                )
            )
    expanded = dedupe_rows(expanded)
    screening_queue = [row for row in expanded if title_key(row) and title_key(row) not in visited_before]
    merged = merge_unique_rows(existing, screening_queue)
    write_jsonl(workspace_path(workspace, "expansion", "expanded_candidates.jsonl"), expanded)
    write_jsonl(workspace_path(workspace, "screening", "screening_queue.jsonl"), screening_queue)
    write_jsonl(workspace_path(workspace, "search", "candidates.jsonl"), merged)
    write_jsonl(workspace_path(workspace, "search", "deduped_candidates.jsonl"), merged)
    write_visited_titles(workspace, merged)
    write_screening_csv(workspace, merged)
    print(
        f"expanded {len(frontier)} frontier records into {len(expanded)} deduped candidates; "
        f"{len(screening_queue)} new records require screening"
    )


def cmd_dedupe(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    source_path = resolve_path(workspace, args.input)
    rows = dedupe_rows(iter_jsonl(source_path))
    output_path = resolve_path(workspace, args.output)
    write_jsonl(output_path, rows)
    if output_path.name in {"candidates.jsonl", "deduped_candidates.jsonl"}:
        write_visited_titles(workspace, rows)
        write_screening_csv(workspace, rows)
    print(f"wrote {len(rows)} deduped records to {output_path}")


def cmd_rank(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    source_path = resolve_path(workspace, args.input)
    rows = [heuristic_rank(row) for row in dedupe_rows(iter_jsonl(source_path))]
    rows.sort(key=lambda row: row.get("ranking", {}).get("importance_score", 0), reverse=True)
    ranked_jsonl = resolve_path(workspace, args.output_jsonl)
    ranked_md = resolve_path(workspace, args.output_md)
    write_jsonl(ranked_jsonl, rows)
    write_ranked_markdown(ranked_md, rows)
    print(f"ranked {len(rows)} references and wrote {ranked_jsonl} and {ranked_md}")


def cmd_fulltext(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    workspace_path(workspace, "fulltext").mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {args.core_api_key}"} if args.core_api_key else {}
    source_path = resolve_path(workspace, args.input)
    rows = dedupe_rows(iter_jsonl(source_path))
    fulltext_hits: dict[str, Any] = {}
    for row in rows[: args.limit]:
        query = row.get("doi") or row.get("title")
        if not query:
            continue
        url = CORE_SEARCH + "?" + urllib.parse.urlencode({"q": query, "limit": "3"})
        try:
            fulltext_hits[row.get("id", row.get("title", ""))] = {
                "query": query,
                "open_access_url": (row.get("open_access") or {}).get("oa_url", ""),
                "core_results": request_json(url, headers=headers),
            }
        except Exception as exc:
            fulltext_hits[row.get("id", row.get("title", ""))] = {
                "query": query,
                "open_access_url": (row.get("open_access") or {}).get("oa_url", ""),
                "error": str(exc),
            }
        time.sleep(args.delay)
    output_path = resolve_path(workspace, args.output)
    output_path.write_text(json.dumps(fulltext_hits, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote full-text discovery results for {len(fulltext_hits)} records to {output_path}")


def cmd_render_review(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    input_path = resolve_path(workspace, args.input)
    output_path = resolve_path(workspace, args.output)
    markdown = input_path.read_text(encoding="utf-8") if input_path.exists() else ""
    blocks = markdown_to_pdf_blocks(markdown)
    document_title = "Literature Review"
    for block in blocks:
        if block.get("type") == "heading" and block.get("level") == 1 and block.get("text"):
            document_title = block["text"]
            break
    write_simple_pdf(output_path, document_title, blocks)
    print(f"rendered review PDF to {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True)

    search = sub.add_parser("search")
    search.add_argument("--topic", default="")
    search.add_argument("--keyword", action="append", default=[])
    search.add_argument("--keywords-file", default="")
    search.add_argument("--out", required=True)
    search.add_argument("--email", default="")
    search.add_argument("--openalex-api-key", default="")
    search.add_argument("--per-page", type=int, default=100)
    search.add_argument("--from-year", type=int)
    search.add_argument("--to-year", type=int)
    search.add_argument(
        "--max-results-per-keyword",
        type=int,
        default=0,
        help="0 means no explicit cap; the script follows cursor pagination until OpenAlex is exhausted.",
    )
    search.set_defaults(func=cmd_search)

    expand = sub.add_parser("expand")
    expand.add_argument("--workspace", required=True)
    expand.add_argument("--input", default="screening/filtered_candidates.jsonl")
    expand.add_argument("--email", default="")
    expand.add_argument("--openalex-api-key", default="")
    expand.add_argument("--backward", action=argparse.BooleanOptionalAction, default=True)
    expand.add_argument("--forward", action=argparse.BooleanOptionalAction, default=True)
    expand.add_argument("--backward-max-results", type=int, default=0)
    expand.add_argument("--forward-max-results", type=int, default=0)
    expand.add_argument("--per-page", type=int, default=100)
    expand.set_defaults(func=cmd_expand)

    fulltext = sub.add_parser("fulltext")
    fulltext.add_argument("--workspace", required=True)
    fulltext.add_argument("--input", default="references/ranked_references.jsonl")
    fulltext.add_argument("--output", default="fulltext/fulltext_hits.json")
    fulltext.add_argument("--core-api-key", default="")
    fulltext.add_argument("--limit", type=int, default=30)
    fulltext.add_argument("--delay", type=float, default=1.0)
    fulltext.set_defaults(func=cmd_fulltext)

    dedupe = sub.add_parser("dedupe")
    dedupe.add_argument("--workspace", required=True)
    dedupe.add_argument("--input", default="search/candidates.jsonl")
    dedupe.add_argument("--output", default="search/deduped_candidates.jsonl")
    dedupe.set_defaults(func=cmd_dedupe)

    rank = sub.add_parser("rank")
    rank.add_argument("--workspace", required=True)
    rank.add_argument("--input", default="screening/filtered_candidates.jsonl")
    rank.add_argument("--output-jsonl", default="references/ranked_references.jsonl")
    rank.add_argument("--output-md", default="references/ranked_references.md")
    rank.set_defaults(func=cmd_rank)

    render_review = sub.add_parser("render-review")
    render_review.add_argument("--workspace", required=True)
    render_review.add_argument("--input", default="review/literature_review.md")
    render_review.add_argument("--output", default="literature_review.pdf")
    render_review.set_defaults(func=cmd_render_review)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
