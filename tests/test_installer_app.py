"""The setup window (installer/app): every screen, driven with a pretend
wizard, off-screen. Nothing on this machine is changed."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 is in requirements-dev")

from installer.app import theme  # noqa: E402
from installer.app.demo import DemoWizard  # noqa: E402
from installer.app.text import TEXT  # noqa: E402
from installer.app.window import SetupWindow  # noqa: E402

QLabel = QtWidgets.QLabel
QLineEdit = QtWidgets.QLineEdit
QPushButton = QtWidgets.QPushButton


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def make(qapp, monkeypatch, wizard=None, answers=None, **kwargs):
    window = SetupWindow(wizard or DemoWizard(**kwargs), dark=False)
    asked: list[str] = []
    replies = list(answers or [])

    def ask(text, yes, no):
        asked.append(text)
        return replies.pop(0) if replies else True

    monkeypatch.setattr(window, "ask", ask)
    opened: list[str] = []
    monkeypatch.setattr(window, "open_target", opened.append)
    window.asked = asked
    window.opened = opened
    window.show()
    qapp.processEvents()
    return window


def buttons(window):
    return {
        b.text(): b for b in window.findChildren(QPushButton) if b.isVisibleTo(window) and b.text()
    }


def press(window, text):
    found = buttons(window)
    assert text in found, f"no {text!r} button on {window.screen_name}: {sorted(found)}"
    assert found[text].isEnabled(), f"{text!r} is disabled on {window.screen_name}"
    found[text].click()


def shown_text(window):
    return " ".join(
        w.text() for w in window.findChildren(QLabel) if w.isVisibleTo(window) and w.text()
    )


def fields(window):
    return [e for e in window.findChildren(QLineEdit) if e.isVisibleTo(window)]


def test_tokens_come_from_the_dashboard_styles():
    for dark in (False, True):
        tokens = theme.tokens(dark)
        assert tokens["accent"].startswith("#")
        assert all("var(" not in value for value in tokens.values())
        sheet = theme.style_sheet(tokens)
        assert "{" in sheet and "var(" not in sheet
    assert theme.tokens(False)["sheet"] != theme.tokens(True)["sheet"]
    # CSS alphas (0 to 1) become Qt's (0 to 255).
    assert theme._qt("rgba(0, 102, 204, 0.10)") == "rgba(0, 102, 204, 26)"


def test_new_install_with_a_server_folder(qapp, monkeypatch):
    window = make(qapp, monkeypatch, java=False)
    assert window.screen_name == "new"
    press(window, TEXT["next"])
    assert window.screen_name == "servers"
    assert not buttons(window)[TEXT["next"]].isEnabled()  # no folder yet
    folder = fields(window)[0]
    folder.setText("C:\\Minecraft\\Survival")
    folder.editingFinished.emit()
    qapp.processEvents()
    assert "Looks like a Fabric server." in shown_text(window)
    assert window.answers["servers"][0]["name"] == "Survival"
    press(window, TEXT["next"])

    assert window.screen_name == "password"
    first, second = fields(window)
    first.setText("short")
    second.setText("short")
    press(window, TEXT["next"])
    assert window.screen_name == "password"
    assert TEXT["too_short"] in shown_text(window)
    first.setText("a long enough password")
    second.setText("a different password!")
    press(window, TEXT["next"])
    assert TEXT["no_match"] in shown_text(window)
    press(window, TEXT["show"])
    assert first.echoMode() == QLineEdit.EchoMode.Normal
    second.setText("a long enough password")
    press(window, TEXT["next"])

    assert window.screen_name == "java"  # this PC has Java 8 only
    press(window, TEXT["next"])
    assert window.screen_name == "options"
    press(window, TEXT["next"])
    assert window.screen_name == "phone"
    press(window, TEXT["skip"])

    assert window.screen_name == "progress"
    body = window.wizard.started[0]
    assert body["password"] == "a long enough password"
    assert body["install_java"] == 21
    assert body["start_with_pc"] is True and body["allow_devices"] is True
    assert body["phone_alerts"] is False
    assert body["servers"] == [
        {"folder": "C:\\Minecraft\\Survival", "name": "Survival", "color": "blue", "type": "fabric"}
    ]
    assert "java_choice" not in body and "advanced_open" not in body


def test_a_wrong_folder_says_why_and_keeps_next_off(qapp, monkeypatch):
    window = make(qapp, monkeypatch)
    window.servers_screen()
    folder = fields(window)[0]
    folder.setText("C:\\missing")
    folder.editingFinished.emit()
    qapp.processEvents()
    assert "That folder isn't there" in shown_text(window)
    assert not buttons(window)[TEXT["next"]].isEnabled()


def test_no_to_the_older_copy_question_goes_back_to_the_folder(qapp, monkeypatch):
    window = make(qapp, monkeypatch, answers=[False, True])
    window.options_screen()
    press(window, "▸  " + TEXT["advanced"])
    folder = window.install_folder_field
    folder.setText("D:\\Apps\\Minecraft Server Controller")
    press(window, TEXT["next"])
    assert window.asked == [TEXT["older_here"]]
    assert window.screen_name == "options"  # No: nothing goes on
    assert folder.isVisibleTo(window)
    assert "program_dir" not in window.answers
    press(window, TEXT["next"])  # Yes, replace it
    assert window.screen_name == "phone"
    assert window.answers["program_dir"] == "D:\\Apps\\Minecraft Server Controller"


def test_none_yet_ends_on_make_your_first_server(qapp, monkeypatch):
    window = make(qapp, monkeypatch)
    window.path = "none"
    window.answers["servers"] = []
    window.phone_screen()
    press(window, TEXT["phone_yes"])
    window.wizard.advance(20)
    window.poll()
    assert window.screen_name == "done"
    assert window.wizard.started[0]["phone_alerts"] is True
    assert "scan this code" in shown_text(window)
    press(window, TEXT["first_server"])
    assert window.opened == ["https://mark-pc.tail1234.ts.net:8765/#add-server"]


def test_update_asks_only_when_players_are_online(qapp, monkeypatch):
    found = [
        {
            "describe": "We found Minecraft Server Controller 1.1.0 with 2 servers.",
            "program_dir": "C:\\Program Files\\Minecraft Server Controller",
            "action": "update",
            "refused": None,
        }
    ]
    window = make(
        qapp, monkeypatch, wizard=DemoWizard(found=found, players_online=3), answers=[False]
    )
    assert window.screen_name == "found"
    assert "with 2 servers" in window.title.text()
    press(window, TEXT["update"])
    assert window.asked == ["3 players are online. Update now or wait?"]
    assert window.wizard.started == []  # Wait
    press(window, TEXT["update"])
    assert window.wizard.started[0]["found"] == 0

    quiet = make(qapp, monkeypatch, wizard=DemoWizard(found=found, players_online=0))
    press(quiet, TEXT["update"])
    assert quiet.asked == []
    assert quiet.wizard.started

    # A running server whose players can't be counted is never taken as empty.
    unknown = make(
        qapp,
        monkeypatch,
        wizard=DemoWizard(found=found, players_online=None, running=1),
        answers=[False],
    )
    press(unknown, TEXT["update"])
    assert unknown.asked == [TEXT["players_unknown"]]
    assert unknown.wizard.started == []
    stopped = make(qapp, monkeypatch, wizard=DemoWizard(found=found, players_online=None))
    press(stopped, TEXT["update"])
    assert stopped.asked == []


def test_downgrade_is_one_sentence_and_close(qapp, monkeypatch):
    found = [
        {
            "describe": "We found Minecraft Server Controller 9.0.0 with 1 server.",
            "program_dir": "C:\\Program Files\\Minecraft Server Controller",
            "action": "refused",
            "refused": "A newer version (9.0.0) is installed, so this older one won't replace it.",
        }
    ]
    window = make(qapp, monkeypatch, wizard=DemoWizard(found=found))
    assert window.screen_name == "refused"
    assert "newer version" in shown_text(window)
    assert set(buttons(window)) == {TEXT["close"]}


def test_failed_update_says_it_was_put_back(qapp, monkeypatch):
    found = [{"describe": "x", "program_dir": "C:\\x", "action": "update", "refused": None}]
    window = make(qapp, monkeypatch, wizard=DemoWizard(found=found, fail_at=5))
    press(window, TEXT["update"])
    window.wizard.advance(5)
    window.poll()
    assert window.screen_name == "failed"
    text = shown_text(window)
    assert "The new version didn't start." in text
    assert TEXT["rolled_back"] in text
    assert "install-1.log" in text
    for name in (TEXT["open_log"], TEXT["copy_log"], TEXT["show_details"], TEXT["try_again"]):
        assert name in buttons(window)
    press(window, TEXT["copy_log"])
    assert QtWidgets.QApplication.clipboard().text().startswith('{"event"')
    press(window, TEXT["open_log"])
    assert window.opened[-1].endswith("install-1.log")
    press(window, TEXT["try_again"])
    assert len(window.wizard.started) == 2


def test_progress_bar_shows_only_real_numbers(qapp, monkeypatch):
    window = make(qapp, monkeypatch)
    window.run()
    bar = window.progress_bar
    assert bar.maximum() == 1000
    window.wizard.advance(1)  # the demo's step 1 has no known total
    window.poll()
    assert (bar.minimum(), bar.maximum()) == (0, 0)  # Qt's busy bar, no number


def test_the_window_waits_for_a_running_install(qapp, monkeypatch):
    window = make(qapp, monkeypatch)
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    window.run()
    assert window.close() is False
    window.wizard.advance(20)
    window.poll()
    assert window.close() is True


def test_not_admin(qapp, monkeypatch):
    window = make(qapp, monkeypatch, admin=False)
    assert window.screen_name == "not_admin"
    assert TEXT["not_admin"] in shown_text(window)


def test_remove_keeps_data_unless_ticked(qapp, monkeypatch):
    window = make(qapp, monkeypatch, uninstall=True)
    assert window.screen_name == "remove"
    press(window, TEXT["remove_button"])
    assert window.wizard.removed == [False]
    assert "kept in C:\\ProgramData\\Minecraft Server Controller" in shown_text(window)

    ticked = make(qapp, monkeypatch, uninstall=True)
    box = next(
        b for b in ticked.findChildren(QtWidgets.QCheckBox) if b.text() == TEXT["remove_data"]
    )
    box.click()
    press(ticked, TEXT["remove_button"])
    assert ticked.wizard.removed == [True]


def test_update_can_give_ticked_servers_a_newer_java(qapp, monkeypatch):
    found = [
        {
            "describe": "We found Minecraft Server Controller 1.1.0 with 3 servers.",
            "program_dir": "C:\\Program Files\\Minecraft Server Controller",
            "action": "update",
            "refused": None,
            "servers": [
                {"id": "survival", "name": "Survival", "java": "java", "major": 17},
                {"id": "old", "name": "Old pack", "java": "C:\\jdk8\\bin\\java.exe", "major": 8},
                {"id": "broken", "name": "Broken", "java": "C:\\gone\\java.exe", "major": None},
                {"id": "new", "name": "New", "java": "java21", "major": 21},
            ],
        }
    ]
    window = make(qapp, monkeypatch, wizard=DemoWizard(found=found, java=False))
    # Opened, because one server's Java doesn't run; only that one is ticked.
    boxes = {
        b.text().split("  ")[0]: b
        for b in window.findChildren(QtWidgets.QCheckBox)
        if b.isVisibleTo(window)
    }
    assert set(boxes) == {"Survival", "Old pack", "Broken"}  # New already has 21
    assert [n for n, b in boxes.items() if b.isChecked()] == ["Broken"]
    assert "Install Java 21 from Adoptium" in shown_text(window)
    boxes["Survival"].click()
    press(window, TEXT["update"])
    body = window.wizard.started[0]
    assert body["java_servers"] == ["broken", "survival"]
    assert body["install_java"] == 21 and body["java_path"] is None


def test_update_with_working_java_folds_the_java_choice_away(qapp, monkeypatch):
    found = [
        {
            "describe": "x",
            "program_dir": "C:\\x",
            "action": "update",
            "refused": None,
            "servers": [{"id": "s", "name": "Survival", "java": "java", "major": 17}],
        }
    ]
    window = make(qapp, monkeypatch, wizard=DemoWizard(found=found))
    assert not [b for b in window.findChildren(QtWidgets.QCheckBox) if b.isVisibleTo(window)]
    press(window, TEXT["update"])
    body = window.wizard.started[0]
    assert body["java_servers"] == [] and body["install_java"] is None
