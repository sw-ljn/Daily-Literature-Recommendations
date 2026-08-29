#!/usr/bin/env python3
"""Write a connector-preflight failure to the canonical task run directory."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from task_data_layout import (
    LayoutError,
    atomic_write_text,
    is_junction,
    path_exists,
    read_task_config,
    relative_display,
    resolve_inside_project,
    resolve_project_root,
    task_data_directory,
    validate_task_id,
)


STAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def parse_invocation_time(raw_value: str, timezone: ZoneInfo) -> datetime:
    if not raw_value:
        return datetime.now(timezone)
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise LayoutError(
            "--invocation-time must be ISO 8601, for example "
            "2026-08-28T12:00:22-07:00"
        ) from exc
    if parsed.tzinfo is None:
        raise LayoutError("--invocation-time must include a UTC offset")
    return parsed.astimezone(timezone)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-file", required=True, type=Path)
    parser.add_argument("--stage", required=True, help="Stable failure stage identifier")
    parser.add_argument("--reason", required=True, help="Concise failure reason; do not include secrets")
    parser.add_argument(
        "--devspace-status",
        choices=("ok", "unavailable", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--gmail-status",
        choices=("ok", "unavailable", "unknown"),
        default="unknown",
    )
    parser.add_argument("--error-code", default="")
    parser.add_argument(
        "--invocation-time",
        default="",
        help="Optional ISO 8601 time with UTC offset; defaults to now in the task timezone",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    project_root = resolve_project_root(args.project_root)
    task_file = resolve_inside_project(project_root, args.task_file, label="task file")
    if not path_exists(task_file) or not task_file.is_file():
        raise LayoutError(f"Task file does not exist: {task_file}")
    if task_file.is_symlink() or is_junction(task_file):
        raise LayoutError(f"Refusing linked or junction task file: {task_file}")
    if not STAGE_PATTERN.fullmatch(args.stage):
        raise LayoutError("--stage must be a safe identifier of at most 64 characters")
    if not args.reason.strip():
        raise LayoutError("--reason must not be empty")

    config = read_task_config(task_file)
    validate_task_id(config.task_id)
    if not config.timezone:
        raise LayoutError(f"Task timezone is missing in {task_file}")
    try:
        timezone = ZoneInfo(config.timezone)
    except ZoneInfoNotFoundError as exc:
        raise LayoutError(f"Unknown task timezone {config.timezone!r}") from exc

    invocation = parse_invocation_time(args.invocation_time, timezone)
    timestamp = invocation.strftime("%Y-%m-%dT%H-%M-%S")
    run_key = f"{config.task_id}:{timestamp}"
    task_root = task_data_directory(project_root, config.task_id)
    run_directory = task_root / "runs" / timestamp
    if path_exists(run_directory):
        raise LayoutError(f"Run directory already exists; refusing to overwrite: {run_directory}")

    failure: dict[str, str] = {
        "stage": args.stage,
        "reason": args.reason.strip(),
    }
    if args.error_code.strip():
        failure["error_code"] = args.error_code.strip()
    record = {
        "task_id": config.task_id,
        "run_key": run_key,
        "invocation_timestamp": invocation.isoformat(timespec="seconds"),
        "timezone": config.timezone,
        "status": "failed_preflight",
        "connection_check": {
            "devspace": args.devspace_status,
            "gmail_profile": args.gmail_status,
            "email_sent_during_check": False,
        },
        "delivery_status": "not_sent",
        "label_status": "not_attempted",
        "execution": {
            "task_started": False,
            "email_sent": False,
            "gmail_label_applied": False,
            "scihub_used": False,
        },
        "failures": [failure],
    }
    run_directory.mkdir(parents=True)
    run_path = run_directory / "run.json"
    atomic_write_text(
        run_path,
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "ok": True,
        "task_id": config.task_id,
        "run_key": run_key,
        "run_path": relative_display(run_path, project_root),
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run(args)
    except (LayoutError, OSError) as exc:
        print(f"write-preflight-failure: error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"Recorded {result['run_key']} at {result['run_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
