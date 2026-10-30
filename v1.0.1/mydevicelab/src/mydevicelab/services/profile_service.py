# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Loads and validates device profiles (built-in + user overrides by id)."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from ..core.errors import ValidationError
from .settings_catalog import DENSITY_BUCKETS, EMU_RAM_MAX_MB, EMU_RAM_MIN_MB

log = logging.getLogger(__name__)


@dataclass
class Profile:
    data: dict
    source: Path
    builtin: bool

    @property
    def id(self) -> str: return self.data["id"]
    @property
    def display_name(self) -> str: return self.data["display_name"]
    @property
    def kind(self) -> str: return self.data["kind"]
    @property
    def label_note(self) -> str: return self.data["label_note"]
    @property
    def hardware(self) -> dict: return self.data.get("hardware", {})
    @property
    def defaults(self) -> dict: return self.data.get("defaults", {})

    def physical_ppi(self) -> float | None:
        hw = self.hardware
        if not hw:
            return None
        return math.hypot(hw["screen_width_px"], hw["screen_height_px"]) / hw["screen_diagonal_in"]

    def density(self) -> int | None:
        hw = self.hardware
        if not hw:
            return None
        if "lcd_density" in hw:
            return int(hw["lcd_density"])
        ppi = self.physical_ppi()
        return min(DENSITY_BUCKETS, key=lambda b: (abs(b - ppi), b))

    def emulator_ram_mb(self) -> int | None:
        hw = self.hardware
        if not hw:
            return None
        return max(EMU_RAM_MIN_MB, min(EMU_RAM_MAX_MB, int(hw["ram_mb_device"])))


class ProfileService:
    def __init__(self, schema_path: Path, builtin_dirs: list[Path], user_dir: Path):
        self.validator = Draft202012Validator(json.loads(Path(schema_path).read_text()))
        self.builtin_dirs = [Path(d) for d in builtin_dirs]
        self.user_dir = Path(user_dir)
        self.errors: list[str] = []

    def validate(self, data: dict) -> list[str]:
        return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
                for e in sorted(self.validator.iter_errors(data), key=lambda e: list(e.path))]

    def _load_dir(self, d: Path, builtin: bool, into: dict[str, Profile]) -> None:
        if not d.is_dir():
            return
        for f in sorted(d.rglob("*.json")):
            try:
                data = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                self.errors.append(f"{f}: {exc}")
                continue
            errs = self.validate(data)
            if errs:
                self.errors.append(f"{f}: " + "; ".join(errs))
                continue
            into[data["id"]] = Profile(data, f, builtin)

    def load_all(self) -> list[Profile]:
        self.errors = []
        found: dict[str, Profile] = {}
        for d in self.builtin_dirs:            # first existing built-in dir wins
            if d.is_dir():
                self._load_dir(d, True, found)
                break
        self._load_dir(self.user_dir, False, found)   # user profiles override by id
        for e in self.errors:
            log.warning("profile rejected: %s", e)
        return sorted(found.values(), key=lambda p: (p.data["family"], p.display_name))

    def get(self, profile_id: str) -> Profile:
        for p in self.load_all():
            if p.id == profile_id:
                return p
        raise ValidationError(f"Profile '{profile_id}' not found or invalid.")
