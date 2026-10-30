# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""GTK4 UI. Declares GI versions before any submodule imports Gtk/Adw."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
