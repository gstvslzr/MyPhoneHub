#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Headless UI smoke test: run with  xvfb-run -a python3 tests/ui_smoke.py OUTDIR

Builds a fake SDK, creates two devices through the real services, opens the real
MainWindow, exercises selection, editing, save, the create dialog and the about
dialog, and writes PNG screenshots. Exit code 0 = no exceptions and checks passed.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "ui-shots")
OUT.mkdir(parents=True, exist_ok=True)

tmp = Path(tempfile.mkdtemp(prefix="mdl-ui-"))
os.environ["HOME"] = str(tmp / "home")
os.environ["XDG_CONFIG_HOME"] = str(tmp / "home/.config")
os.environ["XDG_DATA_HOME"] = str(tmp / "home/.local/share")
os.environ["ANDROID_AVD_HOME"] = str(tmp / "home/.android/avd")
os.environ["ANDROID_FAKE_LOCALE_FLAGS"] = "1"
os.environ["GSK_RENDERER"] = "cairo"
for k in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
    os.environ.pop(k, None)
Path(os.environ["ANDROID_AVD_HOME"]).mkdir(parents=True)

sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from fake_sdk import build_fake_sdk  # noqa: E402

SDK = build_fake_sdk(tmp / "sdk")

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from mydevicelab import paths  # noqa: E402
from mydevicelab.services.context import build_context  # noqa: E402
from mydevicelab.ui.main_window import MainWindow  # noqa: E402

failures = []
errors = []
sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}")


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def pump(seconds=0.6):
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + int(seconds * 1e6)
    while GLib.get_monotonic_time() < end:
        ctx.iteration(False)


def shot(widget, name):
    w, h = widget.get_width(), widget.get_height()
    snap = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(widget).snapshot(snap, w, h)
    node = snap.to_node()
    tex = widget.get_native().get_renderer().render_texture(node, None)
    tex.save_to_png(str(OUT / name))
    print(f"     screenshot {OUT / name} ({w}x{h})")


paths.ensure_private_dirs()
ctx = build_context(str(SDK))
PLAY = "system-images;android-35;google_apis_playstore;x86_64"
r1 = ctx.devices.create("Galaxy_S26_Ultra", ctx.profiles.get("galaxy_s26_ultra_sized"), PLAY)
r2 = ctx.devices.create("Galaxy_A57", ctx.profiles.get("galaxy_a57_sized"), PLAY)
check(any("Screen width" in a for a in r1.applied), "Galaxy profile applied screen width via catalog")

app = Adw.Application(application_id="io.github.gussalazar.MyDeviceLab.Smoke")
state = {}


def on_activate(a):
    win = MainWindow(a, ctx)
    state["win"] = win
    win.present()


app.connect("activate", on_activate)
app.register(None)
app.activate()
pump(1.5)
win = state["win"]

check(len(win.devices) == 2, "sidebar lists 2 devices")
host_ready = ctx.host_report().ready
check(win.run_btn.get_sensitive() == host_ready,
      f"Start button enabled={win.run_btn.get_sensitive()} matches host readiness={host_ready}")
check(win.selected is not None and win.editor is not None, "first device selected, editor shown")
shot(win, "01-main-window.png")

# select the Ultra explicitly and edit RAM + language
row = next(r for i in range(2) if (r := win.listbox.get_row_at_index(i)).avd_name == "Galaxy_S26_Ultra")
win.listbox.select_row(row)
pump()
ed = win.editor
check(ed.avd.name == "Galaxy_S26_Ultra", "editor switched to Galaxy_S26_Ultra")
check(ed.original["ram_mb"] == 8192 and ed.original["lcd_width"] == 1440, "editor shows clamped RAM and width")
check(not win.save_btn.get_sensitive(), "Save disabled before edits")
ed.rows["ram_mb"].set_value(6144)
ed.rows["language"].set_text("es")
pump(0.2)
check(win.save_btn.get_sensitive(), "Save enabled after edits")
check(ed.changes() == {"ram_mb": 6144, "language": "es"}, f"changes tracked: {ed.changes()}")
shot(win, "02-editor-dirty.png")
win._on_save()
pump(1.5)
cfg = (Path(os.environ["ANDROID_AVD_HOME"]) / "Galaxy_S26_Ultra.avd/config.ini").read_text()
check("hw.ramSize=6144" in cfg, "RAM saved to config.ini")
check(ctx.config.read_launch("Galaxy_S26_Ultra").get("language") == "es", "language saved as launch setting")
check(bool(list((Path(os.environ["ANDROID_AVD_HOME"]) / "Galaxy_S26_Ultra.avd").glob("config.ini.*.bak"))),
      "backup written")

# scroll editor to the bottom half for a second view
pump(0.5)
shot(win, "03-after-save.png")

# create dialog
from mydevicelab.ui import create_dialog as cd_mod  # noqa: E402
created = {}
orig_init = cd_mod.CreateDialog.__init__


def spy_init(self, *a, **k):
    orig_init(self, *a, **k)
    created["dlg"] = self


cd_mod.CreateDialog.__init__ = spy_init
import mydevicelab.ui.main_window as mw_mod  # noqa: E402
mw_mod.CreateDialog = cd_mod.CreateDialog
win._on_new()
pump(0.8)
dlg = created.get("dlg")
check(dlg is not None, "create dialog opened")
img = dlg.images[dlg.image_row.get_selected()]
check(img.variant == "google_apis_playstore", f"dialog preselects profile's image variant ({img.variant})")
shot(win, "04-create-dialog.png")

# --- v1.0.1 regression: reproduce the "only A57 gets created" bug from the real machine
def pick(pid):
    dlg.profile_row.set_selected(next(i for i, p in enumerate(dlg.profiles) if p.id == pid))
    pump(0.2)

first_name = dlg.name_row.get_text()
pick("galaxy_s26_ultra_sized")
check(dlg.name_row.get_text() == "galaxy_s26_ultra_sized",
      f"name follows profile change ({first_name!r} -> {dlg.name_row.get_text()!r})")
pick("galaxy_a57_sized")
check(dlg.name_row.get_text() == "galaxy_a57_sized", "name follows back to A57")
dlg.name_row.set_text("Galaxy_A57")          # an existing device name
pump(0.2)
check(not dlg.create_btn.get_sensitive(), "Create disabled for a duplicate name")
check("already exists" in (dlg.g1.get_description() or ""), "duplicate shown inline")
shot(win, "06-duplicate-name.png")
dlg.name_row.set_text("MyCustomName")
pick("galaxy_s26_sized")
check(dlg.name_row.get_text() == "MyCustomName", "a name the user typed survives a profile change")
dlg.name_row.set_text("")
pick("galaxy_s26_ultra_sized")   # a different profile; re-selecting the same one emits no change
check(dlg.name_row.get_text() == "galaxy_s26_ultra_sized", "clearing the name re-enables auto naming")

dlg.name_row.set_text("bad name!")
pump(0.2)
check(not dlg.create_btn.get_sensitive(), "Create disabled for invalid name")
dlg.name_row.set_text("Pixel9_test")
dlg.profile_row.set_selected(next(i for i, p in enumerate(dlg.profiles) if p.id == "pixel_9"))
pump(0.2)
dlg._create()
pump(2.0)
check(any(d.name == "Pixel9_test" for d in win.devices), "device created from dialog appears in sidebar")
shot(win, "05-created-report.png")

# about dialog debug info
win._on_about()
pump(0.5)

check(not errors, f"no exceptions in callbacks ({errors})")
app.quit()
print(f"\nResult: {'UI SMOKE PASSED' if not failures and not errors else f'{len(failures)} failure(s)'}")
sys.exit(0 if not failures and not errors else 1)
