import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def run_script(
    script: Path,
    root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--project-root", str(root), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    cleanup = project / "scripts/cleanup-task-data.py"
    migrate = project / "scripts/migrate-task-data.py"

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "tasks").mkdir()
        config = root / "tasks/config-filename-does-not-match.yaml"
        config.write_text("task_id: target-task\n", encoding="utf-8")

        legacy_run = root / "runs/target-task/run-1"
        legacy_run.mkdir(parents=True)
        (legacy_run / "run.json").write_text('{"task_id":"target-task"}', encoding="utf-8")
        legacy_download = root / "downloads/target-task/run-1"
        legacy_download.mkdir(parents=True)
        (legacy_download / "paper.pdf").write_bytes(b"pdf")
        (root / "runs/target-task-longer/run-1").mkdir(parents=True)
        legacy_temp = root / "tmp/pdfs/target-task-2026-08-28"
        legacy_temp.mkdir(parents=True)
        (legacy_temp / "extract.txt").write_text("text", encoding="utf-8")
        (root / "tmp/pdfs/target-task-longer-2026-08-28").mkdir(parents=True)
        legacy_history = root / "state/recommendations.jsonl"
        write_jsonl(
            legacy_history,
            [
                {"task_id": "target-task", "run_key": "target-task:one"},
                {"task_id": "other-task", "run_key": "other-task:one"},
                {"task_id": "target-task-longer", "run_key": "target-task-longer:one"},
            ],
        )
        orphan = root / "orphan.txt"
        orphan.write_text("legacy output for target-task", encoding="utf-8")

        migration_preview = run_script(
            migrate,
            root,
            "--task-id",
            "target-task",
            "--extra-path",
            "orphan.txt",
            "--json",
        )
        preview = json.loads(migration_preview.stdout)
        assert preview["mode"] == "dry-run"
        assert preview["destination"] == "data/target-task"
        assert preview["legacy_history"]["matching_rows"] == 1
        assert legacy_run.exists()
        assert not (root / "data/target-task").exists()

        migration = run_script(
            migrate,
            root,
            "--task-id",
            "target-task",
            "--extra-path",
            "orphan.txt",
            "--apply",
            "--json",
        )
        assert json.loads(migration.stdout)["mode"] == "applied"
        target = root / "data/target-task"
        assert (target / "runs/run-1/run.json").exists()
        assert (target / "downloads/run-1/paper.pdf").exists()
        assert (target / "tmp/pdfs/target-task-2026-08-28/extract.txt").exists()
        assert (target / "tmp/legacy/orphan.txt").exists()
        task_history = [
            json.loads(line)
            for line in (target / "state/recommendations.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert [row["task_id"] for row in task_history] == ["target-task"]
        remaining_history = [
            json.loads(line) for line in legacy_history.read_text(encoding="utf-8").splitlines()
        ]
        assert [row["task_id"] for row in remaining_history] == [
            "other-task",
            "target-task-longer",
        ]
        assert not (root / "runs/target-task").exists()
        assert not (root / "downloads/target-task").exists()
        assert not legacy_temp.exists()
        assert not orphan.exists()
        assert (root / "runs/target-task-longer").exists()
        assert (root / "tmp/pdfs/target-task-longer-2026-08-28").exists()

        cleanup_preview = run_script(
            cleanup, root, "--task-id", "target-task", "--json"
        )
        cleanup_report = json.loads(cleanup_preview.stdout)
        assert cleanup_report["mode"] == "dry-run"
        assert cleanup_report["target"]["path"] == "data/target-task"
        assert cleanup_report["task_configs"] == [
            "tasks/config-filename-does-not-match.yaml"
        ]
        assert target.exists()

        cleaned = run_script(
            cleanup, root, "--task-id", "target-task", "--apply", "--json"
        )
        assert json.loads(cleaned.stdout)["mode"] == "applied"
        assert not target.exists()
        assert config.exists(), "task config is preserved by default"
        assert (root / "runs/target-task-longer").exists()

        config_cleanup = run_script(
            cleanup,
            root,
            "--task-id",
            "target-task",
            "--remove-task-config",
            "--apply",
            "--json",
        )
        assert json.loads(config_cleanup.stdout)["mode"] == "applied"
        assert not config.exists()

        invalid_id = run_script(
            cleanup,
            root,
            "--task-id",
            "../escape",
            "--apply",
            check=False,
        )
        assert invalid_id.returncode == 2

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "runs/broken-task/run-1").mkdir(parents=True)
        bad_history = root / "state/recommendations.jsonl"
        bad_history.parent.mkdir(parents=True)
        bad_history.write_text('{"task_id":"broken-task"}\nnot-json\n', encoding="utf-8")
        failed = run_script(
            migrate,
            root,
            "--task-id",
            "broken-task",
            "--apply",
            check=False,
        )
        assert failed.returncode == 2
        assert "Invalid JSONL" in failed.stderr
        assert (root / "runs/broken-task/run-1").exists()
        assert not (root / "data/broken-task").exists()

    print("task data migration and cleanup contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
