# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
import stat

import pytest

from mydevicelab.core.errors import ToolFailedError, ToolNotFoundError, ToolTimeoutError
from mydevicelab.core.host_check import run_host_checks
from mydevicelab.core.ini_file import IniFile
from mydevicelab.core.process_runner import ProcessRunner, build_env


# ------------------------------------------------------------ ProcessRunner
def test_env_is_scrubbed(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak-me")
    monkeypatch.setenv("ANDROID_SDK_ROOT", "/x")
    env = build_env()
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env["ANDROID_SDK_ROOT"] == "/x"


def test_no_shell_interpretation(tmp_path):
    marker = tmp_path / "pwned"
    r = ProcessRunner().run(["/bin/echo", f"; touch {marker}"])
    assert not marker.exists()
    assert f"; touch {marker}" in r.stdout


def test_nonzero_exit_raises():
    with pytest.raises(ToolFailedError) as ei:
        ProcessRunner().run(["/bin/sh", "-c", "echo boom >&2; exit 3"])
    assert ei.value.returncode == 3 and "boom" in ei.value.stderr


def test_timeout_kills():
    with pytest.raises(ToolTimeoutError):
        ProcessRunner().run(["/bin/sleep", "5"], timeout=0.5)


def test_missing_tool():
    with pytest.raises(ToolNotFoundError):
        ProcessRunner().run(["/nonexistent/avdmanager", "list"])


# ------------------------------------------------------------ IniFile
def test_ini_preserves_unknown_lines_and_order(tmp_path):
    p = tmp_path / "config.ini"
    p.write_text("# comment\nhw.ramSize=2048\nweird line\nhw.keyboard=yes\n")
    ini = IniFile(p)
    ini.set("hw.ramSize", "4096")
    ini.set("hw.cpu.ncore", "4")
    bak = ini.save()
    assert p.read_text() == "# comment\nhw.ramSize=4096\nweird line\nhw.keyboard=yes\nhw.cpu.ncore=4\n"
    assert bak and bak.read_text() == "# comment\nhw.ramSize=2048\nweird line\nhw.keyboard=yes\n"


def test_ini_rejects_newline_injection(tmp_path):
    ini = IniFile(tmp_path / "c.ini")
    with pytest.raises(ValueError):
        ini.set("hw.ramSize", "1\nhw.evil=1")


def test_ini_keeps_file_mode(tmp_path):
    p = tmp_path / "c.ini"
    p.write_text("a=1\n")
    p.chmod(0o600)
    ini = IniFile(p)
    ini.set("a", "2")
    ini.save(make_backup=False)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


# ------------------------------------------------------------ host checks
def test_host_check_uses_access_not_group(tmp_path):
    kvm = tmp_path / "kvm"
    kvm.write_text("")
    kvm.chmod(0o600)  # owned by us -> rw, though we are not in any 'kvm' group
    cpu = tmp_path / "cpuinfo"
    cpu.write_text("flags\t: fpu vmx sse\n")
    mem = tmp_path / "meminfo"
    mem.write_text("MemAvailable:   20000000 kB\n")
    rep = run_host_checks(tmp_path, kvm_device=kvm, cpuinfo=cpu, meminfo=mem)
    by = {c.name: c for c in rep.checks}
    assert by["KVM access"].ok
    assert by["CPU virtualization"].ok


def test_host_check_blocks_without_virt(tmp_path):
    cpu = tmp_path / "cpuinfo"
    cpu.write_text("flags\t: fpu sse\n")
    rep = run_host_checks(tmp_path, kvm_device=tmp_path / "nokvm", cpuinfo=cpu, meminfo=tmp_path / "m")
    assert not rep.ready
    assert {c.name for c in rep.failed()} >= {"CPU virtualization", "KVM device"}
