"""A stand-in for a Minecraft server, used by the test-suite.

It prints the same console lines a real server prints, accepts the same
commands on stdin, and can be told to crash - so start/stop/crash/restart
logic is tested for real, without a 6 GB JVM or a real world folder.

FAKE_TYPE picks which server type it imitates (fabric, quilt, forge,
neoforge, paper, purpur or vanilla), so each type's version and loader
line is parsed from a real console line rather than asserted about.
FAKE_MC_VERSION sets the Minecraft version it reports, which is how a
version change is confirmed the way a real server confirms it.
"""

import json
import os
import sys
import time


def configured_port() -> str:
    """server-port from server.properties in the working folder, like the
    real server."""
    try:
        with open("server.properties", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("server-port="):
                    return line.split("=", 1)[1].strip() or "25565"
    except OSError:
        pass
    return "25565"


BOOT_DELAY = float(os.environ.get("FAKE_BOOT_DELAY", "0.2"))
# A real server takes seconds to save and stop. Default 0 keeps the unit
# tests fast; the UI tests set it so the "Stopping…" state is observable.
STOP_DELAY = float(os.environ.get("FAKE_STOP_DELAY", "0"))
# Which TPS provider this fake server has: tick (vanilla 1.20.3+ `tick query`),
# carpet (`tps`), spark (`spark tps`) or none. Commands of a missing provider
# get the same "Unknown or incomplete command" reply a real server gives.
TPS_PROVIDER = os.environ.get("FAKE_TPS_PROVIDER", "tick")
MSPT = os.environ.get("FAKE_MSPT", "31.0")
# Which server type this fake imitates, and the version it reports.
SERVER_TYPE = os.environ.get("FAKE_TYPE", "fabric")
MC_VERSION = os.environ.get("FAKE_MC_VERSION", "1.21.1")
LOADER_VERSION = os.environ.get("FAKE_LOADER_VERSION", "")
# Refuse to start until eula.txt says eula=true, like the real server.
CHECK_EULA = os.environ.get("FAKE_CHECK_EULA") == "1"


def out(msg: str) -> None:
    print(msg, flush=True)


def stamp(thread: str, level: str, msg: str) -> str:
    return f"[{time.strftime('%H:%M:%S')}] [{thread}/{level}]: {msg}"


def eula_accepted() -> bool:
    try:
        with open("eula.txt", encoding="utf-8") as fh:
            return "eula=true" in fh.read().lower()
    except OSError:
        return False


# The player lists Minecraft keeps, as Minecraft writes them, so the
# Players page's buttons are answered the way a real server answers them.
LISTS = {"whitelist": "whitelist.json", "ops": "ops.json", "banned": "banned-players.json"}
FAKE_UUID = "069a79f4-44e9-4726-a5be-fca90e38aaf5"


def read_list(which: str) -> list[dict]:
    try:
        with open(LISTS[which], encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def write_list(which: str, entries: list[dict]) -> None:
    with open(LISTS[which], "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)


def player_command(cmd: str, players: list[str]) -> str | None:
    """The line vanilla Minecraft prints for a player command, after
    changing its list file the way Minecraft does. None: not one of them."""
    parts = cmd.split(" ")
    word = parts[0]
    if word == "whitelist" and len(parts) >= 3 and parts[1] in ("add", "remove"):
        name = parts[2]
        entries = read_list("whitelist")
        listed = any(e["name"].lower() == name.lower() for e in entries)
        if parts[1] == "add":
            if listed:
                return "Player is already whitelisted"
            write_list("whitelist", [*entries, {"uuid": FAKE_UUID, "name": name}])
            return f"Added {name} to the whitelist"
        if not listed:
            return "Player is not whitelisted"
        write_list("whitelist", [e for e in entries if e["name"].lower() != name.lower()])
        return f"Removed {name} from the whitelist"
    if word in ("op", "deop") and len(parts) == 2:
        name = parts[1]
        entries = read_list("ops")
        listed = any(e["name"].lower() == name.lower() for e in entries)
        if word == "op":
            if listed:
                return "Nothing changed. The player already is an operator"
            entry = {"uuid": FAKE_UUID, "name": name, "level": 4, "bypassesPlayerLimit": False}
            write_list("ops", [*entries, entry])
            return f"Made {name} a server operator"
        if not listed:
            return "Nothing changed. The player is not an operator"
        write_list("ops", [e for e in entries if e["name"].lower() != name.lower()])
        return f"Made {name} no longer a server operator"
    if word == "kick" and len(parts) >= 2:
        name = parts[1]
        if name not in players:
            return "No player was found"
        players.remove(name)
        reason = " ".join(parts[2:]) or "Kicked by an operator"
        return f"Kicked {name}: {reason}"
    if word == "ban" and len(parts) >= 2:
        name = parts[1]
        entries = read_list("banned")
        if any(e["name"].lower() == name.lower() for e in entries):
            return "Nothing changed. The player is already banned"
        reason = " ".join(parts[2:]) or "Banned by an operator."
        entry = {
            "uuid": FAKE_UUID,
            "name": name,
            "created": "2026-10-05 22:00:00 +0000",
            "source": "Server",
            "expires": "forever",
            "reason": reason,
        }
        write_list("banned", [*entries, entry])
        if name in players:
            players.remove(name)
        return f"Banned {name}: {reason}"
    if word == "pardon" and len(parts) == 2:
        name = parts[1]
        entries = read_list("banned")
        if not any(e["name"].lower() == name.lower() for e in entries):
            return "Nothing changed. The player isn't banned"
        write_list("banned", [e for e in entries if e["name"].lower() != name.lower()])
        return f"Unbanned {name}"
    return None


def startup_lines() -> list[str]:
    """The version and loader lines this type prints when it starts."""
    loader = LOADER_VERSION
    if SERVER_TYPE in ("fabric", "quilt"):
        name = "Fabric" if SERVER_TYPE == "fabric" else "Quilt"
        version = loader or ("0.16.5" if SERVER_TYPE == "fabric" else "0.26.0")
        return [
            stamp("main", "INFO", f"Loading Minecraft {MC_VERSION} with {name} Loader {version}")
        ]
    if SERVER_TYPE in ("forge", "neoforge"):
        name = "MinecraftForge" if SERVER_TYPE == "forge" else "NeoForge"
        version = loader or ("47.3.0" if SERVER_TYPE == "forge" else "21.1.9")
        return [
            stamp("main", "INFO", f"Starting minecraft server version {MC_VERSION}"),
            stamp("main", "INFO", f"{name} v{version} Initialized"),
        ]
    if SERVER_TYPE in ("paper", "purpur"):
        name = "Paper" if SERVER_TYPE == "paper" else "Purpur"
        version = loader or f"{MC_VERSION}-129-main@abc1234"
        return [
            stamp(
                "Server thread",
                "INFO",
                f"This server is running {name} version {version} "
                f"(Implementing API version {MC_VERSION}-R0.1-SNAPSHOT) (MC: {MC_VERSION})",
            )
        ]
    return [stamp("Server thread", "INFO", f"Starting minecraft server version {MC_VERSION}")]


def main() -> int:
    if CHECK_EULA and not eula_accepted():
        out(
            stamp(
                "main",
                "WARN",
                "You need to agree to the EULA in order to run the server. "
                "Go to eula.txt for more info.",
            )
        )
        return 0
    for line in startup_lines():
        out(line)
    # Behave like Fabric: scan the mods folder in the working directory and
    # load only files ending in exactly ".jar". Anything renamed to
    # ".jar.disabled" is ignored, which is what makes the disable feature
    # testable for real rather than by assertion about a filename.
    loaded = (
        sorted(name for name in os.listdir("mods") if name.endswith(".jar"))
        if os.path.isdir("mods")
        else []
    )
    out(stamp("main", "INFO", f"Loading {len(loaded)} mods:"))
    for name in loaded:
        out(stamp("main", "INFO", f"\t- {name[:-4]}"))
    if os.environ.get("FAKE_CRASH_ON_START") == "1":
        out(
            stamp(
                "main",
                "ERROR",
                'Exception in thread "main" java.lang.OutOfMemoryError: Java heap space',
            )
        )
        out("\tat net.minecraft.server.Main.main(Main.java:120)")
        return 1
    if os.environ.get("FAKE_MIXIN_CRASH") == "1":
        out(
            stamp(
                "main",
                "ERROR",
                "Mixin apply for mod voxy failed voxy.mixins.json:RenderMixin -> net.minecraft.class_310: org.spongepowered.asm.mixin.injection.throwables.InjectionError LVT changed",
            )
        )
        return 1
    time.sleep(BOOT_DELAY)
    if SERVER_TYPE in ("fabric", "quilt"):
        out(stamp("Server thread", "INFO", f"Starting minecraft server version {MC_VERSION}"))
    out(stamp("Server thread", "INFO", f"Starting Minecraft server on *:{configured_port()}"))
    if os.environ.get("FAKE_HANG") == "1":
        while True:
            time.sleep(1)
    out(stamp("Server thread", "INFO", 'Done (1.234s)! For help, type "help"'))

    players: list[str] = []
    for raw in sys.stdin:
        cmd = raw.strip()
        if not cmd:
            continue
        if cmd == "stop":
            out(stamp("Server thread", "INFO", "Stopping server"))
            out(stamp("Server thread", "INFO", "Saving worlds"))
            time.sleep(STOP_DELAY)
            return 0
        if cmd == "crash":
            out(stamp("Server thread", "ERROR", "java.lang.OutOfMemoryError: Java heap space"))
            return 1
        if cmd in ("tick query", "tps", "spark tps"):
            provider = {"tick query": "tick", "tps": "carpet", "spark tps": "spark"}[cmd]
            if provider != TPS_PROVIDER:
                out(
                    stamp(
                        "Server thread",
                        "INFO",
                        "Unknown or incomplete command, see below for error",
                    )
                )
                out(stamp("Server thread", "INFO", f"{cmd}<--[HERE]"))
            elif provider == "tick":
                out(stamp("Server thread", "INFO", "The game is running normally"))
                out(stamp("Server thread", "INFO", "Target tick rate: 20.0 per second."))
                out(
                    stamp(
                        "Server thread", "INFO", f"Average time per tick: {MSPT}ms (Target: 50.0ms)"
                    )
                )
            elif provider == "carpet":
                out(stamp("Server thread", "INFO", f"TPS: 19.8 MSPT: {MSPT}"))
            else:
                out(
                    stamp(
                        "Server thread",
                        "INFO",
                        "TPS from last 5s, 10s, 1m, 5m, 15m: 19.9, 19.9, 20.0, 20.0, 20.0",
                    )
                )
            continue
        if cmd == "list":
            names = ", ".join(players)
            out(
                stamp(
                    "Server thread",
                    "INFO",
                    f"There are {len(players)} of a max of 20 players online: {names}",
                )
            )
            continue
        if cmd.startswith("fakejoin "):
            name = cmd.split(" ", 1)[1]
            players.append(name)
            out(
                stamp(
                    "User Authenticator #1",
                    "INFO",
                    f"UUID of player {name} is 069a79f4-44e9-4726-a5be-fca90e38aaf5",
                )
            )
            out(stamp("Server thread", "INFO", f"{name} joined the game"))
            continue
        if cmd.startswith("fakeleave "):
            name = cmd.split(" ", 1)[1]
            if name in players:
                players.remove(name)
            out(stamp("Server thread", "INFO", f"{name} left the game"))
            continue
        before = list(players)
        answer = player_command(cmd, players)
        if answer is not None:
            out(stamp("Server thread", "INFO", answer))
            for name in before:
                if name not in players:  # kicked or banned while online
                    out(stamp("Server thread", "INFO", f"{name} left the game"))
            continue
        out(stamp("Server thread", "INFO", f"[Console] {cmd}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
