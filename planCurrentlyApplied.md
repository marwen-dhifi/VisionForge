# VisionForge — Current Implementation (as of 2026-05-07)

This document describes exactly what is implemented right now, how every piece works,
and what remains broken. It is the single source of truth for the next developer session.

---

## 1. Repository Layout

```
VisionForge/
├── app/
│   ├── core/
│   │   ├── camera_client.py        real ZMQ camera client (QThread)
│   │   └── arm_controller.py       real xArm SDK wrapper (QThread)
│   ├── plugin_sdk/
│   │   ├── __init__.py             public re-exports + __version__ = "1.0.0"
│   │   ├── base.py                 TaskPanel + TaskProcessor ABCs
│   │   ├── manifest.py             PluginManifest dataclass + load_manifest()
│   │   ├── loader.py               PluginLoader + get_plugin_loader() singleton
│   │   ├── utils.py                save_frame(), resolve_path()
│   │   └── dev_runner.py           standalone plugin runner CLI
│   ├── styles/
│   │   └── theme.py                global dark stylesheet
│   ├── widgets/
│   │   ├── camera_config.py        CameraConfigPanel — live camera param editor
│   │   ├── arm_panel.py            _ControlPanel — arm status + controls
│   │   └── status_indicator.py     StatusIndicator — pulsing dot + state label
│   ├── tasks/                      5 built-in hardcoded task panels
│   ├── main_window.py              MainWindow — hosts stack + sidebar + plugins
│   ├── splash.py                   SplashScreen — boots hardware, scans plugins
│   └── connection_dialog.py        startup IP entry
├── plugins/
│   └── example_difference/         reference plugin (frame-difference detector)
│       ├── plugin.json
│       ├── panel.py                DifferencePanel
│       └── processor.py            DifferenceProcessor
├── tools/
│   └── build_sdk_zip.py            produces dist/visionforge-sdk-<version>.zip
├── dist/                           build output (zip files)
└── requirements-sdk.txt            minimal deps for plugin developers
```

The second folder at `VisionFroge-sdk\` (note the typo — it is a working copy of the
SDK zip, not the source of truth). **Always edit files inside `VisionForge\`**.
To push changes to the SDK, re-run `python tools/build_sdk_zip.py`.

---

## 2. Platform Boot Sequence

```
main.py
  └─ QApplication + SplashScreen
       ├─ ConnectionDialog   → user types camera IP + arm IP
       ├─ CameraClient.start()
       ├─ ArmController.start()
       ├─ _on_loader_finished()
       │    └─ get_plugin_loader().scan()   ← discovers plugins/
       └─ MainWindow(camera, arm)
            ├─ 5 built-in task panels added to QStackedWidget (indices 0–4)
            ├─ Plugin loop: for each PluginDescriptor → panel.on_attach() → addWidget (5+)
            ├─ Sidebar(plugin_items=[...])  ← built after plugin indices are known
            └─ show()
```

**Camera reconnect** (`_reconnect_camera`): stop thread → wait for `finished` → start again.
After reconnect, `_attach_camera(cam)` is called on every built-in panel AND every plugin panel.

**Arm reconnect** (`_reconnect_arm`): same stop/wait/start pattern.
After reconnect, `_attach_arm(arm)` is called on every built-in panel AND every plugin panel.

**Close** (`closeEvent`): calls `panel.cleanup()` on all built-in panels + all plugin panels,
then `camera.cleanup()`, then `arm.cleanup()`.

---

## 3. Hardware Clients

### CameraClient (`app/core/camera_client.py`)

- Runs as a `QThread`. Subscribes to two ZMQ PUB sockets on the camera IP:
  - Port 5555 — JPEG frames
  - Port 5556 — metadata (FPS, resolution, exposure, gain, white balance)
- Key signals:
  - `raw_frame_received(np.ndarray, dict)` — emits every decoded frame (RGB HxWx3)
  - `connection_changed(bool)` — True when first frame received, False on disconnect
  - `fps_updated(float)`, `resolution_updated(int, int)`
- `send_params(dict)` — sends camera parameters back to the server over a REQ socket
- `cleanup()` — stops thread, disconnects ZMQ sockets

### ArmController (`app/core/arm_controller.py`)

- Runs as a `QThread`. Wraps the xArm Python SDK (`xarm.wrapper.XArmAPI`).
- A `threading.Lock` guards every SDK call across threads.
- Key signals:
  - `connection_changed(bool)`, `enabled_changed(bool)`
  - `position_updated(x, y, z, roll, pitch, yaw)` — emitted every 100ms from the poll loop
  - `error_occurred(str)`
  - `scan_state_changed(bool)` — True = valve scan running
- Key methods:
  - `get_position()` → `(code, [x,y,z,roll,pitch,yaw])` — uses 1s lock timeout
  - `send_servo_cartesian(pose, mvvelo, mvacc)` — servo mode (mode=1), 50ms lock timeout
  - `go_initial_start/stop()`, `go_zero_start/stop()`, `reset_arm()`
  - `start_valve_scan(pos, amplitude_mm, speed_mmps)` / `stop_valve_scan()` — position mode
  - `get_arm()` → raw `XArmAPI` object (used for poll-based state checks)
- Startup sequence (in `run()`): connect → `motion_enable(True)` → `set_mode(1)` → `set_state(0)`
  Then polls `get_position()` every 100ms, emits `position_updated`, breaks on 5 consecutive errors.

**Arm modes:**
- Mode 0 = position mode — `set_position()` commands with `wait=` flag, blocking or non-blocking.
  Used by `start_valve_scan` and `go_initial_start/go_zero_start`.
- Mode 1 = servo mode — `set_servo_cartesian()` commands, intended for high-frequency (~100Hz)
  direct servo control. Used by `send_servo_cartesian`.

---

## 4. Plugin SDK

### `base.py` — TaskProcessor

Background CV worker running in a `QThread`.

- **Queue**: `queue.Queue(maxsize=1)` — always holds the most recent frame only.
  Old frames are dropped. The processor never falls behind the camera.
- `submit_frame(frame, meta)` — called from the UI thread when a new frame arrives.
  Atomically drops the old queued frame and puts the new one. Non-blocking.
- `run()` — default loop: `queue.get(timeout=0.1)` → `process_frame(frame, meta)`.
  Exceptions in `process_frame` are printed to stderr; the loop continues.
- `stop(timeout_ms=3000)` — sets `_running = False`, waits for thread.
- **Signals**: `display_ready(QImage)`, `result_ready(object)`.
- **Abstract**: `process_frame(frame_rgb, meta)` — subclass must implement.

### `base.py` — TaskPanel

Plugin UI widget (`QWidget`).

- Constructor: `__init__(camera_client=None, arm_controller=None, parent=None)`.
  Stores `self._cam`, `self._arm`, `self._processor = None`.
- **`on_attach()`** — must be implemented by subclass. Build UI, create processor,
  connect processor signals. Called once by `dev_runner` or `MainWindow`.
- **`showEvent`** — connects `self._cam.raw_frame_received → self._processor.submit_frame`
  and starts the processor (if not running). Automatic — subclass does not need to call.
- **`hideEvent`** — disconnects `raw_frame_received → submit_frame`. Automatic.
- **`attach_camera(cam)`** / **`attach_arm(arm)`** — called by MainWindow on reconnect.
- **`cleanup()`** — disconnects signal, calls `self._processor.stop()`.
  Subclass must call `super().cleanup()`.

**Guard rule**: `self._cam` and `self._arm` may be `None` if hardware was not connected
at platform startup. Always guard: `if self._cam:` before using. In `dev_runner` both
are guaranteed non-None because `--camera` and `--arm` are required CLI arguments.

### `manifest.py` — PluginManifest

Frozen dataclass. Fields: `name`, `label`, `icon`, `version`, `panel_module`,
`panel_class`, `description` (optional), `plugin_dir` (set at load time).

`load_manifest(plugin_dir)` reads `plugin.json`, raises `FileNotFoundError` or `ValueError`
on invalid manifests.

### `loader.py` — PluginLoader

- Default `plugins_root`: `repo_root/plugins/` (resolved from `__file__` path).
- `scan()`: idempotent. Iterates `plugins/` alphabetically. Skips non-dirs, dot/underscore
  entries, and dirs without `plugin.json`. Calls `_load_one()` for each candidate.
- `_load_one()`: loads manifest → adds plugin dir to `sys.path` → imports panel module via
  `importlib.util.spec_from_file_location` → resolves panel class → validates it subclasses
  `TaskPanel` → appends `PluginDescriptor`. Any exception prints to stderr and skips the plugin.
  **Platform never crashes due to a broken plugin.**
- `get_plugin_loader()` → module-level singleton.

### `utils.py`

- `save_frame(frame_rgb, filepath)` — creates parent dirs, converts RGB→BGR, `cv2.imwrite`.
- `resolve_path(plugin_file, relative_path)` → absolute path of `relative_path` relative to
  the directory containing `plugin_file`. Usage: `WEIGHTS = resolve_path(__file__, "model.pt")`.

---

## 5. dev_runner

**Command:**
```
python -m VisionForge.app.plugin_sdk.dev_runner <plugin_dir> --camera IP --arm IP
```

Both `--camera` and `--arm` are **required**. Plugins always run against real hardware.

**Optional flags:**
- `--no-status` — hide the hardware status monitor window
- `--no-config`  — hide the camera configuration window

**Startup sequence:**
1. Validate `plugin_dir` exists.
2. Load `plugin.json` via `load_manifest()`.
3. Create `QApplication`, apply `theme.py` stylesheet.
4. Create `CameraClient(args.camera)` + `ArmController(args.arm)`, call `.start()` on both.
5. Build and show the **status monitor window** (unless `--no-status`).
6. Build and show the **camera config window** (unless `--no-config`).
7. Import the panel module via `importlib`.
8. Instantiate `PanelClass(camera_client=camera, arm_controller=arm)`, call `on_attach()`.
9. Wrap panel in `QMainWindow`, title = `[dev] <label> — VisionForge Plugin Runner`, show maximized.
10. `closeEvent`: `panel.cleanup()` → `camera.cleanup()` → `arm.cleanup()` → close both helper windows.

### Status Monitor Window (`_build_status_window`)

Floating `QWidget` (300×560, `WindowStaysOnTopHint`). Two cards:

**Camera card:**
- Pulsing `_Dot` widget (12px, 30ms tick, same visual as `status_indicator.py` in the platform).
- Status label: `"Connecting…"` (orange) → `"Connected"` (green, pulsing) or `"Disconnected"` (red).
- `"Reconnect"` button — visible only when disconnected. Clicks: stop thread → wait `finished` →
  restart. Same logic as `MainWindow._reconnect_camera`.
- FPS and Resolution readouts (updated via `fps_updated`, `resolution_updated` signals).

**xArm card:**
- Pulsing `_Dot` + status label + `"Reconnect"` button (same pattern as camera).
- `"Reset Arm"` button — calls `arm.reset_arm()` + polls state 600ms later.
- 6 position readouts: X, Y, Z, Roll, Pitch, Yaw (updated via `arm.position_updated` signal).
- State is **poll-based** via `QTimer` at 1000ms calling `_poll_arm()`:
  - `arm.get_arm()` returns the raw `XArmAPI` object.
  - `raw.connected == False` → state = `"disconnected"` (red dot, reconnect button visible).
  - `raw.error_code != 0`   → state = `"not_enabled"` (orange dot, reset button enabled).
  - Otherwise               → state = `"ready"` (green dot, reset button enabled).
  - State change is only re-applied when it differs from the previous state (avoids UI flicker).

### Camera Configuration Window (`_build_config_window`)

Floating `QWidget` (400×660, `WindowStaysOnTopHint`). Imports
`CameraConfigPanel` from `VisionForge.app.widgets.camera_config` and wires it
to the live `CameraClient`. Provides identical controls to the main platform:

- Acquisition FPS slider
- Exposure (auto toggle + manual slider)
- Gain (auto toggle + manual slider)
- White Balance (auto toggle + apply-once button)
- Auto-Brightness Target slider

All sliders use a 300ms debounce timer before calling `camera.send_params()`.

---

## 6. SDK Zip (`tools/build_sdk_zip.py`)

Run: `python tools/build_sdk_zip.py [--version X.Y.Z]`

Output: `dist/visionforge-sdk-<version>.zip`

**What is bundled:**

```
visionforge-sdk-1.0.0/
├── VisionForge/
│   ├── __init__.py
│   └── app/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── camera_client.py      verbatim from repo
│       │   └── arm_controller.py     verbatim from repo
│       ├── styles/
│       │   ├── __init__.py
│       │   └── theme.py              verbatim from repo
│       ├── widgets/
│       │   ├── __init__.py
│       │   └── camera_config.py      verbatim from repo  ← for dev_runner config window
│       └── plugin_sdk/
│           ├── __init__.py
│           ├── base.py
│           ├── manifest.py
│           ├── loader.py
│           ├── utils.py
│           └── dev_runner.py
├── plugins/
│   └── example_difference/
│       ├── plugin.json
│       ├── panel.py
│       ├── processor.py
│       └── README.md
├── requirements-sdk.txt
├── run.bat                           python -m VisionForge.app.plugin_sdk.dev_runner %*
└── run.sh                            python3 -m VisionForge.app.plugin_sdk.dev_runner "$@"
```

Files are copied **verbatim from the repo at build time**. The zip is a snapshot.
After every change to a source file in `VisionForge/`, re-run the build script.

---

## 7. Reference Plugin: `plugins/example_difference/`

`DifferenceProcessor` (subclasses `TaskProcessor`):
- Converts frames to grayscale, computes `cv2.absdiff` vs previous frame.
- Applies threshold mask, calculates motion percentage.
- Overlays red highlight on moving regions, emits `display_ready(QImage)` and `result_ready(dict)`.

`DifferencePanel` (subclasses `TaskPanel`):
- `on_attach()`: builds two-column layout (feed left, info right).
  Connects `display_ready` → feed label, `result_ready` → motion percentage label.
  Also connects `arm.position_updated` and `arm.connection_changed` to show live TCP position.
- Click on the feed or "Save frame" button → saves current QLabel pixmap to `captures/`.
- `cleanup()`: disconnects arm signals, then calls `super().cleanup()`.
- The base class `showEvent`/`hideEvent` automatically manages camera→processor connection.

---

## 8. Plugin Development Workflow (summary)

1. Copy or create a plugin folder under `plugins/` with `plugin.json`, `panel.py`, `processor.py`.
2. Test with dev_runner against real hardware:
   ```
   python -m VisionForge.app.plugin_sdk.dev_runner plugins/my_plugin \
       --camera 192.168.1.100 --arm 192.168.1.200
   ```
3. Three windows open: the plugin panel (maximized), the status monitor, the camera config.
4. When done, run `python tools/build_sdk_zip.py` to update the SDK zip.
5. Copy the new zip to the SDK deployment folder (e.g., `VisionForge-sdk/`).
6. Drop the plugin folder into `plugins/` of the target deployment; the platform loads it automatically on next launch.

---

## 9. Known Bug — Arm Movement in arm_spin Plugin (MUST REVISIT)

### What the plugin does

`arm_spin` (in `plugins/arm_spin/` and mirrored in `VisionForge-sdk/plugins/arm_spin/`) is
a tutorial plugin that is supposed to move the arm in a sinusoidal Y-axis oscillation of
±60mm at 0.3Hz from the arm's current position, while the camera feed is displayed.

### Current implementation

`_start_arm()` reads the current position with `self._arm.get_position()`, saves it as
`self._center_pos`, then starts a background `threading.Thread` running `_motion_loop()`.

`_motion_loop()` (runs in background thread at ~20Hz / STEP_S=0.05s):
```python
while not self._stop_event.is_set():
    t       = time.monotonic() - start
    y_delta = AMPLITUDE_MM * math.sin(2 * math.pi * FREQUENCY_HZ * t)
    pose    = list(self._center_pos)
    pose[1] += y_delta
    ok = self._arm.send_servo_cartesian(pose, mvvelo=200)
    time.sleep(STEP_S)
```

### What is broken

`ok` is always `True`, the command is received and logged, the math is correct, but the
arm **does not physically move**.

### Root cause hypothesis

`ArmController.send_servo_cartesian()` calls `xarm.set_servo_cartesian()` which is a
**servo mode** (mode=1) command. Servo mode is designed for **high-frequency** (~100Hz)
direct joint control. At 20Hz the arm controller may silently accept but not execute
the commands because the command rate is too low for the servo interpolator to track.

The pattern that **is proven to work** on this robot is `start_valve_scan()`, which uses
**position mode** (mode=0) and `set_position(..., wait=False)` with a polling loop to
wait for motion completion before issuing the next command.

### How to fix (next session)

Add a new method to `ArmController` that mirrors `start_valve_scan` but oscillates in
the Y axis instead of Z:

```python
def start_y_oscillation(self, pos: list, amplitude_mm: float, speed_mmps: float):
    """Oscillate ±amplitude_mm in the Y axis around pos using position mode."""
    ...  # same structure as start_valve_scan but swaps z_top/z_bot for y_top/y_bot

def stop_y_oscillation(self):
    ...  # same as stop_valve_scan
```

Then update `arm_spin/panel.py` to call `self._arm.start_y_oscillation(...)` and
`self._arm.stop_y_oscillation()` instead of the background thread approach.

After testing, rebuild the SDK zip so the fix propagates to `VisionForge-sdk/`.
