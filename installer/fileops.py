"""Copying files with real progress, and checking the copies.

Every copy reports bytes done out of bytes total, so the progress bar moves
only for work actually done, and every copied file is checked by SHA-256
against the original before anything relies on it.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1024 * 1024
Report = Callable[[int, int], None]  # (bytes done, bytes total)


class CopyError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def list_files(root: Path, skip: Iterable[str] = ()) -> list[Path]:
    """Every file under root (relative paths), skipping top-level names."""
    skipped = set(skip)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in skipped]
            filenames = [f for f in filenames if f not in skipped]
        for name in filenames:
            out.append(rel_dir / name)
    return sorted(out)


@dataclass
class Copied:
    files: int
    bytes: int
    hashes: dict[str, str]


def copy_files(
    pairs: list[tuple[Path, Path]],
    report: Report | None = None,
    verify: bool = True,
) -> Copied:
    """Copy each (source, target), then check each target's SHA-256."""
    total = sum(src.stat().st_size for src, _ in pairs)
    done = 0
    hashes: dict[str, str] = {}
    if report:
        report(0, total)
    for src, dst in pairs:
        dst.parent.mkdir(parents=True, exist_ok=True)
        source_hash = hashlib.sha256()
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            for block in iter(lambda: fin.read(CHUNK), b""):
                fout.write(block)
                source_hash.update(block)
                done += len(block)
                if report:
                    report(done, total)
        shutil.copystat(src, dst, follow_symlinks=False)
        expected = source_hash.hexdigest()
        if verify and sha256_file(dst) != expected:
            raise CopyError(f"The copy of {src} doesn't match the original.")
        hashes[str(dst)] = expected
    return Copied(files=len(pairs), bytes=total, hashes=hashes)


def copy_tree(
    src: Path, dst: Path, report: Report | None = None, skip: Iterable[str] = ()
) -> Copied:
    files = list_files(src, skip)
    return copy_files([(src / rel, dst / rel) for rel in files], report)


def verify_tree(src: Path, dst: Path, skip: Iterable[str] = ()) -> list[str]:
    """Problems with dst as a copy of src: missing files, different counts
    or contents. Empty means a faithful copy."""
    problems = []
    source_files = list_files(src, skip)
    target_files = set(list_files(dst, skip))
    if len(source_files) != len(target_files):
        problems.append(f"{len(source_files)} files in {src}, {len(target_files)} in {dst}")
    for rel in source_files:
        if rel not in target_files:
            problems.append(f"missing: {rel}")
        elif sha256_file(src / rel) != sha256_file(dst / rel):
            problems.append(f"different: {rel}")
    return problems


def copy_database(src: Path, dst: Path) -> None:
    """A consistent copy of a SQLite database (WAL included), checked."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(src))
    try:
        dest = sqlite3.connect(str(dst))
        try:
            source.backup(dest)
            check = dest.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dest.close()
    finally:
        source.close()
    if check != "ok":
        raise CopyError(f"The database copy failed its check: {check}")


def folder_size(root: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                pass
    return total
