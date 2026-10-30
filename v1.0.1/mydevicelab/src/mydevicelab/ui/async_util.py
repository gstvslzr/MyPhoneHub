# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Run blocking service calls off the GTK main loop; deliver results back on it."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from gi.repository import GLib

from ..core.errors import MyDeviceLabError

log = logging.getLogger(__name__)


def run_async(fn: Callable, on_done: Callable | None = None, on_error: Callable | None = None) -> None:
    def worker():
        try:
            result = fn()
        except MyDeviceLabError as exc:
            log.warning("operation failed: %s", exc)
            if on_error:
                GLib.idle_add(_once, on_error, exc.user_message)
            return
        except Exception as exc:  # unexpected: log full trace, show short message
            log.exception("unexpected error")
            if on_error:
                GLib.idle_add(_once, on_error, f"Unexpected error: {exc}")
            return
        if on_done:
            GLib.idle_add(_once, on_done, result)

    threading.Thread(target=worker, daemon=True).start()


def _once(cb, arg):
    cb(arg)
    return GLib.SOURCE_REMOVE
