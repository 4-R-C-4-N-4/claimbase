"""Hermes gateway hook metadata must not replace the session's scope."""
import io
import json
import sqlite3
import sys

from claimbase import cli, sessions


def test_hermes_finalize_uses_session_cwd_and_configured_project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    wd = tmp_path / "scenario"
    wd.mkdir()
    with sqlite3.connect(home / "state.db") as conn:
        conn.execute("CREATE TABLE sessions (id TEXT, cwd TEXT, git_repo_root TEXT, started_at REAL, ended_at REAL)")
        conn.execute("INSERT INTO sessions VALUES ('s', ?, ?, 1, 2)", (str(wd), str(tmp_path)))
        conn.execute("CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, tool_name TEXT, tool_call_id TEXT, timestamp REAL)")
        conn.execute("INSERT INTO messages VALUES (1, 's', 'user', 'Always use local.toml.', NULL, NULL, NULL, 1)")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("CLAIMBASE_PROJECT", "sandbox")
    monkeypatch.setattr(sessions, "SPOOL", tmp_path / "spool")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "s", "cwd": "/unrelated/hermes-gateway", "extra": {"reason": "cli_close"}})))
    assert cli.main(["--no-backup", "submit-session", "--harness", "hermes", "--hook"]) == 0
    queued = sessions.read_generic(sessions.pending()[0])
    assert queued.project == "sandbox"
    assert queued.cwd == str(wd)
