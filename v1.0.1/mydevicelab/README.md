# MyDeviceLab v1.0 — Phase 2

GTK4 desktop front-end for Google's Android Emulator: Pixel devices and Galaxy-sized
approximations, with per-device configuration. Local-first, no telemetry.

**Phase 2 status:** device library, create/clone/rename/delete, config editor, start/stop.
Tested against a fake SDK; the real-SDK check is `docs/INTEGRATION_TEST_v1.0.md`.
Not yet: app install (P3), SDK download UI and `.deb` (P4).

## Install (recommended)

```bash
unzip MyDeviceLab_v1.0.1.zip && cd mydevicelab
bash install_mydevicelab_v1.0.1.sh            # app + Android SDK; you accept Google's licenses
bash install_mydevicelab_v1.0.1.sh --no-sdk   # app only
bash install_mydevicelab_v1.0.1.sh --help     # all options (--sdk-root, --image, --clt-zip, --uninstall)
```

Per-user install: app in `~/.local/share/mydevicelab/app`, launcher `~/.local/bin/mydevicelab`,
menu entry and icon under `~/.local/share`. `sudo` is used only for missing apt packages.
The Google command-line tools download is SHA-256 verified before anything is unpacked.

## Requirements (manual setup)

Ubuntu 24.04 or newer, x86_64 with VT-x/AMD-V, and:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-jsonschema
```

Plus the Android SDK (command-line tools, emulator, one x86_64 system image) —
see `docs/INTEGRATION_TEST_v1.0.md` §1. MyDeviceLab never bundles Google's SDK.

## Run from source

```bash
PYTHONPATH=src python3 -m mydevicelab            # add --sdk-root PATH or --verbose as needed
```

## Tests

```bash
python3 -m pytest tests                          # needs python3-pytest
xvfb-run -a python3 tests/ui_smoke.py /tmp/shots # headless UI test, writes screenshots
python3 tools/validate_profiles_v1.0.py
bash tools/integration_probe_v1.0.sh ~/Android/Sdk   # read-only, on a real SDK
```

## How settings are trusted

Every setting carries its evidence (Google docs, Google AOSP config, Google release blog).
Settings without that evidence appear only if your installed emulator lists them, or if the
device's own `config.ini` already has them. The editor shows the source under each setting.
Every `config.ini` write makes a timestamped `.bak` first.

## Not supported
- iPhone app execution (iOS Simulator is macOS-only).
- One UI / Samsung software on Galaxy-sized profiles.
