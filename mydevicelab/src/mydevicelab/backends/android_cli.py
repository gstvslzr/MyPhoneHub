# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Placeholder for Google's Android CLI ('android emulator ...').

Not usable in v1.0: per developer.android.com/tools/agents/android-cli/commands/emulator_create
(checked 2026-10-28), 'android emulator create' accepts only a named profile and
--list-profiles - no RAM, storage, locale or core options - so it cannot back the
config editor. Revisit when Google adds those options.
"""
from __future__ import annotations


class AndroidCliBackend:
    available = False
    reason = ("Android CLI 'emulator create' has no hardware options yet "
              "(checked 2026-10-28); MyDeviceLab uses the SDK command-line tools.")

    def __init__(self, *_, **__):
        raise NotImplementedError(self.reason)
