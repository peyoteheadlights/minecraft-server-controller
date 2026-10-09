"""A progress bar that never lies.

* Each step has a weight that reflects how much work it does.
* The bar moves only when a step finishes, or when a step that can measure
  itself (a copy, a download) reports bytes done out of bytes total.
* A step that can't say how far along it is shows as indeterminate (a
  moving indicator with its name), never as an invented percentage.
* "Done" appears only after the final check has passed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PENDING, RUNNING, DONE, FAILED, SKIPPED = "pending", "running", "done", "failed", "skipped"


@dataclass
class StepState:
    key: str
    name: str  # the plain name shown above the bar ("Setting up secure connection…")
    weight: float
    state: str = PENDING
    done_units: int | None = None
    total_units: int | None = None
    started: float | None = None
    finished: float | None = None
    message: str = ""  # one plain sentence on failure
    details: str = ""  # the real error, for "Show details"

    @property
    def fraction(self) -> float | None:
        """How far through this step is, when it can measure that."""
        if self.state in (DONE, SKIPPED):
            return 1.0
        if self.state != RUNNING or not self.total_units:
            return None
        return min(1.0, max(0.0, (self.done_units or 0) / self.total_units))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "state": self.state,
            "fraction": self.fraction,
            "done": self.done_units,
            "total": self.total_units,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class Progress:
    steps: list[StepState] = field(default_factory=list)
    on_change: Callable[[dict[str, Any]], None] | None = None
    finished: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, key: str, name: str, weight: float) -> None:
        self.steps.append(StepState(key, name, weight))

    def step(self, key: str) -> StepState:
        for step in self.steps:
            if step.key == key:
                return step
        raise KeyError(key)

    def start(self, key: str) -> None:
        with self._lock:
            step = self.step(key)
            step.state, step.started = RUNNING, time.time()
            step.done_units = step.total_units = None
        self._changed()

    def advance(self, key: str, done: int, total: int) -> None:
        """Real units done out of real units total (bytes, files)."""
        with self._lock:
            step = self.step(key)
            if step.state != RUNNING:
                return
            step.done_units, step.total_units = max(0, done), max(0, total)
        self._changed()

    def reporter(self, key: str) -> Callable[[int, int], None]:
        return lambda done, total: self.advance(key, done, total)

    def finish(self, key: str) -> None:
        with self._lock:
            step = self.step(key)
            step.state, step.finished = DONE, time.time()
        self._changed()

    def skip(self, key: str, why: str = "") -> None:
        with self._lock:
            step = self.step(key)
            step.state, step.message = SKIPPED, why
        self._changed()

    def fail(self, key: str, message: str, details: str = "") -> None:
        with self._lock:
            step = self.step(key)
            step.state, step.finished = FAILED, time.time()
            step.message, step.details = message, details
        self._changed()

    def complete(self) -> None:
        """Called once the final checks passed. Refuses if any step failed
        or never ran, so "Done" can't appear after a failure."""
        with self._lock:
            unfinished = [s.key for s in self.steps if s.state not in (DONE, SKIPPED)]
            if unfinished:
                raise RuntimeError(f"steps not finished: {', '.join(unfinished)}")
            self.finished = True
        self._changed()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = sum(s.weight for s in self.steps) or 1.0
            counted = 0.0
            current = None
            for step in self.steps:
                if step.state in (DONE, SKIPPED):
                    counted += step.weight
                elif step.state in (RUNNING, FAILED) and current is None:
                    current = step
                    if step.state == RUNNING and step.fraction is not None:
                        counted += step.weight * step.fraction
            failed = next((s for s in self.steps if s.state == FAILED), None)
            percent = round(100.0 * counted / total, 1)
            return {
                "percent": percent,
                "indeterminate": bool(
                    current is not None and current.state == RUNNING and current.fraction is None
                ),
                "current": current.name if current is not None else None,
                "failed": failed.to_dict() if failed else None,
                "finished": self.finished,
                "steps": [s.to_dict() for s in self.steps],
            }

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change(self.snapshot())
            except Exception:
                pass
