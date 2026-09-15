import json
import subprocess
import sys
import tempfile
from pathlib import Path


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
    script = project / "scripts/write-preflight-failure.py"

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        task_file = root / "tasks/config-name-differs.yaml"
        task_file.parent.mkdir()
        task_file.write_text(
            "task_id: target-task\ntimezone: America/Los_Angeles\n",
            encoding="utf-8",
        )
        result = run_script(
            script,
            root,
            "--task-file",
            "tasks/config-name-differs.yaml",
            "--stage",
            "gmail_auth",
            "--reason",
            "FORBIDDEN: connector unavailable",
            "--error-code",
            "FORBIDDEN",
            "--runtime-status",
            "ok",
            "--gmail-status",
            "unavailable",
            "--invocation-time",
            "2026-08-28T12:00:22-07:00",
            "--json",
        )
        output = json.loads(result.stdout)
        assert output["run_path"] == "data/target-task/runs/2026-08-28T12-00-22/run.json"
        run_path = root / output["run_path"]
        record = json.loads(run_path.read_text(encoding="utf-8"))
        assert record["task_id"] == "target-task"
        assert record["run_key"] == "target-task:2026-08-28T12-00-22"
        assert record["timezone"] == "America/Los_Angeles"
        assert record["status"] == "failed_preflight"
        assert record["connection_check"]["local_runtime"] == "ok"
        assert record["connection_check"]["gmail_credential"] == "unavailable"
        assert record["delivery_status"] == "not_sent"
        assert record["failures"][0]["error_code"] == "FORBIDDEN"
        assert not (root / "runs").exists(), "legacy roots must never be created"

        duplicate = run_script(
            script,
            root,
            "--task-file",
            "tasks/config-name-differs.yaml",
            "--stage",
            "gmail_auth",
            "--reason",
            "duplicate",
            "--invocation-time",
            "2026-08-28T12:00:22-07:00",
            check=False,
        )
        assert duplicate.returncode == 2
        assert "refusing to overwrite" in duplicate.stderr

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        task_file = root / "tasks/bad-timezone.yaml"
        task_file.parent.mkdir()
        task_file.write_text("task_id: bad-task\ntimezone: Not/AZone\n", encoding="utf-8")
        failed = run_script(
            script,
            root,
            "--task-file",
            "tasks/bad-timezone.yaml",
            "--stage",
            "gmail_auth",
            "--reason",
            "unavailable",
            check=False,
        )
        assert failed.returncode == 2
        assert "Unknown task timezone" in failed.stderr
        assert not (root / "data").exists()

    print("preflight failure path contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
