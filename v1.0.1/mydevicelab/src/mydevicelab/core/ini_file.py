# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
"""Order-preserving key=value file editor for AVD config.ini / <name>.ini.

These files are flat 'key=value' lines (no sections). Comments, blank lines and
unknown keys are preserved exactly. Writes are atomic (temp file + os.replace)
and an optional timestamped backup is made first.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


class IniFile:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lines: list[str] = []
        self._index: dict[str, int] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        self._lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        self._index = {}
        for i, line in enumerate(self._lines):
            key = self._key_of(line)
            if key is not None:
                self._index[key] = i  # last occurrence wins, same as a naive parser

    @staticmethod
    def _key_of(line: str) -> str | None:
        s = line.strip()
        if not s or s.startswith(("#", ";")) or "=" not in s:
            return None
        return s.split("=", 1)[0].strip()

    def get(self, key: str, default: str | None = None) -> str | None:
        i = self._index.get(key)
        if i is None:
            return default
        return self._lines[i].split("=", 1)[1].strip()

    def keys(self) -> list[str]:
        return list(self._index)

    def as_dict(self) -> dict[str, str]:
        return {k: self.get(k) for k in self._index}

    def set(self, key: str, value: str) -> None:
        if "\n" in key or "\n" in str(value) or "=" in key:
            raise ValueError("Keys/values must be single-line and keys must not contain '='")
        line = f"{key}={value}"
        if key in self._index:
            self._lines[self._index[key]] = line
        else:
            self._lines.append(line)
            self._index[key] = len(self._lines) - 1

    def remove(self, key: str) -> None:
        if key in self._index:
            del self._lines[self._index[key]]
            self._load_from_lines()

    def _load_from_lines(self) -> None:
        self._index = {}
        for i, line in enumerate(self._lines):
            k = self._key_of(line)
            if k is not None:
                self._index[k] = i

    def backup(self) -> Path | None:
        if not self.path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = self.path.with_name(f"{self.path.name}.{stamp}.bak")
        shutil.copy2(self.path, dest)
        return dest

    def save(self, make_backup: bool = True) -> Path | None:
        bak = self.backup() if make_backup else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self._lines) + "\n")
            if self.path.exists():
                shutil.copymode(self.path, tmp)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return bak
