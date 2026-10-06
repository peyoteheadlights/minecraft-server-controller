"""How much memory each server may use, against how much the PC has.

The memory slider writes one setting, the ``-Xmx`` limit in a server's
``jvm_args``, and leaves every other launch flag exactly as it was.

House rule 1: the PC's memory is read from the machine (psutil) and is
reported as Unknown when it can't be read; nothing here falls back to a
typical figure. A server's limit is a setting, not a measurement, and is
always described as a limit. The warning compares the limits of the servers
that are running (and the one about to start) with the PC's measured total.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .minecraft.java import memory_limit_mb

if TYPE_CHECKING:
    from .core import ServerContext

log = logging.getLogger("msc.memory")

MIN_MB = 1024  # below this a modern server does not start
STEP_MB = 512


class MemoryLimitError(ValueError):
    """A memory limit that can't be set."""


def total_ram_mb() -> int | None:
    """The PC's total memory in MB, or None when it can't be read."""
    try:
        import psutil

        return int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:  # pragma: no cover - psutil is a hard dependency
        log.debug("could not read total memory", exc_info=True)
        return None


def with_limit(jvm_args: list[str], mb: int) -> list[str]:
    """``jvm_args`` with its -Xmx set to ``mb``. Every other flag stays where
    it was; the limit replaces the old one in place, or is added at the end."""
    flag = f"-Xmx{mb // 1024}G" if mb % 1024 == 0 else f"-Xmx{mb}M"
    out: list[str] = []
    placed = False
    for arg in jvm_args:
        if str(arg).strip().lower().startswith("-xmx"):
            if not placed:
                out.append(flag)
                placed = True
            continue  # a second -Xmx would only confuse which one counts
        out.append(str(arg))
    if not placed:
        out.append(flag)
    return out


def _limit(ctx: ServerContext) -> int | None:
    return memory_limit_mb(ctx.config.server.jvm_args)


def together_mb(ctx: ServerContext, include_self: bool = True) -> tuple[int, list[dict[str, Any]]]:
    """The limits of the running servers (and this one) added up, and who
    they are. A running server with no -Xmx set adds nothing, and is listed
    with its limit as None so the dashboard can say so."""
    rows = []
    total = 0
    for other in ctx.core.servers.values():
        mine = other is ctx
        if not mine and not other.server.running:
            continue
        if mine and not include_self:
            continue
        limit = _limit(other)
        rows.append(
            {
                "id": other.server_id,
                "name": other.name,
                "limit_mb": limit,
                "running": other.server.running,
                "this": mine,
            }
        )
        total += limit or 0
    return total, rows


def overview(ctx: ServerContext) -> dict[str, Any]:
    """What the memory slider needs: the PC's measured total, this server's
    limit, and what running everything at once would add up to."""
    total = total_ram_mb()
    limit = _limit(ctx)
    together, rows = together_mb(ctx)
    return {
        "total_mb": total,
        "total_source": "measured (psutil)" if total else None,
        "limit_mb": limit,
        "jvm_args": [str(a) for a in ctx.config.server.jvm_args],
        "takes_memory_limit": ctx.config.server_type.takes_memory_limit,
        "min_mb": MIN_MB,
        "max_mb": total,
        "step_mb": STEP_MB,
        "together_mb": together,
        "servers": rows,
        "over": bool(total and together > total),
        "running": ctx.server.running,
    }


def check_limit(ctx: ServerContext, mb: int) -> int:
    total = total_ram_mb()
    if mb < MIN_MB:
        raise MemoryLimitError("Give the server at least 1 GB.")
    if total is None:
        raise MemoryLimitError(
            "This PC's memory couldn't be read, so the slider can't check the amount. "
            "Set it in Technical mode instead."
        )
    if mb > total:
        raise MemoryLimitError(
            f"This PC has {total / 1024:.1f} GB of memory, so a server can't be given more."
        )
    return mb


def start_warnings(ctx: ServerContext) -> list[str]:
    """Before a start: would this server, with the ones already running,
    be allowed more memory than the PC has?"""
    total = total_ram_mb()
    if not total:
        return []
    together, rows = together_mb(ctx)
    if together <= total:
        return []
    others = [r["name"] for r in rows if not r["this"]]
    with_others = f" together with {', '.join(others)}" if others else ""
    return [
        f"This server{with_others} may use up to {together / 1024:.1f} GB of memory, but this "
        f"PC has {total / 1024:.1f} GB. Windows may slow down or a server may crash. Lower "
        "the memory in Game settings."
    ]
