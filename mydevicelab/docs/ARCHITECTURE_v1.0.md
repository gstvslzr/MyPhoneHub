# MyDeviceLab v1.0 — Architecture

Status: Phase 2 complete (code + tests against a fake SDK); real-SDK integration test pending.
Date: 2026-10-28
Target hosts: Ubuntu 24.04 LTS (baseline: GTK 4.14 / libadwaita 1.5) and Ubuntu 26.04 LTS
(developer machine: GTK 4.22 / libadwaita 1.9). x86_64, KVM-capable CPU.
UI toolkit: **GTK4 + libadwaita (confirmed by owner 2026-10-28)**. Only libadwaita 1.5 APIs are used.

See §10 for what Phase 2 changed or resolved.

---

## 1. Purpose and scope

MyDeviceLab is a local-first desktop GUI that creates, configures, launches and manages
Android Virtual Devices (AVDs) by driving Google's official Android SDK tools. It does
**not** implement an emulator.

| Target | Support level | Mechanism |
|---|---|---|
| Pixel | Full | Google's built-in device definitions + official system images |
| Samsung Galaxy | Approximation only | Custom hardware profile (resolution, density, RAM, diagonal) on a **stock Android** image. No One UI, no Samsung apps/services. UI label: "Galaxy-sized profile (stock Android, not One UI)". |
| iPhone | Not supported for app execution | iOS Simulator is macOS/Xcode-only. Optional stretch: web viewport preview only. No iPhone data ships in v1.0 (see §9). |

---

## 2. Verified findings that shaped the design

All checked 2026-10-28 against official sources unless noted.

| # | Finding | Design consequence | Source |
|---|---|---|---|
| F1 | The standalone `emulator` tool is marked **deprecated**; Google points to the Android CLI `android emulator` command. | Backend is isolated behind an adapter interface so it can be swapped. | developer.android.com/studio/run/emulator-commandline |
| F2 | `android emulator create` accepts only a named profile (e.g. `medium_phone`) plus `--list-profiles`. It has **no RAM, storage, locale or core-count options**. | Android CLI cannot drive the config editor. v1.0 uses the legacy toolchain (`avdmanager`, `emulator`, `sdkmanager`, `adb`), which is still documented and shipped. | developer.android.com/tools/agents/android-cli/commands/emulator_create |
| F3 | `-memory` accepts **1536–8192 MB** and overrides the AVD setting. | Profile RAM is clamped to 8192 MB at launch. 12 GB Galaxy devices run with 8 GB; the UI shows this. | emulator-commandline, Table 3 |
| F4 | Verified launch flags: `-no-snapshot-load`, `-no-snapshot-save`, `-no-snapshot`, `-camera-back/-camera-front {emulated,environment,webcamN,imagefile:,videofile:,none}`, `-webcam-list`, `-sdcard`, `-wipe-data`, `-netdelay`, `-netspeed`, `-netfast`, `-port` (even, 5554–5682), `-accel {auto,off,on}`, `-accel-check`, `-gpu`, `-timezone` (IANA zoneinfo), `-no-boot-anim`, `-noaudio`, `-cache-size`, `-dns-server`, `-http-proxy`, `-logcat`, `-verbose`. | These are the only runtime flags the launcher will emit in v1.0. | emulator-commandline, Tables 3–4 |
| F5 | AVD data lives in `~/.android/avd/<name>.avd/`; `-wipe-data` does not touch `sdcard.img`; resizing the SD card deletes and recreates the file. | Config editor warns before SD resize (data loss). | emulator-commandline |
| F6 | Play Store images are release-signed: **no root**. AOSP images allow `adb root`. | Settings that require root (e.g. system props) are disabled on Play images. | developer.android.com/studio/run/managing-avds |
| F7 | Official docs describe AVD properties (RAM, VM heap, internal storage, SD card, cores, camera, network, graphics, boot mode) but **do not list `config.ini` key names**. | Key names are not hardcoded. The app reads the key catalog from the installed emulator at runtime (see §5.3). | managing-avds |
| F8 | SDK License §3.1 grants use "solely to develop applications for compatible implementations of Android"; §3.4 prohibits redistributing the SDK; §6.1 allows Google to collect usage stats (with notice/consent); §3.7 grants no trademark rights. | Never bundle SDK or images in the .deb. User accepts license in-app at first run. Usage-stats consent defaults to **decline**. Device names are descriptive only, no logos. | developer.android.com/sdk/terms |
| F9 | PySide6 is packaged for Ubuntu 25.10+ but **not for 24.04 (noble)**. PyQt6 6.6.1 is in noble *universe*. GTK4 + libadwaita 1.5 (`gir1.2-adw-1`) are in noble *main*. | UI toolkit decision — see §4. | packages.ubuntu.com |

### Interpretation (labelled)
- **License scope (F8):** using the emulator primarily to run third-party apps, rather than to develop apps, is arguably outside the §3.1 grant. This is my reading, not legal advice. If MyDeviceLab is ever sold or distributed commercially, get a licensed attorney's opinion first.

---

## 3. Layered architecture

```
┌─────────────────────────────────────────────────────────────┐
│ UI layer (GTK4 + libadwaita, PyGObject)                     │
│  DeviceLibraryView · ConfigEditor · AppManager · RuntimePanel│
│  SdkManagerView · FirstRunWizard · LogcatView               │
└───────────────▲─────────────────────────────────────────────┘
                │ signals / async results (GLib main loop)
┌───────────────┴─────────────────────────────────────────────┐
│ Service layer (pure Python, no UI imports, unit-testable)   │
│  ProfileService   – load/validate JSON profiles             │
│  DeviceService    – create/clone/rename/delete AVDs         │
│  ConfigService    – read/write config.ini with backup       │
│  RuntimeService   – start/stop/snapshots/screenshots        │
│  AppService       – APK inspect/install/uninstall/perms     │
│  SdkService       – list/install images, license gate       │
│  HostCheck        – KVM, RAM, disk, GPU, group membership   │
└───────────────▲─────────────────────────────────────────────┘
                │ ToolBackend interface
┌───────────────┴─────────────────────────────────────────────┐
│ Backend adapters                                            │
│  LegacySdkBackend   (v1.0 default)                          │
│     avdmanager · emulator · sdkmanager · adb                │
│  AndroidCliBackend  (stub; enabled when CLI gains config    │
│                      options — see F2)                      │
└───────────────▲─────────────────────────────────────────────┘
                │
┌───────────────┴─────────────────────────────────────────────┐
│ ProcessRunner                                               │
│  argv lists only (never shell=True) · per-call timeout ·    │
│  env scrubbed to an allowlist · stdout/stderr captured to   │
│  rotating log · cancellation · non-zero exit → typed error  │
└─────────────────────────────────────────────────────────────┘
```

Rule: only the backend layer knows tool names and flags. Services speak in domain terms
(`start(device, overrides)`), so swapping to the Android CLI touches one module.

---

## 4. UI toolkit decision

| Option | In noble repos | License | Notes |
|---|---|---|---|
| PySide6 (originally requested) | No (25.10+ only) | LGPLv3 | Would require vendoring a pip venv (~large .deb, network at build time). |
| PyQt6 6.6.1 | Yes, universe | **GPLv3 or commercial** | If you ever sell MyDeviceLab, the app must be GPL-compatible or you buy a Riverbank commercial license. |
| **GTK4 + libadwaita 1.5 via PyGObject** | **Yes, main** | LGPL | Native on Ubuntu GNOME. Smallest .deb, apt-only deps, no vendoring. |

**Decision for v1.0: GTK4 + libadwaita.** Fallback: PyQt6, if you prefer Qt and accept GPL.
This is a review-gate decision — confirm or override before Phase 2.

---

## 5. Key subsystems

### 5.1 Profiles
- JSON files validated against `schema/device-profile.schema.json` (JSON Schema 2020-12).
- Built-in profiles ship read-only in `/usr/share/mydevicelab/profiles/`.
- User profiles live in `~/.config/mydevicelab/profiles/` and override built-ins by `id`.
- Pixel profiles reference Google's built-in device IDs (resolved at runtime against
  `avdmanager list device -c`); no Pixel specs are hardcoded.
- Galaxy profiles carry explicit hardware values plus a `sources` array (see §9).

### 5.2 Device lifecycle
`avdmanager create avd -n <name> -k "<sdk_id>" [-c <size>M] [-d <device_id>]` → apply
profile to `config.ini` → launch via `emulator -avd <name> <flags>`.
Delete via `avdmanager delete avd -n`, rename via `avdmanager move avd -n -r`.

### 5.3 Config editor
- Reads the emulator's own hardware property catalog at runtime. Expected location:
  `$ANDROID_SDK_ROOT/emulator/lib/hardware-properties.ini`. **Unverified path — confirm
  in Phase 2 on a real install.** If missing, the editor exposes only the properties the
  official docs describe (F7) and maps them to keys found in the AVD's existing `config.ini`.
- Writes only while the AVD is stopped. Atomic write (temp file + rename) and a
  timestamped `.bak` before every change.
- Two layers: persistent (`config.ini`) and per-launch overrides (flags from F4).

### 5.4 Language / locale — OPEN ITEM
No locale flag appears in the verified flag list (F4). Candidate mechanisms, to be tested
on real images in Phase 2:
1. A locale emulator flag, if present in the installed build's `emulator -help`.
2. `adb shell` locale commands on the running device (availability varies by API level).
3. AOSP images only: root-required property change.

The UI will offer only the mechanisms that pass the test on the selected image.

### 5.5 App management
- `.apk` → `adb -s <serial> install -r`.
- `.apks` / `.xapk` → unzip to a temp dir → `adb install-multiple`.
- **ABI pre-check, no extra tools:** read `lib/<abi>/` entries from the APK zip with
  Python `zipfile`. If the APK ships native code only for `arm64-v8a`/`armeabi-v7a`
  and the image is `x86_64`, warn before install. Whether ARM translation works is
  image-dependent and **not guaranteed**.
- List / launch / uninstall / clear data / grant-revoke via `adb shell pm` and `am`.

### 5.6 SDK management
- SDK root default: existing `$ANDROID_SDK_ROOT` if valid, else
  `~/.local/share/mydevicelab/sdk`.
- License text shown in-app; download proceeds only after explicit acceptance.
- Every network action is user-initiated and surfaced with a notice.

---

## 6. Security and OPSEC

| Control | Implementation |
|---|---|
| No telemetry | MyDeviceLab sends nothing. SDK usage-stats prompt answered **No** by default. |
| Network egress | Only user-initiated SDK/image downloads from Google's repository. |
| Inherent egress (flagged) | A booted Google APIs/Play image contacts Google services itself. MyDeviceLab cannot prevent that; AOSP images are the low-egress option. |
| Privilege | GUI never runs as root, never calls sudo. `postinst` prints instructions for `kvm` group membership; it does not force it. |
| Subprocess safety | argv lists only, no shell interpolation of user input; AVD names validated against the documented character set (letters, digits, `. _ ( ) -` and space). |
| Credentials | None stored. Play Store sign-in happens inside the emulator, never in MyDeviceLab. |
| Files | `~/.config/mydevicelab` (0700), logs in `~/.local/share/mydevicelab/logs` with rotation. |

---

## 7. Failure modes

| Failure | Detection | Behavior |
|---|---|---|
| KVM missing/disabled | `emulator -accel-check`, `/dev/kvm` access | Wizard blocks launch; explains BIOS VT-x/AMD-V and `kvm` group. Software mode (`-accel off`) is unsupported by Google and not offered. |
| User not in `kvm` group | `/dev/kvm` permission check | Show exact command; require re-login. |
| Host RAM oversubscription | Sum of running AVD RAM vs `MemAvailable` | Warn before launch. |
| Disk full | Free space vs data partition + SD size | Block create/resize. |
| Port collision | Emulator exits on used ports (F4) | Pick next free even console port in 5554–5682. |
| ABI mismatch | APK `lib/` scan | Warn; allow override. |
| Root-only setting on Play image | Image variant check (F6) | Control disabled with reason. |
| Config write during run | Running-state check | Refuse; offer to stop device. |
| SD resize | Size change detected | Confirm dialog: existing SD contents will be deleted (F5). |
| Legacy tool removed in future SDK | Tool presence check at start | Clear error naming the missing tool; AndroidCliBackend path documented. |
| Wayland GPU issues | Launch failure with `-gpu host` | Retry suggestion with `-gpu swiftshader_indirect`. |

---

## 8. Phase plan and acceptance criteria

| Phase | Deliverable | Acceptance |
|---|---|---|
| 1 (this) | Architecture, schema, profiles, file tree | Profiles validate against schema; decisions reviewed |
| 2 | ProcessRunner, backends, Profile/Device/Config services, Device Library + Config Editor UI | Create Pixel and Galaxy-sized AVD; edit RAM/storage/cores; `.bak` written; locale mechanism resolved |
| 3 | AppService, RuntimeService, logcat, snapshots | Install `.apk` and split APKs; ABI warning fires; screenshot and snapshot round-trip |
| 4 | `.deb` packaging, first-run wizard, README | `dpkg -i` on clean 24.04 VM; wizard completes; `apt remove` leaves user data intact |

---

## 9. Open items requiring verification

1. `hardware-properties.ini` path and contents (§5.3) — verify on real install.
2. Locale mechanism (§5.4) — verify per image type.
3. Pixel device IDs present in the installed `avdmanager` (§5.1) — resolved at runtime.
4. Galaxy specs came from multiple reseller/retailer listings that agree with each other,
   **not from samsung.com directly**. Re-verify against Samsung's spec pages before relying
   on them for anything beyond screen-size approximation.
5. iPhone viewport preview — no data shipped until dimensions are sourced from Apple.
6. Toolkit decision (§4) — your call at this review gate.

---

## 10. Phase 2 addendum (2026-10-28)

### 10.1 New verified findings

| # | Finding | Consequence | Source |
|---|---|---|---|
| F10 | `avdmanager` and `sdkmanager` are now **also** marked deprecated in favor of the Android CLI. | All four legacy tools are deprecated; the backend adapter (§3) is the hedge. | developer.android.com/studio/command-line/avdmanager, /tools/sdkmanager |
| F11 | Official docs list only `-n -k -c -f -p` for `avdmanager create avd` — **no device-definition option documented**. | The app runs `avdmanager create avd --help` and passes `--device` only if the installed tool lists it; otherwise Pixel devices are created with image defaults and the report says so. | avdmanager page |
| F12 | Locale flags `-change-language`, `-change-country`, `-change-locale` exist (emulator 29.1.0, June 2019); they cold-boot a few times; Google said they did not yet work on Play Store images. | Resolves §5.4 option 1. Offered only if the installed emulator's help lists them; Play-image warning shown. Current Play-image behavior is **not re-verified**. | androidstudio.googleblog.com/2019/06/emulator-2910-canary.html |
| F13 | Google's AOSP sample `config.ini` uses `hw.ramSize=4096`, `disk.dataPartition.size=6G`, `hw.lcd.density`, `hw.keyboard=yes`, `hw.gpu.enabled=yes`, `fastboot.forceColdBoot=yes`, `hw.camera.back/front=emulated`. | These keys are treated as verified. Others (`hw.cpu.ncore`, `vm.heapSize`, `sdcard.size`, `hw.lcd.width/height`) are used only when the installed emulator's catalog or the device's own config.ini contains them. | android.googlesource.com/device/generic/goldfish/+/c6acebac/pc/config.ini.pc |
| F14 | SDK layout `android_sdk/cmdline-tools/latest/`; licenses via `sdkmanager --licenses`; no Java version stated. | Tool discovery and README follow this layout. | developer.android.com/tools/sdkmanager |
| F15 | Developer machine runs **Ubuntu 26.04.1**, not 24.04. `/dev/kvm` is `root:kvm 0660` plus an ACL `user:gustavo:rw-` (logind); user is **not** in the `kvm` group. | Host check tests real read/write access, not group membership. | Read-only probe of the linked machine |

### 10.2 Open items status

| §9 item | Status |
|---|---|
| 1. hardware-properties.ini path | **Still open.** Code searches `emulator/lib/` then `emulator/**`; parser format assumed (`name = key`). `tools/integration_probe_v1.0.sh` answers it. |
| 2. Locale mechanism | **Resolved** (F12), with runtime probe and Play-image caveat. |
| 3. Pixel device ids | Resolved at runtime (`avdmanager list device -c`); depends on F11 probe. |
| 4. Galaxy specs from resellers | Unchanged. |
| 5. iPhone viewport | Unchanged (not shipped). |
| 6. Toolkit | **Resolved:** GTK4 + libadwaita. |
| New: unit of a bare `disk.dataPartition.size` number | **Open.** Heuristic in code; app always writes `<n>G` (matches F13). |
| New: `mksdcard` argument syntax (`<size>M <file>`) | **Open.** Verify with probe/integration test. |
| New: graceful stop | Phase 2 sends SIGTERM; Phase 3 moves to the emulator console. |

### 10.3 Test evidence (this workspace: Ubuntu 24.04, GTK 4.14, libadwaita 1.5, Python 3.12)

- 44 unit tests pass (`pytest tests`), against a fake SDK that logs every tool call.
- Mutation checks: removing the evidence gate fails 1 test; disabling backups fails 3.
- Headless UI smoke test (`xvfb-run python3 tests/ui_smoke.py`) passes 17 checks.
- `pyflakes` clean. Real emulator not runnable here (no KVM, Google repository blocked).
