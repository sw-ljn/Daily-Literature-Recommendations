#!/usr/bin/env python3
"""Preview or remove the single data/<task_id> directory for one task."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from task_data_layout import (
    LayoutError,
    collect_path_stats,
    find_task_configs,
    path_exists,
    relative_display,
    remove_path,
    resolve_project_root,
    task_data_directory,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True, help="Exact task_id declared in task YAML")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root (defaults to the parent of this script's directory)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply deletion; default is dry-run")
    parser.add_argument(
        "--remove-task-config",
        action="store_true",
        help="Also remove the matching task YAML; preserve it by default",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = resolve_project_root(args.project_root)
    target = task_data_directory(project_root, args.task_id)
    configs = find_task_configs(project_root, args.task_id)
    config_paths = [config.path.resolve(strict=False) for config in configs]
    stats = collect_path_stats(target)

    if args.apply:
        remove_path(target)
        if args.remove_task_config:
            for config_path in config_paths:
                remove_path(config_path)
        if path_exists(target):
            raise LayoutError(f"Cleanup verification failed; target still exists: {target}")
        if args.remove_task_config:
            remaining = [str(path) for path in config_paths if path_exists(path)]
            if remaining:
                raise LayoutError(f"Task config cleanup verification failed: {remaining}")

    return {
        "task_id": args.task_id,
        "mode": "applied" if args.apply else "dry-run",
        "project_root": str(project_root),
        "target": {
            "path": relative_display(target, project_root),
            "exists": stats.exists,
            "files": stats.files,
            "directories": stats.directories,
            "bytes": stats.bytes,
        },
        "task_configs": [relative_display(path, project_root) for path in config_paths],
        "remove_task_config": bool(args.remove_task_config),
        "scope_exclusions": [
            "tasks YAML unless --remove-task-config is used",
            "legacy scattered data; migrate it first",
            "external Gmail messages",
            "Codex scheduler state",
        ],
    }


def render_human(report: dict[str, Any]) -> str:
    target = report["target"]
    config_action = "remove" if report["remove_task_config"] else "preserve"
    configs = ", ".join(report["task_configs"]) if report["task_configs"] else "not found"
    lines = [
        f"Task: {report['task_id']}",
        f"Mode: {report['mode']}",
        f"Target: {target['path']}",
        f"Contents: exists={target['exists']} files={target['files']} "
        f"dirs={target['directories']} bytes={target['bytes']}",
        f"Task config ({config_action}): {configs}",
        "Legacy scattered paths are intentionally not scanned by this cleaner.",
        "External Gmail messages and Codex scheduler state are outside this cleanup scope.",
    ]
    if report["mode"] == "dry-run":
        lines.append("No data was changed. Re-run with --apply after pausing the scheduled task.")
    else:
        lines.append("Cleanup applied; the exact task data directory was verified absent.")
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run(args)
    except LayoutError as exc:
        print(f"cleanup-task-data: error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
