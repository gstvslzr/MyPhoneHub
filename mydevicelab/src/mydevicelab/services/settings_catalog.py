# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Every user-editable setting, with the evidence for its key/flag.

Evidence levels:
  official_docs  - developer.android.com (emulator-commandline, managing-avds)
  aosp_sample    - key seen in Google's AOSP goldfish config.ini
                   (android.googlesource.com/device/generic/goldfish/+/c6acebac/pc/config.ini.pc)
  google_blog    - Android Studio release blog (emulator 29.1.0 canary, June 2019)
  unverified     - believed correct, NOT confirmed in an official source

Availability rule (enforced in ConfigService, shown in the UI):
  config keys:  aosp_sample/official_docs -> always editable
                unverified -> editable only if the key is in the installed emulator's
                hardware-properties.ini catalog OR already present in this AVD's config.ini
  launch flags: official_docs -> usable whenever the emulator is installed
                google_blog/unverified -> usable only if the flag appears in the
                installed emulator's own help output
"""
from __future__ import annotations

from dataclasses import dataclass

EMU_RAM_MIN_MB = 1536   # official -memory range (emulator-commandline, Table 3)
EMU_RAM_MAX_MB = 8192
DENSITY_BUCKETS = [120, 160, 213, 240, 280, 320, 360, 400, 420, 440, 480, 560, 640]
NETSPEED = ["full", "lte", "evdo", "hsdpa", "umts", "edge", "gprs", "hscsd", "gsm"]
NETDELAY = ["none", "lte", "evdo", "hsdpa", "umts", "edge", "gprs", "hscsd", "gsm"]


@dataclass(frozen=True)
class Setting:
    id: str
    label: str
    group: str
    kind: str                 # "int" | "gb" | "choice" | "bool" | "text"
    store: str                # "config" (config.ini key) | "launch" (emulator flag)
    key: str = ""             # config.ini key
    flag: str = ""            # emulator flag
    evidence: str = "unverified"
    minimum: int = 0
    maximum: int = 0
    step: int = 1
    choices: tuple[str, ...] = ()
    choice_labels: tuple[str, ...] = ()
    warn: str = ""
    help: str = ""
    destructive: bool = False


SETTINGS: tuple[Setting, ...] = (
    # ---- Hardware -------------------------------------------------------
    Setting("ram_mb", "RAM (MB)", "Hardware", "int", "config", key="hw.ramSize",
            evidence="aosp_sample", minimum=EMU_RAM_MIN_MB, maximum=EMU_RAM_MAX_MB, step=256,
            help="Clamped to the emulator's documented -memory range of 1536-8192 MB."),
    Setting("vm_heap_mb", "VM heap (MB)", "Hardware", "int", "config", key="vm.heapSize",
            minimum=16, maximum=1024, step=16,
            help="Per-app Java heap limit."),
    Setting("cpu_cores", "CPU cores", "Hardware", "int", "config", key="hw.cpu.ncore",
            minimum=1, maximum=16, step=1,
            help="Host cores given to the device. Not a property of the real phone."),
    Setting("keyboard", "Use host keyboard", "Hardware", "bool", "config", key="hw.keyboard",
            evidence="aosp_sample"),
    Setting("gpu_enabled", "GPU emulation", "Hardware", "bool", "config", key="hw.gpu.enabled",
            evidence="aosp_sample"),
    # ---- Storage --------------------------------------------------------
    Setting("data_gb", "Internal storage (GB)", "Storage", "gb", "config", key="disk.dataPartition.size",
            evidence="aosp_sample", minimum=2, maximum=256, step=1,
            help="Written in whole GB ('6G' format, as in Google's sample config). "
                 "Shrinking below used space can fail or lose data; increase only after a Wipe if unsure."),
    Setting("sdcard_mb", "SD card (MB)", "Storage", "int", "config", key="sdcard.size",
            minimum=0, maximum=65536, step=128, destructive=True,
            warn="Changing SD card size deletes and recreates the SD card image (Google docs).",
            help="0 = no SD card."),
    # ---- Display --------------------------------------------------------
    Setting("lcd_width", "Screen width (px)", "Display", "int", "config", key="hw.lcd.width",
            minimum=240, maximum=4096, step=1),
    Setting("lcd_height", "Screen height (px)", "Display", "int", "config", key="hw.lcd.height",
            minimum=320, maximum=4096, step=1),
    Setting("lcd_density", "Density (dpi bucket)", "Display", "choice", "config", key="hw.lcd.density",
            evidence="aosp_sample", choices=tuple(str(d) for d in DENSITY_BUCKETS)),
    # ---- Boot -----------------------------------------------------------
    Setting("cold_boot", "Always cold boot", "Boot", "bool", "config", key="fastboot.forceColdBoot",
            evidence="aosp_sample",
            help="Off = Quick Boot from saved snapshot when possible."),
    Setting("no_boot_anim", "Skip boot animation", "Boot", "bool", "launch", flag="-no-boot-anim",
            evidence="official_docs"),
    Setting("no_audio", "Disable audio", "Boot", "bool", "launch", flag="-noaudio",
            evidence="official_docs", help="Use if a faulty host audio driver stops the emulator starting."),
    # ---- Language & region ----------------------------------------------
    Setting("language", "Language (ISO 639, e.g. es)", "Language & region", "text", "launch",
            flag="-change-language", evidence="google_blog",
            warn="Causes a few cold boots to apply. Google noted it did not work on Play Store images "
                 "(needs superuser); not re-verified for current releases."),
    Setting("country", "Country (ISO 3166, e.g. US)", "Language & region", "text", "launch",
            flag="-change-country", evidence="google_blog"),
    Setting("locale", "Locale (BCP 47, e.g. es-US)", "Language & region", "text", "launch",
            flag="-change-locale", evidence="google_blog"),
    Setting("timezone", "Time zone (e.g. America/New_York)", "Language & region", "text", "launch",
            flag="-timezone", evidence="official_docs"),
    # ---- Network --------------------------------------------------------
    Setting("netspeed", "Network speed", "Network", "choice", "launch", flag="-netspeed",
            evidence="official_docs", choices=tuple(NETSPEED)),
    Setting("netdelay", "Network latency", "Network", "choice", "launch", flag="-netdelay",
            evidence="official_docs", choices=tuple(NETDELAY)),
    # ---- Peripherals ----------------------------------------------------
    Setting("camera_back", "Back camera", "Peripherals", "choice", "launch", flag="-camera-back",
            evidence="official_docs", choices=("", "emulated", "webcam0", "none"),
            choice_labels=("Device default", "Emulated", "Host webcam 0", "None")),
    Setting("camera_front", "Front camera", "Peripherals", "choice", "launch", flag="-camera-front",
            evidence="official_docs", choices=("", "emulated", "webcam0", "none"),
            choice_labels=("Device default", "Emulated", "Host webcam 0", "None")),
    Setting("gpu_mode", "Renderer override", "Peripherals", "choice", "launch", flag="-gpu",
            evidence="official_docs", choices=("", "swiftshader_indirect"),
            choice_labels=("Device default", "Software (swiftshader_indirect)"),
            help="Only the value shown in Google's docs is offered."),
)

BY_ID = {s.id: s for s in SETTINGS}
GROUP_ORDER = ["Hardware", "Storage", "Display", "Boot", "Language & region", "Network", "Peripherals"]
VERIFIED_EVIDENCE = {"official_docs", "aosp_sample"}

EVIDENCE_LABEL = {
    "official_docs": "Google docs",
    "aosp_sample": "Google AOSP config",
    "google_blog": "Google release blog",
    "unverified": "found in your emulator",
}
