#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
# MyDeviceLab v1.0 - integration probe (READ-ONLY).
# Answers the Phase 1/2 open items from the real SDK on this machine.
# Changes nothing, downloads nothing, sends nothing off the machine.
# Usage: tools/integration_probe_v1.0.sh [SDK_ROOT]
set -u
SDK="${1:-${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}}"
AVDM="$SDK/cmdline-tools/latest/bin/avdmanager"
EMU="$SDK/emulator/emulator"

hdr() { printf '\n== %s\n' "$1"; }
yesno() { if eval "$1" >/dev/null 2>&1; then echo "YES"; else echo "NO"; fi; }

hdr "Host"
. /etc/os-release 2>/dev/null && echo "OS: $PRETTY_NAME"
echo "CPU virt flags: $(grep -cE 'vmx|svm' /proc/cpuinfo) cores report vmx/svm"
echo "/dev/kvm read+write for $(id -un): $(yesno 'test -r /dev/kvm -a -w /dev/kvm')"
echo "java: $(command -v java || echo 'NOT FOUND')"; java -version 2>&1 | head -1

hdr "SDK at $SDK"
for p in "$AVDM" "$EMU" "$SDK/emulator/mksdcard" "$SDK/platform-tools/adb"; do
  printf '%-60s %s\n' "$p" "$( [ -x "$p" ] && echo present || echo MISSING )"
done
echo "System images:"
IMGS=$(ls -d "$SDK"/system-images/*/*/* 2>/dev/null | sed "s|$SDK/|  |")
echo "${IMGS:-  none}"

hdr "Open item 1: hardware-properties.ini"
CAT=$(find "$SDK/emulator" -name hardware-properties.ini 2>/dev/null | head -1)
if [ -n "$CAT" ]; then
  echo "Found: $CAT"
  echo "Format sample (first 'name =' blocks):"; grep -m3 -A3 -E '^\s*name\s*=' "$CAT"
  for k in hw.ramSize vm.heapSize hw.cpu.ncore disk.dataPartition.size sdcard.size \
           hw.lcd.width hw.lcd.height hw.lcd.density hw.keyboard hw.gpu.enabled fastboot.forceColdBoot; do
    printf '  %-26s %s\n' "$k" "$(grep -qE "^\s*name\s*=\s*$k\s*$" "$CAT" && echo listed || echo 'not listed')"
  done
else
  echo "NOT FOUND under $SDK/emulator"
fi

hdr "Open item 2: language/locale flags"
if [ -x "$EMU" ]; then
  HELP=$("$EMU" -help 2>&1; "$EMU" -help-all 2>&1)
  for f in -change-language -change-country -change-locale -timezone -no-metrics; do
    printf '  %-20s %s\n' "$f" "$(grep -q -- "$f" <<<"$HELP" && echo listed || echo 'not listed')"
  done
  echo "Emulator version: $("$EMU" -version 2>&1 | head -1)"
fi

hdr "Open item 3: avdmanager device option + Pixel ids"
if [ -x "$AVDM" ]; then
  echo "create avd --help mentions --device: $( "$AVDM" create avd --help 2>&1 | grep -q -- '--device' && echo YES || echo NO)"
  echo "Pixel 9 ids available:"; "$AVDM" list device -c 2>/dev/null | grep -E '^pixel_9' || echo "  none"
fi

hdr "Open item 4: real config.ini format (first AVD found)"
CFG=$(ls "${ANDROID_AVD_HOME:-$HOME/.android/avd}"/*.avd/config.ini 2>/dev/null | head -1)
if [ -n "$CFG" ]; then
  echo "$CFG"; grep -E '^(hw.ramSize|disk.dataPartition.size|sdcard.size|hw.cpu.ncore|hw.lcd|vm.heapSize|PlayStore|image.sysdir)' "$CFG"
else
  echo "No AVD yet - create one in MyDeviceLab, then re-run."
fi
echo
echo "Done. Paste this output back into the chat."
