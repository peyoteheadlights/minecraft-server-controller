"""The setup window and its screens.

Each screen asks one question and has one main button, like the dashboard.
The window never does the work itself: it asks ``installer.wizard.Wizard``
(which checks folders, finds old copies and starts ``installer/engine.py``
on a thread of its own) and shows the engine's real progress.
"""

from __future__ import annotations

import functools
import os
import sys
from collections.abc import Callable
from typing import Any

import segno
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QGuiApplication, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from agent import appinfo

from . import theme
from .text import players, t

MIN_PASSWORD = 10
POLL_MS = 400


# ====================================================================
# small building blocks
# ====================================================================
def label(text: str, kind: str = "", wrap: bool = True, name: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if kind:
        widget.setProperty("kind", kind)
    if name:
        widget.setObjectName(name)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text: str, action: Callable[[], Any], kind: str = "") -> QPushButton:
    widget = QPushButton(text)
    if kind:
        widget.setProperty("kind", kind)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(lambda _checked=False: action())
    return widget


def line_edit(value: str = "", placeholder: str = "", secret: bool = False) -> QLineEdit:
    widget = QLineEdit(value)
    widget.setPlaceholderText(placeholder)
    if secret:
        widget.setEchoMode(QLineEdit.EchoMode.Password)
    return widget


def row(*widgets: QWidget, stretch_first: bool = True) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if stretch_first and index == 0 else 0)
    return holder


def left(widget: QWidget) -> QWidget:
    """One widget at its own size, on the left."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)
    layout.addStretch(1)
    return holder


def column(*widgets: QWidget | None, spacing: int = 6) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is not None:
            layout.addWidget(widget)
    return holder


def field(caption: str, control: QWidget, help_text: str = "") -> QWidget:
    return column(label(caption), control, label(help_text, "muted") if help_text else None)


class Choice(QFrame):
    """A big radio choice: a title and one line under it (``.choice``)."""

    def __init__(self, title: str, sub: str, selected: bool, on_pick: Callable[[], None]):
        super().__init__()
        self.setProperty("kind", "choice")
        self.setProperty("selected", "true" if selected else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.on_pick = on_pick
        self.radio = QRadioButton()
        self.radio.setChecked(selected)
        self.radio.setAccessibleName(title)
        self.radio.toggled.connect(lambda on: on and self.on_pick())
        heading = label(title, wrap=True)
        heading.setStyleSheet("font-weight: 600;")
        heading.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        under = label(sub, "sub")
        under.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(self.radio, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(column(heading, under, spacing=2), 1)

    def mousePressEvent(self, event: Any) -> None:
        self.radio.setChecked(True)
        self.on_pick()


class Toggle(QCheckBox):
    """The dashboard's on/off switch (``.switch``), or with ``box=True`` a
    tick box, drawn here so they look the same in light and dark."""

    def __init__(self, text: str, tokens: dict[str, str], box: bool = False):
        super().__init__(text)
        self.tokens = tokens
        self.box = box
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        width = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        return QSize(width + (28 if self.box else 34) + (8 if self.text() else 0), 24)

    def hitButton(self, pos: Any) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event: Any) -> None:
        t = self.tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        y = (self.height() - 18) / 2
        if self.box:
            frame = QRectF(1, y + 1, 16, 16)
            painter.setPen(QColor(t["accent"]) if on else _color(t["border-strong"]))
            painter.setBrush(QColor(t["accent"]) if on else QColor(t["surface"]))
            painter.drawRoundedRect(frame, 4, 4)
            if on:
                pen = painter.pen()
                pen.setColor(QColor(t["accent-text"]))
                pen.setWidthF(2.0)
                painter.setPen(pen)
                painter.drawPolyline(
                    [QPointF(5, y + 9.5), QPointF(8, y + 12.5), QPointF(13.5, y + 6)]
                )
            text_x = 26
        else:
            track = QRectF(0.5, y + 0.5, 30, 18)
            painter.setPen(Qt.PenStyle.NoPen if on else _color(t["border-strong"]))
            painter.setBrush(QColor(t["success"]) if on else _color(t["surface-selected"]))
            painter.drawRoundedRect(track, 9, 9)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(QRectF(14.5 if on else 2.5, y + 2.5, 14, 14))
            text_x = 40
        if self.hasFocus():
            painter.setPen(QColor(t["accent-ring"]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(-1, y - 1.5, 34 if not self.box else 20, 21), 10, 10)
        if self.text():
            painter.setPen(QColor(t["text-primary"]))
            painter.drawText(
                QRectF(text_x, 0, self.width() - text_x, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self.text(),
            )
        painter.end()


def _color(value: str) -> QColor:
    """A token as a QColor; rgba() alphas there are already 0 to 255."""
    if value.startswith("rgba("):
        r, g, b, a = (int(float(x)) for x in value[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(value)


class Switch(QFrame):
    """A setting with an explanation and a tick box (``.switch-row``)."""

    def __init__(
        self,
        title: str,
        sub: str,
        value: bool,
        on_change: Callable[[bool], None],
        tokens: dict[str, str],
    ):
        super().__init__()
        self.box = Toggle("", tokens)
        self.box.setChecked(value)
        self.box.setAccessibleName(title)
        self.box.toggled.connect(on_change)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.addWidget(column(label(title), label(sub, "sub"), spacing=2), 1)
        layout.addWidget(self.box, 0, Qt.AlignmentFlag.AlignVCenter)


class QrCode(QWidget):
    """The pairing code, drawn square by square (black on white, so phone
    cameras read it in a dark window too)."""

    def __init__(self, text: str, size: int = 168):
        super().__init__()
        self.matrix = [list(r) for r in segno.make(text, error="m").matrix]
        self.setFixedSize(QSize(size, size))
        self.setAccessibleName(t("on_phone"))

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        quiet = 2
        count = len(self.matrix) + quiet * 2
        cell = self.width() / count
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#000000"))
        for y, cells in enumerate(self.matrix):
            for x, dark in enumerate(cells):
                if dark:
                    painter.drawRect(
                        QRectF((x + quiet) * cell, (y + quiet) * cell, cell + 0.5, cell + 0.5)
                    )
        painter.end()


# ====================================================================
# the window
# ====================================================================
class SetupWindow(QWidget):
    def __init__(self, wizard: Any, dark: bool | None = None):
        super().__init__()
        self.wizard = wizard
        self.state: dict[str, Any] = wizard.state()
        self.answers: dict[str, Any] = {
            "servers": [],
            "start_with_pc": True,
            "allow_devices": True,
            "install_java": None,
        }
        self.path = "new"  # new | none | import | update
        self.screen_name = ""  # not "screen": that is QWidget.screen()
        self.progress_current: QLabel | None = None
        self.progress_bar: QProgressBar | None = None
        self.progress_steps: QWidget | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.poll)
        if dark is None:
            dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self.dark = dark
        self.tokens = theme.tokens(dark)
        self.setStyleSheet(theme.style_sheet(self.tokens))
        self.setWindowTitle(t("window"))
        icon = appinfo.web_dir() / "icons" / "app.ico"
        if not icon.is_file():
            icon = appinfo.web_dir() / "icons" / "icon-192.png"
        self.setWindowIcon(QIcon(str(icon)))
        self.setMinimumSize(QSize(600, 560))
        self.resize(QSize(700, 620))
        self._build()
        self.begin()

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        self.setObjectName("desk")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        sheet = QFrame()
        sheet.setObjectName("sheet")
        outer.addWidget(sheet)
        inner = QVBoxLayout(sheet)
        inner.setContentsMargins(32, 28, 32, 24)
        inner.setSpacing(18)

        icon = QLabel()
        png = appinfo.web_dir() / "icons" / "icon-192.png"
        icon.setPixmap(
            QIcon(str(png)).pixmap(QSize(44, 44)) if png.is_file() else self.windowIcon().pixmap(44)
        )
        icon.setFixedSize(QSize(44, 44))
        name = label(t("app"), name="appName", wrap=False)
        self.subtitle = label(t("version", version=self.state["version"]), name="appVersion")
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(icon)
        head.addWidget(column(name, self.subtitle, spacing=0), 1)
        inner.addLayout(head)

        self.title = label("", name="title")
        self.intro = label("", name="intro")
        inner.addWidget(self.title)
        inner.addWidget(self.intro)

        self.body_holder = QWidget()
        self.body = QVBoxLayout(self.body_holder)
        self.body.setContentsMargins(0, 0, 4, 0)
        self.body.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.body_holder)
        inner.addWidget(scroll, 1)

        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)
        inner.addLayout(self.footer)

    def show_screen(
        self,
        name: str,
        title: str,
        intro: str | None,
        widgets: list[QWidget | None],
        buttons: list[QWidget | None],
    ) -> None:
        self.screen_name = name
        self.title.setText(title)
        self.intro.setText(intro or "")
        self.intro.setVisible(bool(intro))
        for layout in (self.body, self.footer):
            while layout.count():
                item = layout.takeAt(0)
                gone = item.widget()
                if gone is not None:
                    gone.hide()
                    gone.setParent(None)
                    gone.deleteLater()
        for widget in widgets:
            if widget is not None:
                self.body.addWidget(widget)
                hidden_on_purpose = widget.isHidden() and widget.testAttribute(
                    Qt.WidgetAttribute.WA_WState_ExplicitShowHide
                )
                if not hidden_on_purpose:
                    widget.show()
        self.body.addStretch(1)
        if not any(w is not None and w.property("spacer") for w in buttons):
            self.footer.addStretch(1)  # buttons on the right, unless a spacer splits them
        main: QPushButton | None = None
        for widget in buttons:
            if widget is None:
                continue
            if widget.property("spacer"):
                self.footer.addStretch(1)
                continue
            self.footer.addWidget(widget)
            widget.show()
            if isinstance(widget, QPushButton) and widget.property("kind") in ("primary", "danger"):
                main = widget
        if main is not None:
            main.setDefault(True)
            main.setFocus()

    @staticmethod
    def spacer() -> QWidget:
        widget = QWidget()
        widget.setProperty("spacer", True)
        return widget

    # ------------------------------------------------------------ things the PC does
    def ask(self, text: str, yes: str, no: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(t("window"))
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Question)
        yes_button = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
        no_button = box.addButton(no, QMessageBox.ButtonRole.RejectRole)
        yes_button.setProperty("kind", "primary")
        box.setDefaultButton(no_button)
        box.exec()
        return box.clickedButton() is yes_button

    def pick_folder(self, start: str = "") -> str | None:
        return QFileDialog.getExistingDirectory(self, t("browse"), start) or None

    def pick_file(self, start: str = "") -> str | None:
        name, _ = QFileDialog.getOpenFileName(self, t("browse"), start, t("import_filter"))
        return name or None

    def open_target(self, target: str) -> None:
        url = QUrl(target) if "://" in target else QUrl.fromLocalFile(target)
        QDesktopServices.openUrl(url)

    # ------------------------------------------------------------ start
    def begin(self) -> None:
        if self.state.get("admin") is False:
            self.show_screen(
                "not_admin",
                t("failed_title"),
                t("not_admin"),
                [],
                [button(t("close"), self.close, "primary")],
            )
            return
        if self.state.get("uninstall"):
            self.remove_screen()
        elif self.state["found"]:
            self.found_screen(0)
        else:
            self.new_screen()

    def found_screen(self, index: int) -> None:
        self.path = "update"
        found = self.state["found"]
        pick = found[index]
        widgets: list[QWidget | None] = []
        if len(found) > 1:
            widgets.append(label(t("pick_one")))
            for i, item in enumerate(found):
                widgets.append(
                    Choice(
                        item["describe"],
                        item["program_dir"],
                        i == index,
                        self._pick_found(i, index),
                    )
                )
        if pick.get("refused"):
            widgets.append(label(pick["refused"], "bad"))
            self.show_screen(
                "refused",
                pick["describe"],
                None,
                widgets,
                [button(t("close"), self.close, "primary")],
            )
            return
        word = t("repair") if pick["action"] == "repair" else t("update")
        widgets.append(self.java_for_servers(pick))
        self.show_screen(
            "found",
            pick["describe"],
            t("found_sub"),
            widgets,
            [button(word, lambda: self.update_found(index), "primary")],
        )

    def java_for_servers(self, pick: dict[str, Any]) -> QWidget | None:
        """Updating can also give servers a newer Java: the newest one on
        this PC, or Java from Adoptium when there's none new enough. Folded
        away unless a server's Java doesn't run; only ticked servers change."""
        java = self.state["java"]
        best = java.get("best")
        major = int(best["major"]) if best else int(java["install"])
        older = [s for s in pick.get("servers") or [] if (s.get("major") or 0) < major]
        self.answers.pop("java_servers", None)
        self.answers.pop("install_java", None)
        self.answers.pop("java_path", None)
        if not older:
            return None
        chosen = {s["id"] for s in older if s.get("major") is None}

        def update_answers() -> None:
            self.answers["java_servers"] = sorted(chosen)
            self.answers["java_path"] = best["path"] if best and chosen else None
            self.answers["install_java"] = None if best or not chosen else major

        def tick(server_id: str) -> Callable[[bool], None]:
            def changed(on: bool) -> None:
                if on:
                    chosen.add(server_id)
                else:
                    chosen.discard(server_id)
                update_answers()

            return changed

        boxes = []
        for server in older:
            now = (
                t("java_server_now", major=server["major"])
                if server.get("major")
                else t("java_server_broken")
            )
            box = Toggle(f"{server['name']}  ({now})", self.tokens, box=True)
            box.setChecked(server["id"] in chosen)
            box.toggled.connect(tick(server["id"]))
            boxes.append(box)
        body = column(
            label(t("java_use_have", major=major) if best else t("java_use_install", major=major)),
            *boxes,
            label(t("java_use_note"), "muted"),
        )
        fold = button("", lambda: show(not body.isVisible()), "plain")
        fold.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        def show(on: bool) -> None:
            body.setVisible(on)
            fold.setText(("▾  " if on else "▸  ") + t("java_for_servers"))

        show(bool(chosen))
        update_answers()
        return column(left(fold), body)

    def _pick_found(self, i: int, shown: int) -> Callable[[], None]:
        def pick() -> None:
            if i != shown:
                self.found_screen(i)

        return pick

    def update_found(self, index: int) -> None:
        online = self.wizard.players(index)
        question = None
        if online.get("known") and (online.get("online") or 0) > 0:
            question = players(int(online["online"]))
        elif not online.get("known") and online.get("running") != 0:
            # A server is running but who is on it isn't known: never
            # assume nobody is.
            question = t("players_unknown")
        if question and not self.ask(question, t("update_now"), t("wait")):
            return
        self.answers["found"] = index
        self.run()

    def new_screen(self) -> None:
        options = [
            ("new", t("have_server"), t("have_server_sub")),
            ("none", t("no_server"), t("no_server_sub")),
            ("import", t("import_pc"), t("import_pc_sub")),
        ]

        def pick(choice: str) -> None:
            if self.path != choice:
                self.path = choice
                self.new_screen()

        widgets: list[QWidget | None] = [
            Choice(title, sub, self.path == key, functools.partial(pick, key))
            for key, title, sub in options
        ]

        def go_on() -> None:
            if self.path == "new":
                self.servers_screen()
            elif self.path == "import":
                self.import_screen()
            else:
                self.answers["servers"] = []
                self.password_screen()

        self.show_screen(
            "new",
            t("welcome"),
            t("welcome_sub"),
            widgets,
            [button(t("next"), go_on, "primary")],
        )

    # ------------------------------------------------------------ servers
    def blank_server(self) -> dict[str, Any]:
        used = {s["color"] for s in self.answers["servers"]}
        palette = self.state["palette"]
        color = next((c for c in palette if c["id"] not in used), palette[0])["id"]
        return {"folder": "", "name": "", "color": color, "type": "", "ok": False, "problem": ""}

    def servers_screen(self) -> None:
        servers = self.answers["servers"]
        if not servers:
            servers.append(self.blank_server())
        rows: list[QWidget | None] = [self.server_row(s, i) for i, s in enumerate(servers)]

        def add() -> None:
            servers.append(self.blank_server())
            self.servers_screen()

        rows.append(left(button(t("add_another"), add, "plain")))
        nxt = button(t("next"), self.password_screen, "primary")
        nxt.setEnabled(all(s["ok"] for s in servers))
        self.show_screen(
            "servers",
            t("where_server"),
            t("where_server_sub"),
            rows,
            [button(t("back"), self.new_screen), nxt],
        )

    def server_row(self, server: dict[str, Any], index: int) -> QWidget:
        frame = QFrame()
        frame.setProperty("kind", "row")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        folder = line_edit(server["folder"], t("folder_placeholder"))
        folder.setAccessibleName(t("where_server"))

        def check() -> None:
            if folder.text() == server["folder"] and server["ok"]:
                return
            answer = self.wizard.check_folder(folder.text())
            server.update(
                folder=answer.get("folder") or folder.text(),
                ok=bool(answer.get("ok")),
                problem=answer.get("problem") or "",
            )
            if answer.get("ok"):
                server["type"] = answer.get("type") or ""
                server["type_name"] = answer.get("type_name") or ""
                if not server["name"]:
                    server["name"] = answer.get("name") or ""
            self.servers_screen()

        def browse() -> None:
            picked = self.pick_folder(folder.text())
            if picked:
                folder.setText(os.path.normpath(picked))
                check()

        folder.editingFinished.connect(check)
        layout.addWidget(row(folder, button(t("browse"), browse)))
        if server["problem"]:
            layout.addWidget(label(server["problem"], "problem"))
        elif server["ok"] and server.get("type_name"):
            layout.addWidget(label(t("found_type", type=server["type_name"]), "ok"))
        name = line_edit(server["name"], t("server_name"))
        name.setMaxLength(60)
        name.setAccessibleName(t("server_name"))
        name.textChanged.connect(lambda text: server.__setitem__("name", text))
        layout.addWidget(name)
        swatches = QHBoxLayout()
        swatches.setSpacing(6)
        for color in self.state["palette"]:
            swatch = QPushButton()
            swatch.setProperty("kind", "swatch")
            swatch.setCheckable(True)
            swatch.setChecked(server["color"] == color["id"])
            swatch.setToolTip(color["name"])
            swatch.setAccessibleName(color["name"])
            swatch.setStyleSheet(f"background: {color['hex']};")
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)

            def choose(_checked: bool = False, color_id: str = color["id"]) -> None:
                server["color"] = color_id
                self.servers_screen()

            swatch.clicked.connect(choose)
            swatches.addWidget(swatch)
        swatches.addStretch(1)
        if len(self.answers["servers"]) > 1:

            def drop() -> None:
                self.answers["servers"].pop(index)
                self.servers_screen()

            swatches.addWidget(button(t("remove"), drop, "plain"))
        layout.addLayout(swatches)
        return frame

    # ------------------------------------------------------------ import
    def import_screen(self) -> None:
        file = line_edit(self.answers.get("import_file") or "")
        file.setAccessibleName(t("import_file"))
        target = line_edit(self.answers.get("import_to") or self.state["default_import_to"])
        target.setAccessibleName(t("import_to"))
        passphrase = line_edit(self.answers.get("import_passphrase") or "", secret=True)
        passphrase.setAccessibleName(t("import_pass"))
        problem = label("", "problem")
        problem.hide()

        def browse_file() -> None:
            picked = self.pick_file(file.text())
            if picked:
                file.setText(os.path.normpath(picked))

        def browse_folder() -> None:
            picked = self.pick_folder(target.text())
            if picked:
                target.setText(os.path.normpath(picked))

        def go_on() -> None:
            answer = self.wizard.check_import(file.text())
            if not answer.get("ok"):
                problem.setText(answer.get("problem") or "")
                problem.show()
                return
            self.answers.update(
                import_file=file.text(),
                import_to=target.text(),
                import_passphrase=passphrase.text(),
                servers=[],
            )
            if (answer.get("includes") or {}).get("secrets") and passphrase.text():
                self.java_screen()
            else:
                self.password_screen()

        self.show_screen(
            "import",
            t("import_title"),
            None,
            [
                field(t("import_file"), row(file, button(t("browse"), browse_file))),
                field(t("import_to"), row(target, button(t("browse"), browse_folder))),
                field(t("import_pass"), passphrase, t("import_pass_sub")),
                problem,
            ],
            [button(t("back"), self.new_screen), button(t("next"), go_on, "primary")],
        )

    # ------------------------------------------------------------ password
    def password_screen(self) -> None:
        first = line_edit(secret=True)
        first.setAccessibleName(t("password"))
        second = line_edit(secret=True)
        second.setAccessibleName(t("password_again"))
        problem = label("", "problem")
        problem.hide()
        toggle = QPushButton(t("show"))

        def flip() -> None:
            hidden = first.echoMode() == QLineEdit.EchoMode.Password
            mode = QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
            first.setEchoMode(mode)
            second.setEchoMode(mode)
            toggle.setText(t("hide") if hidden else t("show"))

        toggle.clicked.connect(lambda _c=False: flip())

        def go_on() -> None:
            if len(first.text()) < MIN_PASSWORD:
                problem.setText(t("too_short"))
                problem.show()
                return
            if first.text() != second.text():
                problem.setText(t("no_match"))
                problem.show()
                return
            self.answers["password"] = first.text()
            self.java_screen()

        back = {"new": self.servers_screen, "import": self.import_screen}.get(
            self.path, self.new_screen
        )
        self.show_screen(
            "password",
            t("password"),
            t("password_sub"),
            [row(first, toggle), field(t("password_again"), second), problem],
            [button(t("back"), back), button(t("next"), go_on, "primary")],
        )
        first.setFocus()
        self.password_fields = (first, second, toggle, problem)

    # ------------------------------------------------------------ java
    def java_screen(self) -> None:
        java = self.state["java"]
        if java.get("best"):
            self.answers["java_path"] = java["best"]["path"]
            self.answers["install_java"] = None
            self.options_screen()
            return
        newest = next((j for j in java["found"] if j.get("major")), None)
        intro = (
            t("java_old", found=newest["major"], needed=java["needed"])
            if newest
            else t("java_missing")
        )
        install = self.answers.get("java_choice", True)

        def choose(value: bool) -> None:
            if self.answers.get("java_choice", True) != value:
                self.answers["java_choice"] = value
                self.java_screen()

        def go_on() -> None:
            self.answers["install_java"] = (
                java["install"] if self.answers.get("java_choice", True) else None
            )
            self.options_screen()

        self.show_screen(
            "java",
            t("java_title", needed=java["needed"]),
            intro,
            [
                Choice(
                    t("java_install", major=java["install"]),
                    t("java_install_sub"),
                    install,
                    lambda: choose(True),
                ),
                Choice(t("java_skip"), t("java_skip_sub"), not install, lambda: choose(False)),
            ],
            [button(t("back"), self.password_screen), button(t("next"), go_on, "primary")],
        )

    # ------------------------------------------------------------ options
    def options_screen(self) -> None:
        folder = line_edit(self.answers.get("program_dir") or self.state["program_dir"])
        folder.setAccessibleName(t("install_folder"))
        problem = label("", "problem")
        problem.hide()

        def browse() -> None:
            picked = self.pick_folder(folder.text())
            if picked:
                folder.setText(os.path.normpath(picked))

        advanced_body = column(
            field(t("install_folder"), row(folder, button(t("browse"), browse))), problem
        )
        advanced = button(
            t("advanced"), lambda: open_advanced(not self.answers["advanced_open"]), "plain"
        )
        advanced.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        def open_advanced(on: bool) -> None:
            self.answers["advanced_open"] = on
            advanced_body.setVisible(on)
            advanced.setText(("▾  " if on else "▸  ") + t("advanced"))

        open_advanced(bool(self.answers.get("advanced_open")))

        def set_answer(key: str) -> Callable[[bool], None]:
            return lambda value: self.answers.__setitem__(key, bool(value))

        def go_on() -> None:
            chosen = folder.text().strip()
            if os.path.normcase(chosen) != os.path.normcase(self.state["program_dir"]):
                answer = self.wizard.check_install_folder(chosen)
                if not answer.get("ok"):
                    problem.setText(answer.get("problem") or "")
                    problem.show()
                    open_advanced(True)
                    return
                if answer.get("older") and not self.ask(t("older_here"), t("yes_replace"), t("no")):
                    # Back to the folder field; nothing goes on until a
                    # folder is chosen.
                    open_advanced(True)
                    folder.setFocus()
                    folder.selectAll()
                    return
            self.answers["program_dir"] = chosen
            self.phone_screen()

        line = QFrame()
        line.setProperty("kind", "line")
        self.show_screen(
            "options",
            t("options"),
            None,
            [
                Switch(
                    t("start_with_pc"),
                    t("start_with_pc_sub"),
                    self.answers["start_with_pc"],
                    set_answer("start_with_pc"),
                    self.tokens,
                ),
                line,
                Switch(
                    t("allow_devices"),
                    t("allow_devices_sub"),
                    self.answers["allow_devices"],
                    set_answer("allow_devices"),
                    self.tokens,
                ),
                advanced,
                advanced_body,
            ],
            [button(t("back"), self.java_screen), button(t("next"), go_on, "primary")],
        )
        self.install_folder_field = folder

    # ------------------------------------------------------------ phone alerts
    def phone_screen(self) -> None:
        email = line_edit(self.answers.get("push_contact") or "")
        email.setAccessibleName(t("phone_email"))

        def skip() -> None:
            self.answers["phone_alerts"] = False
            self.run()

        def yes() -> None:
            self.answers["phone_alerts"] = True
            self.answers["push_contact"] = email.text().strip()
            self.run()

        self.show_screen(
            "phone",
            t("phone_title"),
            t("phone_sub"),
            [field(t("phone_email"), email)],
            [
                button(t("back"), self.options_screen),
                self.spacer(),
                button(t("skip"), skip),
                button(t("phone_yes"), yes, "primary"),
            ],
        )

    # ------------------------------------------------------------ the work
    def choices(self) -> dict[str, Any]:
        keep = ("folder", "name", "color", "type")
        return {
            **{k: v for k, v in self.answers.items() if k not in ("java_choice", "advanced_open")},
            "servers": [{k: s.get(k) for k in keep} for s in self.answers["servers"]],
        }

    def run(self) -> None:
        answer = self.wizard.start(self.choices())
        if not answer.get("ok"):
            return
        self.draw_progress(self.wizard.progress().get("progress"))
        self.timer.start()

    def poll(self) -> None:
        answer = self.wizard.progress()
        if answer.get("result"):
            self.timer.stop()
            if answer["result"].get("ok"):
                self.done_screen(answer)
            else:
                self.failed_screen(answer)
            return
        self.draw_progress(answer.get("progress"))

    def steps(self, snapshot: dict[str, Any]) -> QWidget:
        marks = {"done": "✓", "skipped": "–", "running": "●", "failed": "✕"}
        kinds = {"done": "", "skipped": "muted", "running": "step", "failed": "problem"}
        rows = []
        for step in snapshot.get("steps", []):
            state = step.get("state", "")
            rows.append(label(f"{marks.get(state, '○')}  {step['name']}", kinds.get(state, "sub")))
        return column(*rows, spacing=4)

    def draw_progress(self, snapshot: dict[str, Any] | None) -> None:
        if not snapshot:
            return
        if (
            self.screen_name == "progress"
            and self.progress_current is not None
            and self.progress_bar is not None
            and self.progress_steps is not None
        ):
            # Update in place, so the bar doesn't flicker.
            self.progress_current.setText(snapshot.get("current") or "")
            self._set_bar(self.progress_bar, snapshot)
            old = self.progress_steps
            self.progress_steps = self.steps(snapshot)
            self.body.replaceWidget(old, self.progress_steps)
            old.hide()
            old.setParent(None)
            old.deleteLater()
            return
        self.progress_current = label(snapshot.get("current") or "", "step")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAccessibleName(t("working"))
        self._set_bar(self.progress_bar, snapshot)
        self.progress_steps = self.steps(snapshot)
        self.show_screen(
            "progress",
            t("working"),
            t("working_sub"),
            [self.progress_current, self.progress_bar, self.progress_steps],
            [],
        )

    @staticmethod
    def _set_bar(bar: QProgressBar, snapshot: dict[str, Any]) -> None:
        if snapshot.get("indeterminate"):
            bar.setRange(0, 0)  # Qt's own "busy" bar: no made-up number
        else:
            bar.setRange(0, 1000)
            bar.setValue(round(float(snapshot.get("percent") or 0) * 10))

    def failed_screen(self, answer: dict[str, Any]) -> None:
        result = answer["result"]
        details = QPlainTextEdit(result.get("details") or "")
        details.setReadOnly(True)
        details.setMaximumHeight(160)
        details.hide()
        toggle = QPushButton(t("show_details"))
        toggle.setProperty("kind", "plain")

        def flip() -> None:
            details.setVisible(not details.isVisible())
            toggle.setText(t("hide_details") if details.isVisible() else t("show_details"))

        toggle.clicked.connect(lambda _c=False: flip())
        copy = QPushButton(t("copy_log"))

        def copy_log() -> None:
            QGuiApplication.clipboard().setText(self.wizard.log_text())
            copy.setText(t("copied"))

        copy.clicked.connect(lambda _c=False: copy_log())
        rolled = result.get("rolled_back")
        said = (
            t("rolled_back_new" if result.get("action") == "install" else "rolled_back")
            if rolled is True
            else t("not_rolled_back")
            if rolled is False
            else t("nothing_changed")
        )
        log_path = str(result.get("log_path") or "")
        self.show_screen(
            "failed",
            t("failed_title"),
            None,
            [
                label(result.get("message") or "", "bad"),
                label(said),
                self.steps(answer["progress"]) if answer.get("progress") else None,
                label(t("log_at", path=log_path), "muted"),
                left(toggle),
                details,
            ],
            [
                button(t("open_log"), lambda: self.open_target(log_path) if log_path else None),
                copy,
                self.spacer(),
                button(t("close"), self.close),
                button(t("try_again"), self.run, "primary"),
            ],
        )

    def done_screen(self, answer: dict[str, Any]) -> None:
        result = answer["result"]
        pairing = answer.get("pairing") or {}
        first = self.path == "none"
        url = str(result.get("dashboard_url") or "")

        def open_dashboard() -> None:
            if url:
                self.open_target(url + ("/#add-server" if first else "/"))

        if pairing.get("ok"):
            phone = column(
                label(t("on_phone")), label(str(pairing.get("address_url") or ""), "address")
            )
        else:
            phone = column(label(t("no_qr")), label(str(pairing.get("reason") or ""), "muted"))
        notes = [label(str(note), "notice") for note in result.get("notes") or []]
        grid = QWidget()
        layout = QHBoxLayout(grid)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        layout.addWidget(column(phone, *notes, spacing=10), 1)
        if pairing.get("ok") and pairing.get("url"):
            layout.addWidget(QrCode(str(pairing["url"])), 0, Qt.AlignmentFlag.AlignTop)
        self.show_screen(
            "done",
            t("done_title"),
            t("done_sub"),
            [grid],
            [
                button(t("close"), self.close),
                button(
                    t("first_server") if first else t("open_dashboard"), open_dashboard, "primary"
                ),
            ],
        )

    # ------------------------------------------------------------ remove
    def remove_screen(self) -> None:
        data = Toggle(t("remove_data"), self.tokens, box=True)

        def remove() -> None:
            result = self.wizard.uninstall(data.isChecked())
            kept = result.get("kept")
            self.show_screen(
                "removed",
                t("removed"),
                t("kept_at", path=kept) if kept else None,
                [label(str(p), "bad") for p in result.get("problems") or []],
                [button(t("close"), self.close, "primary")],
            )

        self.show_screen(
            "remove",
            t("remove_title"),
            t("remove_sub"),
            [data],
            [button(t("close"), self.close), button(t("remove_button"), remove, "danger")],
        )

    # ------------------------------------------------------------ closing
    def closeEvent(self, event: QCloseEvent) -> None:
        thread = getattr(self.wizard, "thread", None)
        if thread is not None and thread.is_alive():
            # Stopping half way would leave things half changed.
            QMessageBox.information(self, t("window"), t("still_working"))
            event.ignore()
            return
        event.accept()


def dark_title_bar(window: QWidget) -> None:
    """Ask Windows 10/11 for a dark title bar to go with a dark window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(window.winId()), 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def run(wizard: Any) -> int:
    """Show the window until it is closed; 0 if setup finished (or nothing
    was started), 1 if it failed."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    QApplication.setStyle("Fusion")
    app.setApplicationName(t("window"))
    window = SetupWindow(wizard)
    if window.dark:
        dark_title_bar(window)
    window.show()
    app.exec()
    result = getattr(wizard, "result", None)
    if result is None:
        return 0
    return 0 if result.ok else 1


__all__ = ["SetupWindow", "run"]
