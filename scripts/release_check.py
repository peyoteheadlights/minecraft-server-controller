"""Checks a release tag before anything is built (run by
.github/workflows/release.yml), and writes the release page's text.

    python scripts/release_check.py v1.2.0
    python scripts/release_check.py v1.2.0 --notes notes.md

It refuses when:

* the tag isn't ``v`` plus the version in ``agent/__init__.py``;
* ``CHANGELOG.md`` has no section for that version;
* ``docs/api/released.txt`` doesn't name this version's saved API copy, or
  that copy isn't the API this code answers (run
  ``python scripts/api_contract.py save`` and commit it before tagging);
* no update-signing public key is built into ``agent/signing.py``, so the
  copies it installs couldn't check their own updates.

``--notes`` writes the newest CHANGELOG section plus the plain words about
Windows' "unknown publisher" warning and how to check the download.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UNSIGNED_NOTE = """\
### Before you run it

- Windows may say **"Windows protected your PC"** or **"Unknown publisher"**.
  The setup file isn't code-signed yet (see `docs/installation.md`), so
  Windows doesn't recognise who made it. Select **More info**, then **Run
  anyway**, only if you downloaded it from this page.
- To check the file is exactly the one built here, compare its SHA-256 with
  the `.sha256` file next to it: in PowerShell,
  `Get-FileHash .\\{setup} -Algorithm SHA256`.
- Every file on this page was built by this repository's release workflow,
  which GitHub can confirm: `gh attestation verify {setup} --repo {repo}`.
- `update.json` and `update.json.sig` are what the app checks before it
  installs an update by itself. You don't need them to install by hand.
"""


def changelog_section(text: str, version: str) -> str | None:
    """The lines under ``## <version>``, up to the next ``## `` heading."""
    match = re.search(rf"^## {re.escape(version)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else None


def problems(tag: str) -> list[str]:
    from agent import __version__, signing
    from scripts import api_contract

    found = []
    if tag != f"v{__version__}":
        found.append(f"The tag {tag} isn't v{__version__} (agent/__init__.py).")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not changelog_section(changelog, __version__):
        found.append(f"CHANGELOG.md has no '## {__version__}' section.")
    released = api_contract.released_schema()
    expected = f"openapi-{__version__}.json"
    if released is None or released[0] != expected:
        found.append(
            f"docs/api/released.txt doesn't name {expected}: "
            "run python scripts/api_contract.py save and commit it."
        )
    elif released[1] != json.loads(json.dumps(api_contract.current_schema())):
        found.append(
            f"docs/api/{expected} isn't the API this code answers: "
            "run python scripts/api_contract.py save again and commit it."
        )
    if not signing.has_key():
        found.append(
            "agent/signing.py has no update-signing public key: "
            "run python scripts/make_update_key.py (docs/releases.md)."
        )
    return found


def notes(version: str) -> str:
    from agent import downloads, updates

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = changelog_section(changelog, version) or ""
    setup = updates.asset_name(version)
    return (
        "## What's new\n\n"
        + section
        + "\n\n"
        + UNSIGNED_NOTE.format(setup=setup, repo=downloads.REPO)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", help="the pushed tag, like v1.2.0")
    parser.add_argument("--notes", type=Path, help="write the release page's text here")
    args = parser.parse_args(argv)
    found = problems(args.tag)
    for line in found:
        print(f"::error::{line}")
    if found:
        return 1
    if args.notes:
        args.notes.write_text(notes(args.tag[1:]), encoding="utf-8")
        print(f"release notes: {args.notes}")
    print(f"{args.tag} is ready to build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
