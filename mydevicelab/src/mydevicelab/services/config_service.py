# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Reads/writes per-device settings.

- 'config' settings live in the AVD's config.ini (backed up before every write).
- 'launch' settings live in ~/.config/mydevicelab/devices/<name>.json and become
  emulator flags at start.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..backends.base import AvdInfo, Capabilities
from ..core.errors import DeviceBusyError, ValidationError
from ..core.ini_file import IniFile
from .settings_catalog import (BY_ID, EMU_RAM_MAX_MB, EMU_RAM_MIN_MB, SETTINGS,
                               VERIFIED_EVIDENCE, Setting)

ZONEINFO = Path("/usr/share/zoneinfo")
_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)B?\s*$", re.I)


# ----------------------------------------------------------------- conversions
def parse_size_mb(raw: str | None) -> int | None:
    """'6G' -> 6144, '512M' -> 512, '1048576K' -> 1024, '4096' (no unit) -> 4096 (MB).
    A bare number is treated as MB because that is how hw.ramSize appears in Google's sample."""
    if raw is None:
        return None
    m = _SIZE_RE.match(str(raw))
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).upper()
    factor = {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}[unit]
    return int(round(n * factor))


def parse_data_partition_gb(raw: str | None) -> int | None:
    """disk.dataPartition.size. Google's sample uses '6G'. The unit of a bare number is
    NOT documented: values >= 2^20 are read as bytes, smaller ones as MB (heuristic,
    to be confirmed on a real config.ini). MyDeviceLab always writes '<n>G'."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.isdigit():
        n = int(s)
        return int(round(n / (1024 ** 3))) if n >= 1024 ** 2 else int(round(n / 1024))
    mb = parse_size_mb(s)
    return None if mb is None else int(round(mb / 1024))


def parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return str(raw).strip().lower() in ("yes", "true", "1", "on")


# ----------------------------------------------------------------- availability
@dataclass
class Availability:
    available: bool
    reason: str


@dataclass
class SaveResult:
    backup: Path | None
    changed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class ConfigService:
    def __init__(self, device_settings_dir: Path, zoneinfo: Path = ZONEINFO):
        self.device_settings_dir = Path(device_settings_dir)
        self.zoneinfo = zoneinfo

    # ---- availability -------------------------------------------------------
    def availability(self, s: Setting, avd: AvdInfo, caps: Capabilities) -> Availability:
        if s.store == "config":
            if s.evidence in VERIFIED_EVIDENCE:
                return Availability(True, "")
            if s.key in caps.hardware_keys:
                return Availability(True, "")
            if s.key in avd.config:
                return Availability(True, "")
            return Availability(False, f"'{s.key}' is not in your emulator's hardware catalog or this "
                                       f"device's config, so it is not offered.")
        # launch flag
        if not caps.emulator_present:
            return Availability(False, "Emulator not installed.")
        if s.evidence == "official_docs":
            return Availability(True, "")
        if s.flag in caps.emulator_flags:
            return Availability(True, "")
        return Availability(False, f"Your emulator's help does not list {s.flag}.")

    # ---- read ---------------------------------------------------------------
    def _launch_path(self, name: str) -> Path:
        return self.device_settings_dir / f"{name}.json"

    def read_launch(self, name: str) -> dict:
        p = self._launch_path(name)
        try:
            return json.loads(p.read_text()).get("launch", {})
        except (OSError, json.JSONDecodeError):
            return {}

    def read_values(self, avd: AvdInfo) -> dict[str, object]:
        cfg = IniFile(avd.config_path)
        launch = self.read_launch(avd.name)
        vals: dict[str, object] = {}
        for s in SETTINGS:
            if s.store == "launch":
                vals[s.id] = launch.get(s.id, False if s.kind == "bool" else "")
                continue
            raw = cfg.get(s.key)
            if s.kind == "bool":
                vals[s.id] = parse_bool(raw)
            elif s.kind == "gb":
                vals[s.id] = parse_data_partition_gb(raw)
            elif s.id in ("ram_mb", "vm_heap_mb", "sdcard_mb"):
                vals[s.id] = parse_size_mb(raw)
            elif s.kind == "int":
                vals[s.id] = int(raw) if raw and raw.strip().isdigit() else None
            else:
                vals[s.id] = raw
        return vals

    # ---- validate -----------------------------------------------------------
    def validate(self, s: Setting, value) -> object:
        if s.kind == "bool":
            return bool(value)
        if s.kind in ("int", "gb"):
            try:
                v = int(value)
            except (TypeError, ValueError):
                raise ValidationError(f"{s.label}: must be a whole number")
            if s.id == "ram_mb":
                v = max(EMU_RAM_MIN_MB, min(EMU_RAM_MAX_MB, v))
            if not (s.minimum <= v <= s.maximum):
                raise ValidationError(f"{s.label}: must be between {s.minimum} and {s.maximum}")
            return v
        if s.kind == "choice":
            v = "" if value is None else str(value)
            if v not in s.choices:
                raise ValidationError(f"{s.label}: '{v}' is not an allowed value")
            return v
        v = ("" if value is None else str(value)).strip()
        if not v:
            return ""
        patterns = {
            "language": (r"^[a-z]{2,3}$", "2-3 lowercase letters, e.g. es"),
            "country": (r"^([A-Z]{2}|\d{3})$", "2 uppercase letters, e.g. US"),
            "locale": (r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$", "e.g. es-US"),
            "timezone": (r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+){1,2}$", "IANA name, e.g. America/New_York"),
        }
        pat, hint = patterns.get(s.id, (r"^[\w./+-]{1,64}$", "letters, digits, ./+-"))
        if not re.match(pat, v):
            raise ValidationError(f"{s.label}: invalid value ({hint})")
        if s.id == "timezone" and self.zoneinfo.is_dir() and not (self.zoneinfo / v).is_file():
            raise ValidationError(f"{s.label}: '{v}' is not in the time zone database")
        return v

    # ---- write --------------------------------------------------------------
    def save(self, avd: AvdInfo, changes: dict[str, object], caps: Capabilities,
             sdcard_maker=None) -> SaveResult:
        """changes: setting id -> new value. Refuses while the device runs."""
        if avd.running:
            raise DeviceBusyError(f"'{avd.name}' is running. Stop it before changing settings.")
        current = self.read_values(avd)
        cfg = IniFile(avd.config_path)
        launch = self.read_launch(avd.name)
        result = SaveResult(None)
        cfg_dirty = launch_dirty = False
        sd_resize_to: int | None = None

        for sid, raw in changes.items():
            s = BY_ID.get(sid)
            if s is None:
                raise ValidationError(f"Unknown setting: {sid}")
            av = self.availability(s, avd, caps)
            if not av.available:
                raise ValidationError(f"{s.label} cannot be changed: {av.reason}")
            v = self.validate(s, raw)
            if v == current.get(sid):
                continue
            result.changed.append(s.label)
            if s.store == "launch":
                launch[sid] = v
                launch_dirty = True
                continue
            if s.kind == "bool":
                cfg.set(s.key, "yes" if v else "no")
            elif s.kind == "gb":
                cfg.set(s.key, f"{v}G")
            elif s.id in ("sdcard_mb", "vm_heap_mb"):
                cfg.set(s.key, f"{v}M")
                if s.id == "sdcard_mb":
                    sd_resize_to = v
            else:
                cfg.set(s.key, str(v))
            cfg_dirty = True

        if cfg_dirty:
            result.backup = cfg.save(make_backup=True)
        if launch_dirty:
            self.write_launch(avd.name, launch)

        if sd_resize_to is not None:
            img = avd.avd_dir / "sdcard.img"
            if img.exists():
                img.unlink()
            if sd_resize_to > 0:
                if sdcard_maker is None:
                    result.notes.append("SD card size saved; image not recreated (mksdcard not available).")
                else:
                    sdcard_maker(sd_resize_to, img)
                    result.notes.append(f"SD card image recreated at {sd_resize_to} MB (previous contents deleted).")
            else:
                result.notes.append("SD card removed.")
        if "ram_mb" in changes:
            try:
                if int(changes["ram_mb"]) > EMU_RAM_MAX_MB:
                    result.notes.append(f"RAM clamped to {EMU_RAM_MAX_MB} MB (emulator maximum).")
            except (TypeError, ValueError):
                pass
        return result

    def write_launch(self, name: str, launch: dict) -> None:
        self.device_settings_dir.mkdir(parents=True, exist_ok=True)
        p = self._launch_path(name)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"launch": launch}, indent=2, sort_keys=True))
        os.replace(tmp, p)

    def rename_launch(self, old: str, new: str) -> None:
        p = self._launch_path(old)
        if p.exists():
            os.replace(p, self._launch_path(new))

    def delete_launch(self, name: str) -> None:
        self._launch_path(name).unlink(missing_ok=True)

    # ---- launch flags -------------------------------------------------------
    def launch_flags(self, avd: AvdInfo, caps: Capabilities) -> tuple[list[str], list[str]]:
        """Returns (flags, notes). Settings the installed emulator cannot take are skipped with a note."""
        launch = self.read_launch(avd.name)
        flags: list[str] = []
        notes: list[str] = []
        for s in SETTINGS:
            if s.store != "launch":
                continue
            v = launch.get(s.id)
            if v in (None, "", False):
                continue
            av = self.availability(s, avd, caps)
            if not av.available:
                notes.append(f"Skipped {s.label}: {av.reason}")
                continue
            if s.kind == "bool":
                flags.append(s.flag)
            else:
                flags += [s.flag, str(v)]
            if s.evidence == "google_blog" and avd.is_play_store_image:
                notes.append(f"{s.label}: Google reported this did not work on Play Store images (2019).")
        return flags, notes
