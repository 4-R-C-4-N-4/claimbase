"""Independent CLI and whole-session evidence contracts."""
import json
import os
import subprocess
import sys
from pathlib import Path

from claimbase import usage
from conftest import TEST_DSN, seed_claim


def test_brief_inference_is_reported_even_without_any_recall(db):
    claim = seed_claim(db, "Use reports/rpt_YYYYMMDD.md.")
    with db.cursor() as cur:
        cur.execute("INSERT INTO sessions (id, corpus, harness) VALUES ('hermes:brief', 'guru', 'hermes')")
        cur.execute("""INSERT INTO exposures (claim_id, kind, session_id, via, dedupe)
                       VALUES (%s, 'used', 'hermes:brief', 'writer', 'brief-inference')""", (claim,))
    report = usage.measures(db, "guru")
    assert report["miss_rate"]["recalls"] == 0
    assert report["inference"]["claim_uses"] == 1
    assert report["inference"]["sessions"] == 1
    assert report["outcomes"]["passed"] == 0


def test_record_outcome_cli_persists_without_claiming_memory_use(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO sessions (id, corpus, harness) VALUES ('hermes:cli-check', 'guru', 'hermes')")
    db.commit()
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "CLAIMBASE_DSN": TEST_DSN}
    result = subprocess.run([sys.executable, "-m", "claimbase.cli", "--no-backup", "usage",
        "record-outcome", "--project", "guru", "--session", "hermes:cli-check",
        "--run", "cli-test", "--checker", "fixture", "--passed", "true",
        "--evidence", '{"artifact":"fixture-only"}', "--json"],
        env=env, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    stored = json.loads(result.stdout)
    assert stored["passed"] is True
    assert stored["session"] == "hermes:cli-check"
    assert usage.measures(db, "guru")["outcomes"]["passed"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM exposures")
        assert cur.fetchone()[0] == 0
