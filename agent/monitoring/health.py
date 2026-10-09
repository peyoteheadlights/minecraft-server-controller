"""The individual checks behind MetricsMonitor.health.

Each function returns one check: its value, its threshold, where the value
came from, and "unknown" (never a pass) when it could not be measured.
"""

from __future__ import annotations

from typing import Any

Check = dict[str, Any]


def check(
    name: str,
    ok: bool,
    value: Any,
    threshold: Any = None,
    detail: str = "",
    source: str = "",
    unknown: bool = False,
) -> Check:
    return {
        "name": name,
        "status": "unknown" if unknown else ("ok" if ok else "warn"),
        "value": value,
        "threshold": threshold,
        "detail": detail,
        "source": source,
    }


def process(server) -> Check:
    state = server.state.value
    if state == "UNKNOWN":
        return check(
            "Minecraft process",
            False,
            "UNKNOWN",
            "ONLINE",
            unknown=True,
            detail="The agent has not yet verified whether Minecraft is running.",
            source="not checked",
        )
    return check(
        "Minecraft process",
        state in ("ONLINE", "STARTING"),
        state,
        "ONLINE",
        detail=f"State is {state}",
        source=server._state_source(),
    )


def tps(server, th) -> Check:
    if server.tps is None:
        return check(
            "TPS",
            True,
            None,
            th.tps_min,
            unknown=True,
            detail=server.tps_unavailable_reason() or "No tick-rate source available",
            source="no provider answered",
        )
    return check(
        "TPS",
        server.tps >= th.tps_min,
        round(server.tps, 2),
        th.tps_min,
        f"Minimum acceptable is {th.tps_min}",
        source=server.tps_source or "server console reply",
    )


def mspt(server, th) -> Check:
    if server.mspt is None:
        return check(
            "MSPT",
            True,
            None,
            th.mspt_max,
            unknown=True,
            detail="No tick-time report has been received from the server.",
            source="no provider answered",
        )
    return check(
        "MSPT",
        server.mspt <= th.mspt_max,
        round(server.mspt, 1),
        th.mspt_max,
        f"Maximum acceptable is {th.mspt_max} ms",
        source=server.tps_source or "server console reply",
    )


def players(player_count: int | None, max_players: int) -> Check:
    if player_count is None:
        return check(
            "Players",
            True,
            None,
            None,
            unknown=True,
            detail="The player list has not been established yet. It becomes known "
            "when a player joins or leaves, when /list is answered, or when the "
            "server stops.",
            source="not established",
        )
    return check(
        "Players",
        True,
        player_count,
        max_players,
        detail="Players currently connected",
        source="console join/leave and /list",
    )


def cpu(snap: dict[str, Any], th) -> Check:
    if snap["cpu_percent"] is None:
        return check(
            "CPU",
            True,
            None,
            th.cpu_percent,
            "Not measured yet: CPU use needs two readings a second apart",
            source="psutil (operating system)",
            unknown=True,
        )
    return check(
        "CPU",
        snap["cpu_percent"] < th.cpu_percent,
        round(snap["cpu_percent"], 1),
        th.cpu_percent,
        "Whole-machine CPU use, percent",
        source="psutil (operating system)",
    )


def system_ram(snap: dict[str, Any], th) -> Check:
    return check(
        "System RAM",
        snap["ram_percent"] < th.ram_percent,
        round(snap["ram_percent"], 1),
        th.ram_percent,
        f"{snap['ram_used_mb'] / 1024:.1f} of {snap['ram_total_mb'] / 1024:.1f} GB used",
        source="psutil (operating system)",
    )


def minecraft_ram(snap: dict[str, Any], jvm_args: list[str]) -> Check:
    if snap["proc_ram_mb"] is None:
        return check(
            "Minecraft RAM",
            True,
            None,
            None,
            unknown=True,
            detail="The Minecraft process is not running, or its memory could not be "
            "read. The -Xmx value is an allocation limit, not a measurement, so "
            "it is not shown here.",
            source="not measured",
        )
    return check(
        "Minecraft RAM",
        True,
        round(snap["proc_ram_mb"] / 1024, 2),
        None,
        f"Actual process memory. Allocation limit is "
        f"{' '.join(str(a) for a in jvm_args) or 'not set'}",
        source="psutil process RSS",
    )


def disk(snap: dict[str, Any], th) -> Check:
    if snap["disk_free_gb"] is None:
        return check(
            "Disk space",
            True,
            None,
            th.disk_free_gb,
            unknown=True,
            detail=snap["disk_unknown_reason"],
            source="filesystem query failed",
        )
    return check(
        "Disk space",
        snap["disk_free_gb"] > th.disk_free_gb,
        round(snap["disk_free_gb"], 1),
        th.disk_free_gb,
        "Free space on the server drive, GB",
        source="filesystem query",
    )


def tailscale(ts: dict[str, Any]) -> Check:
    if ts["connected"] is None:
        return check(
            "Tailscale", True, None, None, unknown=True, detail=ts["detail"], source=ts["source"]
        )
    return check(
        "Tailscale",
        ts["connected"],
        ts.get("dns_name") or ts.get("address") or "connected",
        None,
        ts["detail"],
        source=ts["source"],
    )


def port(port_number: int, state: str, listening: bool | None, method: str = "tcp") -> Check:
    if state != "ONLINE" or listening is None:
        return check(
            f"Port {port_number}",
            True,
            None,
            "listening",
            unknown=True,
            detail="Not checked: the server is not online, so the port is not "
            "expected to be listening.",
            source="not checked",
        )
    return check(
        f"Port {port_number}",
        listening,
        "listening" if listening else "not listening",
        "listening",
        "Minecraft accepts connections when the server is online",
        source="Bedrock (RakNet) ping over UDP" if method == "raknet" else "TCP connect attempt",
    )


def certificate(cert: dict[str, Any], warn_days: float) -> Check:
    if not cert.get("parsed"):
        return check(
            "TLS certificate",
            False,
            "not readable",
            None,
            cert.get("parse_error") or "The certificate file could not be read",
            source="certificate file",
        )
    days = cert.get("days_remaining")
    return check(
        "TLS certificate",
        cert.get("expiry_severity") == "ok",
        f"{days:.0f} days remaining" if days is not None else None,
        warn_days,
        f"Issued by {cert.get('issuer')}",
        source="certificate file",
        unknown=days is None,
    )


def recent_crashes(count: int, window_minutes: float) -> Check:
    return check(
        "Recent crashes",
        count == 0,
        count,
        0,
        f"Crashes in the last {window_minutes} minutes",
        source="agent crash records",
    )


def summarize(checks: list[Check]) -> dict[str, Any]:
    """The overall verdict. Unknown checks are listed, never counted as passing."""
    unknown = [c["name"] for c in checks if c["status"] == "unknown"]
    warnings = [c["name"] for c in checks if c["status"] == "warn"]
    if warnings:
        overall = "ATTENTION NEEDED"
    elif unknown:
        overall = "PARTIALLY VERIFIED"
    else:
        overall = "ALL CHECKS VERIFIED"
    return {
        "overall": overall,
        "verified_count": len([c for c in checks if c["status"] != "unknown"]),
        "unverified": unknown,
        "warnings": warnings,
        "note": (
            "Some values could not be measured and are reported as unknown. "
            "They are not counted as passing."
        )
        if unknown
        else "",
    }
