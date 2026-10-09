"""Copying a running Bedrock server's world safely.

A Bedrock world is a LevelDB database that can't be copied while the server
writes to it. Bedrock Dedicated Server has its own way:

  1. ``save hold``: finish the current save, then stop changing the files
  2. ``save query``: once the files are ready it answers "Data saved. Files
     are now ready to be copied." and lists each file with the length to
     copy, like ``Bedrock level/db/000005.ldb:1234, Bedrock level/level.dat:2386``
     (paths inside worlds/). Until then it is asked again.
  3. copy each listed file, cut to its listed length (LevelDB may have
     written more since; that part isn't part of the saved state)
  4. ``save resume``, **always**, even when the copy failed, so the server
     never stays unable to save

A stopped server's files are copied directly by the backup manager.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..security.paths import PathSafetyError, check_archive_member, is_inside

if TYPE_CHECKING:
    from ..minecraft.process import MinecraftServer

# Listed paths are checked against a folder that is never written to.
CHECK_BASE = Path("/archive-check")

log = logging.getLogger("msc.backups.hold")

READY_RE = re.compile(r"Data saved\. Files are now ready to be copied\.")
# One "path:length" entry, followed by ", " or the end. A world's name can
# hold a comma ("Mark, Sam and Jo"), so the list isn't simply split on
# commas: a path ends only where ":<digits>" is followed by ", " or the end.
ENTRY_RE = re.compile(r"(?P<path>[^:]+?):(?P<length>\d+)(?:,\s*|\s*$)")
WAIT_SECONDS = 60.0
POLL_SECONDS = 1.0
CHUNK = 1024 * 1024


class HoldError(RuntimeError):
    """Written for the person reading it."""


def parse_files(text: str) -> list[tuple[str, int]]:
    """The "path:length, path:length" list ``save query`` prints. Every
    path must stay inside worlds/; anything else refuses the whole list."""
    found = []
    text = text.strip()
    position = 0
    while position < len(text):
        match = ENTRY_RE.match(text, position)
        if not match:
            raise HoldError(
                f"The server's file list couldn't be read ('{text[position : position + 80]}')."
            )
        position = match.end()
        path = match.group("path").strip().replace("\\", "/")
        try:
            check_archive_member(CHECK_BASE, path)
        except PathSafetyError:
            raise HoldError(
                f"The server listed a file outside its worlds folder ('{path[:80]}'), so "
                "nothing was copied."
            ) from None
        found.append((path, int(match.group("length"))))
    if not found:
        raise HoldError("The server said its files were ready but listed none.")
    return found


def _answer(server: MinecraftServer, since: int) -> list[tuple[str, int]] | None:
    """The file list, if the console has printed it since ``since``."""
    lines = [ln for ln in server.console.since(since, limit=2000) if ln.source == "stdout"]
    for index, line in enumerate(lines):
        text = (line.message or line.raw).strip()
        match = READY_RE.search(text)
        if not match:
            continue
        rest = text[match.end() :].strip()
        if rest:
            return parse_files(rest)
        if index + 1 < len(lines):
            following = lines[index + 1]
            return parse_files((following.message or following.raw).strip())
        return None  # the list is on the next line, not printed yet
    return None


def copy_truncated(source: Path, target: Path, length: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = length
    with open(source, "rb") as src, open(target, "wb") as dst:
        while remaining > 0:
            chunk = src.read(min(CHUNK, remaining))
            if not chunk:
                break
            dst.write(chunk)
            remaining -= len(chunk)
    if remaining > 0:
        raise HoldError(f"{source.name} is shorter than the server said it would be.")


def copy_unlisted(worlds: Path, staging: Path, listed: list[str]) -> list[str]:
    """The world's own small files that ``save query`` may leave out of its
    list: the files directly in each listed world's folder, such as
    world_behavior_packs.json, world_resource_packs.json and levelname.txt.
    They aren't part of the LevelDB database (that is db/, which is only
    copied as listed), so copying them whole is safe. Without them a
    restored world would lose which add-ons it has on."""
    done = set(listed)
    copied = []
    for world in sorted({rel.split("/", 1)[0] for rel in listed if "/" in rel}):
        folder = worlds / world
        if folder.is_symlink() or not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            relative = f"{world}/{entry.name}"
            if relative in done or entry.is_symlink() or not entry.is_file():
                continue
            target = staging / relative
            if not is_inside(staging, target.resolve()):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry, target)
            copied.append(relative)
    return copied


async def copy_world(
    server: MinecraftServer,
    worlds: Path,
    staging: Path,
    wait: float = WAIT_SECONDS,
    poll: float = POLL_SECONDS,
) -> list[str]:
    """Hold, query, copy each listed file into ``staging`` (keeping its path
    inside worlds/), resume. Returns the relative paths copied."""
    await server.send_command("save hold", internal=True)
    try:
        deadline = time.monotonic() + wait
        files = None
        while files is None:
            if time.monotonic() > deadline:
                raise HoldError(
                    "The server didn't say its world was ready to copy, so no backup was made."
                )
            mark = server.console._seq
            await server.send_command("save query", internal=True)
            stop = time.monotonic() + poll
            while files is None and time.monotonic() < stop:
                await asyncio.sleep(min(0.1, poll))
                files = _answer(server, mark)
        copied = []
        for relative, length in files:
            source = worlds / relative
            target = staging / relative
            if not is_inside(worlds, source.resolve()) or not is_inside(staging, target.resolve()):
                raise HoldError("The server listed a file outside its worlds folder.")
            await asyncio.to_thread(copy_truncated, source, target, length)
            copied.append(relative)
        copied += await asyncio.to_thread(copy_unlisted, worlds, staging, copied)
        return copied
    finally:
        try:
            await server.send_command("save resume", internal=True)
        except Exception:  # reported; the backup's own error, if any, still raises
            log.exception("could not send save resume")
