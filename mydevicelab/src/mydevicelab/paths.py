# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Filesystem locations (XDG) and SDK root resolution."""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()


def _xdg(var: str, fallback: Path) -> Path:
    v = os.environ.get(var)
    return Path(v) if v and Path(v).is_absolute() else fallback


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", HOME / ".config") / "mydevicelab"
DATA_DIR = _xdg("XDG_DATA_HOME", HOME / ".local" / "share") / "mydevicelab"
LOG_DIR = DATA_DIR / "logs"
USER_PROFILES_DIR = CONFIG_DIR / "profiles"
DEVICE_SETTINGS_DIR = CONFIG_DIR / "devices"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
DEFAULT_PRIVATE_SDK = DATA_DIR / "sdk"

# Built-in profiles: installed copy first, then the source tree (development).
_SRC_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_PROFILE_DIRS = [Path("/usr/share/mydevicelab/profiles"), _SRC_ROOT / "profiles"]
SCHEMA_PATHS = [Path("/usr/share/mydevicelab/schema/device-profile.schema.json"),
                _SRC_ROOT / "schema" / "device-profile.schema.json"]


def avd_home() -> Path:
    """AVD directory. Default ~/.android/avd per Google docs; ANDROID_AVD_HOME overrides."""
    v = os.environ.get("ANDROID_AVD_HOME")
    return Path(v) if v else HOME / ".android" / "avd"


def sdk_root_candidates(configured: str | None = None) -> list[Path]:
    cands: list[Path] = []
    if configured:
        cands.append(Path(configured).expanduser())
    for var in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        v = os.environ.get(var)
        if v:
            cands.append(Path(v).expanduser())
    cands += [HOME / "Android" / "Sdk", DEFAULT_PRIVATE_SDK]
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def ensure_private_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, LOG_DIR, USER_PROFILES_DIR, DEVICE_SETTINGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for d in (CONFIG_DIR, DATA_DIR):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
