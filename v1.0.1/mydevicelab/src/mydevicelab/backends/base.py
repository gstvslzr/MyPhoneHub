# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Backend interface. Services depend on this, never on tool names or flags."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AvdInfo:
    name: str
    ini_path: Path
    avd_dir: Path
    config: dict[str, str] = field(default_factory=dict)
    running: bool = False

    @property
    def config_path(self) -> Path:
        return self.avd_dir / "config.ini"

    @property
    def system_image(self) -> str:
        """e.g. 'android-35 / google_apis_playstore / x86_64' from image.sysdir.1."""
        sysdir = self.config.get("image.sysdir.1", "").strip("/")
        parts = [p for p in sysdir.split("/") if p]
        if len(parts) >= 4 and parts[0] == "system-images":
            return " / ".join(parts[1:4])
        return sysdir or "unknown image"

    @property
    def is_play_store_image(self) -> bool:
        return "playstore" in self.config.get("image.sysdir.1", "") or \
               self.config.get("PlayStore.enabled", "").lower() in ("yes", "true")


@dataclass(frozen=True)
class SystemImage:
    sdk_id: str        # "system-images;android-35;google_apis_playstore;x86_64"
    api: str
    variant: str
    abi: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.api} · {self.variant} · {self.abi}"


@dataclass
class Capabilities:
    emulator_present: bool = False
    avdmanager_present: bool = False
    adb_present: bool = False
    emulator_flags: frozenset[str] = frozenset()
    avdmanager_device_flag: bool = False
    hardware_keys: frozenset[str] = frozenset()
    hardware_catalog_path: Path | None = None
    notes: list[str] = field(default_factory=list)


class ToolBackend(ABC):
    @abstractmethod
    def capabilities(self, refresh: bool = False) -> Capabilities: ...

    @abstractmethod
    def list_avds(self) -> list[AvdInfo]: ...

    @abstractmethod
    def list_system_images(self) -> list[SystemImage]: ...

    @abstractmethod
    def list_device_definitions(self) -> list[str]: ...

    @abstractmethod
    def create_avd(self, name: str, sdk_id: str, sdcard_mb: int | None,
                   device_id: str | None) -> AvdInfo: ...

    @abstractmethod
    def delete_avd(self, name: str) -> None: ...

    @abstractmethod
    def rename_avd(self, name: str, new_name: str) -> None: ...

    @abstractmethod
    def clone_avd(self, name: str, new_name: str) -> AvdInfo: ...

    @abstractmethod
    def build_launch_argv(self, name: str, flags: list[str]) -> list[str]: ...

    @abstractmethod
    def start(self, name: str, flags: list[str], log_path: Path): ...

    @abstractmethod
    def stop(self, name: str) -> bool: ...

    @abstractmethod
    def make_sdcard(self, size_mb: int, path: Path) -> None: ...
