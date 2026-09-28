"""A stand-in for a Fabric Minecraft server, used by the test-suite.

It prints the same console lines a real server prints, accepts the same
commands on stdin, and can be told to crash - so start/stop/crash/restart
logic is tested for real, without a 6 GB JVM or a real world folder.
"""
import os
import sys
import time

BOOT_DELAY = float(os.environ.get("FAKE_BOOT_DELAY", "0.2"))
# A real server takes seconds to save and stop. Default 0 keeps the unit
# tests fast; the UI tests set it so the "Stopping…" state is observable.
STOP_DELAY = float(os.environ.get("FAKE_STOP_DELAY", "0"))
# Which TPS provider this fake server has: tick (vanilla 1.20.3+ `tick query`),
# carpet (`tps`), spark (`spark tps`) or none. Commands of a missing provider
# get the same "Unknown or incomplete command" reply a real server gives.
TPS_PROVIDER = os.environ.get("FAKE_TPS_PROVIDER", "tick")
MSPT = os.environ.get("FAKE_MSPT", "31.0")


def out(msg: str) -> None:
    print(msg, flush=True)


def stamp(thread: str, level: str, msg: str) -> str:
    return f"[{time.strftime('%H:%M:%S')}] [{thread}/{level}]: {msg}"


def main() -> int:
    out(stamp("main", "INFO", "Loading Minecraft 1.21.1 with Fabric Loader 0.16.5"))
    # Behave like Fabric: scan the mods folder in the working directory and
    # load only files ending in exactly ".jar". Anything renamed to
    # ".jar.disabled" is ignored, which is what makes the disable feature
    # testable for real rather than by assertion about a filename.
    loaded = sorted(
        name for name in os.listdir("mods")
        if name.endswith(".jar")
    ) if os.path.isdir("mods") else []
    out(stamp("main", "INFO", f"Loading {len(loaded)} mods:"))
    for name in loaded:
        out(stamp("main", "INFO", f"\t- {name[:-4]}"))
    if os.environ.get("FAKE_CRASH_ON_START") == "1":
        out(stamp("main", "ERROR", "Exception in thread \"main\" java.lang.OutOfMemoryError: Java heap space"))
        out("\tat net.minecraft.server.Main.main(Main.java:120)")
        return 1
    if os.environ.get("FAKE_MIXIN_CRASH") == "1":
        out(stamp("main", "ERROR", "Mixin apply for mod voxy failed voxy.mixins.json:RenderMixin -> net.minecraft.class_310: org.spongepowered.asm.mixin.injection.throwables.InjectionError LVT changed"))
        return 1
    time.sleep(BOOT_DELAY)
    out(stamp("Server thread", "INFO", "Starting minecraft server version 1.21.1"))
    out(stamp("Server thread", "INFO", "Starting Minecraft server on *:25565"))
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
                out(stamp("Server thread", "INFO", "Unknown or incomplete command, see below for error"))
                out(stamp("Server thread", "INFO", f"{cmd}<--[HERE]"))
            elif provider == "tick":
                out(stamp("Server thread", "INFO", "The game is running normally"))
                out(stamp("Server thread", "INFO", "Target tick rate: 20.0 per second."))
                out(stamp("Server thread", "INFO", f"Average time per tick: {MSPT}ms (Target: 50.0ms)"))
            elif provider == "carpet":
                out(stamp("Server thread", "INFO", f"TPS: 19.8 MSPT: {MSPT}"))
            else:
                out(stamp("Server thread", "INFO",
                          "TPS from last 5s, 10s, 1m, 5m, 15m: 19.9, 19.9, 20.0, 20.0, 20.0"))
            continue
        if cmd == "list":
            names = ", ".join(players)
            out(stamp("Server thread", "INFO",
                      f"There are {len(players)} of a max of 20 players online: {names}"))
            continue
        if cmd.startswith("fakejoin "):
            name = cmd.split(" ", 1)[1]
            players.append(name)
            out(stamp("User Authenticator #1", "INFO",
                      f"UUID of player {name} is 069a79f4-44e9-4726-a5be-fca90e38aaf5"))
            out(stamp("Server thread", "INFO", f"{name} joined the game"))
            continue
        if cmd.startswith("fakeleave "):
            name = cmd.split(" ", 1)[1]
            if name in players:
                players.remove(name)
            out(stamp("Server thread", "INFO", f"{name} left the game"))
            continue
        out(stamp("Server thread", "INFO", f"[Console] {cmd}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
