import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    script = project / ".agents/skills/daily-literature-recommendations/scripts/history.py"
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        selected = root / "selected.jsonl"
        history = root / "history.jsonl"
        selected.write_text(
            json.dumps({"canonical_id": "doi:10.1/test", "normalized_title": "test", "title": "Test"}) + "\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                str(script),
                "record-delivery",
                "--history",
                str(history),
                "--input",
                str(selected),
                "--task-id",
                "test-task",
                "--run-key",
                "test-task:2026-08-19",
                "--email-subject",
                "Test",
                "--gmail-label",
                "Configured exact label",
                "--label-status",
                "applied",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        row = json.loads(history.read_text(encoding="utf-8"))
        assert row["gmail_label"] == "Configured exact label"
        assert row["label_status"] == "applied"
        foreign_history = root / "foreign-history.jsonl"
        foreign_history.write_text(
            json.dumps({"task_id": "another-task", "delivery_status": "delivered"}) + "\n",
            encoding="utf-8",
        )
        rejected = subprocess.run(
            [
                sys.executable,
                str(script),
                "filter-new",
                "--history",
                str(foreign_history),
                "--input",
                str(selected),
                "--output",
                str(root / "filtered.jsonl"),
                "--task-id",
                "test-task",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert rejected.returncode != 0
        assert "History task mismatch" in rejected.stderr
    print("history gmail-label contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
