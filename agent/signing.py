"""Signed releases: how an update proves it was made by the app's owner.

A SHA-256 file stored next to the setup file in the same GitHub release
catches a damaged download, but not a fake release made by someone who got
into the GitHub account: they could upload a matching checksum too. So each
release also carries a small *release file* signed with an Ed25519 key:

    update.json       what was released
    update.json.sig   its signature (Ed25519, base64)

The release file names the product, this repo, the version, the setup
file's name, size and SHA-256. The private half of the key is kept by the
owner (a GitHub Actions secret, ``MCSC_UPDATE_SIGNING_KEY``, plus an
offline copy) and never goes in the repo. The public half is built into the
app below, so an update is installed only when:

* the signature checks out with the public key this copy was built with;
* the release file names this product, this repo, the version offered and
  the expected setup file name;
* the downloaded setup file's SHA-256 (and size) match the release file.

Until the owner has made a key (``make-update-key.cmd``), the
public key is empty and the app installs no update by itself: it says so
and links the release page instead.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PRODUCT = "Minecraft Server Controller"

# The public half of the owner's release signing key (32 bytes, base64).
# Written by make-update-key.cmd (scripts/make_update_key.py). Empty:
# updates are never installed by the app itself.
UPDATE_PUBLIC_KEY = "vF9SYzNynG3vf5kdnC+N7OuxqWXpd1LIO1rnzQ3Nz5M="

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_RELEASE_FILE = 8192


class SignatureError(RuntimeError):
    """Said to the owner as it is; nothing was installed."""


@dataclass
class SignedRelease:
    version: str
    file: str
    sha256: str
    size: int


def release_file_name(version: str) -> str:
    """The signed file's name in a release. Each release has its own, so
    the name is the same every time (``version`` is checked inside it)."""
    return "update.json"


def release_document(repo: str, version: str, file: str, sha256: str, size: int) -> bytes:
    """The exact bytes that are signed."""
    body = {
        "product": PRODUCT,
        "repo": repo,
        "version": version,
        "file": file,
        "sha256": sha256.lower(),
        "size": int(size),
    }
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _raw(text: str, length: int, what: str) -> bytes:
    try:
        data = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f"The {what} isn't readable.") from exc
    if len(data) != length:
        raise SignatureError(f"The {what} isn't readable.")
    return data


def has_key(public_key: str | None = None) -> bool:
    return bool((UPDATE_PUBLIC_KEY if public_key is None else public_key).strip())


def verify(
    document: bytes,
    signature: str,
    *,
    repo: str,
    version: str,
    file: str,
    public_key: str | None = None,
) -> SignedRelease:
    """Check a release file and its signature. Raises SignatureError."""
    key_text = UPDATE_PUBLIC_KEY if public_key is None else public_key
    if not key_text.strip():
        raise SignatureError(
            "This copy has no key to check updates with, so it doesn't install them itself. "
            "Download the setup file from the release page and run it."
        )
    if len(document) > MAX_RELEASE_FILE:
        raise SignatureError("The release file is too big to be one of ours.")
    key = Ed25519PublicKey.from_public_bytes(_raw(key_text, 32, "built-in key"))
    try:
        key.verify(_raw(signature, 64, "release signature"), document)
    except InvalidSignature as exc:
        raise SignatureError(
            "The release isn't signed with this app's key, so it wasn't installed."
        ) from exc
    try:
        body: Any = json.loads(document.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SignatureError("The release file couldn't be read.") from exc
    if not isinstance(body, dict):
        raise SignatureError("The release file couldn't be read.")
    expected = {"product": PRODUCT, "repo": repo, "version": version, "file": file}
    for name, value in expected.items():
        if body.get(name) != value:
            raise SignatureError(
                f"The signed release file is for a different {name}, so it wasn't installed."
            )
    sha256 = str(body.get("sha256") or "")
    size = body.get("size")
    if not _HEX64.match(sha256) or not isinstance(size, int) or size <= 0:
        raise SignatureError("The signed release file has no usable checksum.")
    return SignedRelease(version=version, file=file, sha256=sha256, size=size)


# ------------------------------------------------------------ the owner's side
def new_key() -> tuple[str, str]:
    """A new key pair as (private, public), both base64."""
    from cryptography.hazmat.primitives import serialization

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw_private).decode(), base64.b64encode(raw_public).decode()


def public_key_of(private_key: str) -> str:
    from cryptography.hazmat.primitives import serialization

    private = Ed25519PrivateKey.from_private_bytes(_raw(private_key, 32, "signing key"))
    return base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()


def sign(document: bytes, private_key: str) -> str:
    private = Ed25519PrivateKey.from_private_bytes(_raw(private_key, 32, "signing key"))
    return base64.b64encode(private.sign(document)).decode() + "\n"
