# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_sdk import build_fake_sdk  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake SDK + isolated AVD/config/log dirs. Returns a namespace of paths."""
    sdk = build_fake_sdk(tmp_path / "sdk")
    avd_home = tmp_path / "home" / ".android" / "avd"
    avd_home.mkdir(parents=True)
    log = tmp_path / "fake-calls.jsonl"
    monkeypatch.setenv("ANDROID_FAKE_LOG", str(log))
    monkeypatch.setenv("ANDROID_AVD_HOME", str(avd_home))
    for v in ("ANDROID_FAKE_DEVICE_FLAG", "ANDROID_FAKE_LOCALE_FLAGS", "ANDROID_FAKE_FAIL_CREATE"):
        monkeypatch.delenv(v, raising=False)

    class NS:
        pass
    ns = NS()
    ns.tmp, ns.sdk, ns.avd_home, ns.log = tmp_path, sdk, avd_home, log
    ns.config_dir = tmp_path / "config"
    ns.log_dir = tmp_path / "logs"
    ns.empty_proc = tmp_path / "proc"
    ns.empty_proc.mkdir()
    return ns


@pytest.fixture
def services(env):
    from mydevicelab.backends.legacy_sdk import LegacySdkBackend
    from mydevicelab.services.config_service import ConfigService
    from mydevicelab.services.device_service import DeviceService
    from mydevicelab.services.profile_service import ProfileService

    backend = LegacySdkBackend(env.sdk, env.avd_home, proc_root=env.empty_proc)
    profiles = ProfileService(ROOT / "schema/device-profile.schema.json", [ROOT / "profiles"],
                              env.config_dir / "profiles")
    config = ConfigService(env.config_dir / "devices")
    devices = DeviceService(backend, config, env.log_dir)

    class S:
        pass
    s = S()
    s.backend, s.profiles, s.config, s.devices = backend, profiles, config, devices
    return s
