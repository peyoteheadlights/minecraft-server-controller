"""Fail when a commit is not under the owner's name.

Every commit in the given range must be authored by the owner's GitHub
address, and committed either by that address or by GitHub itself (which
commits merges made on the website). Commit messages may not carry
co-author or session trailers, or a "generated with" line, so nothing but
the owner is credited for the work.

    python scripts/check_authorship.py origin/main..HEAD
"""

from __future__ import annotations

import re
import subprocess
import sys

OWNER = "202191691+peyoteheadlights@users.noreply.github.com"
COMMITTERS = {OWNER, "noreply@github.com"}
# Trailers and footers that credit someone besides the owner.
BANNED = re.compile(r"^(co-authored-by:|[\w-]+-session:|\W*generated with \[)", re.IGNORECASE)

SEP = "\x1f"
END = "\x1e"


def commits(revision_range: str) -> list[tuple[str, str, str, str]]:
    out = subprocess.run(
        ["git", "log", f"--format=%h{SEP}%ae{SEP}%ce{SEP}%B{END}", revision_range],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    rows = []
    for record in out.split(END):
        record = record.strip("\n")
        if record:
            sha, author, committer, message = record.split(SEP, 3)
            rows.append((sha, author, committer, message))
    return rows


def problems(rows: list[tuple[str, str, str, str]]) -> list[str]:
    found = []
    for sha, author, committer, message in rows:
        if author != OWNER:
            found.append(f"{sha}: authored by {author}, not {OWNER}")
        if committer not in COMMITTERS:
            found.append(f"{sha}: committed by {committer}, not {OWNER}")
        for line in message.splitlines():
            if BANNED.match(line.strip()):
                found.append(f"{sha}: message line {line.strip()!r} credits someone else")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rows = commits(argv[1])
    found = problems(rows)
    for line in found:
        print(line)
    if found:
        print("\nRewrite these commits under your own name, without those lines, before merging.")
        return 1
    print(f"{len(rows)} commit(s) checked, all under {OWNER}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
