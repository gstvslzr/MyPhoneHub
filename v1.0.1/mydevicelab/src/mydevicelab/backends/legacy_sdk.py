# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Backend for the Android SDK command-line tools: avdmanager, emulator, adb.

Only documented arguments are hard-coded (developer.android.com, checked 2026-10-28):
  avdmanager create avd -n NAME -k "SDK_ID" [-c SIZE] [-f] [-p PATH]
  avdmanager delete avd -n NAME
  avdmanager move avd -n NAME [-p PATH] [-r NEW_NAME]
  avdmanager list device -c
  emulator -avd NAME [options]
Anything else (e.g. a device-definition flag for 'create avd') is used only if the
installed tool's own --help output lists it.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import signal
from pathlib import Path

from ..core.errors import (DeviceBusyError, MyDeviceLabError, ToolNotFoundError,
                           ValidationError)
from ..core.ini_file import IniFile
from ..core.process_runner import ProcessRunner
from .base import AvdInfo, Capabilities, SystemImage, ToolBackend

log = logging.getLogger(__name__)

# Subset of the characters Google documents for AVD names (letters, digits, . _ ( ) - space).
# Spaces and parentheses are excluded because the name is passed through CLI tools.
AVD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
FLAG_RE = re.compile(r"(?<![\w-])(-{1,2}[a-z][a-z0-9-]*)")


def validate_avd_name(name: str) -> str:
    if not AVD_NAME_RE.match(name or ""):
        raise ValidationError(
            "Device name must start with a letter or digit and use only letters, digits, '.', '_' or '-' "
            "(max 63 characters).")
    return name


def _find_tool(sdk_root: Path | None, rel_candidates: list[str], path_name: str | None) -> Path | None:
    if sdk_root:
        for rel in rel_candidates:
            for p in sorted(sdk_root.glob(rel), reverse=True):  # 'latest' sorts after digits
                if p.is_file() and os.access(p, os.X_OK):
                    return p
    if path_name:
        w = shutil.which(path_name)
        if w:
            return Path(w)
    return None


class LegacySdkBackend(ToolBackend):
    def __init__(self, sdk_root: Path | None, avd_home: Path, runner: ProcessRunner | None = None,
                 proc_root: Path = Path("/proc")):
        self.sdk_root = Path(sdk_root) if sdk_root else None
        self.avd_home = Path(avd_home)
        self.proc_root = proc_root
        env = {"ANDROID_AVD_HOME": str(self.avd_home)}
        if self.sdk_root:
            env.update(ANDROID_SDK_ROOT=str(self.sdk_root), ANDROID_HOME=str(self.sdk_root))
        self.runner = runner or ProcessRunner(env)
        self._caps: Capabilities | None = None
        self.avdmanager = _find_tool(self.sdk_root, ["cmdline-tools/latest/bin/avdmanager",
                                                     "cmdline-tools/*/bin/avdmanager",
                                                     "tools/bin/avdmanager"], "avdmanager")
        self.emulator = _find_tool(self.sdk_root, ["emulator/emulator"], "emulator")
        self.adb = _find_tool(self.sdk_root, ["platform-tools/adb"], "adb")
        self.mksdcard = _find_tool(self.sdk_root, ["emulator/mksdcard"], "mksdcard")

    # ------------------------------------------------------------ capabilities
    def _require(self, tool: Path | None, name: str) -> Path:
        if tool is None:
            raise ToolNotFoundError(
                f"{name} is not installed.",
                f"Looked in SDK root {self.sdk_root} and on PATH.")
        return tool

    def hardware_catalog_path(self) -> Path | None:
        if not self.sdk_root:
            return None
        direct = self.sdk_root / "emulator" / "lib" / "hardware-properties.ini"
        if direct.is_file():
            return direct
        emu = self.sdk_root / "emulator"
        if emu.is_dir():
            for p in emu.rglob("hardware-properties.ini"):
                return p
        return None

    @staticmethod
    def parse_hardware_catalog(text: str) -> frozenset[str]:
        keys = set()
        for line in text.splitlines():
            m = re.match(r"^\s*name\s*=\s*([A-Za-z0-9_.]+)\s*$", line)
            if m:
                keys.add(m.group(1))
        return frozenset(keys)

    def capabilities(self, refresh: bool = False) -> Capabilities:
        if self._caps is not None and not refresh:
            return self._caps
        caps = Capabilities(emulator_present=self.emulator is not None,
                            avdmanager_present=self.avdmanager is not None,
                            adb_present=self.adb is not None)
        if self.emulator:
            texts = []
            for args in (["-help"], ["-help-all"]):
                try:
                    r = self.runner.run([str(self.emulator), *args], timeout=20, check=False)
                    texts.append(r.stdout + "\n" + r.stderr)
                except MyDeviceLabError as exc:
                    caps.notes.append(f"emulator {' '.join(args)} failed: {exc.user_message}")
            caps.emulator_flags = frozenset(FLAG_RE.findall("\n".join(texts)))
            if not caps.emulator_flags:
                caps.notes.append("Could not read the emulator's option list; only Google-documented flags are used.")
        if self.avdmanager:
            try:
                r = self.runner.run([str(self.avdmanager), "create", "avd", "--help"], timeout=60, check=False)
                help_text = r.stdout + "\n" + r.stderr
                caps.avdmanager_device_flag = bool(re.search(r"(^|\s)(-d,\s*)?--device\b", help_text, re.M))
            except MyDeviceLabError as exc:
                caps.notes.append(f"avdmanager --help failed: {exc.user_message}")
        cat = self.hardware_catalog_path()
        if cat:
            caps.hardware_catalog_path = cat
            caps.hardware_keys = self.parse_hardware_catalog(cat.read_text(errors="replace"))
        else:
            caps.notes.append("Emulator hardware catalog (hardware-properties.ini) not found; "
                              "settings without Google evidence are limited to keys already in each device.")
        self._caps = caps
        return caps

    # ------------------------------------------------------------ listing
    def list_avds(self) -> list[AvdInfo]:
        out: list[AvdInfo] = []
        if not self.avd_home.is_dir():
            return out
        running = self.running_names()
        for ini in sorted(self.avd_home.glob("*.ini")):
            name = ini.stem
            meta = IniFile(ini)
            path = meta.get("path")
            avd_dir = Path(path) if path else self.avd_home / f"{name}.avd"
            if not avd_dir.is_absolute():
                avd_dir = self.avd_home.parent / avd_dir
            if not avd_dir.is_dir():
                rel = meta.get("path.rel")
                if rel and (self.avd_home.parent / rel).is_dir():
                    avd_dir = self.avd_home.parent / rel
                else:
                    log.warning("AVD %s: directory %s missing; skipped", name, avd_dir)
                    continue
            cfg = IniFile(avd_dir / "config.ini").as_dict()
            out.append(AvdInfo(name, ini, avd_dir, cfg, name in running))
        return out

    def get_avd(self, name: str) -> AvdInfo:
        for a in self.list_avds():
            if a.name == name:
                return a
        raise MyDeviceLabError(f"Device '{name}' not found in {self.avd_home}")

    def list_system_images(self) -> list[SystemImage]:
        imgs: list[SystemImage] = []
        base = self.sdk_root / "system-images" if self.sdk_root else None
        if not base or not base.is_dir():
            return imgs
        for api_dir in sorted(base.iterdir()):
            for var_dir in sorted(p for p in api_dir.iterdir() if p.is_dir()):
                for abi_dir in sorted(p for p in var_dir.iterdir() if p.is_dir()):
                    if (abi_dir / "system.img").exists() or (abi_dir / "source.properties").exists():
                        imgs.append(SystemImage(
                            f"system-images;{api_dir.name};{var_dir.name};{abi_dir.name}",
                            api_dir.name, var_dir.name, abi_dir.name, abi_dir))
        return imgs

    def list_device_definitions(self) -> list[str]:
        tool = self._require(self.avdmanager, "avdmanager (Android SDK Command-line Tools)")
        r = self.runner.run([str(tool), "list", "device", "-c"], timeout=90,
                            fail_message="Could not list device definitions")
        return [ln.strip() for ln in r.stdout.splitlines()
                if ln.strip() and re.match(r"^[A-Za-z0-9_.-]+$", ln.strip())]

    # ------------------------------------------------------------ lifecycle
    def create_avd(self, name: str, sdk_id: str, sdcard_mb: int | None,
                   device_id: str | None) -> AvdInfo:
        validate_avd_name(name)
        if not re.match(r"^system-images;[A-Za-z0-9._-]+;[A-Za-z0-9._-]+;[A-Za-z0-9._-]+$", sdk_id):
            raise ValidationError(f"Invalid system image id: {sdk_id}")
        if (self.avd_home / f"{name}.ini").exists():
            raise ValidationError(f"A device named '{name}' already exists.")
        tool = self._require(self.avdmanager, "avdmanager (Android SDK Command-line Tools)")
        argv = [str(tool), "create", "avd", "-n", name, "-k", sdk_id]
        if sdcard_mb:
            argv += ["-c", f"{int(sdcard_mb)}M"]
        if device_id:
            if not self.capabilities().avdmanager_device_flag:
                raise ValidationError("The installed avdmanager does not list a device option.")
            argv += ["--device", device_id]
        # avdmanager may ask whether to create a custom hardware profile; answer 'no'
        # (keeps the image defaults). Harmless if no prompt appears.
        self.runner.run(argv, timeout=300, input_text="no\n", fail_message=f"Could not create device '{name}'")
        return self.get_avd(name)

    def _refuse_if_running(self, name: str) -> None:
        if name in self.running_names():
            raise DeviceBusyError(f"'{name}' is running. Stop it first.")

    def delete_avd(self, name: str) -> None:
        validate_avd_name(name)
        self._refuse_if_running(name)
        tool = self._require(self.avdmanager, "avdmanager")
        self.runner.run([str(tool), "delete", "avd", "-n", name], timeout=120,
                        fail_message=f"Could not delete '{name}'")

    def rename_avd(self, name: str, new_name: str) -> None:
        validate_avd_name(name)
        validate_avd_name(new_name)
        self._refuse_if_running(name)
        if (self.avd_home / f"{new_name}.ini").exists():
            raise ValidationError(f"A device named '{new_name}' already exists.")
        tool = self._require(self.avdmanager, "avdmanager")
        self.runner.run([str(tool), "move", "avd", "-n", name, "-r", new_name], timeout=120,
                        fail_message=f"Could not rename '{name}'")

    def clone_avd(self, name: str, new_name: str) -> AvdInfo:
        """Copy an AVD on disk (no tool supports this). Skips lock files, snapshots and backups,
        so the clone cold-boots the first time."""
        validate_avd_name(new_name)
        self._refuse_if_running(name)
        src = self.get_avd(name)
        dst_dir = self.avd_home / f"{new_name}.avd"
        dst_ini = self.avd_home / f"{new_name}.ini"
        if dst_dir.exists() or dst_ini.exists():
            raise ValidationError(f"A device named '{new_name}' already exists.")
        shutil.copytree(src.avd_dir, dst_dir,
                        ignore=shutil.ignore_patterns("*.lock", "snapshots", "*.bak", "*.pid"))
        try:
            meta = IniFile(src.ini_path)
            new_meta = IniFile(dst_ini)
            for k, v in meta.as_dict().items():
                new_meta.set(k, v)
            new_meta.set("path", str(dst_dir))
            if meta.get("path.rel") is not None:
                new_meta.set("path.rel", f"{self.avd_home.name}/{new_name}.avd")
            new_meta.save(make_backup=False)
            cfg = IniFile(dst_dir / "config.ini")
            for key in ("AvdId", "avd.ini.displayname"):
                if cfg.get(key) is not None:
                    cfg.set(key, new_name)
            cfg.save(make_backup=False)
        except BaseException:
            shutil.rmtree(dst_dir, ignore_errors=True)
            dst_ini.unlink(missing_ok=True)
            raise
        return self.get_avd(new_name)

    # ------------------------------------------------------------ runtime
    def running_names(self) -> set[str]:
        """Names of AVDs whose emulator/qemu process is alive (reads /proc/*/cmdline)."""
        names: set[str] = set()
        try:
            entries = list(self.proc_root.iterdir())
        except OSError:
            return names
        for d in entries:
            if not d.name.isdigit():
                continue
            try:
                argv = (d / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if not argv or not argv[0]:
                continue
            exe = os.path.basename(argv[0].decode(errors="replace"))
            if not (exe.startswith("emulator") or exe.startswith("qemu-system")):
                continue
            args = [a.decode(errors="replace") for a in argv[1:]]
            for i, a in enumerate(args):
                if a == "-avd" and i + 1 < len(args):
                    names.add(args[i + 1])
                elif a.startswith("@") and len(a) > 1:
                    names.add(a[1:])
        return names

    def build_launch_argv(self, name: str, flags: list[str]) -> list[str]:
        validate_avd_name(name)
        tool = self._require(self.emulator, "emulator (Android Emulator package)")
        return [str(tool), "-avd", name, *flags]

    def start(self, name: str, flags: list[str], log_path: Path):
        self._refuse_if_running(name)
        argv = self.build_launch_argv(name, flags)
        return self.runner.spawn(argv, log_path)

    def stop(self, name: str) -> bool:
        """Send SIGTERM to the emulator processes for this AVD. Phase 3 replaces this with a
        console-based graceful shutdown."""
        stopped = False
        for d in self.proc_root.iterdir():
            if not d.name.isdigit():
                continue
            try:
                argv = (d / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            args = [a.decode(errors="replace") for a in argv]
            if not args or not os.path.basename(args[0]).startswith(("emulator", "qemu-system")):
                continue
            if ("-avd" in args and args.index("-avd") + 1 < len(args) and args[args.index("-avd") + 1] == name) \
                    or f"@{name}" in args:
                try:
                    os.kill(int(d.name), signal.SIGTERM)
                    stopped = True
                except (ProcessLookupError, PermissionError):
                    pass
        return stopped

    def make_sdcard(self, size_mb: int, path: Path) -> None:
        tool = self._require(self.mksdcard, "mksdcard (Android Emulator package)")
        self.runner.run([str(tool), f"{int(size_mb)}M", str(path)], timeout=300,
                        fail_message="Could not create the SD card image")
