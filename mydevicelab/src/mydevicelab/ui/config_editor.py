# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Per-device settings editor. Uses only libadwaita 1.5 widgets (Ubuntu 24.04 baseline)."""
from __future__ import annotations

from gi.repository import Adw, GLib, GObject, Gtk

from ..backends.base import AvdInfo, Capabilities

esc = GLib.markup_escape_text  # libadwaita parses titles/descriptions as Pango markup
from ..services.config_service import ConfigService
from ..services.settings_catalog import EVIDENCE_LABEL, GROUP_ORDER, SETTINGS, Setting


class ConfigEditor(Gtk.Box):
    __gsignals__ = {"dirty-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,))}

    def __init__(self, config: ConfigService, avd: AvdInfo, caps: Capabilities):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config, self.avd, self.caps = config, avd, caps
        self.original = config.read_values(avd)
        self.current: dict[str, object] = dict(self.original)
        self.rows: dict[str, Adw.PreferencesRow] = {}
        self._loading = True

        page = Adw.PreferencesPage()
        self.append(page)

        info = Adw.PreferencesGroup(title=esc(avd.name), description=esc(self._describe()))
        page.add(info)
        if avd.running:
            info.add(Adw.ActionRow(title="Device is running", use_markup=False,
                                   subtitle="Stop it to change settings. Launch settings apply at next start."))

        groups: dict[str, Adw.PreferencesGroup] = {}
        for g in GROUP_ORDER:
            groups[g] = Adw.PreferencesGroup(title=esc(g))
            page.add(groups[g])
        groups["Storage"].set_description("Hardware and storage changes are written to config.ini; "
                                          "a timestamped .bak copy is made first.")
        groups["Language & region"].set_description("Applied as emulator options at each start.")

        for s in SETTINGS:
            row = self._make_row(s)
            if row is not None:
                groups[s.group].add(row)
                self.rows[s.id] = row
        self._loading = False

    # --------------------------------------------------------------- helpers
    def _describe(self) -> str:
        cfg = self.avd.config
        parts = [self.avd.system_image]
        if cfg.get("hw.device.name"):
            parts.append(f"definition {cfg['hw.device.name']}")
        return " · ".join(parts)

    def _subtitle(self, s: Setting, available: bool, reason: str) -> str:
        bits = []
        if s.help:
            bits.append(s.help)
        if s.warn:
            bits.append("⚠ " + s.warn)
        if not available:
            bits.append("Unavailable: " + reason)
        bits.append(f"Source: {EVIDENCE_LABEL[s.evidence]}")
        return "\n".join(bits)

    def _make_row(self, s: Setting):
        av = self.config.availability(s, self.avd, self.caps)
        value = self.original.get(s.id)
        subtitle = self._subtitle(s, av.available, av.reason)
        editable = av.available and not (self.avd.running and s.store == "config")

        if s.kind == "bool":
            row = Adw.SwitchRow(title=s.label, subtitle=subtitle)
            row.set_active(bool(value))
            row.connect("notify::active", lambda r, _p, sid=s.id: self._changed(sid, r.get_active()))
        elif s.kind in ("int", "gb"):
            row = Adw.SpinRow.new_with_range(s.minimum, s.maximum, s.step)
            row.set_title(s.label)
            if value is None:
                row.set_subtitle("Not set — device default\n" + subtitle)
                row.set_value(s.minimum)
            else:
                row.set_subtitle(subtitle)
                row.set_value(int(value))
            row.connect("notify::value", lambda r, _p, sid=s.id: self._changed(sid, int(r.get_value())))
        elif s.kind == "choice":
            labels = list(s.choice_labels or s.choices)
            row = Adw.ComboRow(title=s.label, subtitle=subtitle, model=Gtk.StringList.new(labels))
            idx = s.choices.index(value) if value in s.choices else 0
            row.set_selected(idx)
            row.connect("notify::selected",
                        lambda r, _p, sid=s.id, ch=s.choices: self._changed(sid, ch[r.get_selected()]))
        else:
            row = Adw.EntryRow(title=s.label)
            row.set_text(str(value or ""))
            row.set_tooltip_text(subtitle)
            row.connect("changed", lambda r, sid=s.id: self._changed(sid, r.get_text().strip()))
        row.set_use_markup(False)
        row.set_sensitive(editable)
        return row

    def _changed(self, sid: str, value) -> None:
        if self._loading:
            return
        self.current[sid] = value
        self.emit("dirty-changed", bool(self.changes()))

    # --------------------------------------------------------------- public
    def changes(self) -> dict[str, object]:
        out = {}
        for sid, v in self.current.items():
            o = self.original.get(sid)
            if o is None and v in ("", False):
                continue
            if v != o:
                out[sid] = v
        return out

    def destructive_changes(self) -> list[Setting]:
        from ..services.settings_catalog import BY_ID
        return [BY_ID[sid] for sid in self.changes() if BY_ID[sid].destructive]
