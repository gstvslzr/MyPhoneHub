# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Typed errors. UI shows .user_message; logs keep the detail."""


class MyDeviceLabError(Exception):
    def __init__(self, user_message: str, detail: str = ""):
        super().__init__(user_message if not detail else f"{user_message}\n{detail}")
        self.user_message = user_message
        self.detail = detail


class ToolNotFoundError(MyDeviceLabError):
    """A required SDK tool is not installed."""


class ToolFailedError(MyDeviceLabError):
    """A tool ran and exited non-zero."""

    def __init__(self, user_message: str, argv=None, returncode=None, stdout="", stderr=""):
        detail = f"argv={argv!r} rc={returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        super().__init__(user_message, detail)
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ToolTimeoutError(MyDeviceLabError):
    """A tool exceeded its timeout and was killed."""


class ValidationError(MyDeviceLabError):
    """User input or a profile failed validation."""


class DeviceBusyError(MyDeviceLabError):
    """Operation refused because the device is running."""
