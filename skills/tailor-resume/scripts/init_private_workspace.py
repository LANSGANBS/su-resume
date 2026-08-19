#!/usr/bin/env python3
"""Create a private, non-repository workspace for resume source material."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


LEDGER_TEMPLATE = {
    "schema_version": 1,
    "source_index": [],
    "facts": [],
    "open_questions": [],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an access-restricted workspace outside the public resume "
            "repository and initialize its fact ledger."
        )
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        type=Path,
        help="Path to the public resume repository.",
    )
    parser.add_argument(
        "--private-root",
        type=Path,
        help=(
            "Private workspace location. Defaults to "
            "$XDG_STATE_HOME/tailor-resume/<repo>-<hash>."
        ),
    )
    return parser.parse_args()


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def default_private_root(repo_root: Path) -> Path:
    state_home = Path(
        os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
    ).expanduser()
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", repo_root.name).strip("-") or "resume"
    digest = hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:10]
    return state_home / "tailor-resume" / f"{slug}-{digest}"


def ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"refusing symlinked private directory: {path}")
    if path.exists() and not path.is_dir():
        raise RuntimeError(f"private workspace path is not a directory: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError as exc:
        raise RuntimeError(f"could not restrict permissions on {path}: {exc}") from exc


def enclosing_git_root(path: Path) -> Path | None:
    git = shutil.which("git")
    if not git:
        return None
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if candidate.is_file():
        candidate = candidate.parent
    completed = subprocess.run(
        [git, "-C", str(candidate), "rev-parse", "--show-toplevel"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return Path(completed.stdout.strip()).resolve()


def ensure_private_file(path: Path, content: str) -> None:
    if path.is_symlink():
        raise RuntimeError(f"refusing symlinked private file: {path}")
    if path.exists() and not path.is_file():
        raise RuntimeError(f"private workspace path is not a file: {path}")
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    if not repo_root.is_dir():
        print(f"error: repository root does not exist: {repo_root}", file=sys.stderr)
        return 2

    required = ("resume.tex", "content.tex", "theme.tex")
    missing = [name for name in required if not (repo_root / name).is_file()]
    if missing:
        print(
            "error: repository does not look like this resume template; missing "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    private_root = (
        args.private_root.expanduser().resolve()
        if args.private_root
        else default_private_root(repo_root).resolve()
    )
    if is_within(private_root, repo_root):
        print(
            "error: private workspace must be outside the public repository",
            file=sys.stderr,
        )
        return 2
    git_root = enclosing_git_root(private_root)
    if git_root is not None and is_within(private_root, git_root):
        print(
            "error: private workspace must not be inside any Git worktree",
            file=sys.stderr,
        )
        return 2

    try:
        ensure_private_directory(private_root)
        directories = {
            "sources_dir": private_root / "sources",
            "working_dir": private_root / "working",
            "qa_dir": private_root / "qa",
        }
        for directory in directories.values():
            ensure_private_directory(directory)

        ledger_path = private_root / "fact-ledger.json"
        ensure_private_file(
            ledger_path,
            json.dumps(LEDGER_TEMPLATE, ensure_ascii=False, indent=2) + "\n",
        )

        denylist_path = private_root / "privacy-denylist.txt"
        ensure_private_file(
            denylist_path,
            "# Add one private name, handle, hostname, or project term per line.\n"
            "# Keep this file in the private workspace; never commit it.\n",
        )

        marker_path = private_root / ".gitignore"
        ensure_private_file(marker_path, "*\n!.gitignore\n")
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = {
        "repo_root": str(repo_root),
        "private_root": str(private_root),
        "ledger_path": str(ledger_path),
        "denylist_path": str(denylist_path),
        **{key: str(value) for key, value in directories.items()},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
