# MyDeviceLab v1.0 — Integration test on a real machine (Phase 2)

The unit tests and UI smoke test run against a **fake** SDK. This checklist confirms
behavior against Google's real tools. Target: your Ubuntu 26.04.1 machine (`my-i9`),
which already has KVM access for your user and GTK 4.22 / libadwaita 1.9.

## 1. Install the SDK (one-time, ~3–5 GB)

**Easiest:** `bash install_mydevicelab_v1.0.sh` does all of this (you still accept the licenses yourself)
and runs the probe in step 2 automatically. Manual equivalent:

```bash
sudo apt install default-jre-headless unzip      # skip java if 'java -version' already works
mkdir -p ~/Android/Sdk/cmdline-tools
# Download "Command line tools only" for Linux from developer.android.com/studio
# (accept Google's terms on that page), then:
unzip ~/Downloads/commandlinetools-linux-*_latest.zip -d /tmp/clt
mv /tmp/clt/cmdline-tools ~/Android/Sdk/cmdline-tools/latest   # Google's required layout

export ANDROID_SDK_ROOT=~/Android/Sdk
SDKM=~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager
$SDKM --licenses                                  # read, then accept
$SDKM --list | grep 'system-images;android-' | grep x86_64 | tail   # pick an image
$SDKM "platform-tools" "emulator" "system-images;android-35;google_apis_playstore;x86_64"
```

Use whichever x86_64 image `--list` shows; `android-35` is an example, not a requirement.

## 2. Run the probe (read-only)

```bash
cd mydevicelab
bash tools/integration_probe_v1.0.sh ~/Android/Sdk
```

It answers the open items: catalog path and format, locale flags, `avdmanager` device
option, Pixel ids, and real `config.ini` units.

## 3. Run the app from source

```bash
cd mydevicelab
PYTHONPATH=src python3 -m mydevicelab --verbose
```

## 4. Checklist

| # | Action | Pass if |
|---|---|---|
| 1 | Open the app | Banner is hidden (SDK, emulator, image, KVM all OK) |
| 2 | **+** → *Galaxy S26 Ultra-sized* → Create | Report lists screen 1440×3120, density 480, RAM 8192; any **Skipped** lines name a reason |
| 3 | **+** → *Pixel 9* → Create | Report says device definition `pixel_9` applied, **or** explains why it was skipped |
| 4 | Change RAM to 4096, storage to 16 GB, cores to 4 → Save | Toast shows backup name; `config.ini` has `hw.ramSize=4096`, `disk.dataPartition.size=16G`, `hw.cpu.ncore=4` |
| 5 | Start the Galaxy device | Emulator window opens at phone proportions; sidebar shows **Running** within ~3 s |
| 6 | While running: try to Save a hardware change | Refused; launch settings still editable |
| 7 | Stop; set Language `es`, Country `US` → Start | Device UI in Spanish (Play image may not change — Google reported this in 2019) |
| 8 | Clone, Rename, Delete | Each works; clone cold-boots once |
| 9 | Check `~/.local/share/mydevicelab/logs/` | `mydevicelab.log` and one `emulator-*.log` per start |
