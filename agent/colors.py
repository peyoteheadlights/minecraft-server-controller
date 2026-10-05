"""Each server's color.

A server is told apart from the others by its color: its tab, the band on
its page, its buttons and the browser tab icon all use it. The palette is
twelve hues spread around the color wheel, chosen so any two stay clearly
different side by side for people with normal color vision and with the
common forms of color blindness (protanopia, deuteranopia, tritanopia).
``tests/test_server_colors.py`` simulates each and fails if two colors get
too close. A new server gets the first palette color no other server uses;
anyone can pick another palette color or their own hex instead.

These are the base colors. The dashboard derives darker or lighter shades
of each for text and buttons so they stay readable on every theme
(agent/web/js/colors.js); the base color itself is only ever a fill.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# (id, name, hex). The order is the order new servers get them in.
PALETTE: tuple[tuple[str, str, str], ...] = (
    ("blue", "Blue", "#1967D4"),
    ("orange", "Orange", "#F87906"),
    ("green", "Green", "#30C067"),
    ("crimson", "Crimson", "#D7213E"),
    ("violet", "Violet", "#B78AF6"),
    ("amber", "Amber", "#F7E10D"),
    ("teal", "Teal", "#0D4B48"),
    ("magenta", "Magenta", "#A61888"),
    ("cyan", "Cyan", "#54E7F0"),
    ("olive", "Olive", "#4F610A"),
    ("rose", "Rose", "#FCA1B1"),
    ("indigo", "Indigo", "#18185F"),
)

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ColorError(ValueError):
    """Not a color the dashboard can use."""


def normalise(value: str) -> str:
    """A palette id or a "#RRGGBB" hex, as the hex stored on the server row."""
    text = (value or "").strip()
    for color_id, _name, hex_ in PALETTE:
        if text.lower() == color_id:
            return hex_
    if _HEX.match(text):
        return text.upper()
    raise ColorError("Pick a color from the list, or type one as # and six hex digits")


def next_unused(taken: Iterable[str | None]) -> str:
    """The first palette color no other server has. When all twelve are
    taken, colors are shared, least-used first."""
    used = [t.upper() for t in taken if t]
    counts = {hex_: used.count(hex_) for _id, _name, hex_ in PALETTE}
    fewest = min(counts.values())
    return next(hex_ for _id, _name, hex_ in PALETTE if counts[hex_] == fewest)


def palette() -> list[dict[str, str]]:
    return [{"id": color_id, "name": name, "hex": hex_} for color_id, name, hex_ in PALETTE]
