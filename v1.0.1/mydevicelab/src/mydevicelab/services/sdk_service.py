# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""SDK location and status. Image download/licensing UI arrives in Phase 4;
until then system images are installed with Google's own sdkmanager (README)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import paths


@dataclass
class SdkStatus:
    root: Path | None
    candidates: list[Path]
    has_cmdline_tools: bool
    has_emulator: bool
    has_platform_tools: bool
    image_count: int

    @property
    def usable(self) -> bool:
        return self.root is not None and self.has_cmdline_tools and self.has_emulator and self.image_count > 0


def load_settings(settings_file: Path = paths.SETTINGS_FILE) -> dict:
    try:
        return json.loads(settings_file.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict, settings_file: Path = paths.SETTINGS_FILE) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(settings_file)


def _looks_like_sdk(p: Path) -> bool:
    return p.is_dir() and any((p / d).is_dir() for d in ("cmdline-tools", "emulator", "platform-tools",
                                                          "system-images", "tools"))


def resolve_sdk_root(configured: str | None) -> tuple[Path | None, list[Path]]:
    cands = paths.sdk_root_candidates(configured)
    for c in cands:
        if _looks_like_sdk(c):
            return c, cands
    return None, cands


def sdk_status(configured: str | None) -> SdkStatus:
    root, cands = resolve_sdk_root(configured)
    if root is None:
        return SdkStatus(None, cands, False, False, False, 0)
    images = list((root / "system-images").glob("*/*/*")) if (root / "system-images").is_dir() else []
    return SdkStatus(
        root, cands,
        has_cmdline_tools=any(root.glob("cmdline-tools/*/bin/avdmanager")),
        has_emulator=(root / "emulator" / "emulator").is_file(),
        has_platform_tools=(root / "platform-tools" / "adb").is_file(),
        image_count=sum(1 for i in images if i.is_dir()),
    )
