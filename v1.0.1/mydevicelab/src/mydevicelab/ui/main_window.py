# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Main window: device list (sidebar) + device detail/config editor (content)."""
from __future__ import annotations

import logging

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_NAME, __version__
from ..backends.legacy_sdk import AVD_NAME_RE
from ..services.context import AppContext
from .async_util import run_async
from .config_editor import ConfigEditor
from .create_dialog import CreateDialog

log = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, ctx: AppContext):
        super().__init__(application=app, title=f"{APP_NAME} v{__version__}",
                         default_width=1120, default_height=760)
        self.ctx = ctx
        self.devices = []
        self.selected: str | None = None
        self.editor: ConfigEditor | None = None
        self.caps = ctx.backend.capabilities()
        self._running: set[str] = set()

        self.toasts = Adw.ToastOverlay()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toasts.set_child(root)
        self.set_content(self.toasts)

        self.banner = Adw.Banner()
        root.append(self.banner)

        self.split = Adw.NavigationSplitView(vexpand=True)
        self.split.set_min_sidebar_width(280)
        root.append(self.split)

        # ---- sidebar
        side_view = Adw.ToolbarView()
        side_head = Adw.HeaderBar()
        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New device")
        add_btn.connect("clicked", self._on_new)
        side_head.pack_start(add_btn)
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        side_head.pack_end(refresh_btn)
        side_view.add_top_bar(side_head)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.connect("row-selected", self._on_row_selected)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.listbox)
        side_view.set_content(scroller)
        self.split.set_sidebar(Adw.NavigationPage(title="Devices", child=side_view))

        # ---- content
        self.content_view = Adw.ToolbarView()
        head = Adw.HeaderBar()
        self.run_btn = Gtk.Button(label="Start")
        self.run_btn.add_css_class("suggested-action")
        self.run_btn.connect("clicked", self._on_run_clicked)
        head.pack_start(self.run_btn)
        self.save_btn = Gtk.Button(label="Save")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._on_save)
        self.revert_btn = Gtk.Button(label="Revert")
        self.revert_btn.connect("clicked", lambda *_: self._show_device(self.selected))
        menu = Gio.Menu()
        menu.append("Clone…", "win.clone")
        menu.append("Rename…", "win.rename")
        menu.append("Delete…", "win.delete")
        app_menu = Gio.Menu()
        app_menu.append(f"About {APP_NAME}", "win.about")
        menu.append_section(None, app_menu)
        self.menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Device menu")
        head.pack_end(self.menu_btn)
        head.pack_end(self.save_btn)
        head.pack_end(self.revert_btn)
        self.content_view.add_top_bar(head)
        self.content_page = Adw.NavigationPage(title="Device", child=self.content_view)
        self.split.set_content(self.content_page)

        for name, cb in (("clone", self._on_clone), ("rename", self._on_rename),
                         ("delete", self._on_delete), ("about", self._on_about)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

        self._update_banner()
        self.refresh()
        GLib.timeout_add_seconds(3, self._poll_running)

    # ================================================================= state
    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=5))

    def _update_banner(self) -> None:
        problems = []
        if self.ctx.sdk.root is None:
            problems.append("Android SDK not found (see README → Install the SDK)")
        else:
            if not self.caps.avdmanager_present:
                problems.append("SDK Command-line Tools missing")
            if not self.caps.emulator_present:
                problems.append("Emulator package missing")
            if self.ctx.sdk.image_count == 0:
                problems.append("no system images installed")
        host = self.ctx.host_report()
        blocking = [c for c in host.failed() if c.blocking]
        problems += [f"{c.name}: {c.detail}" for c in blocking]
        self.start_block_reason = "; ".join(f"{c.name}: {c.fix}" for c in blocking) or (
            "" if self.caps.emulator_present else "Emulator package is not installed")
        if problems:
            self.banner.set_title(GLib.markup_escape_text(" · ".join(problems)))
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    def refresh(self, select: str | None = None) -> None:
        def load():
            return self.ctx.devices.list()

        def done(devs):
            self.devices = devs
            self._running = {d.name for d in devs if d.running}
            self._rebuild_list(select or self.selected)

        run_async(load, done, self.toast)

    def _rebuild_list(self, select: str | None) -> None:
        while (row := self.listbox.get_row_at_index(0)) is not None:
            self.listbox.remove(row)
        target = None
        for d in self.devices:
            ram = d.config.get("hw.ramSize", "?")
            status = "Running" if d.running else "Stopped"
            api = d.system_image.split(" / ")[0]
            play = " · Play" if d.is_play_store_image else ""
            row = Adw.ActionRow(title=d.name, subtitle=f"{status} · {api}{play} · {ram} MB",
                                use_markup=False)
            row.set_tooltip_text(d.system_image)
            row.avd_name = d.name
            self.listbox.append(row)
            if d.name == select:
                target = row
        if not self.devices:
            self._show_empty()
        elif target is not None:
            self.listbox.select_row(target)
        else:
            self.listbox.select_row(self.listbox.get_row_at_index(0))

    def _poll_running(self) -> bool:
        try:
            now = self.ctx.backend.running_names()
        except Exception:  # never let the timer die
            return GLib.SOURCE_CONTINUE
        if now != self._running:
            self.refresh()
        return GLib.SOURCE_CONTINUE

    # ================================================================= content
    def _show_empty(self) -> None:
        self.selected = None
        self.editor = None
        page = Adw.StatusPage(title="No devices yet",
                              description="Create a Pixel or Galaxy-sized device with the + button.",
                              icon_name="list-add-symbolic")
        self.content_view.set_content(page)
        self.content_page.set_title("Devices")
        for w in (self.run_btn, self.save_btn, self.revert_btn, self.menu_btn):
            w.set_sensitive(False)

    def _on_row_selected(self, _lb, row) -> None:
        if row is None:
            return
        if self.editor and self.editor.changes() and row.avd_name != self.selected:
            self.toast(f"Unsaved changes to {self.selected} were discarded")
        self._show_device(row.avd_name)

    def _avd(self, name):
        return next((d for d in self.devices if d.name == name), None)

    def _show_device(self, name: str | None) -> None:
        avd = self._avd(name) if name else None
        if avd is None:
            self._show_empty()
            return
        self.selected = name
        self.editor = ConfigEditor(self.ctx.config, avd, self.caps)
        self.editor.connect("dirty-changed", lambda _e, dirty: self._set_dirty(dirty))
        self.content_view.set_content(self.editor)
        self.content_page.set_title(name)
        self.run_btn.set_label("Stop" if avd.running else "Start")
        self.run_btn.remove_css_class("suggested-action" if avd.running else "destructive-action")
        self.run_btn.add_css_class("destructive-action" if avd.running else "suggested-action")
        can_start = avd.running or not self.start_block_reason
        self.run_btn.set_sensitive(can_start)
        self.run_btn.set_tooltip_text(None if can_start else f"Cannot start: {self.start_block_reason}")
        self.menu_btn.set_sensitive(True)
        self._set_dirty(False)

    def _set_dirty(self, dirty: bool) -> None:
        self.save_btn.set_sensitive(dirty)
        self.revert_btn.set_sensitive(dirty)

    # ================================================================= actions
    def _on_new(self, *_):
        profiles = self.ctx.profiles.load_all()
        images = self.ctx.backend.list_system_images()
        if not images:
            self.toast("No system images installed — see README → Install the SDK")
        existing = {d.name for d in self.ctx.devices.list()}   # fresh from disk, not the cached list
        dlg = CreateDialog(profiles, images, self._do_create, existing_names=existing)
        dlg.present(self)

    def _do_create(self, name, profile, sdk_id, sdcard_mb):
        self.toast(f"Creating {name}…")

        def done(rep):
            lines = []
            if rep.applied:
                lines.append("Applied:\n• " + "\n• ".join(rep.applied))
            if rep.skipped:
                lines.append("Skipped:\n• " + "\n• ".join(rep.skipped))
            if rep.notes:
                lines.append("Notes:\n• " + "\n• ".join(rep.notes))
            dlg = Adw.AlertDialog(heading=f"Created {rep.name}", body="\n\n".join(lines))
            dlg.add_response("ok", "OK")
            dlg.present(self)
            self.refresh(select=rep.name)

        def failed(msg):
            dlg = Adw.AlertDialog(heading=f"Could not create {name}", body=msg)
            dlg.add_response("ok", "OK")
            dlg.present(self)
            self.refresh()

        run_async(lambda: self.ctx.devices.create(name, profile, sdk_id, sdcard_mb), done, failed)

    def _on_save(self, *_):
        if not self.editor:
            return
        destructive = self.editor.destructive_changes()
        if destructive:
            dlg = Adw.AlertDialog(heading="Confirm data loss",
                                  body="\n".join(s.warn for s in destructive))
            dlg.add_response("cancel", "Cancel")
            dlg.add_response("save", "Save anyway")
            dlg.set_response_appearance("save", Adw.ResponseAppearance.DESTRUCTIVE)
            dlg.connect("response", lambda _d, r: r == "save" and self._do_save())
            dlg.present(self)
        else:
            self._do_save()

    def _do_save(self):
        avd = self._avd(self.selected)
        changes = self.editor.changes()
        maker = self.ctx.backend.make_sdcard if self.ctx.backend.mksdcard else None

        def done(res):
            msg = f"Saved {len(res.changed)} change(s)"
            if res.backup:
                msg += f" · backup {res.backup.name}"
            self.toast(msg)
            for n in res.notes:
                self.toast(n)
            self.refresh(select=avd.name)

        run_async(lambda: self.ctx.config.save(avd, changes, self.caps, sdcard_maker=maker), done, self.toast)

    def _on_run_clicked(self, *_):
        name = self.selected
        avd = self._avd(name)
        if avd is None:
            return
        if avd.running:
            run_async(lambda: self.ctx.devices.stop(name),
                      lambda ok: (self.toast(f"Stop signal sent to {name}" if ok else f"{name} was not running"),
                                  self.refresh()), self.toast)
            return
        if self.editor and self.editor.changes():
            self.toast("Save or revert your changes first")
            return

        def done(rep):
            self.toast(f"Starting {name} — log: {rep.log_path.name}")
            for n in rep.notes:
                self.toast(n)
            GLib.timeout_add_seconds(2, lambda: (self.refresh(), GLib.SOURCE_REMOVE)[1])

        run_async(lambda: self.ctx.devices.start(name), done, self.toast)

    def _ask_name(self, heading: str, initial: str, verb: str, cb) -> None:
        entry = Gtk.Entry(text=initial, activates_default=True)
        dlg = Adw.AlertDialog(heading=heading, body="Letters, digits, '.', '_' or '-'.")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", verb)
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        entry.connect("changed", lambda e: dlg.set_response_enabled("ok", bool(AVD_NAME_RE.match(e.get_text()))))

        def on_resp(_d, r):
            if r == "ok":
                cb(entry.get_text())
        dlg.connect("response", on_resp)
        dlg.present(self)

    def _on_clone(self, *_):
        src = self.selected
        self._ask_name(f"Clone {src}", f"{src}_copy", "Clone",
                       lambda new: run_async(lambda: self.ctx.devices.clone(src, new),
                                             lambda _a: (self.toast(f"Cloned to {new}"), self.refresh(select=new)),
                                             self.toast))

    def _on_rename(self, *_):
        src = self.selected
        self._ask_name(f"Rename {src}", src, "Rename",
                       lambda new: run_async(lambda: self.ctx.devices.rename(src, new),
                                             lambda _r: (self.toast(f"Renamed to {new}"), self.refresh(select=new)),
                                             self.toast))

    def _on_delete(self, *_):
        name = self.selected
        dlg = Adw.AlertDialog(heading=f"Delete {name}?",
                              body="Deletes the device, its installed apps, data and SD card image. "
                                   "This cannot be undone.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_resp(_d, r):
            if r == "delete":
                run_async(lambda: self.ctx.devices.delete(name),
                          lambda _r: (self.toast(f"Deleted {name}"), self.refresh()), self.toast)
        dlg.connect("response", on_resp)
        dlg.present(self)

    def _on_about(self, *_):
        about = Adw.AboutDialog(application_name=APP_NAME, version=__version__, developer_name="Gus Salazar",
                                comments="Local-first front-end for Google's Android Emulator.\n"
                                         "No telemetry. Not affiliated with Google or Samsung.")
        notes = [f"SDK root: {self.ctx.sdk.root or 'not found'}",
                 f"Hardware catalog: {self.caps.hardware_catalog_path or 'not found'}",
                 f"Emulator flags detected: {len(self.caps.emulator_flags)}",
                 f"avdmanager device option: {'yes' if self.caps.avdmanager_device_flag else 'no'}"]
        notes += self.caps.notes
        about.set_debug_info("\n".join(notes))
        about.present(self)
