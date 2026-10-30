#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
# =============================================================================
# MyDeviceLab v1.0 - full installer (per-user, Ubuntu 24.04 / 26.04, x86_64)
#
# Installs:
#   1. System packages (apt, needs sudo): GTK4, libadwaita, PyGObject, jsonschema,
#      Java runtime, unzip, curl - only the ones missing.
#   2. MyDeviceLab into ~/.local/share/mydevicelab/app, a launcher in ~/.local/bin,
#      an icon and a desktop menu entry. No root-owned app files.
#   3. Android SDK (unless --no-sdk): Google's command-line tools (SHA-256 verified),
#      then platform-tools, emulator and one system image via Google's sdkmanager.
#      YOU read and accept Google's licenses interactively; this script never does.
#
# Network: only dl.google.com and Google's SDK repository (via sdkmanager), plus
#          your configured apt mirrors. MyDeviceLab itself sends nothing.
# Run from the unzipped mydevicelab folder:   bash install_mydevicelab_v1.0.sh
# =============================================================================
set -euo pipefail

MDL_VERSION="1.0.0"
APP_ID="io.github.gussalazar.MyDeviceLab"

# Google "Command line tools only" for Linux - from developer.android.com/studio,
# checked 2026-10-28. If Google publishes a newer build, update both lines.
CLT_FILE="commandlinetools-linux-15859902_latest.zip"
CLT_SHA256="4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"
CLT_URL="https://dl.google.com/android/repository/${CLT_FILE}"

APT_PACKAGES=(python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-jsonschema default-jre-headless unzip curl)
PY=""                          # chosen in step 2: a /usr/bin python that can load GTK4 + libadwaita
MIN_FREE_GB=10                 # recommendation, not a measured requirement

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_DIR="$DATA_HOME/mydevicelab/app"
LOG_DIR="$DATA_HOME/mydevicelab/logs"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/mydevicelab"
DESKTOP_FILE="$DATA_HOME/applications/${APP_ID}.desktop"
ICON_FILE="$DATA_HOME/icons/hicolor/scalable/apps/${APP_ID}.svg"
SETTINGS_FILE="$CONFIG_HOME/mydevicelab/settings.json"

# ------------------------------------------------------------------ options
SDK_ROOT=""
IMAGE=""
CLT_ZIP=""
DO_SDK=1
ASSUME_YES=0
UNINSTALL=0

usage() {
  cat <<EOF
MyDeviceLab ${MDL_VERSION} installer

Usage: bash $(basename "$0") [options]

  --sdk-root PATH   Android SDK folder (default: existing SDK if found, else ~/Android/Sdk)
  --image ID        System image, e.g. "system-images;android-35;google_apis_playstore;x86_64"
                    (default: newest Play Store x86_64 image Google lists; you confirm it)
  --clt-zip PATH    Use an already-downloaded ${CLT_FILE} (still SHA-256 checked)
  --no-sdk          Install MyDeviceLab only; skip the Android SDK
  --yes             Don't ask "continue?" questions (license prompts are ALWAYS interactive)
  --uninstall       Remove MyDeviceLab app files, launcher, icon, menu entry
                    (keeps settings, devices and the SDK; prints how to remove them)
  -h, --help        This help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sdk-root) SDK_ROOT="${2:?--sdk-root needs a path}"; shift 2 ;;
    --image)    IMAGE="${2:?--image needs an id}"; shift 2 ;;
    --clt-zip)  CLT_ZIP="${2:?--clt-zip needs a path}"; shift 2 ;;
    --no-sdk)   DO_SDK=0; shift ;;
    --yes)      ASSUME_YES=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# ------------------------------------------------------------------ output helpers
if [[ -t 1 ]]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B=''; G=''; Y=''; R=''; N=''; fi
step() { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '\n%sERROR:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
confirm() {  # confirm "question" -> 0 yes / 1 no
  [[ $ASSUME_YES -eq 1 ]] && return 0
  local a; read -r -p "  $1 [Y/n] " a || return 1
  [[ -z "$a" || "$a" =~ ^[Yy] ]]
}

# ------------------------------------------------------------------ uninstall
if [[ $UNINSTALL -eq 1 ]]; then
  step "Uninstalling MyDeviceLab app files"
  for p in "$APP_DIR" "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE"; do
    if [[ -e "$p" ]]; then rm -rf -- "$p"; ok "removed $p"; else ok "not present: $p"; fi
  done
  command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
  cat <<EOF

Kept (remove manually only if you want them gone):
  Settings & launch options : $CONFIG_HOME/mydevicelab
  Logs                      : $LOG_DIR
  Virtual devices (AVDs)    : ${ANDROID_AVD_HOME:-$HOME/.android/avd}
  Android SDK               : $(sed -n 's/.*"sdk_root": *"\([^"]*\)".*/\1/p' "$SETTINGS_FILE" 2>/dev/null || echo "see $SETTINGS_FILE")
EOF
  exit 0
fi

# ------------------------------------------------------------------ log everything
mkdir -p "$LOG_DIR"
INSTALL_LOG="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$INSTALL_LOG") 2>&1
echo "MyDeviceLab ${MDL_VERSION} installer - $(date -Is) - log: $INSTALL_LOG"

# ------------------------------------------------------------------ 1. preflight
step "1/7 Checking this computer"
[[ $EUID -ne 0 ]] || die "Run as your normal user, not root. The script uses sudo only for apt."
[[ -f "$SRC_DIR/src/mydevicelab/__init__.py" ]] || die "Run this script from the unzipped mydevicelab folder (src/mydevicelab not found next to it)."

# Read os-release in a subshell so its variables (VERSION, NAME, ID...) can't clobber ours.
OS_ID="$(. /etc/os-release 2>/dev/null; echo "${ID:-unknown}")"
OS_PRETTY="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}")"
OS_MAJOR="$(. /etc/os-release 2>/dev/null; echo "${VERSION_ID%%.*}")"
if [[ "$OS_ID" == "ubuntu" ]]; then
  ok "OS: $OS_PRETTY"
  [[ "${OS_MAJOR:-0}" -ge 24 ]] || die "Ubuntu 24.04 or newer is required (libadwaita 1.5)."
else
  warn "OS is '$OS_PRETTY'. Only Ubuntu 24.04/26.04 are tested; continuing."
fi
[[ "$(uname -m)" == "x86_64" ]] || die "x86_64 CPU required (found $(uname -m))."
ok "CPU architecture: x86_64"

if grep -qE 'vmx|svm' /proc/cpuinfo; then ok "CPU virtualization flags present"
else
  warn "No vmx/svm CPU flag: devices will not start until VT-x/AMD-V is enabled in BIOS/UEFI"
  warn "(inside a VM, enable nested virtualization). The app itself can still be installed."
  confirm "Continue anyway?" || die "Stopped at your request."
fi

KVM_FIX=0
if [[ -e /dev/kvm ]]; then
  if [[ -r /dev/kvm && -w /dev/kvm ]]; then ok "/dev/kvm is readable and writable by $(id -un)"
  else warn "/dev/kvm exists but $(id -un) cannot use it"; KVM_FIX=1; fi
else
  warn "/dev/kvm missing - the emulator cannot run accelerated until KVM is available"
fi

# ------------------------------------------------------------------ 2. apt packages
step "2/7 System packages"
missing=()
for p in "${APT_PACKAGES[@]}"; do
  if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed"; then ok "$p"
  else missing+=("$p"); fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "  Missing: ${missing[*]}"
  echo "  Will run: sudo apt-get update && sudo apt-get install -y ${missing[*]}"
  confirm "Install them now?" || die "Cannot continue without: ${missing[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing[@]}"
  ok "installed: ${missing[*]}"
fi

if [[ $KVM_FIX -eq 1 ]]; then
  echo "  Will run: sudo usermod -aG kvm $(id -un)   (takes effect after you log out and back in)"
  if confirm "Add $(id -un) to the kvm group?"; then
    sudo usermod -aG kvm "$(id -un)"; ok "added to kvm group - log out and back in before starting devices"
  else warn "skipped; devices will not start until /dev/kvm is usable"; fi
fi

# Pick the system interpreter that can actually load the apt-installed bindings.
# /usr/bin only: pyenv/conda/venv pythons don't see Ubuntu's python3-gi.
GI_CHECK='import gi, jsonschema
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
v = (Adw.get_major_version(), Adw.get_minor_version())
assert v >= (1, 5), "libadwaita %d.%d < 1.5" % v
import sys
print("%s|GTK %d.%d, libadwaita %d.%d" % (sys.version.split()[0], Gtk.get_major_version(), Gtk.get_minor_version(), *v))'
py_cands=(/usr/bin/python3)
for f in /usr/bin/python3.[0-9] /usr/bin/python3.[0-9][0-9]; do [[ -x "$f" ]] && py_cands+=("$f"); done
for cand in "${py_cands[@]}"; do
  if info="$("$cand" -c "$GI_CHECK" 2>/dev/null)"; then PY="$cand"; break; fi
done
[[ -n "$PY" ]] || die "No /usr/bin python3 can load GTK4 + libadwaita >= 1.5 + jsonschema.
  Check: dpkg -l python3-gi gir1.2-adw-1 python3-jsonschema ; ls -l /usr/bin/python3"
ok "Python: $PY (${info%%|*}), ${info#*|}"

# ------------------------------------------------------------------ 3. app files
step "3/7 Installing MyDeviceLab ${MDL_VERSION} to $APP_DIR"
STAGE="${APP_DIR}.new.$$"
rm -rf -- "$STAGE"
mkdir -p "$STAGE"
for item in src profiles schema tools docs packaging README.md; do
  [[ -e "$SRC_DIR/$item" ]] && cp -a "$SRC_DIR/$item" "$STAGE/"
done
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
PYTHONPATH="$STAGE/src" "$PY" -c "import mydevicelab.ui.main_window" \
  || { rm -rf -- "$STAGE"; die "Installed code failed to import - previous install left untouched."; }
"$PY" "$STAGE/tools/validate_profiles_v1.0.py" >/dev/null \
  || { rm -rf -- "$STAGE"; die "Device profiles failed validation - previous install left untouched."; }
if [[ -d "$APP_DIR" ]]; then rm -rf -- "${APP_DIR}.old"; mv "$APP_DIR" "${APP_DIR}.old"; fi
mv "$STAGE" "$APP_DIR"
rm -rf -- "${APP_DIR}.old"
ok "app files installed and verified (imports + profile validation)"

# ------------------------------------------------------------------ 4. launcher, icon, menu
step "4/7 Launcher, icon and menu entry"
mkdir -p "$BIN_DIR" "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON_FILE")"
cat > "$LAUNCHER" <<EOF
#!/bin/sh
# MyDeviceLab ${MDL_VERSION} launcher (generated by installer).
# Uses a /usr/bin Python that can load Ubuntu's GTK bindings (never pyenv/conda).
export PYTHONPATH="$APP_DIR/src"
for py in /usr/bin/python3 $PY; do
  if [ -x "\$py" ] && "\$py" -c 'import gi; gi.require_version("Adw", "1"); from gi.repository import Adw' 2>/dev/null; then
    exec "\$py" -m mydevicelab "\$@"
  fi
done
echo "MyDeviceLab: no /usr/bin Python can load GTK4/libadwaita. Re-run the installer." >&2
exit 1
EOF
chmod 755 "$LAUNCHER"
ok "launcher: $LAUNCHER"
cp "$APP_DIR/packaging/${APP_ID}.svg" "$ICON_FILE"
ok "icon: $ICON_FILE"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=MyDeviceLab
GenericName=Android Device Lab
Comment=Create and run Pixel and Galaxy-sized Android emulators
Exec=$LAUNCHER
Icon=${APP_ID}
Terminal=false
Categories=Development;Emulator;System;
Keywords=android;emulator;avd;pixel;galaxy;
StartupWMClass=${APP_ID}
EOF
ok "menu entry: $DESKTOP_FILE"
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not on your PATH; use the menu entry or run $LAUNCHER";; esac

# ------------------------------------------------------------------ SDK helpers
write_sdk_setting() {
  "$PY" - "$SETTINGS_FILE" "$1" <<'EOF'
import json, os, sys
path, root = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
data["sdk_root"] = root
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(data, fh, indent=2, sort_keys=True)
os.replace(tmp, path)
EOF
}

find_existing_sdk() {
  local c
  for c in "$SDK_ROOT" "${ANDROID_SDK_ROOT:-}" "${ANDROID_HOME:-}" "$HOME/Android/Sdk"; do
    [[ -n "$c" && -x "$c/cmdline-tools/latest/bin/sdkmanager" ]] && { echo "$c"; return 0; }
  done
  return 1
}

if [[ $DO_SDK -eq 0 ]]; then
  step "5/7 Android SDK - skipped (--no-sdk)"
  step "6/7 System image - skipped"
else
  # ---------------------------------------------------------------- 5. SDK tools
  step "5/7 Android SDK command-line tools"
  if existing="$(find_existing_sdk)"; then
    SDK_ROOT="$existing"; ok "using existing SDK: $SDK_ROOT"
  else
    SDK_ROOT="${SDK_ROOT:-$HOME/Android/Sdk}"
    probe_dir="$SDK_ROOT"
    while [[ ! -d "$probe_dir" && "$probe_dir" != "/" ]]; do probe_dir="$(dirname "$probe_dir")"; done
    free_kb="$(df -Pk "$probe_dir" 2>/dev/null | awk 'NR==2{print $4}')"
    free_gb=$(( ${free_kb:-0} / 1024 / 1024 ))
    if [[ $free_gb -ge $MIN_FREE_GB ]]; then ok "free space: ${free_gb} GB at $probe_dir"
    else warn "only ${free_gb} GB free at $probe_dir (${MIN_FREE_GB} GB+ recommended)"; fi
    echo "  Will download ${CLT_FILE} (181.8 MB per Google) from dl.google.com into $SDK_ROOT"
    confirm "Download Google's command-line tools?" || die "Stopped before downloading. Re-run with --no-sdk to install the app only."
    TMPD="$(mktemp -d)"; trap 'rm -rf -- "$TMPD"' EXIT
    if [[ -n "$CLT_ZIP" ]]; then
      [[ -f "$CLT_ZIP" ]] || die "--clt-zip file not found: $CLT_ZIP"
      cp "$CLT_ZIP" "$TMPD/clt.zip"
    else
      curl -fL --proto '=https' --tlsv1.2 --retry 3 -o "$TMPD/clt.zip" "$CLT_URL" \
        || die "Download failed. Get ${CLT_FILE} from https://developer.android.com/studio#command-tools and re-run with --clt-zip PATH."
    fi
    got="$(sha256sum "$TMPD/clt.zip" | awk '{print $1}')"
    [[ "$got" == "$CLT_SHA256" ]] || die "SHA-256 mismatch for ${CLT_FILE}
  expected $CLT_SHA256
  got      $got
The file is corrupt or not the version this installer expects; nothing was installed."
    ok "SHA-256 verified ($CLT_SHA256)"
    unzip -q "$TMPD/clt.zip" -d "$TMPD/x"
    [[ -d "$TMPD/x/cmdline-tools/bin" ]] || die "Unexpected zip layout (no cmdline-tools/bin)."
    mkdir -p "$SDK_ROOT/cmdline-tools"
    rm -rf -- "$SDK_ROOT/cmdline-tools/latest"
    mv "$TMPD/x/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"   # layout required by Google
    ok "installed to $SDK_ROOT/cmdline-tools/latest"
  fi
  export ANDROID_SDK_ROOT="$SDK_ROOT" ANDROID_HOME="$SDK_ROOT"
  SDKM="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
  if sdkm_ver="$("$SDKM" --version 2>&1)"; then ok "sdkmanager $(tail -1 <<<"$sdkm_ver") runs with $(java -version 2>&1 | head -1)"
  else printf '%s\n' "$sdkm_ver" | tail -5; die "sdkmanager failed to run (output above). Check the Java runtime."; fi

  echo
  echo "  ${B}Google's SDK licenses come next.${N} sdkmanager shows each license; read it and"
  echo "  answer y or N yourself. This script does not accept licenses for you."
  [[ $ASSUME_YES -eq 1 ]] || read -r -p "  Press Enter to review the licenses... " _
  "$SDKM" --licenses || die "License step did not complete."

  # ---------------------------------------------------------------- 6. image
  step "6/7 Emulator, platform-tools and a system image"
  if [[ -z "$IMAGE" ]]; then
    echo "  Asking Google's repository for available x86_64 Play Store images..."
    IMAGE="$("$SDKM" --list 2>/dev/null \
      | grep -oE 'system-images;android-[0-9]+;google_apis_playstore;x86_64' \
      | sort -u -t';' -k2,2V | tail -1 || true)"
    if [[ -n "$IMAGE" ]]; then
      echo "  Newest listed: $IMAGE"
      if [[ $ASSUME_YES -eq 0 ]]; then
        read -r -p "  Press Enter to use it, or type another system-images;... id: " alt || true
        [[ -n "${alt:-}" ]] && IMAGE="$alt"
      fi
    else
      read -r -p "  Could not parse the list. Type a system image id: " IMAGE || true
      [[ -n "$IMAGE" ]] || die "No system image chosen. Re-run with --image ID."
    fi
  fi
  [[ "$IMAGE" =~ ^system-images\;[A-Za-z0-9._-]+\;[A-Za-z0-9._-]+\;[A-Za-z0-9._-]+$ ]] \
    || die "Invalid image id: $IMAGE"
  echo "  Will run: sdkmanager \"platform-tools\" \"emulator\" \"$IMAGE\"  (several GB)"
  confirm "Download and install them now?" || die "Stopped before installing SDK packages."
  "$SDKM" "platform-tools" "emulator" "$IMAGE"
  for t in "$SDK_ROOT/emulator/emulator" "$SDK_ROOT/platform-tools/adb"; do
    [[ -x "$t" ]] && ok "$t" || die "Missing after install: $t"
  done
  ok "system image: $IMAGE"
  write_sdk_setting "$SDK_ROOT"
  ok "MyDeviceLab will use SDK at $SDK_ROOT ($SETTINGS_FILE)"
fi

# ------------------------------------------------------------------ 7. verify
step "7/7 Verifying"
"$LAUNCHER" --version | sed 's/^/  ✓ /'
if [[ $DO_SDK -eq 1 ]]; then
  PROBE_OUT="$LOG_DIR/probe-$(date +%Y%m%d-%H%M%S).txt"
  bash "$APP_DIR/tools/integration_probe_v1.0.sh" "$SDK_ROOT" > "$PROBE_OUT" 2>&1 || true
  ok "read-only SDK probe saved: $PROBE_OUT"
  grep -E 'read\+write|hardware-properties|change-locale|mentions --device' "$PROBE_OUT" | sed 's/^/    /' || true
fi

cat <<EOF

${G}${B}MyDeviceLab ${MDL_VERSION} is installed.${N}
  Start it   : menu → MyDeviceLab, or run: mydevicelab
  Install log: $INSTALL_LOG
  Uninstall  : bash $(basename "$0") --uninstall
EOF
[[ $DO_SDK -eq 0 ]] && echo "  SDK        : not installed (--no-sdk). Re-run without --no-sdk when ready."
exit 0
