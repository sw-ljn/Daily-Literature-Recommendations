#!/usr/bin/env python3
"""Filter previously delivered papers and append per-invocation delivery history."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if isinstance(item, dict):
            rows.append(item)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def validate_task_ownership(history: list[dict[str, Any]], task_id: str, path: Path) -> None:
    mismatches = [
        (line_number, row.get("task_id"))
        for line_number, row in enumerate(history, start=1)
        if row.get("task_id") != task_id
    ]
    if mismatches:
        line_number, found_task_id = mismatches[0]
        raise SystemExit(
            f"History task mismatch at {path}:{line_number}: "
            f"expected task_id={task_id!r}, found {found_task_id!r}"
        )


def delivered_keys(history: list[dict[str, Any]], task_id: str) -> tuple[set[str], set[str]]:
    canonical_ids: set[str] = set()
    titles: set[str] = set()
    for row in history:
        if row.get("task_id") != task_id or row.get("delivery_status") != "delivered":
            continue
        if row.get("canonical_id"):
            canonical_ids.add(str(row["canonical_id"]))
        if row.get("normalized_title"):
            titles.add(str(row["normalized_title"]))
    return canonical_ids, titles


def filter_new(args: argparse.Namespace) -> int:
    history = read_jsonl(args.history)
    validate_task_ownership(history, args.task_id, args.history)
    papers = read_jsonl(args.input)
    canonical_ids, titles = delivered_keys(history, args.task_id)
    kept = [
        row
        for row in papers
        if str(row.get("canonical_id") or "") not in canonical_ids
        and str(row.get("normalized_title") or "") not in titles
    ]
    write_jsonl(args.output, kept)
    print(json.dumps({"input": len(papers), "already_delivered": len(papers) - len(kept), "new": len(kept), "output": str(args.output)}, ensure_ascii=False))
    return 0


def record_delivery(args: argparse.Namespace) -> int:
    history = read_jsonl(args.history)
    validate_task_ownership(history, args.task_id, args.history)
    papers = read_jsonl(args.input)
    existing = {
        (str(row.get("task_id") or ""), str(row.get("run_key") or ""), str(row.get("canonical_id") or ""))
        for row in history
    }
    timestamp = args.recommended_at or datetime.now().astimezone().isoformat(timespec="seconds")
    appended = 0
    for paper in papers:
        key = (args.task_id, args.run_key, str(paper.get("canonical_id") or ""))
        if key in existing:
            continue
        history.append(
            {
                "task_id": args.task_id,
                "run_key": args.run_key,
                "canonical_id": paper.get("canonical_id", ""),
                "normalized_title": paper.get("normalized_title", ""),
                "title": paper.get("title", ""),
                "doi": paper.get("doi", ""),
                "url": paper.get("url", ""),
                "recommended_at": timestamp,
                "email_subject": args.email_subject,
                "delivery_status": "delivered",
                "gmail_label": args.gmail_label,
                "label_status": args.label_status,
            }
        )
        existing.add(key)
        appended += 1
    write_jsonl(args.history, history)
    print(json.dumps({"selected": len(papers), "appended": appended, "history": str(args.history)}, ensure_ascii=False))
    return 0


def mark_label_status(args: argparse.Namespace) -> int:
    """Update label_status for one run without touching delivery or resending.

    Retry path from references/contracts.md: after a failed or deferred label
    write, re-apply the label to the already-sent message and mark the same
    rows applied. Rows are matched by task_id plus run_key, optionally narrowed
    to one exact gmail_label value.
    """
    history = read_jsonl(args.history)
    validate_task_ownership(history, args.task_id, args.history)
    expected_label = (args.gmail_label or "").strip()
    updated = 0
    matched = 0
    for row in history:
        if row.get("task_id") != args.task_id or row.get("run_key") != args.run_key:
            continue
        if row.get("delivery_status") != "delivered":
            continue
        if expected_label:
            if str(row.get("gmail_label") or "").strip() != expected_label:
                continue
            if str(row.get("label_status") or "") == args.status:
                continue
        matched += 1
        if row.get("label_status") != args.status:
            row["label_status"] = args.status
            updated += 1
    if matched == 0:
        raise SystemExit(
            f"No delivered rows for task_id={args.task_id!r} run_key={args.run_key!r}"
            + (f" with gmail_label={expected_label!r}" if expected_label else "")
            + f" in {args.history}"
        )
    write_jsonl(args.history, history)
    print(
        json.dumps(
            {
                "run_key": args.run_key,
                "matched": matched,
                "updated": updated,
                "label_status": args.status,
                "history": str(args.history),
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    filter_parser = subparsers.add_parser("filter-new")
    filter_parser.add_argument("--history", required=True, type=Path)
    filter_parser.add_argument("--input", required=True, type=Path)
    filter_parser.add_argument("--output", required=True, type=Path)
    filter_parser.add_argument("--task-id", required=True)
    filter_parser.set_defaults(func=filter_new)

    record_parser = subparsers.add_parser("record-delivery")
    record_parser.add_argument("--history", required=True, type=Path)
    record_parser.add_argument("--input", required=True, type=Path)
    record_parser.add_argument("--task-id", required=True)
    record_parser.add_argument("--run-key", required=True)
    record_parser.add_argument("--email-subject", required=True)
    record_parser.add_argument("--gmail-label", default="")
    record_parser.add_argument("--label-status", choices=("pending", "applied", "failed"), default="pending")
    record_parser.add_argument("--recommended-at", default="")
    record_parser.set_defaults(func=record_delivery)

    mark_parser = subparsers.add_parser("mark-label-status")
    mark_parser.add_argument("--history", required=True, type=Path)
    mark_parser.add_argument("--task-id", required=True)
    mark_parser.add_argument("--run-key", required=True)
    mark_parser.add_argument("--gmail-label", default="", help="narrow to this exact label name")
    mark_parser.add_argument("--status", required=True, choices=("pending", "applied", "failed"))
    mark_parser.set_defaults(func=mark_label_status)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
