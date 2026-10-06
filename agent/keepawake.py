"""Keep the PC awake while a server runs.

Windows going to sleep stops every server for everyone playing. While any
server is running, the agent asks Windows not to sleep, with the
SetThreadExecutionState API called through ctypes (no program is run and
pywin32 isn't needed), and lets it sleep again once every server has
stopped. ``power.keep_awake`` turns this off.

The request belongs to the thread that made it, so it is always made from
the agent's event loop thread, which lives as long as the agent does.

What the request can't stop is reported, not guessed: closing a laptop's
lid, the power button, and a battery running low still put Windows to
sleep. The battery state comes from psutil and the lid setting from
Windows' own power plan (powrprof.dll); either is Unknown when it can't be
read.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import AgentCore
    from .events import Event

log = logging.getLogger("msc.keepawake")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

# Windows' power plan: the "Power buttons and lid" group and its lid action.
GUID_SYSTEM_BUTTON_SUBGROUP = "4f971e89-eebd-4455-a8de-9e59040e7347"
GUID_LIDSWITCH_ACTION = "5ca83367-6e45-459f-a27b-476b1d01c936"
LID_ACTIONS = {0: "nothing", 1: "sleep", 2: "hibernate", 3: "shut down"}


def _windows_call(flags: int) -> int:
    import ctypes

    return int(ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint32(flags)))  # type: ignore[attr-defined]


def battery() -> dict[str, Any] | None:
    """{"present", "plugged_in", "percent"}, or None when it can't be read.
    A PC with no battery reads as present False."""
    try:
        import psutil

        reading = psutil.sensors_battery()
    except Exception:
        return None
    if reading is None:
        return {"present": False, "plugged_in": None, "percent": None}
    return {
        "present": True,
        "plugged_in": reading.power_plugged,
        "percent": round(reading.percent) if reading.percent is not None else None,
    }


def lid_actions() -> dict[str, str] | None:
    """What closing the lid does on mains power and on battery, from the
    active power plan, or None when it can't be read (not Windows, or the
    plan has no lid setting)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        def guid(text: str) -> GUID:
            raw = uuid.UUID(text).bytes_le
            return GUID.from_buffer_copy(raw)

        powrprof = ctypes.windll.powrprof  # type: ignore[attr-defined]
        scheme = ctypes.POINTER(GUID)()
        if powrprof.PowerGetActiveScheme(None, ctypes.byref(scheme)) != 0:
            return None
        try:
            group, setting = guid(GUID_SYSTEM_BUTTON_SUBGROUP), guid(GUID_LIDSWITCH_ACTION)
            found: dict[str, str] = {}
            for name, reader in (
                ("plugged_in", powrprof.PowerReadACValueIndex),
                ("battery", powrprof.PowerReadDCValueIndex),
            ):
                value = wintypes.DWORD()
                if reader(None, scheme, ctypes.byref(group), ctypes.byref(setting), ctypes.byref(value)) == 0:
                    found[name] = LID_ACTIONS.get(value.value, "unknown")
            return found or None
        finally:
            ctypes.windll.kernel32.LocalFree(scheme)  # type: ignore[attr-defined]
    except Exception:
        log.debug("could not read the lid setting", exc_info=True)
        return None


class KeepAwake:
    def __init__(self, core: AgentCore, call: Callable[[int], int] | None = None):
        self.core = core
        self.supported = os.name == "nt" or call is not None
        self._call = call or _windows_call
        self.active = False
        self.problem: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.core.config.power.keep_awake)

    def running_servers(self) -> list[str]:
        return [ctx.name for ctx in self.core.servers.values() if ctx.server.running]

    def update(self) -> bool:
        """Ask Windows not to sleep while a server runs, or stop asking."""
        want = self.enabled and bool(self.running_servers())
        if not self.supported or want == self.active:
            return self.active
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED if want else ES_CONTINUOUS
        try:
            ok = self._call(flags) != 0
        except Exception as exc:  # pragma: no cover - reported, never hidden
            ok = False
            self.problem = f"Windows refused the request: {exc}"
        if ok:
            self.active = want
            self.problem = None
            log.info("keep awake %s", "on" if want else "off")
        elif not self.problem:
            self.problem = "Windows refused the request to stay awake."
        return self.active

    async def handle(self, event: Event) -> None:
        if event.type == "state" or event.type in ("server_started", "server_stopped"):
            self.update()

    def stop(self) -> None:
        if self.active:
            try:
                self._call(ES_CONTINUOUS)
            except Exception:  # pragma: no cover
                pass
            self.active = False

    def status(self) -> dict[str, Any]:
        """What the Overview and App settings show: whether the PC is being
        kept awake now, and what can still put it to sleep."""
        power = battery()
        lid = lid_actions() if power and power.get("present") else None
        notes: list[str] = []
        if power and power.get("present") and power.get("plugged_in") is False:
            notes.append("on_battery")
        if lid and any(action in ("sleep", "hibernate") for action in lid.values()):
            notes.append("lid_sleeps")
        return {
            "supported": self.supported,
            "enabled": self.enabled,
            "active": self.active,
            "running": self.running_servers(),
            "problem": self.problem,
            "battery": power,
            "lid": lid,
            "still_sleeps": notes,
        }
