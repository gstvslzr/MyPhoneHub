# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Gustavo Salazar
import json

import pytest

from fake_sdk import read_log
from mydevicelab.backends.legacy_sdk import LegacySdkBackend, validate_avd_name
from mydevicelab.core.errors import DeviceBusyError, ValidationError
from mydevicelab.core.ini_file import IniFile
from mydevicelab.services.config_service import parse_data_partition_gb, parse_size_mb
from mydevicelab.services.settings_catalog import BY_ID

PLAY35 = "system-images;android-35;google_apis_playstore;x86_64"
AOSP35 = "system-images;android-35;default;x86_64"


# ------------------------------------------------------------ profiles
def test_all_builtin_profiles_load(services):
    profs = services.profiles.load_all()
    assert {p.id for p in profs} == {"pixel_9", "pixel_9_pro", "galaxy_s26_sized",
                                     "galaxy_s26_ultra_sized", "galaxy_a57_sized"}
    assert services.profiles.errors == []


def test_user_profile_overrides_and_invalid_rejected(services, env):
    user = env.config_dir / "profiles"
    user.mkdir(parents=True)
    good = json.loads((services.profiles.builtin_dirs[0] / "pixel/pixel_9.json").read_text())
    good["display_name"] = "My Pixel 9"
    (user / "p9.json").write_text(json.dumps(good))
    (user / "bad.json").write_text(json.dumps({"id": "x"}))
    profs = {p.id: p for p in services.profiles.load_all()}
    assert profs["pixel_9"].display_name == "My Pixel 9" and not profs["pixel_9"].builtin
    assert any("bad.json" in e for e in services.profiles.errors)


def test_profile_math(services):
    p = services.profiles.get("galaxy_s26_ultra_sized")
    assert round(p.physical_ppi(), 2) == 498.01
    assert p.density() == 480
    assert p.emulator_ram_mb() == 8192


# ------------------------------------------------------------ backend
def test_capabilities_probe(services, env, monkeypatch):
    caps = services.backend.capabilities()
    assert caps.emulator_present and caps.avdmanager_present
    assert "-timezone" in caps.emulator_flags and "-change-locale" not in caps.emulator_flags
    assert not caps.avdmanager_device_flag
    assert "hw.cpu.ncore" in caps.hardware_keys
    monkeypatch.setenv("ANDROID_FAKE_DEVICE_FLAG", "1")
    monkeypatch.setenv("ANDROID_FAKE_LOCALE_FLAGS", "1")
    caps = services.backend.capabilities(refresh=True)
    assert caps.avdmanager_device_flag and "-change-locale" in caps.emulator_flags


def test_system_images_listed(services):
    ids = {i.sdk_id for i in services.backend.list_system_images()}
    assert ids == {PLAY35, AOSP35}


@pytest.mark.parametrize("bad", ["", "-rf", "a b", "../x", "x;rm", "a" * 64, "(x)"])
def test_bad_names_rejected(bad):
    with pytest.raises(ValidationError):
        validate_avd_name(bad)


def test_create_uses_only_documented_args(services, env):
    services.backend.create_avd("t1", PLAY35, 512, None)
    calls = [c for c in read_log(env.log) if c["tool"] == "avdmanager" and c["argv"][:2] == ["create", "avd"]
             and "--help" not in c["argv"]]
    assert calls[-1]["argv"] == ["create", "avd", "-n", "t1", "-k", PLAY35, "-c", "512M"]
    assert calls[-1]["stdin"] == "no\n"


# ------------------------------------------------------------ create from profiles
def test_create_galaxy_applies_hardware(services, env):
    p = services.profiles.get("galaxy_s26_sized")
    rep = services.devices.create("s26", p, PLAY35)
    cfg = IniFile(env.avd_home / "s26.avd" / "config.ini")
    assert cfg.get("hw.lcd.width") == "1080" and cfg.get("hw.lcd.height") == "2340"
    assert cfg.get("hw.lcd.density") == "400"
    assert cfg.get("hw.ramSize") == "8192"
    assert any("12288 MB on the real phone" in n for n in rep.notes)
    assert list((env.avd_home / "s26.avd").glob("config.ini.*.bak")), "backup must exist"


def test_create_galaxy_without_catalog_skips_unverified_keys(env, services):
    import shutil
    shutil.rmtree(env.sdk / "emulator/lib")
    services.backend._caps = None
    rep = services.devices.create("s26b", services.profiles.get("galaxy_s26_sized"), PLAY35)
    cfg = IniFile(env.avd_home / "s26b.avd" / "config.ini")
    assert cfg.get("hw.lcd.width") is None, "unverified key must not be written without evidence"
    assert cfg.get("hw.lcd.density") == "400" and cfg.get("hw.ramSize") == "8192"
    assert any("Screen width" in s for s in rep.skipped)


def test_create_pixel_without_device_flag_reports_skip(services):
    rep = services.devices.create("p9", services.profiles.get("pixel_9"), PLAY35)
    assert any("does not list a device option" in s for s in rep.skipped)
    assert not any("own device definition" in n for n in rep.notes), "report must not contradict itself"
    assert any("generic image defaults" in n for n in rep.notes)


def test_create_pixel_with_device_flag(services, env, monkeypatch):
    monkeypatch.setenv("ANDROID_FAKE_DEVICE_FLAG", "1")
    services.backend._caps = None
    rep = services.devices.create("p9", services.profiles.get("pixel_9"), PLAY35)
    assert IniFile(env.avd_home / "p9.avd/config.ini").get("hw.device.name") == "pixel_9"
    assert "Device definition: pixel_9" in rep.applied


def test_duplicate_name_rejected(services):
    services.devices.create("dup", services.profiles.get("galaxy_a57_sized"), PLAY35)
    with pytest.raises(ValidationError):
        services.devices.create("dup", services.profiles.get("galaxy_a57_sized"), PLAY35)


# ------------------------------------------------------------ config editing
def _mk(services, name="d1", sdk=PLAY35):
    services.devices.create(name, services.profiles.get("galaxy_a57_sized"), sdk)
    return services.devices.get(name)


def test_edit_ram_storage_cores_writes_backup(services, env):
    avd = _mk(services)
    caps = services.backend.capabilities()
    before = len(list(avd.avd_dir.glob("config.ini.*.bak")))
    res = services.config.save(avd, {"ram_mb": 4096, "data_gb": 16, "cpu_cores": 4}, caps)
    cfg = IniFile(avd.config_path)
    assert (cfg.get("hw.ramSize"), cfg.get("disk.dataPartition.size"), cfg.get("hw.cpu.ncore")) == ("4096", "16G", "4")
    assert res.backup is not None and res.backup.exists()
    assert len(list(avd.avd_dir.glob("config.ini.*.bak"))) == before + 1


def test_ram_clamped(services):
    avd = _mk(services)
    res = services.config.save(avd, {"ram_mb": 12288}, services.backend.capabilities())
    assert IniFile(avd.config_path).get("hw.ramSize") == "8192"
    assert any("clamped" in n for n in res.notes)


def test_refuses_while_running(services):
    avd = _mk(services)
    avd.running = True
    with pytest.raises(DeviceBusyError):
        services.config.save(avd, {"ram_mb": 4096}, services.backend.capabilities())


def test_sdcard_resize_recreates_image(services, env):
    avd = _mk(services)
    (avd.avd_dir / "sdcard.img").write_bytes(b"old data")
    res = services.config.save(avd, {"sdcard_mb": 256}, services.backend.capabilities(),
                               sdcard_maker=services.backend.make_sdcard)
    assert (avd.avd_dir / "sdcard.img").stat().st_size == 256 * 1024 * 1024
    assert any("previous contents deleted" in n for n in res.notes)


@pytest.mark.parametrize("sid,val", [("language", "Spanish"), ("country", "usa"),
                                     ("timezone", "Mars/Olympus"), ("netspeed", "6g"),
                                     ("ram_mb", "lots"), ("data_gb", 1000)])
def test_invalid_values_rejected(services, sid, val, monkeypatch):
    monkeypatch.setenv("ANDROID_FAKE_LOCALE_FLAGS", "1")
    services.backend._caps = None
    avd = _mk(services)
    with pytest.raises(ValidationError):
        services.config.save(avd, {sid: val}, services.backend.capabilities())


def test_locale_flags_require_probe(services, monkeypatch):
    avd = _mk(services)
    caps = services.backend.capabilities()
    with pytest.raises(ValidationError):
        services.config.save(avd, {"language": "es"}, caps)
    monkeypatch.setenv("ANDROID_FAKE_LOCALE_FLAGS", "1")
    caps = services.backend.capabilities(refresh=True)
    services.config.save(avd, {"language": "es", "country": "US", "locale": "es-US",
                               "timezone": "America/New_York"}, caps)
    flags, notes = services.config.launch_flags(services.devices.get("d1"), caps)
    assert flags[flags.index("-change-language") + 1] == "es"
    assert flags[flags.index("-timezone") + 1] == "America/New_York"
    assert any("Play Store" in n for n in notes)


def test_start_builds_argv_and_logs(services, env):
    _mk(services)
    services.config.save(services.devices.get("d1"), {"no_boot_anim": True, "netspeed": "lte"},
                         services.backend.capabilities())
    rep = services.devices.start("d1")
    assert rep.argv[1:3] == ["-avd", "d1"] and "-no-boot-anim" in rep.argv
    assert rep.argv[rep.argv.index("-netspeed") + 1] == "lte"


def test_clone_rename_delete(services, env):
    avd = _mk(services)
    (avd.avd_dir / "snapshots").mkdir()
    (avd.avd_dir / "multiinstance.lock").write_text("")
    services.config.save(avd, {"netspeed": "edge"}, services.backend.capabilities())
    c = services.devices.clone("d1", "d2")
    assert not (c.avd_dir / "snapshots").exists() and not (c.avd_dir / "multiinstance.lock").exists()
    assert IniFile(c.config_path).get("AvdId") == "d2"
    assert services.config.read_launch("d2")["netspeed"] == "edge"
    services.devices.rename("d2", "d3")
    assert services.config.read_launch("d3")["netspeed"] == "edge"
    services.devices.delete("d3")
    assert {a.name for a in services.devices.list()} == {"d1"}


def test_running_detection_from_proc(env, tmp_path):
    proc = tmp_path / "fakeproc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242/cmdline").write_bytes(b"/opt/sdk/emulator/qemu/linux-x86_64/qemu-system-x86_64\0-avd\0d1\0")
    (proc / "99").mkdir()
    (proc / "99/cmdline").write_bytes(b"/usr/bin/vim\0-avd\0d9\0")
    b = LegacySdkBackend(env.sdk, env.avd_home, proc_root=proc)
    assert b.running_names() == {"d1"}


def test_size_parsers():
    assert parse_size_mb("6G") == 6144 and parse_size_mb("512M") == 512 and parse_size_mb("4096") == 4096
    assert parse_data_partition_gb("6G") == 6 and parse_data_partition_gb(str(6 * 1024 ** 3)) == 6


def test_every_setting_has_evidence():
    assert all(s.evidence in {"official_docs", "aosp_sample", "google_blog", "unverified"} for s in BY_ID.values())
