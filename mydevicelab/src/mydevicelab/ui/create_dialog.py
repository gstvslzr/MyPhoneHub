# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""'New device' dialog (Adw.Dialog, libadwaita 1.5)."""
from __future__ import annotations

import re

from gi.repository import Adw, Gtk

from ..backends.legacy_sdk import AVD_NAME_RE


class CreateDialog(Adw.Dialog):
    def __init__(self, profiles, images, on_create):
        super().__init__(title="New device", content_width=520, content_height=560)
        self.profiles, self.images, self.on_create = profiles, images, on_create

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.create_btn = Gtk.Button(label="Create")
        self.create_btn.add_css_class("suggested-action")
        self.create_btn.connect("clicked", self._create)
        header.pack_end(self.create_btn)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        g1 = Adw.PreferencesGroup(title="Device")
        self.profile_row = Adw.ComboRow(title="Profile",
                                        model=Gtk.StringList.new([p.display_name for p in profiles]))
        self.profile_row.connect("notify::selected", self._profile_changed)
        g1.add(self.profile_row)
        self.name_row = Adw.EntryRow(title="Name")
        self.name_row.connect("changed", self._validate)
        g1.add(self.name_row)
        self.note_row = Adw.ActionRow(title="About this profile", use_markup=False)
        self.note_row.set_subtitle_lines(4)
        g1.add(self.note_row)
        page.add(g1)

        g2 = Adw.PreferencesGroup(title="System image",
                                  description="Installed images only. Images whose variant contains "
                                              "'playstore' include Google Play and cannot be rooted.")
        self.image_row = Adw.ComboRow(title="Image", model=Gtk.StringList.new([i.label for i in images]))
        g2.add(self.image_row)
        self.sd_row = Adw.SpinRow.new_with_range(0, 65536, 128)
        self.sd_row.set_title("SD card (MB)")
        self.sd_row.set_subtitle("0 = no SD card")
        g2.add(self.sd_row)
        page.add(g2)

        view.set_content(page)
        self.set_child(view)
        if profiles:
            self._profile_changed()
        self._validate()

    def _profile(self):
        i = self.profile_row.get_selected()
        return self.profiles[i] if 0 <= i < len(self.profiles) else None

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
        if not self.name_row.get_text():
            self.name_row.set_text(re.sub(r"[^A-Za-z0-9._-]", "_", p.id))

    def _validate(self, *_):
        ok_name = bool(AVD_NAME_RE.match(self.name_row.get_text()))
        if ok_name:
            self.name_row.remove_css_class("error")
        else:
            self.name_row.add_css_class("error")
        self.create_btn.set_sensitive(ok_name and bool(self.images) and bool(self.profiles))

    def _create(self, *_):
        p = self._profile()
        img = self.images[self.image_row.get_selected()]
        self.create_btn.set_sensitive(False)
        self.on_create(self.name_row.get_text(), p, img.sdk_id, int(self.sd_row.get_value()))
        self.close()
