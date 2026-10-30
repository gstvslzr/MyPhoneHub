# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Adw.Application entry point."""
from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from .. import APP_ID, paths  # noqa: E402
from ..services.context import build_context, setup_logging  # noqa: E402


class MyDeviceLabApp(Adw.Application):
    def __init__(self, sdk_root: str | None = None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.sdk_root = sdk_root
        self.window = None

    def do_activate(self):
        if self.window is None:
            from .main_window import MainWindow
            self.window = MainWindow(self, build_context(self.sdk_root))
        self.window.present()


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="mydevicelab")
    ap.add_argument("--sdk-root", help="Android SDK folder (overrides settings and environment)")
    ap.add_argument("--verbose", action="store_true", help="debug logging")
    ap.add_argument("--version", action="store_true")
    args, rest = ap.parse_known_args(argv if argv is not None else sys.argv[1:])
    if args.version:
        from .. import __version__
        print(f"MyDeviceLab {__version__}")
        return 0
    paths.ensure_private_dirs()
    setup_logging(verbose=args.verbose)
    if Adw.get_minor_version() < 5:
        print("MyDeviceLab needs libadwaita 1.5 or newer (Ubuntu 24.04+).", file=sys.stderr)
        return 1
    return MyDeviceLabApp(args.sdk_root).run([sys.argv[0], *rest])
