# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""'New device' dialog (Adw.Dialog, libadwaita 1.5).

Name handling (fix for v1.0.0 bug where the name stayed on the first profile):
- The name follows the selected profile until the user types their own.
- Auto names are made unique against existing devices (galaxy_a57_sized, galaxy_a57_sized_2, ...).
- Invalid or duplicate names are flagged inline and Create stays disabled.
"""
from __future__ import annotations

import re

from gi.repository import Adw, GLib, Gtk

from ..backends.legacy_sdk import AVD_NAME_RE


def unique_name(base: str, existing: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:56] or "device"
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


class CreateDialog(Adw.Dialog):
    def __init__(self, profiles, images, on_create, existing_names: set[str] | None = None):
        super().__init__(title="New device", content_width=520, content_height=600)
        self.profiles, self.images, self.on_create = profiles, images, on_create
        self.existing = set(existing_names or ())
        self._user_named = False
        self._programmatic = False

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.create_btn = Gtk.Button(label="Create")
        self.create_btn.add_css_class("suggested-action")
        self.create_btn.connect("clicked", self._create)
        header.pack_end(self.create_btn)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        self.g1 = Adw.PreferencesGroup(title="Device")
        self.profile_row = Adw.ComboRow(title="Profile", use_markup=False,
                                        model=Gtk.StringList.new([p.display_name for p in profiles]))
        self.g1.add(self.profile_row)
        self.name_row = Adw.EntryRow(title="Name", use_markup=False)
        self.g1.add(self.name_row)
        self.note_row = Adw.ActionRow(title="About this profile", use_markup=False)
        self.note_row.set_subtitle_lines(4)
        self.g1.add(self.note_row)
        page.add(self.g1)

        g2 = Adw.PreferencesGroup(title="System image",
                                  description="Installed images only. Images whose variant contains "
                                              "'playstore' include Google Play and cannot be rooted.")
        self.image_row = Adw.ComboRow(title="Image", use_markup=False,
                                      model=Gtk.StringList.new([i.label for i in images]))
        g2.add(self.image_row)
        self.sd_row = Adw.SpinRow.new_with_range(0, 65536, 128)
        self.sd_row.set_title("SD card (MB)")
        self.sd_row.set_subtitle("0 = no SD card")
        g2.add(self.sd_row)
        page.add(g2)

        view.set_content(page)
        self.set_child(view)

        # connect after widgets exist so the first _profile_changed() sees everything
        self.profile_row.connect("notify::selected", self._profile_changed)
        self.name_row.connect("changed", self._name_edited)
        if profiles:
            self._profile_changed()
        self._validate()

    # ------------------------------------------------------------------
    def _profile(self):
        i = self.profile_row.get_selected()
        return self.profiles[i] if 0 <= i < len(self.profiles) else None

    def _set_name(self, text: str) -> None:
        self._programmatic = True
        self.name_row.set_text(text)
        self._programmatic = False

    def _name_edited(self, *_):
        if not self._programmatic:
            # user typed; stop auto-naming unless they cleared the field
            self._user_named = bool(self.name_row.get_text())
        self._validate()

    def _profile_changed(self, *_):
        p = self._profile()
        if not p:
            return
        sub = p.label_note
        if p.hardware:
            hw = p.hardware
            sub += (f"\n{hw['screen_width_px']}×{hw['screen_height_px']} · {hw['screen_diagonal_in']} in · "
                    f"{p.physical_ppi():.0f} ppi → density {p.density()} · RAM {p.emulator_ram_mb()} MB")
        self.note_row.set_subtitle(sub)
        self.sd_row.set_value(p.defaults.get("sdcard_mb", 512))
        want = p.defaults.get("image_variant")
        if want:
            match = next((i for i, img in enumerate(self.images) if img.variant == want), None)
            if match is not None:
                self.image_row.set_selected(match)
        if not self._user_named:
            self._set_name(unique_name(p.id, self.existing))
        self._validate()

    def name_problem(self) -> str:
        name = self.name_row.get_text()
        if not name:
            return "Enter a name."
        if not AVD_NAME_RE.match(name):
            return "Use letters, digits, '.', '_' or '-' (max 63), starting with a letter or digit."
        if name in self.existing:
            return f"A device named '{name}' already exists. Choose another name."
        return ""

    def _validate(self, *_):
        problem = self.name_problem()
        if problem:
            self.name_row.add_css_class("error")
            self.g1.set_description(GLib.markup_escape_text(problem))
        else:
            self.name_row.remove_css_class("error")
            self.g1.set_description(None)
        self.create_btn.set_sensitive(not problem and bool(self.images) and bool(self.profiles))

    def _create(self, *_):
        if self.name_problem():
            return
        p = self._profile()
        img = self.images[self.image_row.get_selected()]
        self.create_btn.set_sensitive(False)
        self.on_create(self.name_row.get_text(), p, img.sdk_id, int(self.sd_row.get_value()))
        self.close()
