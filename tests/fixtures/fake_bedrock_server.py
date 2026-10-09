"""A stand-in for Bedrock Dedicated Server, used by the test-suite.

It prints the console lines the real server prints (the formats in
bedrock_console.txt), reads server.properties from its working folder like
the real one, and answers the commands the agent sends:

  * list (two lines: the count, then the names)
  * save hold / save query / save resume, over the real files in worlds/
  * allowlist add/remove, op, deop and kick, writing allowlist.json and
    permissions.json the way the real server does
  * stop
  * fakejoin <name> <xuid> / fakeleave <name> (test-only, like the Java fake)

FAKE_BEDROCK_VERSION sets the version it reports. FAKE_SAVE_QUERY sets how
``save query`` behaves: "ok" (default; not ready the first time, then the
file list), "never" (never ready), "outside" (lists a path outside worlds/).
"""

import json
import os
import sys
import time

VERSION = os.environ.get("FAKE_BEDROCK_VERSION", "1.21.95.1")
SAVE_QUERY = os.environ.get("FAKE_SAVE_QUERY", "ok")
BOOT_DELAY = float(os.environ.get("FAKE_BOOT_DELAY", "0.2"))


def stamp() -> str:
    now = time.time()
    return (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)) + f":{int(now * 1000) % 1000:03d}"
    )


def log(message: str, level: str = "INFO") -> None:
    print(f"[{stamp()} {level}] {message}", flush=True)


def plain(message: str) -> None:
    print(message, flush=True)


def properties() -> dict[str, str]:
    values = {}
    try:
        with open("server.properties", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def read_json(name: str) -> list:
    try:
        with open(name, encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def write_json(name: str, data: list) -> None:
    with open(name, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def world_files(level: str) -> list[str]:
    """Every file of the world, as "path:length" inside worlds/."""
    root = os.path.join("worlds", level)
    found = []
    for folder, _dirs, names in os.walk(root):
        for name in sorted(names):
            full = os.path.join(folder, name)
            relative = os.path.relpath(full, "worlds").replace(os.sep, "/")
            found.append(f"{relative}:{os.path.getsize(full)}")
    return found


def main() -> None:
    props = properties()
    level = props.get("level-name", "Bedrock level")
    port = props.get("server-port", "19132")
    port_v6 = props.get("server-portv6", "19133")
    max_players = props.get("max-players", "10")
    online: dict[str, str] = {}
    holding = False
    queries = 0

    log("Starting Server")
    log(f"Version: {VERSION}")
    log("Session ID: 00000000-0000-0000-0000-000000000000")
    log(f"Level Name: {level}")
    os.makedirs(os.path.join("worlds", level, "db"), exist_ok=True)
    time.sleep(BOOT_DELAY)
    log(f"IPv4 supported, port: {port}: Used for gameplay and LAN discovery")
    log(f"IPv6 supported, port: {port_v6}: Used for gameplay")
    log("Server started.")

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        word, _, rest = line.partition(" ")
        word = word.lower()
        if word == "stop":
            log("Server stop requested.")
            log("Stopping server...")
            plain("Quit correctly")
            return
        if word == "list":
            log(f"There are {len(online)}/{max_players} players online:")
            plain(", ".join(online))
        elif word == "fakejoin":
            name, _, xuid = rest.rpartition(" ")
            online[name] = xuid
            log(f"Player connected: {name}, xuid: {xuid}")
        elif word == "fakeleave":
            xuid = online.pop(rest, "")
            log(f"Player disconnected: {rest}, xuid: {xuid}, pfid: 0123456789abcdef")
        elif word == "save":
            sub = rest.strip().lower()
            if sub == "hold":
                holding = True
                queries = 0
                plain("Saving...")
            elif sub == "query":
                queries += 1
                if not holding:
                    plain("A previous save has not been completed.")
                elif SAVE_QUERY == "never" or queries == 1:
                    plain("A previous save has not been completed.")
                else:
                    plain("Data saved. Files are now ready to be copied.")
                    files = world_files(level)
                    if SAVE_QUERY == "outside":
                        files.append("../server.properties:10")
                    plain(", ".join(files))
            elif sub == "resume":
                holding = False
                plain("Changes to the world are resumed.")
        elif word == "allowlist":
            action, _, who = rest.partition(" ")
            name = unquote(who)
            entries = read_json("allowlist.json")
            listed = any(e.get("name", "").lower() == name.lower() for e in entries)
            if action == "add":
                if listed:
                    plain("Player already in allowlist")
                else:
                    entries.append({"ignoresPlayerLimit": False, "name": name})
                    write_json("allowlist.json", entries)
                    plain("Player added to allowlist")
            elif action == "remove":
                if not listed:
                    plain("Player not in allowlist")
                else:
                    entries = [e for e in entries if e.get("name", "").lower() != name.lower()]
                    write_json("allowlist.json", entries)
                    plain("Player removed from allowlist")
        elif word in ("op", "deop"):
            name = unquote(rest)
            if name not in online:
                log("No targets matched selector")
                continue
            entries = [e for e in read_json("permissions.json") if e.get("xuid") != online[name]]
            if word == "op":
                entries.append({"permission": "operator", "xuid": online[name]})
                write_json("permissions.json", entries)
                log(f"Opped: {name}")
            else:
                write_json("permissions.json", entries)
                log(f"De-opped: {name}")
        elif word == "kick":
            name = unquote(
                rest.split(" ", 1)[0] if not rest.startswith('"') else rest.split('"')[1]
            )
            if name in online:
                online.pop(name)
                log(f"Kicked {name} from the game")
            else:
                log("No targets matched selector")
        elif word == "say":
            pass  # Bedrock's console doesn't print chat or say
        else:
            log(
                f"Unknown command: {word}. Please check that the command exists and that you "
                "have permission to use it.",
                "ERROR",
            )


if __name__ == "__main__":
    main()
