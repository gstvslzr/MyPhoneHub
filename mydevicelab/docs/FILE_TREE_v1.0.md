# MyDeviceLab v1.0 — File tree

`[P1]` delivered in Phase 1 · `[P2]` delivered in Phase 2 · `[P3]`/`[P4]` planned.

```
mydevicelab/
├── README.md                              [P2]  setup + run (full version in P4)
├── docs/
│   ├── ARCHITECTURE_v1.0.md               [P1, updated P2 §10]
│   ├── FILE_TREE_v1.0.md                  [P2]
│   └── INTEGRATION_TEST_v1.0.md           [P2]  real-SDK checklist
├── schema/
│   └── device-profile.schema.json         [P1]
├── profiles/                              → /usr/share/mydevicelab/profiles/
│   ├── pixel/pixel_9.json, pixel_9_pro.json                       [P1]
│   └── galaxy/galaxy_s26_sized.json, galaxy_s26_ultra_sized.json,
│              galaxy_a57_sized.json                               [P1]
├── tools/
│   ├── validate_profiles_v1.0.py          [P1]
│   └── integration_probe_v1.0.sh          [P2]  read-only real-SDK probe
├── src/mydevicelab/
│   ├── __init__.py                        [P2]  version 1.0.0
│   ├── __main__.py                        [P2]  python3 -m mydevicelab
│   ├── paths.py                           [P2]  XDG dirs, SDK root candidates
│   ├── core/
│   │   ├── errors.py                      [P2]  typed errors
│   │   ├── process_runner.py              [P2]  argv-only, env allowlist, timeouts
│   │   ├── ini_file.py                    [P2]  order-preserving config.ini, .bak, atomic
│   │   └── host_check.py                  [P2]  CPU virt, KVM rw access, RAM, disk, Java
│   ├── backends/
│   │   ├── base.py                        [P2]  ToolBackend interface + data types
│   │   ├── legacy_sdk.py                  [P2]  avdmanager / emulator / mksdcard
│   │   └── android_cli.py                 [P2]  stub with reason (F2)
│   ├── services/
│   │   ├── settings_catalog.py            [P2]  every setting + its evidence
│   │   ├── profile_service.py             [P2]
│   │   ├── config_service.py              [P2]  availability rule, validate, save
│   │   ├── device_service.py              [P2]  create/clone/rename/delete/start/stop
│   │   ├── sdk_service.py                 [P2]  SDK location/status (install UI → P4)
│   │   ├── context.py                     [P2]  wiring + logging
│   │   ├── runtime_service.py             [P3]  console stop, snapshots, screenshots
│   │   ├── app_service.py                 [P3]  APK/split install, ABI scan
│   │   └── logcat_service.py              [P3]
│   └── ui/                                       GTK4 + libadwaita 1.5 API
│       ├── app.py                         [P2]  Adw.Application, CLI flags
│       ├── async_util.py                  [P2]  worker thread → main loop
│       ├── main_window.py                 [P2]  device list + detail + actions
│       ├── config_editor.py               [P2]
│       ├── create_dialog.py               [P2]
│       ├── app_manager.py                 [P3]
│       ├── runtime_panel.py               [P3]
│       ├── logcat_view.py                 [P3]
│       ├── sdk_manager.py                 [P4]
│       └── first_run_wizard.py            [P4]
├── tests/
│   ├── conftest.py, fake_sdk.py           [P2]  fake SDK that logs every call
│   ├── test_core.py                       [P2]  runner, ini, host checks
│   ├── test_services.py                   [P2]  profiles, backend, create, edit, run
│   ├── ui_smoke.py                        [P2]  headless GTK run + screenshots
│   └── test_app_service_abi.py            [P3]
└── packaging/                             [P4]  build_deb_v1.0.sh, debian/, .desktop, icon, man page
```

## Runtime locations (not in the package)

| Path | Contents | Removed by `apt remove`? |
|---|---|---|
| `~/.config/mydevicelab/` | settings.json, user profiles, per-device launch settings (0700) | No |
| `~/.local/share/mydevicelab/logs/` | app log (rotating) + one log per emulator start | No |
| `~/.android/avd/` | AVDs (Google default; `ANDROID_AVD_HOME` overrides) | No |
