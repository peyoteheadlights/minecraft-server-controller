from __future__ import annotations

from enum import Enum


class ServerState(str, Enum):
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    ONLINE = "ONLINE"
    STOPPING = "STOPPING"
    CRASHED = "CRASHED"
    RESTARTING = "RESTARTING"
    # Crashed, with an automatic restart counting down. Nothing but
    # "restart now" or "cancel" may leave this state; a normal start is refused.
    RESTART_PENDING = "RESTART_PENDING"
    UNKNOWN = "UNKNOWN"


class ExitReason(str, Enum):
    USER_STOP = "user_stop"              # operator pressed STOP / RESTART
    SCHEDULED_STOP = "scheduled_stop"    # a scheduled task asked for it
    CLEAN_EXIT = "clean_exit"            # server shut itself down cleanly
    CRASH = "crash"                      # died while running
    STARTUP_FAILURE = "startup_failure"  # died before "Done (..)!"
    FORCE_KILLED = "force_killed"        # graceful stop timed out / kill requested
    UNKNOWN = "unknown"


NORMAL_REASONS = {ExitReason.USER_STOP, ExitReason.SCHEDULED_STOP, ExitReason.CLEAN_EXIT}
