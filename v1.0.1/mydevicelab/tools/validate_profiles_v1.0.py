#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""MyDeviceLab v1.0 - profile validator.

Validates every profiles/**/*.json against schema/device-profile.schema.json,
checks id uniqueness, computes physical ppi and the nearest Android density
bucket, applies the emulator RAM clamp, and runs negative tests that must FAIL.

Exit code 0 = all checks passed. Local only; no network.
"""
import copy
import json
import math
import pathlib
import sys

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "device-profile.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)

DENSITY_BUCKETS = [120, 160, 213, 240, 280, 320, 360, 400, 420, 440, 480, 560, 640]
EMU_RAM_MIN_MB, EMU_RAM_MAX_MB = 1536, 8192   # official -memory range
PPI_TOLERANCE = 0.02                          # 2% vs stated ppi


def physical_ppi(w, h, diag_in):
    return math.hypot(w, h) / diag_in


def nearest_bucket(ppi):
    return min(DENSITY_BUCKETS, key=lambda b: (abs(b - ppi), b))


def clamp_ram(mb):
    return max(EMU_RAM_MIN_MB, min(EMU_RAM_MAX_MB, mb))


def errors_for(doc):
    return sorted(VALIDATOR.iter_errors(doc), key=lambda e: list(e.path))


def main():
    failures = 0
    seen_ids = {}
    files = sorted((ROOT / "profiles").rglob("*.json"))
    print(f"Validating {len(files)} profile(s)\n")

    for f in files:
        doc = json.loads(f.read_text())
        rel = f.relative_to(ROOT)
        errs = errors_for(doc)
        if errs:
            failures += 1
            print(f"FAIL {rel}")
            for e in errs:
                print(f"     {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
            continue
        pid = doc["id"]
        if pid in seen_ids:
            failures += 1
            print(f"FAIL {rel}: duplicate id '{pid}' (also in {seen_ids[pid]})")
            continue
        seen_ids[pid] = rel
        print(f"PASS {rel}")

        hw = doc.get("hardware")
        if hw:
            w, h, d = hw["screen_width_px"], hw["screen_height_px"], hw["screen_diagonal_in"]
            diag_px = math.hypot(w, h)
            ppi = diag_px / d
            bucket = hw.get("lcd_density") or nearest_bucket(ppi)
            ram_dev = hw["ram_mb_device"]
            ram_emu = clamp_ram(ram_dev)
            print(f"     diag_px = sqrt({w}^2 + {h}^2) = {diag_px:.2f}")
            print(f"     ppi     = {diag_px:.2f} / {d} = {ppi:.2f}")
            stated = hw.get("physical_ppi_stated")
            if stated:
                delta = abs(ppi - stated) / stated
                flag = "OK" if delta <= PPI_TOLERANCE else "MISMATCH"
                print(f"     stated ppi {stated} -> delta {delta*100:.2f}% [{flag}]")
                if flag != "OK":
                    failures += 1
            print(f"     density bucket -> {bucket}")
            note = " (clamped)" if ram_emu != ram_dev else ""
            print(f"     RAM device {ram_dev} MB -> emulator {ram_emu} MB{note}")

    # Negative tests: each mutated profile MUST be rejected.
    print("\nNegative tests (each must be REJECTED)")
    base_custom = json.loads((ROOT / "profiles/galaxy/galaxy_s26_sized.json").read_text())
    base_builtin = json.loads((ROOT / "profiles/pixel/pixel_9.json").read_text())

    def mutate(base, fn):
        d = copy.deepcopy(base)
        fn(d)
        return d

    cases = [
        ("custom_hardware without sources", mutate(base_custom, lambda d: d.pop("sources"))),
        ("custom_hardware claiming support_level=full", mutate(base_custom, lambda d: d.update(support_level="full"))),
        ("builtin_device without device id", mutate(base_builtin, lambda d: d.pop("avd_device_id_candidates"))),
        ("non-standard density 410", mutate(base_custom, lambda d: d["hardware"].update(lcd_density=410))),
        ("unknown top-level key", mutate(base_custom, lambda d: d.update(telemetry=True))),
        ("missing label_note", mutate(base_custom, lambda d: d.pop("label_note"))),
        ("http (not https) source", mutate(base_custom, lambda d: d["sources"][0].update(url="http://x.example"))),
        ("bad id characters", mutate(base_custom, lambda d: d.update(id="Galaxy S26!"))),
    ]
    for name, doc in cases:
        rejected = bool(errors_for(doc))
        print(f"  {'PASS' if rejected else 'FAIL'}  {name} -> {'rejected' if rejected else 'ACCEPTED (bug)'}")
        if not rejected:
            failures += 1

    print(f"\nResult: {'ALL CHECKS PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
