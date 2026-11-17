"""Durable supervisor distinguishes expected control failures from errors."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "durable_eval", Path(__file__).resolve().parents[1] / "scripts/run_memory_eval.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def report(tmp_path, *, teach="completed", memory="pass", errors=None):
    trial = tmp_path / "trial.json"
    trial.write_text(json.dumps({"scenarios": {"example": {
        "control": {"status": "fail"}, "teach": {"status": teach},
        "memory": {"status": memory}}}, "errors": errors or []}))
    batch = tmp_path / "results.json"
    batch.write_text(json.dumps({"status": "fail", "attempted_trials": 1,
                                "trials": [{"path": str(trial)}]}))
    return batch


def test_completed_teaching_and_expected_control_failure_are_complete(tmp_path):
    result = runner.inspect_batch(report(tmp_path), 1, 1)
    assert result["complete"]
    assert result["memory_all_pass"]
    assert result["memory_total"] == 1


def test_interrupted_arm_is_not_complete(tmp_path):
    result = runner.inspect_batch(report(tmp_path, memory="running"), 1, 1)
    assert not result["complete"]
    assert not result["memory_all_pass"]


def test_missing_requested_trials_is_not_complete(tmp_path):
    assert not runner.inspect_batch(report(tmp_path), 3, 1)["complete"]


def test_failed_memory_is_complete_but_not_successful(tmp_path):
    result = runner.inspect_batch(report(tmp_path, memory="fail"), 1, 1)
    assert result["complete"]
    assert not result["memory_all_pass"]


def test_disk_reserve_refuses_before_space_is_exhausted(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.shutil, 'disk_usage', lambda _: SimpleNamespace(free=9 * 1024**3))
    with pytest.raises(RuntimeError, match='disk reserve'):
        runner.check_disk(tmp_path)
