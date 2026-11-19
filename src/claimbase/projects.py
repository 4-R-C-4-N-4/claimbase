"""Project scoping: which project does a session belong to?

**Project is `corpus`.** Every row has carried one since migration 001, so
"projects never conflate" needs no new column — it needs every read and write
to name its project, and it needs the name to be *stamped at capture* rather
than inferred afterwards (RFC, Data model).

Resolution, in order:

1. An explicit name. The harness knows where it is running; if it says, that
   is the answer.
1b. A `.claimbase` marker file in the working directory or the nearest
   ancestor that has one (`project = "name"`, written by `claimbase init`).
   It is the one identity that survives `git init`, renames, moves and fresh
   clones, so it outranks everything below.
2. A working directory inside a repo that some `corpora/*.toml` declares. Those
   paths are declared, not discovered — three repos (guru, guru-web, rellm)
   are one project because a human wrote that down.
3. A working directory inside any other git repo: the repo's directory name.
   A project nobody declared is still its own namespace; the alternative is
   that undeclared work lands in someone else's.
4. Otherwise the user scope, `self`. A shell opened in `~/Work` is not a
   project.

What this never does is guess from content. A claim's project is where the
session that produced it was running.
"""

from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORPORA = ROOT / "corpora"

# The user scope: preferences, tools, machine setup — facts about the person
# rather than about any one project. The name is the one harnesses/hermes.toml
# already reserves for exactly this.
USER_SCOPE = "self"

_SAFE = re.compile(r"[^a-z0-9._-]+")


@lru_cache(maxsize=1)
def declared() -> dict[str, list[Path]]:
    """corpus name -> the repo paths its definition declares."""
    out: dict[str, list[Path]] = {}
    for f in sorted(CORPORA.glob("*.toml")):
        with f.open("rb") as fh:
            spec = tomllib.load(fh)
        paths = [
            Path(s["path"]).expanduser().resolve()
            for s in spec.get("source", [])
            if s.get("kind") == "repo" and "path" in s
        ]
        out[spec.get("name", f.stem)] = paths
    return out


MARKER = ".claimbase"


def read_marker(path: Path) -> str | None:
    """The project a marker file names, or None if it is absent, unreadable
    or names the user scope (which a directory cannot claim)."""
    try:
        with path.open("rb") as fh:
            name = tomllib.load(fh).get("project")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    name = normalize(name)
    return None if name == USER_SCOPE else name


def marked(path: Path) -> tuple[Path, str] | None:
    """The nearest ancestor (or `path` itself) with a valid marker."""
    for p in (path, *path.parents):
        f = p / MARKER
        if f.is_file() and (name := read_marker(f)):
            return p, name
    return None


def _git_root(path: Path) -> Path | None:
    for p in (path, *path.parents):
        if (p / ".git").exists():
            return p
    return None


def normalize(name: str) -> str:
    """A project name is a storage key. Keep it boring."""
    return _SAFE.sub("-", name.strip().lower()).strip("-") or USER_SCOPE


def resolve(project: str | None = None, cwd: str | Path | None = None) -> str:
    """The project a session at `cwd` belongs to. Never raises, never guesses
    from content; an unplaceable session is user-scoped."""
    if project:
        return normalize(project)
    if not cwd:
        return USER_SCOPE
    here = Path(cwd).expanduser()
    try:
        here = here.resolve()
    except OSError:
        pass
    if m := marked(here):
        return m[1]
    best: tuple[int, str] | None = None
    for name, paths in declared().items():
        for p in paths:
            if here == p or p in here.parents:
                depth = len(p.parts)
                if best is None or depth > best[0]:
                    best = (depth, name)
    if best:
        return best[1]
    root = _git_root(here)
    if root is not None:
        # A linked worktree's directory is not the project's name; the repo it
        # belongs to is. `.git` is a file there, pointing at the real gitdir.
        dotgit = root / ".git"
        if dotgit.is_file():
            try:
                gitdir = Path(dotgit.read_text().split("gitdir:", 1)[1].strip())
                main = gitdir.parent.parent.parent  # <repo>/.git/worktrees/<name>
                if (main / ".git").is_dir():
                    return resolve(cwd=main)
            except (IndexError, OSError):
                pass
        return normalize(root.name)
    return USER_SCOPE


def scopes(project: str) -> list[str]:
    """What a read in `project` may see: the project and the user scope.
    Another project's claims appear only when asked for by name."""
    return [project] if project == USER_SCOPE else [project, USER_SCOPE]
