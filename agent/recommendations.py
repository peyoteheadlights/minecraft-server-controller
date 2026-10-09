"""Suggested fixes for one server, behind the Overview's Recommendations card.

Each rule looks at measured facts only (house rule 1) and either says
nothing or returns one recommendation: what to do, one line on why, the
evidence it is based on, and where in the dashboard the fix is. A rule
never fires from a value nobody measured, and nothing here changes
anything on the PC; the person always presses the button themselves.

Later features add rules here (updates) instead of adding banners of
their own.

The person can dismiss a recommendation (hidden on this server until they
bring it back) or snooze it (hidden until its evidence changes, or until the
problem goes away and comes back).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import appinfo, memory
from .minecraft.java import memory_limit_mb

DAY = 86400.0
BACKUP_MAX_AGE_DAYS = 7
MEMORY_CRASH_DAYS = 7  # out-of-memory crashes this recent count
BUSY_PLAYERS = 2  # "player count is high" for a home server
SLOW_SHARE = 0.25  # speed below the alert line in a quarter of busy samples
SLOW_MIN_SAMPLES = 5


@dataclass
class Facts:
    """Everything the rules may look at, as measured. None means unknown."""

    now: float
    backups: list[dict[str, Any]]  # newest first
    schedules: list[dict[str, Any]]
    samples: list[dict[str, Any]]  # the last hour of metrics, oldest first
    sample_interval: float
    memory_limit_mb: int | None
    disk_free_gb: float | None
    disk_alert_gb: float
    tps_alert: float
    mod_updates: list[dict[str, Any]]
    java: dict[str, Any] | None  # java_compatibility from the server status
    auto_restart: bool
    crashes: list[dict[str, Any]] = field(default_factory=list)  # newest first
    # TPS detection's result for this start (agent/monitoring/tps.py).
    tps: dict[str, Any] | None = None
    modrinth: bool = False  # this server type installs mods from Modrinth
    spark_installed: bool | None = None
    # The running servers' memory limits added up, against the PC's
    # measured total (agent/memory.py). None when RAM couldn't be read.
    memory: dict[str, Any] | None = None
    power: dict[str, Any] | None = None  # agent/keepawake.py status()
    offsite_folder: str = ""  # backups.offsite_directory, "" when off
    # Installed with the setup, whose Start menu entry installs Java.
    installed: bool = False


@dataclass
class Recommendation:
    id: str
    title: str
    reason: str
    evidence: str
    action: dict[str, str]  # {"label": ..., "page": ...}
    fingerprint: str
    details: dict[str, Any] = field(default_factory=dict)  # numbers and sources

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "reason": self.reason,
            "evidence": self.evidence,
            "action": self.action,
            "details": self.details,
        }


Rule = Callable[[Facts], Recommendation | None]


def _days(seconds: float) -> str:
    days = int(seconds // DAY)
    return "1 day" if days == 1 else f"{days} days"


def no_recent_backup(f: Facts) -> Recommendation | None:
    good = [b for b in f.backups if b.get("status") == "ok"]
    if not good:
        return Recommendation(
            id="no_backup",
            title="Take a first backup",
            reason="If the world breaks, a backup is the only way back.",
            evidence="No checked backup of this server exists yet.",
            action={"label": "Back up now", "page": "backups"},
            fingerprint="none",
            details={"backups_recorded": len(f.backups), "source": "backups table"},
        )
    newest = good[0]
    age = f.now - float(newest["created_at"])
    if age < BACKUP_MAX_AGE_DAYS * DAY:
        return None
    return Recommendation(
        id="old_backup",
        title="Back up the world",
        reason="The newest backup is over a week old. A problem now would lose that week.",
        evidence=f"Last checked backup was {_days(age)} ago ({newest['name']}).",
        action={"label": "Back up now", "page": "backups"},
        fingerprint=f"backup:{newest['id']}",
        details={"backup": newest["name"], "age_seconds": round(age), "source": "backups table"},
    )


def no_backup_schedule(f: Facts) -> Recommendation | None:
    if any(s.get("enabled") and s.get("task") == "backup" for s in f.schedules):
        return None
    return Recommendation(
        id="no_backup_schedule",
        title="Back up automatically",
        reason="A daily backup means you never have to remember.",
        evidence="No backup schedule is on for this server.",
        action={"label": "Add schedule", "page": "schedules"},
        fingerprint=f"schedules:{len(f.schedules)}",
        details={"schedules": len(f.schedules), "source": "schedules table"},
    )


def memory_ran_out(f: Facts) -> Recommendation | None:
    """Fires on crashes the log proved were out of memory, not on the
    process's memory use: that includes Java's own overhead on top of the
    -Xmx heap limit, so a healthy server routinely sits at or above it."""
    cutoff = f.now - MEMORY_CRASH_DAYS * DAY
    crashes = [
        c
        for c in f.crashes
        if c.get("category") == "OutOfMemoryError" and float(c.get("ts") or 0) >= cutoff
    ]
    if not crashes:
        return None
    count = len(crashes)
    times = "once" if count == 1 else f"{count} times"
    age = f.now - float(crashes[0]["ts"])
    last = "under a day ago" if age < DAY else f"{_days(age)} ago"
    limit = f" The limit is {f.memory_limit_mb / 1024:g} GB." if f.memory_limit_mb else ""
    return Recommendation(
        id="memory_ran_out",
        title="Give the server more memory",
        reason="It crashed because it ran out of memory.",
        evidence=f"The log shows it ran out of memory {times} in the last "
        f"{MEMORY_CRASH_DAYS} days, last {last}.{limit}",
        action={"label": "Open settings", "page": "settings"},
        fingerprint=f"oom:{crashes[0].get('id')}:{f.memory_limit_mb}",
        details={
            "crashes": count,
            "limit_mb": f.memory_limit_mb,
            "source": "crash records (java.lang.OutOfMemoryError in the log); limit from -Xmx",
        },
    )


def disk_low(f: Facts) -> Recommendation | None:
    if f.disk_free_gb is None or f.disk_free_gb >= f.disk_alert_gb:
        return None
    return Recommendation(
        id="disk_low",
        title="Free up disk space",
        reason="Backups and the world stop saving when the drive is full.",
        evidence=f"{f.disk_free_gb:.1f} GB free on the server's drive, below the "
        f"{f.disk_alert_gb:g} GB alert line.",
        action={"label": "See what uses space", "page": "performance"},
        fingerprint=f"disk:{int(f.disk_free_gb)}",
        details={"free_gb": f.disk_free_gb, "alert_gb": f.disk_alert_gb, "source": "disk usage"},
    )


def mod_updates(f: Facts) -> Recommendation | None:
    if not f.mod_updates:
        return None
    names = [m["name"] for m in f.mod_updates]
    shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    count = len(names)
    return Recommendation(
        id="mod_updates",
        title=f"Update {count} mod{'s' if count != 1 else ''}",
        reason="Updates often fix bugs and crashes.",
        evidence=f"Modrinth has newer builds for {shown}.",
        action={"label": "Open mods", "page": "mods"},
        fingerprint="updates:" + ",".join(sorted(m["mod_id"] for m in f.mod_updates)),
        details={"mods": names, "source": "last Modrinth update check"},
    )


def java_too_old(f: Facts) -> Recommendation | None:
    if not f.java or f.java.get("verdict") != "incompatible":
        return None
    reason = "This Minecraft version won't start on the Java installed now."
    if f.installed:
        # The setup installs Java and points this server at it, on the PC.
        reason += (
            f' On the PC, open "{appinfo.SETUP_SHORTCUT}" from the Start menu, then '
            '"Java for your servers", and tick this server.'
        )
    return Recommendation(
        id="java_too_old",
        title=f"Install Java {f.java['required']}",
        reason=reason,
        evidence=f"Minecraft {f.java['minecraft_version']} needs Java {f.java['required']}; "
        f"this PC has Java {f.java['java_major']}.",
        action={"label": "Get Java", "url": "https://adoptium.net/temurin/releases/"},
        fingerprint=f"java:{f.java['java_major']}:{f.java['required']}",
        details={k: f.java.get(k) for k in ("java_major", "required", "minecraft_version")},
    )


def auto_restart_off(f: Facts) -> Recommendation | None:
    if f.auto_restart:
        return None
    return Recommendation(
        id="auto_restart_off",
        title="Restart after a crash",
        reason="With this off, a crash keeps the server down until someone starts it.",
        evidence="Restart after a crash is off.",
        action={"label": "Open settings", "page": "settings"},
        fingerprint="auto_restart:off",
        details={"setting": "monitor.auto_restart", "value": False},
    )


def slow_while_busy(f: Facts) -> Recommendation | None:
    busy = [
        s
        for s in f.samples
        if s.get("players") is not None
        and s["players"] >= BUSY_PLAYERS
        and s.get("tps") is not None
    ]
    slow = [s for s in busy if s["tps"] < f.tps_alert]
    if len(slow) < SLOW_MIN_SAMPLES or len(slow) < SLOW_SHARE * len(busy):
        return None
    worst = min(s["tps"] for s in slow)
    return Recommendation(
        id="slow_while_busy",
        title="Reduce lag when friends play",
        reason="The server falls behind when several people are on.",
        evidence=f"Game speed dropped below {f.tps_alert:g} of 20 in {len(slow)} of {len(busy)} "
        f"readings with {BUSY_PLAYERS} or more players in the last hour (lowest {worst:.1f}).",
        action={"label": "Open performance", "page": "performance"},
        fingerprint=f"slow:{len(slow) // 10}",
        details={
            "busy_samples": len(busy),
            "slow_samples": len(slow),
            "lowest_tps": worst,
            "tps_alert": f.tps_alert,
            "source": "TPS samples with player counts",
        },
    )


def install_spark(f: Facts) -> Recommendation | None:
    """Only when automatic detection asked and nothing answered. spark adds
    a way to read the game speed; it does not make anything faster."""
    tps = f.tps or {}
    if (
        not f.modrinth
        or f.spark_installed is not False
        or tps.get("mode") != "auto"
        or tps.get("state") != "unavailable"
        or not tps.get("tried")
    ):
        return None
    tried = ", ".join(str(t.get("command")) for t in tps["tried"])
    return Recommendation(
        id="install_spark",
        title="Install spark to see game speed",
        reason="Game speed shows as Unknown because nothing on this server reports it.",
        evidence=f"Asked with {tried} when the server started; none answered.",
        action={"label": "Find spark", "page": "mods", "search": "spark"},
        fingerprint="spark:" + ",".join(sorted(str(t.get("command")) for t in tps["tried"])),
        details={"tried": [t.get("command") for t in tps["tried"]], "source": "TPS detection"},
    )


def memory_over_pc(f: Facts) -> Recommendation | None:
    m = f.memory
    if not m or not m.get("total_mb") or m["together_mb"] <= m["total_mb"]:
        return None
    names = ", ".join(m["names"])
    return Recommendation(
        id="memory_over_pc",
        title="Lower the memory limits",
        reason="Running servers are allowed more memory than the PC has, so one may crash.",
        evidence=f"{names} may use up to {m['together_mb'] / 1024:.1f} GB together; this PC "
        f"has {m['total_mb'] / 1024:.1f} GB.",
        action={"label": "Open game settings", "page": "game-settings"},
        fingerprint=f"memory:{m['together_mb']}:{m['total_mb']}",
        details={**m, "source": "-Xmx of running servers; total memory measured by psutil"},
    )


def pc_may_sleep(f: Facts) -> Recommendation | None:
    p = f.power
    if not p or not p.get("supported"):
        return None
    if not p.get("enabled"):
        return Recommendation(
            id="pc_may_sleep",
            title="Keep the PC awake",
            reason="If Windows sleeps, the server stops for everyone playing.",
            evidence="Keep the PC awake is off.",
            action={"label": "Open app settings", "page": "app-settings"},
            fingerprint="keep_awake:off",
            details={"setting": "power.keep_awake", "value": False},
        )
    notes = p.get("still_sleeps") or []
    if not notes:
        return None
    if "on_battery" in notes:
        evidence = "This PC is running on battery. Windows can still sleep when it runs low."
    else:
        evidence = "Closing the lid puts this PC to sleep (Windows power settings)."
    return Recommendation(
        id="pc_may_sleep",
        title="Windows can still sleep",
        reason="Keep awake is on, but some things still put the PC to sleep.",
        evidence=evidence,
        action={"label": "Open app settings", "page": "app-settings"},
        fingerprint="sleep:" + ",".join(sorted(notes)),
        details={"still_sleeps": notes, "source": "battery (psutil), lid (Windows power plan)"},
    )


def offsite_backups(f: Facts) -> Recommendation | None:
    good = [b for b in f.backups if b.get("status") == "ok"]
    if not good:
        return None  # no_backup comes first
    if not f.offsite_folder:
        return Recommendation(
            id="offsite_backups",
            title="Keep a copy off this PC",
            reason="Backups on the same drive are lost if the drive fails.",
            evidence="No folder for second copies is set.",
            action={"label": "Open backups", "page": "backups"},
            fingerprint="offsite:none",
            details={"setting": "backups.offsite_directory", "value": ""},
        )
    newest = good[0]
    copy = newest.get("copy") or {}
    if copy.get("state") in ("failed", "unreachable", "missing"):
        return Recommendation(
            id="offsite_copy_failed",
            title="Copy the newest backup off the PC",
            reason="The newest backup has no second copy.",
            evidence=f"{newest['name']}: {copy.get('reason') or 'not copied'}.",
            action={"label": "Open backups", "page": "backups"},
            fingerprint=f"offsite:{newest['id']}:{copy.get('state')}",
            details={"backup": newest["name"], "copy": copy, "source": "backups table"},
        )
    return None


RULES: tuple[Rule, ...] = (
    java_too_old,
    no_recent_backup,
    no_backup_schedule,
    disk_low,
    memory_ran_out,
    slow_while_busy,
    memory_over_pc,
    offsite_backups,
    pc_may_sleep,
    auto_restart_off,
    install_spark,
    mod_updates,
)


def evaluate(facts: Facts) -> list[Recommendation]:
    found = []
    for rule in RULES:
        result = rule(facts)
        if result is not None:
            found.append(result)
    return found


def gather(ctx) -> Facts:
    """Read one server's measured facts for the rules."""
    status = ctx.server.status()
    # The sampler's latest reading. Taking a fresh one here would restart
    # the sampler's network and process CPU windows.
    last = ctx.metrics.last or {}
    installed = ctx.mods.list_installed(use_cache=True)
    updates = [
        {"mod_id": m["mod_id"], "name": m["name"]} for m in installed if m.get("update_available")
    ]
    server_type = ctx.config.server_type
    spark = any(
        "spark" in str(m.get(k) or "").lower()
        for m in installed
        for k in ("mod_id", "name", "filename")
    )
    total = memory.total_ram_mb()
    running_mb, rows = memory.together_mb(ctx, include_self=ctx.server.running)
    running = [r for r in rows if r["running"]]
    keepawake = getattr(ctx.core, "keepawake", None)
    return Facts(
        now=time.time(),
        backups=ctx.backups.list_backups(),
        schedules=ctx.scheduler.list_schedules(),
        samples=ctx.metrics.history(hours=1),
        sample_interval=float(ctx.config.monitor.sample_interval),
        memory_limit_mb=memory_limit_mb(ctx.config.server.jvm_args),
        disk_free_gb=last.get("disk_free_gb"),
        disk_alert_gb=float(ctx.config.thresholds.disk_free_gb),
        tps_alert=float(ctx.config.thresholds.tps_min),
        mod_updates=updates,
        java=status.get("java_compatibility"),
        auto_restart=bool(ctx.config.monitor.auto_restart),
        crashes=ctx.crashes.list_crashes(limit=50),
        tps=dict(ctx.server.tps_status or {}) if getattr(ctx.server, "tps_status", None) else None,
        modrinth=server_type.modrinth,
        spark_installed=spark if server_type.modrinth else None,
        memory=(
            {
                "total_mb": total,
                "together_mb": running_mb,
                "names": [r["name"] for r in running],
            }
            if total and running
            else None
        ),
        power=keepawake.status() if keepawake else None,
        offsite_folder=ctx.config.backups.offsite_directory.strip(),
        installed=appinfo.installed(),
    )


STATE_KEY = "recommendations"


def visible(db, found: list[Recommendation]) -> dict[str, Any]:
    """Apply the person's dismissals and snoozes. A snooze ends when the
    rule's evidence changes or when the rule stops firing."""
    saved = db.get_setting(STATE_KEY, {}) or {}
    dismissed = set(saved.get("dismissed", []))
    snoozed = dict(saved.get("snoozed", {}))
    firing = {r.id: r for r in found}
    still = {
        rid: fp for rid, fp in snoozed.items() if rid in firing and firing[rid].fingerprint == fp
    }
    if still != snoozed:
        db.set_setting(STATE_KEY, {"dismissed": sorted(dismissed), "snoozed": still})
    shown = [r for r in found if r.id not in dismissed and r.id not in still]
    hidden = [r for r in found if r.id in dismissed or r.id in still]
    return {
        "recommendations": [r.to_dict() for r in shown],
        "hidden": [{**r.to_dict(), "dismissed": r.id in dismissed} for r in hidden],
    }


def act(db, found: list[Recommendation], rec_id: str, action: str) -> None:
    """Dismiss, snooze or bring back one recommendation."""
    saved = db.get_setting(STATE_KEY, {}) or {}
    dismissed = set(saved.get("dismissed", []))
    snoozed = dict(saved.get("snoozed", {}))
    if action == "restore":
        dismissed.discard(rec_id)
        snoozed.pop(rec_id, None)
    else:
        current = next((r for r in found if r.id == rec_id), None)
        if current is None:
            raise LookupError("That suggestion no longer applies")
        if action == "dismiss":
            dismissed.add(rec_id)
        else:
            snoozed[rec_id] = current.fingerprint
    db.set_setting(STATE_KEY, {"dismissed": sorted(dismissed), "snoozed": snoozed})
