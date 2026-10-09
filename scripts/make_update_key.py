"""Make the key that signs releases, once (docs/releases.md).

The easy way, on Windows: double-click ``make-update-key.cmd`` in the
project folder. It runs this with ``--github``, which:

1. checks the GitHub CLI (``gh``) is installed and signed in;
2. makes the key pair;
3. saves the private half as the repository's Actions secret
   MCSC_UPDATE_SIGNING_KEY (``gh secret set``, through stdin: it is never
   on the command line or in a file);
4. writes the public half into agent/signing.py (UPDATE_PUBLIC_KEY), which
   you commit: every copy built from then on checks updates with it.

It never writes the private key to a file. It offers to show it once, so
you can keep a copy in a password manager.

Without ``--github`` it only prints the private key, for you to paste into
GitHub (Settings > Secrets and variables > Actions) yourself.

If a key already exists (in agent/signing.py or on GitHub), it asks before
making a new one: copies built with the old public key then refuse updates
until the new version is installed by hand once.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SIGNING = ROOT / "agent" / "signing.py"
LINE = re.compile(r'^UPDATE_PUBLIC_KEY = "(.*)"$', re.MULTILINE)
SECRET = "MCSC_UPDATE_SIGNING_KEY"
BATCH = "make-update-key.cmd"
CONFIRM = "REPLACE"

Run = Callable[..., subprocess.CompletedProcess]


def write_public_key(public: str, path: Path = SIGNING) -> None:
    text = path.read_text(encoding="utf-8")
    if not LINE.search(text):
        raise SystemExit(f"{path} has no UPDATE_PUBLIC_KEY line")
    path.write_text(LINE.sub(f'UPDATE_PUBLIC_KEY = "{public}"', text, count=1), encoding="utf-8")


def built_in_key(path: Path = SIGNING) -> str:
    match = LINE.search(path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else ""


def run_gh(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=False, timeout=60
    )


def github_problem(repo: str, run: Run, which: Callable[[str], str | None]) -> str | None:
    """Why gh can't save the secret yet, in words Mark can act on."""
    if which("gh") is None:
        return (
            "The GitHub CLI (gh) isn't installed.\n"
            "Install it from https://cli.github.com (or in PowerShell: "
            "winget install --id GitHub.cli),\n"
            f"then close this window and double-click {BATCH} again."
        )
    if run(["auth", "status", "--hostname", "github.com"]).returncode != 0:
        return (
            "gh isn't signed in to GitHub.\n"
            "In PowerShell run:  gh auth login\n"
            f"then double-click {BATCH} again."
        )
    listed = run(["secret", "list", "--repo", repo])
    if listed.returncode != 0:
        detail = (listed.stderr or listed.stdout).strip()
        return (
            f"gh can't reach the secrets of {repo}:\n    {detail}\n"
            "Sign in with the account that owns the repository (gh auth login), then try again."
        )
    return None


def secret_exists(repo: str, run: Run) -> bool:
    listed = run(["secret", "list", "--repo", repo])
    return any(line.split("\t")[0].strip() == SECRET for line in listed.stdout.splitlines())


def to_github(
    repo: str,
    *,
    signing_file: Path = SIGNING,
    run: Run = run_gh,
    which: Callable[[str], str | None] = shutil.which,
    ask: Callable[[str], str] = input,
) -> int:
    from agent import signing

    if not LINE.search(signing_file.read_text(encoding="utf-8")):
        print(f"{signing_file} has no UPDATE_PUBLIC_KEY line. Nothing was changed.")
        return 1
    problem = github_problem(repo, run, which)
    if problem:
        print(problem)
        print("\nNothing was changed.")
        return 1

    existing = []
    if built_in_key(signing_file):
        existing.append("agent/signing.py already has a public key.")
    if secret_exists(repo, run):
        existing.append(f"GitHub already has the secret {SECRET}.")
    if existing:
        print("\n".join(existing))
        print(
            "Making a new key replaces it. Copies already installed with the old key\n"
            "will refuse updates until the new version is installed by hand once.\n"
            "Only do this if the old private key was lost or leaked."
        )
        if ask(f"Type {CONFIRM} to make a new key, or press Enter to stop: ").strip() != CONFIRM:
            print("Stopped. Nothing was changed.")
            return 1

    private, public = signing.new_key()
    saved = run(["secret", "set", SECRET, "--repo", repo], stdin=private)
    if saved.returncode != 0:
        detail = (saved.stderr or saved.stdout).strip()
        print(f"GitHub didn't take the secret:\n    {detail}\nNothing was changed.")
        return 1
    write_public_key(public, signing_file)

    print(f"\nDone. The private key is saved on GitHub as the secret {SECRET}")
    print(f"for {repo}. It isn't in any file on this PC.")
    print(f"The public key was written to {signing_file.name} (agent/signing.py).\n")
    answer = ask("Show the private key once, to keep a copy in your password manager? [y/N] ")
    if answer.strip().lower() in ("y", "yes"):
        print(f"\n    {private}\n")
        print("Save it now, then close this window. It isn't shown again.")
    else:
        print("Not shown. If the GitHub secret is ever lost, run this again to make a new key.")
    print("\nLast step: commit the public key. In PowerShell, in the project folder:")
    print("    git add agent/signing.py")
    print('    git commit -m "Add the update-signing public key"')
    print("    git push origin HEAD")
    return 0


def print_only() -> int:
    from agent import signing

    if signing.UPDATE_PUBLIC_KEY and "--replace" not in sys.argv:
        print("A release key is already built in (agent/signing.py).")
        print("Run this with --replace only if the private key was lost or leaked.")
        return 1
    private, public = signing.new_key()
    write_public_key(public)
    print("Private key (save it now; it isn't shown again or written anywhere):\n")
    print(f"    {private}\n")
    print("1. GitHub > Settings > Secrets and variables > Actions > New repository secret")
    print(f"   Name: {SECRET}   Value: the line above")
    print("2. Save the same line in your password manager.")
    print(f"\nThe public key was written to {SIGNING.relative_to(ROOT)}. Commit that change.")
    return 0


def main() -> int:
    if "--github" in sys.argv:
        from agent import downloads

        return to_github(downloads.REPO)
    return print_only()


if __name__ == "__main__":
    raise SystemExit(main())
