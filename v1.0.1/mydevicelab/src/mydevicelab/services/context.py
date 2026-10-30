# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Wires paths, backend and services together. One instance per app run."""
from __future__ import annotations

import logging
import logging.handlers
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from ..backends.legacy_sdk import LegacySdkBackend
from ..core.host_check import HostReport, run_host_checks
from .config_service import ConfigService
from .device_service import DeviceService
from .profile_service import ProfileService
from .sdk_service import SdkStatus, load_settings, sdk_status


def _first_existing(cands: list[Path]) -> Path:
    for c in cands:
        if c.exists():
            return c
    raise FileNotFoundError(f"None of these exist: {cands}")


def setup_logging(log_dir: Path = paths.LOG_DIR, verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    h = logging.handlers.RotatingFileHandler(log_dir / "mydevicelab.log", maxBytes=2_000_000,
                                             backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


@dataclass
class AppContext:
    sdk: SdkStatus
    backend: LegacySdkBackend
    profiles: ProfileService
    config: ConfigService
    devices: DeviceService
    avd_home: Path

    def host_report(self) -> HostReport:
        return run_host_checks(self.avd_home)


def build_context(sdk_root_override: str | None = None, avd_home: Path | None = None,
                  config_dir: Path | None = None, log_dir: Path | None = None) -> AppContext:
    settings = load_settings()
    status = sdk_status(sdk_root_override or settings.get("sdk_root"))
    avd_home = avd_home or paths.avd_home()
    config_dir = config_dir or paths.CONFIG_DIR
    log_dir = log_dir or paths.LOG_DIR
    backend = LegacySdkBackend(status.root, avd_home)
    profiles = ProfileService(_first_existing(paths.SCHEMA_PATHS), paths.BUILTIN_PROFILE_DIRS,
                              config_dir / "profiles")
    config = ConfigService(config_dir / "devices")
    devices = DeviceService(backend, config, log_dir)
    return AppContext(status, backend, profiles, config, devices, avd_home)
