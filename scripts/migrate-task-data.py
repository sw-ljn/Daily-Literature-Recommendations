#!/usr/bin/env python3
"""One-time migration from scattered legacy roots to data/<task_id>."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from task_data_layout import (
    LayoutError,
    atomic_write_text,
    collect_path_stats,
    ensure_no_links,
    find_task_configs,
    is_relative_to,
    path_exists,
    relative_display,
    remove_path,
    resolve_inside_project,
    resolve_project_root,
    task_data_directory,
)


@dataclass(frozen=True)
class LegacyHistoryPlan:
    path: Path
    exists: bool
    total_rows: int
    matching_rows: int
    matching_bytes: int
    target_text: str
    retained_text: str


def prepare_legacy_history(path: Path, task_id: str) -> LegacyHistoryPlan:
    if not path_exists(path):
        return LegacyHistoryPlan(path, False, 0, 0, 0, "", "")
    if not path.is_file() or path.is_symlink():
        raise LayoutError(f"Legacy history is not a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LayoutError(f"Cannot read legacy history {path}: {exc}") from exc

    target_lines: list[str] = []
    retained_lines: list[str] = []
    total_rows = 0
    matching_rows = 0
    matching_bytes = 0
    for line_number, raw_line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = raw_line.strip()
        if not stripped:
            retained_lines.append(raw_line)
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise LayoutError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise LayoutError(f"Expected a JSON object at {path}:{line_number}")
        total_rows += 1
        if row.get("task_id") == task_id:
            target_lines.append(raw_line)
            matching_rows += 1
            matching_bytes += len(raw_line.encode("utf-8"))
        else:
            retained_lines.append(raw_line)

    return LegacyHistoryPlan(
        path=path,
        exists=True,
        total_rows=total_rows,
        matching_rows=matching_rows,
        matching_bytes=matching_bytes,
        target_text="".join(target_lines),
        retained_text="".join(retained_lines),
    )


def find_legacy_temp_targets(project_root: Path, task_id: str) -> list[Path]:
    temp_root = project_root / "tmp"
    if not temp_root.is_dir():
        return []
    matches: list[Path] = []
    timestamped_name = re.compile(
        rf"^{re.escape(task_id)}-\d{{4}}-\d{{2}}-\d{{2}}"
        rf"(?:T\d{{2}}-\d{{2}}-\d{{2}})?(?:$|[-_.])"
    )

    def belongs_to_task(name: str) -> bool:
        return name == task_id or bool(timestamped_name.match(name))

    for current_root, dir_names, file_names in os.walk(temp_root, followlinks=False):
        current = Path(current_root)
        retained_dirs: list[str] = []
        for name in dir_names:
            candidate = current / name
            if belongs_to_task(name):
                resolved = candidate.resolve(strict=False)
                if not is_relative_to(resolved, project_root):
                    raise LayoutError(f"Legacy temp target resolves outside the project: {candidate}")
                matches.append(resolved)
            else:
                retained_dirs.append(name)
        dir_names[:] = retained_dirs
        for name in file_names:
            if belongs_to_task(name):
                candidate = (current / name).resolve(strict=False)
                if not is_relative_to(candidate, project_root):
                    raise LayoutError(f"Legacy temp target resolves outside the project: {candidate}")
                matches.append(candidate)
    return sorted(set(matches), key=lambda item: str(item).casefold())


def copy_source(source: Path, destination: Path) -> None:
    ensure_no_links(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, copy_function=shutil.copy2, symlinks=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def verify_copy(source: Path, destination: Path) -> None:
    source_stats = collect_path_stats(source)
    destination_stats = collect_path_stats(destination)
    if (
        not destination_stats.exists
        or source_stats.files != destination_stats.files
        or source_stats.bytes != destination_stats.bytes
    ):
        raise LayoutError(
            f"Copy verification failed: {source} -> {destination} "
            f"(source files/bytes={source_stats.files}/{source_stats.bytes}, "
            f"destination={destination_stats.files}/{destination_stats.bytes})"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True, help="Exact legacy task_id to migrate")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root (defaults to the parent of this script's directory)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply migration; default is dry-run")
    parser.add_argument(
        "--extra-path",
        action="append",
        default=[],
        metavar="PATH",
        help="Explicit project-local legacy artifact to place under task tmp/legacy/; repeatable",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = resolve_project_root(args.project_root)
    destination = task_data_directory(project_root, args.task_id)
    if path_exists(destination):
        raise LayoutError(f"Destination already exists; refusing to merge: {destination}")

    legacy_runs = resolve_inside_project(project_root, Path("runs") / args.task_id, label="legacy runs")
    legacy_downloads = resolve_inside_project(
        project_root, Path("downloads") / args.task_id, label="legacy downloads"
    )
    legacy_history_path = resolve_inside_project(
        project_root, "state/recommendations.jsonl", label="legacy history"
    )
    history = prepare_legacy_history(legacy_history_path, args.task_id)
    temp_root = (project_root / "tmp").resolve(strict=False)
    temp_targets = find_legacy_temp_targets(project_root, args.task_id)

    broad_or_shared = {
        project_root,
        (project_root / "runs").resolve(strict=False),
        (project_root / "downloads").resolve(strict=False),
        (project_root / "state").resolve(strict=False),
        (project_root / "tmp").resolve(strict=False),
        (project_root / "tasks").resolve(strict=False),
        legacy_history_path,
    }
    extra_targets: list[Path] = []
    for raw_path in args.extra_path:
        extra = resolve_inside_project(project_root, raw_path, label="extra legacy path")
        if extra in broad_or_shared:
            raise LayoutError(f"Refusing broad or shared --extra-path target: {extra}")
        if any(
            extra == standard or is_relative_to(extra, standard)
            for standard in [legacy_runs, legacy_downloads, *temp_targets]
        ):
            raise LayoutError(f"--extra-path is already covered by a standard legacy target: {extra}")
        extra_targets.append(extra)
    extra_targets = sorted(set(extra_targets), key=lambda item: str(item).casefold())

    configs = find_task_configs(project_root, args.task_id)
    source_items = [
        ("runs", legacy_runs, Path("runs")),
        ("downloads", legacy_downloads, Path("downloads")),
    ]
    source_stats = [
        {
            "kind": kind,
            "path": relative_display(source, project_root),
            "exists": (stats := collect_path_stats(source)).exists,
            "files": stats.files,
            "directories": stats.directories,
            "bytes": stats.bytes,
        }
        for kind, source, _ in source_items
    ]
    temp_stats = [
        {
            "kind": "temp",
            "path": relative_display(source, project_root),
            "exists": (stats := collect_path_stats(source)).exists,
            "files": stats.files,
            "directories": stats.directories,
            "bytes": stats.bytes,
        }
        for source in temp_targets
    ]
    extra_stats = [
        {
            "kind": "extra",
            "path": relative_display(source, project_root),
            "exists": (stats := collect_path_stats(source)).exists,
            "files": stats.files,
            "directories": stats.directories,
            "bytes": stats.bytes,
        }
        for source in extra_targets
    ]

    if args.apply:
        data_root = destination.parent
        data_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".migrate-{args.task_id}-", dir=data_root))
        committed = False
        try:
            for name in ("runs", "downloads", "state", "tmp"):
                (stage / name).mkdir()

            for _, source, relative_destination in source_items:
                if path_exists(source):
                    staged_destination = stage / relative_destination
                    remove_path(staged_destination)
                    copy_source(source, staged_destination)
                    verify_copy(source, staged_destination)

            for source in temp_targets:
                relative_source = source.relative_to(temp_root)
                staged_destination = stage / "tmp" / relative_source
                copy_source(source, staged_destination)
                verify_copy(source, staged_destination)

            for source in extra_targets:
                if not path_exists(source):
                    continue
                relative_source = source.relative_to(project_root)
                staged_destination = stage / "tmp" / "legacy" / relative_source
                copy_source(source, staged_destination)
                verify_copy(source, staged_destination)

            (stage / "state/recommendations.jsonl").write_text(
                history.target_text, encoding="utf-8", newline=""
            )
            os.replace(stage, destination)
            committed = True

            if history.exists and history.matching_rows:
                atomic_write_text(history.path, history.retained_text)
            for _, source, _ in source_items:
                remove_path(source)
            for source in [*temp_targets, *extra_targets]:
                remove_path(source)

            if not path_exists(destination):
                raise LayoutError(f"Migration verification failed; destination is missing: {destination}")
            verified_history = prepare_legacy_history(legacy_history_path, args.task_id)
            if verified_history.matching_rows:
                raise LayoutError(
                    f"Migration verification failed; {verified_history.matching_rows} legacy history rows remain"
                )
            remaining_sources = [
                str(path)
                for path in [legacy_runs, legacy_downloads, *temp_targets, *extra_targets]
                if path_exists(path)
            ]
            if remaining_sources:
                raise LayoutError(f"Migration verification failed; legacy paths remain: {remaining_sources}")
        finally:
            if not committed and path_exists(stage):
                remove_path(stage)

    all_stats = [*source_stats, *temp_stats, *extra_stats]
    return {
        "task_id": args.task_id,
        "mode": "applied" if args.apply else "dry-run",
        "project_root": str(project_root),
        "destination": relative_display(destination, project_root),
        "task_configs": [relative_display(config.path, project_root) for config in configs],
        "legacy_paths": all_stats,
        "legacy_history": {
            "path": relative_display(history.path, project_root),
            "exists": history.exists,
            "total_rows": history.total_rows,
            "matching_rows": history.matching_rows,
            "matching_bytes": history.matching_bytes,
        },
        "totals": {
            "files": sum(item["files"] for item in all_stats),
            "bytes": sum(item["bytes"] for item in all_stats) + history.matching_bytes,
        },
    }


def render_human(report: dict[str, Any]) -> str:
    lines = [
        f"Task: {report['task_id']}",
        f"Mode: {report['mode']}",
        f"Destination: {report['destination']}",
        "Legacy paths:",
    ]
    for item in report["legacy_paths"]:
        lines.append(
            f"  - [{item['kind']}] {item['path']} | exists={item['exists']} "
            f"files={item['files']} dirs={item['directories']} bytes={item['bytes']}"
        )
    history = report["legacy_history"]
    lines.append(
        f"Legacy history: {history['path']} | matching_rows={history['matching_rows']} "
        f"total_rows={history['total_rows']} bytes={history['matching_bytes']}"
    )
    lines.append(
        f"Total task data: {report['totals']['bytes']} bytes and {report['totals']['files']} files"
    )
    if report["mode"] == "dry-run":
        lines.append("No data was changed. Re-run with --apply after pausing the scheduled task.")
    else:
        lines.append("Migration applied; copied data was verified before legacy sources were removed.")
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run(args)
    except (LayoutError, OSError) as exc:
        print(f"migrate-task-data: error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
