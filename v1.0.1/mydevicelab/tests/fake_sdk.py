# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Builds a fake Android SDK in a temp dir for tests.

The fake tools only imitate the documented command shapes; they are not a
substitute for the integration test on a real SDK (see docs/INTEGRATION_TEST_v1.0.md).
Every invocation is appended as JSON to $ANDROID_FAKE_LOG.
"""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

PY = sys.executable

AVDMANAGER = r'''#!__PY__
import json, os, sys
from pathlib import Path
log = os.environ.get("ANDROID_FAKE_LOG")
stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"tool": "avdmanager", "argv": sys.argv[1:], "stdin": stdin}) + "\n")
avd_home = Path(os.environ["ANDROID_AVD_HOME"])
a = sys.argv[1:]
def opt(flag):
    return a[a.index(flag) + 1] if flag in a else None
if a[:2] == ["create", "avd"] and "--help" in a:
    # Mirrors real cmdline-tools on emulator 37.2.12: rejects --help with exit 1 but still prints options.
    print("Error: Flag '--help' is not valid for 'create avd'.", file=sys.stderr)
    print("Action \"create avd\":")
    print("  -c --sdcard  : Path to a shared SD card image, or size of a new sdcard for")
    print("  -k --package : Package path of the system image for this AVD (e.g.")
    print("  -n --name    : Name of the new AVD. [required]")
    if os.environ.get("ANDROID_FAKE_DEVICE_FLAG") == "1":
        print("  -d --device  : The optional device definition to use. Can be a device index")
    sys.exit(1)
if a[:2] == ["create", "avd"]:
    name, pkg = opt("-n"), opt("-k")
    if os.environ.get("ANDROID_FAKE_FAIL_CREATE") == "1":
        print("Error: simulated failure", file=sys.stderr); sys.exit(1)
    d = avd_home / f"{name}.avd"
    d.mkdir(parents=True)
    _, api, var, abi = pkg.split(";")
    cfg = [f"AvdId={name}", f"avd.ini.displayname={name}",
           f"image.sysdir.1=system-images/{api}/{var}/{abi}/",
           "hw.ramSize=2048", "disk.dataPartition.size=6G", "hw.lcd.density=420",
           # real avdmanager defaults seen on the target machine (emulator 37.2.12):
           "hw.keyboard=no", "hw.gpu.enabled=no", "fastboot.forceColdBoot=no",
           "PlayStore.enabled=no", "vm.heapSize=32M"]
    if opt("-c"):
        cfg.append(f"sdcard.size={opt('-c')}")
    if opt("--device"):
        cfg.append(f"hw.device.name={opt('--device')}")
    (d / "config.ini").write_text("\n".join(cfg) + "\n")
    (avd_home / f"{name}.ini").write_text(f"avd.ini.encoding=UTF-8\npath={d}\npath.rel=avd/{name}.avd\ntarget={api}\n")
    sys.exit(0)
if a[:2] == ["delete", "avd"]:
    name = opt("-n")
    import shutil
    shutil.rmtree(avd_home / f"{name}.avd", ignore_errors=True)
    (avd_home / f"{name}.ini").unlink(missing_ok=True)
    sys.exit(0)
if a[:2] == ["move", "avd"]:
    name, new = opt("-n"), opt("-r")
    (avd_home / f"{name}.avd").rename(avd_home / f"{new}.avd")
    (avd_home / f"{name}.ini").unlink()
    (avd_home / f"{new}.ini").write_text(f"path={avd_home / (new + '.avd')}\npath.rel=avd/{new}.avd\n")
    sys.exit(0)
if a[:3] == ["list", "device", "-c"]:
    print("medium_phone\npixel_9\npixel_9_pro")
    sys.exit(0)
print("unknown command", a, file=sys.stderr)
sys.exit(2)
'''

EMULATOR = r'''#!__PY__
import json, os, sys
log = os.environ.get("ANDROID_FAKE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"tool": "emulator", "argv": sys.argv[1:]}) + "\n")
a = sys.argv[1:]
if a and a[0] in ("-help", "-help-all"):
    flags = ["-avd", "-memory", "-timezone", "-netspeed", "-netdelay", "-no-boot-anim", "-noaudio",
             "-camera-back", "-camera-front", "-gpu", "-wipe-data", "-no-snapshot-load",
             "-no-metrics", "-crash-report-mode"]
    if os.environ.get("ANDROID_FAKE_LOCALE_FLAGS") == "1":
        flags += ["-change-language", "-change-country", "-change-locale"]
    for f in flags:
        print(f"    {f:<24} some description")
    sys.exit(0)
if "-avd" in a:
    import time
    time.sleep(float(os.environ.get("ANDROID_FAKE_RUN_SECONDS", "0")))
    sys.exit(0)
sys.exit(0)
'''

MKSDCARD = r'''#!__PY__
import json, os, sys
log = os.environ.get("ANDROID_FAKE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"tool": "mksdcard", "argv": sys.argv[1:]}) + "\n")
size, path = sys.argv[1], sys.argv[2]
mb = int(size.rstrip("M"))
with open(path, "wb") as fh:
    fh.truncate(mb * 1024 * 1024)
'''

HARDWARE_PROPERTIES = """# fake catalog (format assumed; verify against a real emulator)
name        = hw.cpu.ncore
type        = integer
default     = 2

name        = hw.lcd.width
type        = integer

name        = hw.lcd.height
type        = integer

name        = vm.heapSize
type        = diskSize
"""


def _write_exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.replace("__PY__", PY))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_fake_sdk(root: Path, with_catalog: bool = True) -> Path:
    _write_exe(root / "cmdline-tools/latest/bin/avdmanager", AVDMANAGER)
    _write_exe(root / "emulator/emulator", EMULATOR)
    _write_exe(root / "emulator/mksdcard", MKSDCARD)
    (root / "platform-tools").mkdir(parents=True, exist_ok=True)
    img = root / "system-images/android-35/google_apis_playstore/x86_64"
    img.mkdir(parents=True, exist_ok=True)
    (img / "system.img").write_bytes(b"")
    img2 = root / "system-images/android-35/default/x86_64"
    img2.mkdir(parents=True, exist_ok=True)
    (img2 / "system.img").write_bytes(b"")
    if with_catalog:
        (root / "emulator/lib").mkdir(parents=True, exist_ok=True)
        (root / "emulator/lib/hardware-properties.ini").write_text(HARDWARE_PROPERTIES)
    return root


def read_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
