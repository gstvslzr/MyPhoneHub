# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Subprocess wrapper.

Rules enforced here (ARCHITECTURE section 6):
- argv lists only; shell=True is never used, so user input is never parsed by a shell.
- Environment is rebuilt from an allowlist instead of inheriting everything.
- Every call has a timeout; on expiry the process is killed.
- Every call is logged (argv, rc, duration); output is logged truncated.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .errors import ToolFailedError, ToolNotFoundError, ToolTimeoutError

log = logging.getLogger(__name__)

# Variables the SDK tools and the emulator window need. Anything else is dropped.
ENV_ALLOWLIST = {
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE",
    "TMPDIR", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "DBUS_SESSION_BUS_ADDRESS", "PULSE_SERVER", "JAVA_HOME",
}
ENV_PREFIX_ALLOWLIST = ("ANDROID_",)
LOG_OUTPUT_LIMIT = 4000


def build_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k in ENV_ALLOWLIST or k.startswith(ENV_PREFIX_ALLOWLIST)}
    if extra:
        env.update(extra)
    return env


@dataclass(frozen=True)
class RunResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


class ProcessRunner:
    def __init__(self, extra_env: dict[str, str] | None = None):
        self.extra_env = dict(extra_env or {})

    def _check_exe(self, argv: Sequence[str]) -> None:
        if not argv:
            raise ValueError("argv must not be empty")
        exe = argv[0]
        if os.sep in exe:
            if not (Path(exe).is_file() and os.access(exe, os.X_OK)):
                raise ToolNotFoundError(f"Tool not found or not executable: {exe}")

    def run(self, argv: Sequence[str], *, timeout: float = 120, input_text: str | None = None,
            check: bool = True, fail_message: str | None = None) -> RunResult:
        argv = tuple(str(a) for a in argv)
        self._check_exe(argv)
        start = time.monotonic()
        log.info("run %s", argv)
        try:
            proc = subprocess.run(
                argv, input=input_text, capture_output=True, text=True,
                timeout=timeout, env=build_env(self.extra_env), shell=False,
                stdin=None if input_text is not None else subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ToolNotFoundError(f"Tool not found: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolTimeoutError(f"{Path(argv[0]).name} did not finish within {timeout:.0f} s",
                                   f"argv={argv!r}") from exc
        result = RunResult(argv, proc.returncode, proc.stdout or "", proc.stderr or "",
                           time.monotonic() - start)
        log.info("rc=%s in %.2fs", result.returncode, result.duration_s)
        if result.stdout:
            log.debug("stdout: %s", result.stdout[:LOG_OUTPUT_LIMIT])
        if result.stderr:
            log.debug("stderr: %s", result.stderr[:LOG_OUTPUT_LIMIT])
        if check and result.returncode != 0:
            raise ToolFailedError(fail_message or f"{Path(argv[0]).name} failed (exit {result.returncode})",
                                  argv, result.returncode, result.stdout, result.stderr)
        return result

    def spawn(self, argv: Sequence[str], log_path: Path) -> subprocess.Popen:
        """Start a long-running process (the emulator), detached from our stdin,
        output appended to log_path. Caller owns the Popen."""
        argv = tuple(str(a) for a in argv)
        self._check_exe(argv)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log.info("spawn %s -> %s", argv, log_path)
        fh = open(log_path, "ab", buffering=0)
        try:
            return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                    env=build_env(self.extra_env), shell=False, start_new_session=True)
        finally:
            fh.close()  # child keeps its own descriptor
