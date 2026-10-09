"""pyproject.toml is where dependencies are declared; the hash-pinned lock
files made from it must hold every one of them."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def names(requirements: list[str]) -> set[str]:
    out = set()
    for line in requirements:
        match = re.match(r"^\s*([A-Za-z0-9_.\-]+)", line)
        assert match, line
        out.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return out


def locked(lock: str) -> set[str]:
    text = (ROOT / lock).read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9_.\-]+)==\S+ \\$", text, flags=re.M)
    assert "--hash=sha256:" in text
    return {re.sub(r"[-_.]+", "-", name).lower() for name in pins}


def test_the_locks_hold_what_pyproject_asks_for():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    app = names(project["dependencies"])
    extras = project["optional-dependencies"]
    assert app <= locked("requirements.lock")
    assert app | names(extras["dev"]) <= locked("requirements-dev.lock")
    assert app | names(extras["build"]) <= locked("requirements-build.lock")


def test_locks_are_made_from_pyproject():
    for lock, extra in (
        ("requirements.lock", ""),
        ("requirements-dev.lock", " --extra dev"),
        ("requirements-build.lock", " --extra build"),
    ):
        head = (ROOT / lock).read_text(encoding="utf-8").splitlines()[1]
        assert f"uv pip compile pyproject.toml{extra} " in head, lock
        assert "--generate-hashes" in head


def test_no_old_requirements_files():
    for old in ("requirements.txt", "requirements-dev.txt", "requirements-build.txt"):
        assert not (ROOT / old).exists(), f"{old}: dependencies live in pyproject.toml now"
