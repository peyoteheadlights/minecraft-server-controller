"""The CI check that keeps every commit under the owner's name."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_authorship", ROOT / "scripts" / "check_authorship.py"
)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

OWNER = check.OWNER


def _row(message: str, author: str = OWNER, committer: str = OWNER) -> tuple[str, str, str, str]:
    return ("abc1234", author, committer, message)


def test_the_owners_commits_pass() -> None:
    assert check.problems([_row("Add a thing\n\nLonger words, generated with uv.")]) == []


def test_a_website_merge_passes() -> None:
    assert check.problems([_row("Merge pull request #1", committer="noreply@github.com")]) == []


def test_someone_else_as_author_or_committer_fails() -> None:
    assert len(check.problems([_row("x", author="someone@example.com")])) == 1
    assert len(check.problems([_row("x", committer="someone@example.com")])) == 1


def test_crediting_trailers_fail() -> None:
    for line in (
        "Co-Authored-By: Someone <someone@example.com>",
        "Tool-Session: https://example.com/session",
        "\N{ROBOT FACE} Generated with [A Tool](https://example.com)",
    ):
        assert check.problems([_row(f"Subject\n\n{line}")]), line


def test_it_reads_real_git_history(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git(
        "-c",
        "user.name=Owner",
        "-c",
        f"user.email={OWNER}",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "One",
    )
    git(
        "-c",
        "user.name=Other",
        "-c",
        "user.email=other@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Two",
    )
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_authorship.py"), "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 1
    assert "other@example.com" in out.stdout
