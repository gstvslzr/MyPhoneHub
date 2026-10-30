# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Host readiness checks. Read-only; never changes the system.

KVM access is tested with os.access(), not group membership: on systemd hosts
logind grants the active desktop user an ACL on /dev/kvm (seen on the target
machine as 'user:<name>:rw-') without adding them to the kvm group.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

KVM_DEVICE = Path("/dev/kvm")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    blocking: bool = False


@dataclass
class HostReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(c.ok or not c.blocking for c in self.checks)

    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


def cpu_virt_flags(cpuinfo: Path = Path("/proc/cpuinfo")) -> set[str]:
    try:
        text = cpuinfo.read_text()
    except OSError:
        return set()
    flags: set[str] = set()
    for line in text.splitlines():
        if line.startswith("flags"):
            flags.update(line.split(":", 1)[1].split())
    return flags & {"vmx", "svm"}


def mem_available_mb(meminfo: Path = Path("/proc/meminfo")) -> int | None:
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def free_disk_mb(path: Path) -> int | None:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free // (1024 * 1024)
    except OSError:
        return None


def run_host_checks(avd_home: Path, kvm_device: Path = KVM_DEVICE,
                    cpuinfo: Path = Path("/proc/cpuinfo"),
                    meminfo: Path = Path("/proc/meminfo")) -> HostReport:
    rep = HostReport()

    flags = cpu_virt_flags(cpuinfo)
    rep.checks.append(Check(
        "CPU virtualization", bool(flags),
        f"CPU flags present: {', '.join(sorted(flags))}" if flags else "No vmx/svm flag in /proc/cpuinfo",
        "Enable Intel VT-x or AMD-V (SVM) in BIOS/UEFI." if not flags else "", blocking=True))

    if not kvm_device.exists():
        rep.checks.append(Check("KVM device", False, f"{kvm_device} does not exist",
                                "Install the KVM kernel modules (package qemu-system-x86 pulls them in) "
                                "and enable virtualization in firmware.", blocking=True))
    else:
        rw = os.access(kvm_device, os.R_OK | os.W_OK)
        rep.checks.append(Check(
            "KVM access", rw,
            f"{kvm_device} is readable and writable by this user" if rw
            else f"{kvm_device} exists but this user cannot open it read/write",
            "" if rw else f"Run: sudo usermod -aG kvm {os.environ.get('USER', '$USER')}  then log out and back in.",
            blocking=True))

    mem = mem_available_mb(meminfo)
    rep.checks.append(Check(
        "Available RAM", mem is not None and mem >= 4096,
        f"{mem} MB available" if mem is not None else "Could not read /proc/meminfo",
        "Close applications; each running device needs its configured RAM plus overhead."
        if (mem or 0) < 4096 else ""))

    disk = free_disk_mb(avd_home)
    rep.checks.append(Check(
        "Free disk (AVD folder)", disk is not None and disk >= 10240,
        f"{disk} MB free at {avd_home}" if disk is not None else f"Could not stat {avd_home}",
        "Each device needs its data partition, SD card and snapshots; keep 10 GB+ free."
        if (disk or 0) < 10240 else ""))

    java = shutil.which("java")
    rep.checks.append(Check(
        "Java runtime", java is not None,
        f"java found at {java}" if java else "java not found on PATH",
        "avdmanager/sdkmanager need a Java runtime: sudo apt install default-jre-headless"
        if not java else ""))

    return rep
