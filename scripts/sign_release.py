"""Sign a built installer for release (run by .github/workflows/release.yml).

    MCSC_UPDATE_SIGNING_KEY=... python scripts/sign_release.py dist/MinecraftServerController-Setup-1.2.0.exe

It writes, next to the setup file:

    update.json       version, file name, size, SHA-256
    update.json.sig   Ed25519 signature of that file

It refuses when the secret is missing, or when its public half isn't the
key built into the app (agent/signing.py): copies built from this code
couldn't check a release signed with another key.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def sign_setup(setup: Path, private_key: str) -> tuple[Path, Path]:
    from agent import downloads, signing

    match = re.fullmatch(r"MinecraftServerController-Setup-(\d+\.\d+\.\d+)\.exe", setup.name)
    if not match:
        raise SystemExit(f"{setup.name} isn't named like a setup file")
    version = match.group(1)
    if signing.public_key_of(private_key) != signing.UPDATE_PUBLIC_KEY:
        raise SystemExit(
            "MCSC_UPDATE_SIGNING_KEY isn't the key built into agent/signing.py, so it wasn't used."
        )
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    document = signing.release_document(
        downloads.REPO, version, setup.name, digest, setup.stat().st_size
    )
    out = setup.with_name(signing.release_file_name(version))
    out.write_bytes(document)
    sig = out.with_name(out.name + ".sig")
    sig.write_text(signing.sign(document, private_key), encoding="utf-8")
    return out, sig


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2
    key = os.environ.get("MCSC_UPDATE_SIGNING_KEY", "").strip()
    if not key:
        print("MCSC_UPDATE_SIGNING_KEY isn't set (see docs/releases.md).")
        return 1
    out, sig = sign_setup(Path(args[0]), key)
    print(f"signed: {out.name} and {sig.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
