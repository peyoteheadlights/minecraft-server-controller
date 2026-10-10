"""Make the phone apps' shared files from the dashboard's own, so the
dashboard and both apps never say or look different.

    python mobile/tools/generate.py           # write mobile/shared/
    python mobile/tools/generate.py --check   # fail if they are out of date (CI)

Writes into mobile/shared/ (never edit those by hand):

  strings.json       every [Simple, Technical] pair: the dashboard's table
                     (agent/web/js/strings.js) plus the app's own words
                     (mobile/app-strings.json, keys starting "mobile.")
  feed.json          which event types have a sentence in the activity feed
                     (agent/web/js/feed.js FEED), and its strings key
  theme.json         each theme's colors (agent/web/styles.css)
  palette.json       the twelve server colors (agent/colors.py)
  color-cases.json   what colors.js derives for each palette color in each
                     theme, for the apps' tests (needs Node)
  version.json       the app's version and the agent API versions it works
                     with (mobile/version.json), plus the agent's own

Standard library only, so it runs anywhere Python 3.12 does.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOBILE = ROOT / "mobile"
SHARED = MOBILE / "shared"
WEB = ROOT / "agent" / "web"
THEMES = {
    "light": r":root\s*\{",
    "dark": r':root\[data-theme="dark"\]\s*\{',
    "graphite": r':root\[data-theme="graphite"\]\s*\{',
    "contrast": r':root\[data-theme="contrast"\]\s*\{',
}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def dashboard_strings() -> dict[str, list[str]]:
    source = (WEB / "js" / "strings.js").read_text(encoding="utf-8")
    match = re.search(r"/\* strings-table \*/(.*?)/\* end-strings-table \*/", source, re.S)
    if not match:
        raise SystemExit("agent/web/js/strings.js lost its table markers")
    return json.loads(match.group(1))


def app_strings() -> dict[str, list[str]]:
    data = json.loads((MOBILE / "app-strings.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("//")}


def check_pairs(table: dict[str, list[str]], where: str) -> None:
    for key, pair in table.items():
        if not (
            isinstance(pair, list) and len(pair) == 2 and all(isinstance(t, str) for t in pair)
        ):
            raise SystemExit(f"{where}: {key} needs exactly [Simple, Technical]")
        if set(PLACEHOLDER.findall(pair[0])) != set(PLACEHOLDER.findall(pair[1])):
            raise SystemExit(f"{where}: {key}'s two versions use different {{placeholders}}")


def strings() -> dict[str, list[str]]:
    web, app = dashboard_strings(), app_strings()
    check_pairs(web, "strings.js")
    check_pairs(app, "mobile/app-strings.json")
    for key in app:
        if not key.startswith("mobile."):
            raise SystemExit(f"mobile/app-strings.json: {key} must start with 'mobile.'")
        if key in web:
            raise SystemExit(f"mobile/app-strings.json: {key} is already in strings.js")
    return {**web, **app}


def feed() -> dict[str, str]:
    source = (WEB / "js" / "feed.js").read_text(encoding="utf-8")
    match = re.search(r"export const FEED = \{(.*?)\n\};", source, re.S)
    if not match:
        raise SystemExit("agent/web/js/feed.js lost its FEED table")
    pairs = re.findall(r"^\s*([a-z_]+):\s*\"([a-z0-9_.]+)\"", match.group(1), re.M)
    if not pairs:
        raise SystemExit("agent/web/js/feed.js: FEED has no entries this script can read")
    return dict(pairs)


def _color(value: str):
    value = value.strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value.upper()
    rgba = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", value)
    if rgba:
        r, g, b, a = rgba.groups()
        return {"rgb": f"#{int(r):02X}{int(g):02X}{int(b):02X}", "alpha": float(a)}
    return None


def theme() -> dict[str, dict]:
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for name, opener in THEMES.items():
        match = re.search(opener + r"(.*?)\n\}", css, re.S)
        if not match:
            raise SystemExit(f"styles.css: no {name} theme block")
        tokens: dict = {}
        for prop, value in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", match.group(1)):
            color = _color(value)
            if color is not None:
                tokens[prop] = color
        out[name] = tokens
    # Dark, graphite and high contrast only list what differs from light.
    for name in ("dark", "graphite", "contrast"):
        out[name] = {**out["light"], **out[name]}
    return out


def palette() -> list[dict[str, str]]:
    tree = ast.parse((ROOT / "agent" / "colors.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PALETTE":
            rows = ast.literal_eval(node.value)
            return [{"id": i, "name": n, "hex": h} for i, n, h in rows]
    raise SystemExit("agent/colors.py has no PALETTE")


def version() -> dict:
    app = json.loads((MOBILE / "version.json").read_text(encoding="utf-8"))
    init = (ROOT / "agent" / "__init__.py").read_text(encoding="utf-8")
    api = int(re.search(r"^API_VERSION = (\d+)", init, re.M).group(1))
    agent = re.search(r'^__version__ = "([^"]+)"', init, re.M).group(1)
    low, high = app["agent_api"]["min"], app["agent_api"]["max"]
    if not low <= api <= high:
        raise SystemExit(
            f"mobile/version.json works with agent API {low}-{high}, but the agent is at "
            f"API {api}: update the app and its range together"
        )
    return {**app, "agent_api_now": api, "agent_version_now": agent}


def color_cases(theme_data: dict, palette_data: list) -> list:
    with tempfile.TemporaryDirectory() as folder:
        theme_file = Path(folder) / "theme.json"
        palette_file = Path(folder) / "palette.json"
        flat = {
            name: {k: v for k, v in tokens.items() if isinstance(v, str)}
            for name, tokens in theme_data.items()
        }
        theme_file.write_text(json.dumps(flat), encoding="utf-8")
        palette_file.write_text(json.dumps(palette_data), encoding="utf-8")
        colors_module = Path(folder) / "colors.mjs"
        shutil.copyfile(ROOT / "agent" / "web" / "js" / "colors.js", colors_module)
        script = MOBILE / "tools" / "color_cases.mjs"
        done = subprocess.run(
            ["node", str(script), str(theme_file), str(palette_file), str(colors_module)],
            capture_output=True,
            text=True,
            check=False,
        )
    if done.returncode != 0:
        raise SystemExit(f"node failed: {done.stderr.strip()}")
    return json.loads(done.stdout)


def render(data) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def outputs() -> dict[str, str]:
    theme_data, palette_data = theme(), palette()
    return {
        "strings.json": render(strings()),
        "feed.json": render(feed()),
        "theme.json": render(theme_data),
        "palette.json": render(palette_data),
        "color-cases.json": render(color_cases(theme_data, palette_data)),
        "version.json": render(version()),
    }


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for name, text in outputs().items():
        path = SHARED / name
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    if stale:
        print(
            "mobile/shared is out of date: "
            + ", ".join(stale)
            + ". Run: python mobile/tools/generate.py"
        )
        return 1
    print("mobile/shared is up to date." if check else "Wrote mobile/shared/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
