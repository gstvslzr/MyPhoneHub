# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Device lifecycle: create from a profile, clone, rename, delete, start, stop."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..backends.base import AvdInfo, ToolBackend
from ..core.errors import ValidationError
from .config_service import ConfigService
from .profile_service import Profile
from .settings_catalog import BY_ID

log = logging.getLogger(__name__)


@dataclass
class CreateReport:
    name: str
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class StartReport:
    name: str
    argv: list[str]
    log_path: Path
    notes: list[str] = field(default_factory=list)


class DeviceService:
    def __init__(self, backend: ToolBackend, config: ConfigService, log_dir: Path):
        self.backend = backend
        self.config = config
        self.log_dir = Path(log_dir)

    def list(self) -> list[AvdInfo]:
        return self.backend.list_avds()

    def get(self, name: str) -> AvdInfo:
        for a in self.list():
            if a.name == name:
                return a
        raise ValidationError(f"Device '{name}' not found.")

    # ------------------------------------------------------------------ create
    def create(self, name: str, profile: Profile, sdk_id: str, sdcard_mb: int | None = None) -> CreateReport:
        rep = CreateReport(name)
        caps = self.backend.capabilities()
        device_id = None

        if profile.kind == "builtin_device":
            available = set(self.backend.list_device_definitions())
            match = next((c for c in profile.data["avd_device_id_candidates"] if c in available), None)
            if match is None:
                raise ValidationError(
                    f"{profile.display_name}: none of {profile.data['avd_device_id_candidates']} "
                    f"exist in your installed avdmanager. Update the SDK command-line tools.")
            if caps.avdmanager_device_flag:
                device_id = match
                rep.applied.append(f"Device definition: {match}")
            else:
                rep.skipped.append(f"Device definition {match}: installed avdmanager does not list a device "
                                   f"option; created with the system image defaults.")
        elif profile.kind == "viewport_preview":
            raise ValidationError("Viewport-only profiles cannot create Android devices.")

        sd = sdcard_mb if sdcard_mb is not None else profile.defaults.get("sdcard_mb")
        avd = self.backend.create_avd(name, sdk_id, sd or None, device_id)
        if sd:
            rep.applied.append(f"SD card: {sd} MB")

        # Hardware values for custom (Galaxy-sized) profiles.
        changes: dict[str, object] = {}
        if profile.kind == "custom_hardware":
            hw = profile.hardware
            changes.update(lcd_width=hw["screen_width_px"], lcd_height=hw["screen_height_px"],
                           lcd_density=str(profile.density()), ram_mb=profile.emulator_ram_mb())
            if profile.emulator_ram_mb() != hw["ram_mb_device"]:
                rep.notes.append(f"RAM {hw['ram_mb_device']} MB on the real phone; emulator uses "
                                 f"{profile.emulator_ram_mb()} MB (documented maximum).")
            cams = hw.get("cameras", {})
            if cams.get("back") is False:
                changes["camera_back"] = "none"
            if cams.get("front") is False:
                changes["camera_front"] = "none"

        d = profile.defaults
        for sid, key in (("netspeed", "netspeed"), ("netdelay", "netdelay"), ("timezone", "timezone")):
            if d.get(key):
                changes[sid] = d[key]
        if d.get("gpu_mode") == "swiftshader_indirect":
            changes["gpu_mode"] = "swiftshader_indirect"

        allowed: dict[str, object] = {}
        for sid, v in changes.items():
            s = BY_ID[sid]
            av = self.config.availability(s, avd, caps)
            if av.available:
                allowed[sid] = v
            else:
                rep.skipped.append(f"{s.label} = {v}: {av.reason}")
        if allowed:
            res = self.config.save(avd, allowed, caps)
            rep.applied += [f"{BY_ID[sid].label}: {v}" for sid, v in allowed.items()]
            rep.notes += res.notes
        if profile.kind == "builtin_device" and device_id is None:
            rep.notes.append(f"This device uses generic image defaults, not the {profile.display_name} "
                             f"screen/RAM. Update SDK command-line tools, then re-create it.")
        else:
            rep.notes.append(profile.label_note)
        log.info("created %s: applied=%s skipped=%s", name, rep.applied, rep.skipped)
        return rep

    # ------------------------------------------------------------------ manage
    def clone(self, name: str, new_name: str) -> AvdInfo:
        avd = self.backend.clone_avd(name, new_name)
        launch = self.config.read_launch(name)
        if launch:
            self.config.write_launch(new_name, launch)
        return avd

    def rename(self, name: str, new_name: str) -> None:
        self.backend.rename_avd(name, new_name)
        self.config.rename_launch(name, new_name)

    def delete(self, name: str) -> None:
        self.backend.delete_avd(name)
        self.config.delete_launch(name)

    # ------------------------------------------------------------------ run
    def start(self, name: str) -> StartReport:
        avd = self.get(name)
        caps = self.backend.capabilities()
        flags, notes = self.config.launch_flags(avd, caps)
        log_path = self.log_dir / f"emulator-{name}-{datetime.now():%Y%m%d-%H%M%S}.log"
        self.backend.start(name, flags, log_path)
        return StartReport(name, self.backend.build_launch_argv(name, flags), log_path, notes)

    def stop(self, name: str) -> bool:
        return self.backend.stop(name)
