"""Shared safety helpers for the task-local data layout."""

from __future__ import annotations

import ast
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class LayoutError(RuntimeError):
    """A layout preflight or safety check failed."""


@dataclass(frozen=True)
class PathStats:
    path: Path
    exists: bool
    files: int
    directories: int
    bytes: int


@dataclass(frozen=True)
class TaskConfig:
    path: Path
    task_id: str
    timezone: str


def validate_task_id(task_id: str) -> None:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise LayoutError(
            "task_id must be 1-128 ASCII letters, digits, dots, underscores, or "
            "hyphens, and must start with a letter or digit"
        )


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


def resolve_project_root(raw_root: Path) -> Path:
    try:
        project_root = raw_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise LayoutError(f"Project root does not exist: {raw_root}") from exc
    if not project_root.is_dir():
        raise LayoutError(f"Project root is not a directory: {project_root}")
    return project_root


def resolve_inside_project(
    project_root: Path,
    raw_path: str | Path,
    *,
    label: str,
    allow_project_root: bool = False,
) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    resolved = candidate.resolve(strict=False)
    if not is_relative_to(resolved, project_root):
        raise LayoutError(f"{label} resolves outside the project: {candidate}")
    if resolved == project_root and not allow_project_root:
        raise LayoutError(f"{label} must not be the project root")
    return resolved


def task_data_directory(project_root: Path, task_id: str) -> Path:
    validate_task_id(task_id)
    data_root = resolve_inside_project(project_root, "data", label="data root")
    target = resolve_inside_project(project_root, data_root / task_id, label="task data directory")
    if target.parent != data_root or target.name != task_id:
        raise LayoutError(f"Unsafe task data directory: {target}")
    return target


def strip_yaml_comment(value: str) -> str:
    quote = ""
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "#":
            return value[:index].rstrip()
    return value.strip()


def parse_yaml_scalar(value: str, *, path: Path, line_number: int) -> str:
    value = strip_yaml_comment(value).strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise LayoutError(f"Invalid quoted scalar at {path}:{line_number}") from exc
        if not isinstance(parsed, str):
            raise LayoutError(f"Expected a string scalar at {path}:{line_number}")
        return parsed
    return value


def read_task_config(path: Path) -> TaskConfig:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LayoutError(f"Cannot read task config {path}: {exc}") from exc
    task_id = ""
    timezone = ""
    for line_number, line in enumerate(lines, start=1):
        match = re.match(r"^(task_id|timezone)\s*:\s*(.*)$", line)
        if not match:
            continue
        value = parse_yaml_scalar(match.group(2), path=path, line_number=line_number)
        if match.group(1) == "task_id":
            task_id = value
        else:
            timezone = value
    return TaskConfig(path=path, task_id=task_id, timezone=timezone)


def find_task_configs(project_root: Path, task_id: str) -> list[TaskConfig]:
    task_dir = project_root / "tasks"
    if not task_dir.is_dir():
        return []
    if task_dir.is_symlink() or is_junction(task_dir):
        raise LayoutError(f"Refusing linked or junction tasks directory: {task_dir}")
    if not is_relative_to(task_dir.resolve(strict=True), project_root):
        raise LayoutError(f"Tasks directory resolves outside the project: {task_dir}")
    candidates = sorted(task_dir.glob("*.yaml")) + sorted(task_dir.glob("*.yml"))
    matches: list[TaskConfig] = []
    for path in candidates:
        if path.is_symlink() or is_junction(path):
            raise LayoutError(f"Refusing linked or junction task config: {path}")
        if not is_relative_to(path.resolve(strict=True), project_root):
            raise LayoutError(f"Task config resolves outside the project: {path}")
        config = read_task_config(path)
        if config.task_id == task_id:
            matches.append(config)
    if len(matches) > 1:
        rendered = ", ".join(str(config.path) for config in matches)
        raise LayoutError(f"Multiple task configs declare task_id {task_id!r}: {rendered}")
    return matches


def collect_path_stats(path: Path) -> PathStats:
    if not path_exists(path):
        return PathStats(path=path, exists=False, files=0, directories=0, bytes=0)
    if path.is_symlink() or is_junction(path) or not path.is_dir():
        try:
            size = path.lstat().st_size
        except OSError:
            size = 0
        return PathStats(path=path, exists=True, files=1, directories=0, bytes=size)

    files = 0
    directories = 0
    total_bytes = 0
    for current_root, dir_names, file_names in os.walk(path, followlinks=False):
        current = Path(current_root)
        directories += len(dir_names)
        for name in file_names:
            child = current / name
            files += 1
            try:
                total_bytes += child.lstat().st_size
            except OSError:
                pass
    return PathStats(path=path, exists=True, files=files, directories=directories, bytes=total_bytes)


def ensure_no_links(path: Path) -> None:
    if not path_exists(path):
        return
    if path.is_symlink() or is_junction(path):
        raise LayoutError(f"Refusing linked or junction source: {path}")
    if not path.is_dir():
        return
    for current_root, dir_names, file_names in os.walk(path, followlinks=False):
        current = Path(current_root)
        for name in [*dir_names, *file_names]:
            candidate = current / name
            if candidate.is_symlink() or is_junction(candidate):
                raise LayoutError(f"Refusing linked or junction source: {candidate}")


def remove_path(path: Path) -> None:
    if not path_exists(path):
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    elif is_junction(path):
        path.rmdir()
    else:
        shutil.rmtree(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def relative_display(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)
