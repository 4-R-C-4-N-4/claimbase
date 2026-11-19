"""A `.claimbase` marker names a directory tree's project explicitly, so the
name survives `git init`, renames, moves and fresh clones. Observed failure it
exists for: a project started in a plain folder had half its memory filed
under the user scope until the folder became a git repo."""

import pytest

from claimbase import projects
from claimbase.cli import main


@pytest.fixture(autouse=True)
def nothing_declared(monkeypatch):
    monkeypatch.setattr(projects, "declared", lambda: {})


def _mark(d, name):
    (d / ".claimbase").write_text(f'project = "{name}"\n')


def test_marker_names_a_plain_folder_and_its_subdirectories(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_git_root", lambda path: None)
    root = tmp_path / "lilguy"
    (root / "src" / "deep").mkdir(parents=True)
    _mark(root, "lilguy")
    assert projects.resolve(cwd=root / "src" / "deep") == "lilguy"


def test_marker_survives_a_rename_and_wins_over_the_repo_name(tmp_path):
    root = tmp_path / "lilguy"
    (root / ".git").mkdir(parents=True)
    _mark(root, "lilguy")
    moved = root.rename(tmp_path / "lilguy-v2")
    assert projects.resolve(cwd=moved) == "lilguy"


def test_nearest_marker_wins(tmp_path):
    outer = tmp_path / "mono"
    inner = outer / "services" / "api"
    inner.mkdir(parents=True)
    _mark(outer, "mono")
    _mark(inner, "mono-api")
    assert projects.resolve(cwd=inner / "x") == "mono-api"
    assert projects.resolve(cwd=outer / "services") == "mono"


def test_marker_beats_a_declared_corpus_path(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(projects, "declared", lambda: {"guru": [root]})
    _mark(root, "repo-own")
    assert projects.resolve(cwd=root) == "repo-own"


def test_an_unreadable_marker_is_ignored_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_git_root", lambda path: None)
    (tmp_path / ".claimbase").write_text("this is not toml = = =")
    assert projects.resolve(cwd=tmp_path) == projects.USER_SCOPE


def test_marker_name_is_normalized_and_cannot_claim_the_user_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_git_root", lambda path: None)
    _mark(tmp_path, "My Project")
    assert projects.resolve(cwd=tmp_path) == "my-project"
    _mark(tmp_path, "self")
    assert projects.resolve(cwd=tmp_path) == projects.USER_SCOPE  # ignored, falls through


# --- claimbase init ----------------------------------------------------------

def test_init_in_a_plain_folder_uses_the_folder_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(projects, "_git_root", lambda path: None)
    d = tmp_path / "newthing"
    d.mkdir()
    assert main(["init", "--path", str(d)]) == 0
    assert projects.resolve(cwd=d) == "newthing"
    assert "newthing" in capsys.readouterr().out


def test_init_inside_a_repo_marks_the_repo_root_with_its_current_name(tmp_path, monkeypatch):
    root = tmp_path / "lilguy"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    assert main(["init", "--path", str(root / "src")]) == 0
    assert (root / ".claimbase").is_file() and not (root / "src" / ".claimbase").exists()
    assert projects.resolve(cwd=root) == "lilguy", "existing memory keeps its project"


def test_init_with_an_explicit_name(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_git_root", lambda path: None)
    assert main(["init", "--path", str(tmp_path), "--name", "Lil Guy"]) == 0
    assert projects.resolve(cwd=tmp_path) == "lil-guy"


def test_init_refuses_to_overwrite_and_refuses_the_user_scope(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(projects, "_git_root", lambda path: None)
    assert main(["init", "--path", str(tmp_path), "--name", "one"]) == 0
    assert main(["init", "--path", str(tmp_path), "--name", "two"]) != 0
    assert projects.resolve(cwd=tmp_path) == "one"
    assert main(["init", "--path", str(tmp_path), "--name", "two", "--force"]) == 0
    assert projects.resolve(cwd=tmp_path) == "two"
    other = tmp_path / "x"
    other.mkdir()
    assert main(["init", "--path", str(other), "--name", "self"]) != 0
    assert not (other / ".claimbase").exists()
