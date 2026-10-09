"""Make the key that signs releases, once (docs/releases.md).

    python scripts/make_update_key.py

It prints the private key once, for you to save in two places:

1. GitHub: Settings > Secrets and variables > Actions > New repository
   secret, named MCSC_UPDATE_SIGNING_KEY. The release workflow signs with it.
2. Somewhere offline that only you can open (a password manager), in case
   GitHub loses it. Without it, copies already installed can't be updated
   from inside the app any more.

It never writes the private key to a file. It writes the public key into
agent/signing.py (UPDATE_PUBLIC_KEY), which you commit: every copy built
from then on checks updates with it.

Run it again only if the private key was lost or leaked. Copies built with
the old public key then need the new version installed by hand once.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SIGNING = ROOT / "agent" / "signing.py"
LINE = re.compile(r'^UPDATE_PUBLIC_KEY = ".*"$', re.MULTILINE)


def write_public_key(public: str, path: Path = SIGNING) -> None:
    text = path.read_text(encoding="utf-8")
    if not LINE.search(text):
        raise SystemExit(f"{path} has no UPDATE_PUBLIC_KEY line")
    path.write_text(LINE.sub(f'UPDATE_PUBLIC_KEY = "{public}"', text, count=1), encoding="utf-8")


def main() -> int:
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
    print("   Name: MCSC_UPDATE_SIGNING_KEY   Value: the line above")
    print("2. Save the same line in your password manager.")
    print(f"\nThe public key was written to {SIGNING.relative_to(ROOT)}. Commit that change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
