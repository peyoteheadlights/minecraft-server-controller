"""The dashboard's strings table (agent/web/js/strings.js).

Every label has a Simple and a Technical version with the same
{placeholders}; every key the code looks up exists; every entry in the
table is used. Keys built at run time (t(`color.${id}`)) are checked
against the list they come from, so a new crash category, alert event or
palette color without wording fails here instead of showing a raw key.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent import colors
from agent.config import NotificationSettings
from agent.minecraft.analyzer import CATEGORIES
from agent.scheduler.scheduler import TASKS
from agent.security.auth import AuthManager

WEB = Path(__file__).resolve().parent.parent / "agent" / "web"
JS = WEB / "js"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def table() -> dict[str, list[str]]:
    source = (JS / "strings.js").read_text(encoding="utf-8")
    match = re.search(r"/\* strings-table \*/(.*?)/\* end-strings-table \*/", source, re.S)
    assert match, "strings.js lost its table markers"
    data: dict[str, list[str]] = json.loads(match.group(1))
    return data


def sources() -> dict[str, str]:
    return {
        p.relative_to(JS).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(JS.rglob("*.js"))
    }


def js_list(path: str, name: str) -> list[str]:
    """The quoted strings in `const NAME = [...]` / `{...}` keys in a module."""
    source = (JS / path).read_text(encoding="utf-8")
    match = re.search(rf"const {name} = [\[{{](.*?)[\]}}];", source, re.S)
    assert match, f"{name} not found in {path}"
    body = match.group(1)
    if source[match.start() :].split("=", 1)[1].strip().startswith("{"):
        return re.findall(r"[\"']?(\w+)[\"']?\s*:", body)
    return re.findall(r"[\"']?([\w]+)[\"']?", body)


def families() -> dict[str, set[str]]:
    """Every key prefix the code completes at run time, with the suffixes it can take."""
    events = NotificationSettings().events
    return {
        "color.": {c["id"] for c in colors.palette()},
        "alert_event.": set(events),
        "task.": set(TASKS),
        "cause.": set(CATEGORIES) - {"Unknown"},
        "theme.": set(AuthManager.PREFERENCE_CHOICES["theme"]),
        "appset.": {"theme", "mode"},
        "perf.range_": {str(h) for h in js_list("pages/performance.js", "RANGES")},
        "tps.state_": {"active", "detecting", "unavailable", "disabled", "idle"},
        "deps.status_": set(js_list("panels/dependencies.js", "STATUS")),
        "serverset.keep_": {"daily", "weekly", "monthly"},
        "startup.": {"registered_correctly", "not_registered", "problems_found", "unsupported"},
    }


def used_keys() -> set[str]:
    strings = table()
    groups = {key.split(".")[0] for key in strings}
    keys: set[str] = set()
    for path, text in sources().items():
        if path == "strings.js":  # the table itself
            continue
        for match in re.finditer(r"\btn\(\s*\"([a-z0-9_.]+)\"", text):
            keys |= {f"{match.group(1)}.one", f"{match.group(1)}.other"}
        plural = {m.group(1) for m in re.finditer(r"\btn\(\s*\"([a-z0-9_.]+)\"", text)}
        for match in re.finditer(r"\"([a-z_]+(?:\.[a-z0-9_]+)+)\"", text):
            key = match.group(1)
            if key.split(".")[0] in groups and key not in plural:
                keys.add(key)
    return keys


def test_table_entries_have_simple_and_technical_text():
    strings = table()
    assert len(strings) > 300
    for key, entry in strings.items():
        assert isinstance(entry, list) and len(entry) == 2, key
        simple, technical = entry
        assert isinstance(simple, str) and simple.strip(), f"{key}: Simple text is empty"
        assert isinstance(technical, str) and technical.strip(), f"{key}: Technical text is empty"
        assert sorted(PLACEHOLDER.findall(simple)) == sorted(PLACEHOLDER.findall(technical)), (
            f"{key}: Simple and Technical use different placeholders"
        )


def test_keys_are_well_formed():
    for key in table():
        assert re.fullmatch(r"[a-z_]+(\.[A-Za-z0-9_]+)+", key), key


def test_every_key_the_code_uses_exists():
    strings = table()
    missing = sorted(key for key in used_keys() if key not in strings)
    assert not missing, f"used in the dashboard but not in the strings table: {missing}"


def test_every_runtime_key_family_is_known_and_complete():
    strings = table()
    known = families()
    for path, text in sources().items():
        if path == "strings.js":  # tn() itself, which adds .one/.other
            continue
        for match in re.finditer(r"\btn?\(\s*`([a-z_.]*)\$\{", text):
            prefix = match.group(1)
            assert prefix in known, (
                f"{path} builds a strings key from {prefix!r}: add it to families() in this test"
            )
    for prefix, suffixes in known.items():
        missing = sorted(f"{prefix}{s}" for s in suffixes if f"{prefix}{s}" not in strings)
        assert not missing, f"no wording for {missing}"


def test_every_entry_is_used():
    used = used_keys()
    runtime = {f"{p}{s}" for p, suffixes in families().items() for s in suffixes}
    unused = sorted(k for k in table() if k not in used and k not in runtime)
    assert not unused, f"in the strings table but never shown: {unused}"


def test_crash_causes_match_the_analyzer():
    assert set(js_list("state.js", "CAUSES")) == set(CATEGORIES) - {"Unknown"}


def test_palette_colors_each_have_a_name():
    strings = table()
    for color in colors.palette():
        assert f"color.{color['id']}" in strings
