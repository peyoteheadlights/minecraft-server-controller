"""Draw the app's PNG icons from the same design as agent/web/icon.svg.

    python scripts/make_icons.py

A phone will only offer "add to home screen" with real PNG icons, so these
are generated here rather than hand-drawn, from the same shape and colours
as the SVG: a rounded square with the cube outline on it. The maskable one
keeps the cube inside the safe circle phones crop to, and fills the whole
square so no corner shows through.

It also writes ``app.ico`` for the Windows programs and installer: the
ICO format can hold PNG pictures as they are, so it is the same drawings at
16 to 256 pixels.

Run this again if the icon's design changes, and commit the files it writes.
No image library is needed: the shapes are distances to lines, and the PNG
is written with zlib and struct, both from the standard library.
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "agent" / "web" / "icons"

BACKGROUND = (0x3C, 0x3C, 0x43)
INK = (0xFF, 0xFF, 0xFF)
# The SVG's own coordinates, on its 32x32 canvas.
CORNER = 8.0
STROKE = 2.2
OUTLINE = [
    (16, 5.5),
    (25.5, 10.7),
    (25.5, 21.3),
    (16, 26.5),
    (6.5, 21.3),
    (6.5, 10.7),
    (16, 5.5),
]
INNER = [
    [(6.8, 11), (16, 16)],
    [(16, 16), (25.2, 11)],
    [(16, 16), (16, 26)],
]
SAMPLES = 3  # per axis, for smooth edges


def segments() -> list[tuple[tuple[float, float], tuple[float, float]]]:
    lines = [(OUTLINE[i], OUTLINE[i + 1]) for i in range(len(OUTLINE) - 1)]
    return lines + [(a, b) for a, b in INNER]


def distance_to_segment(px: float, py: float, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def inside_rounded_square(x: float, y: float, side: float, radius: float) -> bool:
    cx = min(max(x, radius), side - radius)
    cy = min(max(y, radius), side - radius)
    if x < radius or x > side - radius:
        if y < radius or y > side - radius:
            return math.hypot(x - cx, y - cy) <= radius
    return 0 <= x <= side and 0 <= y <= side


def render(size: int, maskable: bool) -> bytes:
    """One icon's raw RGBA rows."""
    lines = segments()
    # The maskable icon fills the square and draws the cube smaller, so a
    # phone cropping it to a circle never cuts the shape.
    art_scale = 0.74 if maskable else 1.0
    offset = (1 - art_scale) * 16
    scale = size / 32.0
    half_stroke = STROKE / 2
    rows = bytearray()
    for py in range(size):
        row = bytearray()
        for px in range(size):
            red = green = blue = alpha = 0.0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    x = (px + (sx + 0.5) / SAMPLES) / scale
                    y = (py + (sy + 0.5) / SAMPLES) / scale
                    if maskable:
                        on_background = True
                    else:
                        on_background = inside_rounded_square(x, y, 32.0, CORNER)
                    if not on_background:
                        continue
                    ax = (x - offset) / art_scale
                    ay = (y - offset) / art_scale
                    near = min(distance_to_segment(ax, ay, a, b) for a, b in lines)
                    colour = INK if near <= half_stroke else BACKGROUND
                    red += colour[0]
                    green += colour[1]
                    blue += colour[2]
                    alpha += 255
            total = SAMPLES * SAMPLES
            if alpha == 0:
                row += bytes((0, 0, 0, 0))
                continue
            # Colours are averaged over the covered samples only, so an edge
            # fades out instead of darkening towards black.
            covered = alpha / 255
            row += bytes(
                (
                    round(red / covered),
                    round(green / covered),
                    round(blue / covered),
                    round(alpha / total),
                )
            )
        rows += b"\x00" + row
    return bytes(rows)


def png_bytes(size: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack("!2I5B", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    return png


def write_png(path: Path, size: int, raw: bytes) -> None:
    path.write_bytes(png_bytes(size, raw))


def write_ico(path: Path, sizes: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> None:
    """An .ico holding one PNG per size (Windows Vista and later read these)."""
    images = [png_bytes(size, render(size, False)) for size in sizes]
    header = struct.pack("<3H", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in zip(sizes, images, strict=True):
        side = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<4B2H2I", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(header + entries + b"".join(images))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("maskable-512.png", 512, True),
    ]
    for name, size, maskable in wanted:
        path = OUT / name
        write_png(path, size, render(size, maskable))
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    ico = OUT / "app.ico"
    write_ico(ico)
    print(f"wrote {ico.relative_to(ROOT)} ({ico.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
