"""The dashboard's design tokens, as a Qt style sheet.

The tokens are read from ``agent/web/styles.css`` itself (the light ``:root``
block and the ``[data-theme="dark"]`` block), so the installer can't drift
from the dashboard: change a color there and setup follows. Qt style sheets
have no ``var()``, so the sheet below is filled in from those values.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent import appinfo

NEEDED = (
    "desk",
    "sheet",
    "surface",
    "surface-sunken",
    "surface-hover",
    "surface-selected",
    "text-primary",
    "text-secondary",
    "text-tertiary",
    "border",
    "border-strong",
    "accent",
    "accent-text",
    "accent-hover",
    "accent-ink",
    "accent-soft",
    "accent-ring",
    "success",
    "success-soft",
    "danger",
    "danger-soft",
    "console-bg",
    "radius",
    "radius-lg",
)

_RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)")


def styles_path() -> Path:
    return appinfo.web_dir() / "styles.css"


def _block(css: str, selector: str) -> str:
    start = css.find(selector + " {")
    if start < 0:
        raise ValueError(f"styles.css has no {selector} block")
    end = css.find("\n}", start)
    return css[start:end]


def _tokens(block: str) -> dict[str, str]:
    return {
        name: value.strip() for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", block)
    }


def _qt(value: str) -> str:
    """CSS rgba() alphas are 0 to 1; Qt's are 0 to 255."""
    match = _RGBA.fullmatch(value)
    if match:
        r, g, b, a = match.groups()
        return f"rgba({r}, {g}, {b}, {round(float(a) * 255)})"
    return value


def tokens(dark: bool, css: str | None = None) -> dict[str, str]:
    css = css if css is not None else styles_path().read_text(encoding="utf-8")
    found = _tokens(_block(css, ":root"))
    if dark:
        found.update(_tokens(_block(css, ':root[data-theme="dark"]')))
    missing = [name for name in NEEDED if name not in found]
    if missing:
        raise ValueError("styles.css is missing " + ", ".join(missing))
    return {name: _qt(found[name]) for name in NEEDED}


def style_sheet(t: dict[str, str]) -> str:
    """The whole window's look. Object names and the ``kind`` property pick
    the variants, like the dashboard's classes (``.btn.primary``)."""
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt;
     color: {t["text-primary"]}; }}
QWidget#desk {{ background: {t["desk"]}; }}
QFrame#sheet {{ background: {t["sheet"]}; border-radius: {t["radius-lg"]};
                border: 1px solid {t["border"]}; }}
QLabel {{ background: transparent; }}
QLabel#appName {{ font-size: 15pt; font-weight: 600; }}
QLabel#appVersion, QLabel[kind="sub"] {{ color: {t["text-secondary"]}; }}
QLabel#title {{ font-size: 13pt; font-weight: 600; }}
QLabel#intro {{ color: {t["text-secondary"]}; }}
QLabel[kind="muted"] {{ color: {t["text-tertiary"]}; font-size: 9pt; }}
QLabel[kind="problem"] {{ color: {t["danger"]}; }}
QLabel[kind="ok"] {{ color: {t["success"]}; }}
QLabel[kind="step"] {{ font-weight: 600; }}
QLabel[kind="address"] {{ font-family: "Cascadia Mono", Consolas, monospace; }}
QLabel[kind="notice"] {{ background: {t["surface"]}; border: 1px solid {t["border"]};
                         border-radius: {t["radius"]}; padding: 8px 12px; }}
QLabel[kind="bad"] {{ background: {t["danger-soft"]}; border-radius: {t["radius"]};
                      padding: 8px 12px; }}
QLabel[kind="good"] {{ background: {t["success-soft"]}; border-radius: {t["radius"]};
                       padding: 8px 12px; }}

QPushButton {{ background: {t["surface"]}; border: 1px solid {t["border-strong"]};
               border-radius: {t["radius"]}; padding: 5px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {t["surface-sunken"]}; }}
QPushButton:focus {{ border: 2px solid {t["accent-ring"]}; padding: 4px 13px; }}
QPushButton:disabled {{ color: {t["text-tertiary"]}; background: {t["surface-sunken"]}; }}
QPushButton[kind="primary"] {{ background: {t["accent"]}; color: {t["accent-text"]};
                               border: 1px solid {t["accent"]}; min-width: 96px; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {t["accent-hover"]}; }}
QPushButton[kind="primary"]:focus {{ border: 2px solid {t["accent-ring"]}; }}
QPushButton[kind="primary"]:disabled {{ background: {t["accent-soft"]}; color: {t["text-tertiary"]};
                                        border-color: transparent; }}
QPushButton[kind="danger"] {{ background: {t["danger"]}; color: #FFFFFF; border: 1px solid {t["danger"]};
                              font-weight: 600; }}
QPushButton[kind="plain"] {{ background: transparent; border: 1px solid transparent;
                             color: {t["accent-ink"]}; padding: 5px 8px; }}
QPushButton[kind="plain"]:hover {{ background: {t["accent-soft"]}; }}
QPushButton[kind="swatch"] {{ border-radius: 11px; min-width: 22px; max-width: 22px;
                              min-height: 22px; max-height: 22px; padding: 0;
                              border: 1px solid {t["border-strong"]}; }}
QPushButton[kind="swatch"]:checked {{ border: 3px solid {t["text-primary"]}; }}

QLineEdit {{ background: {t["surface"]}; border: 1px solid {t["border-strong"]};
             border-radius: {t["radius"]}; padding: 5px 8px; min-height: 20px;
             selection-background-color: {t["accent"]}; }}
QLineEdit:focus {{ border: 2px solid {t["accent-ring"]}; padding: 4px 7px; }}

QFrame[kind="choice"], QFrame[kind="row"] {{ background: {t["surface"]}; border: 1px solid {t["border"]};
                                             border-radius: {t["radius"]}; }}
QFrame[kind="choice"][selected="true"] {{ background: {t["accent-soft"]};
                                          border: 1px solid {t["accent-ring"]}; }}
QFrame[kind="line"] {{ background: {t["border"]}; max-height: 1px; min-height: 1px; }}
QRadioButton, QCheckBox {{ background: transparent; spacing: 8px; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; background: {t["surface"]};
                           border: 1px solid {t["border-strong"]}; }}
QRadioButton::indicator:checked {{ background: {t["accent-text"]}; border: 5px solid {t["accent"]};
                                   width: 6px; height: 6px; }}

QProgressBar {{ background: {t["surface-sunken"]}; border: 0; border-radius: 4px;
                max-height: 8px; min-height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {t["accent"]}; border-radius: 4px; }}

QPlainTextEdit {{ background: {t["console-bg"]}; border: 1px solid {t["border"]};
                  border-radius: {t["radius"]}; font-family: "Cascadia Mono", Consolas, monospace;
                  font-size: 9pt; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: 0; }}
QMessageBox {{ background: {t["sheet"]}; }}
QToolTip {{ background: {t["surface"]}; border: 1px solid {t["border-strong"]}; }}
"""
