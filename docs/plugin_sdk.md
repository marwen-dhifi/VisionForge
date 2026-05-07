# VisionForge Plugin SDK

Developer guide for building new task panels that integrate seamlessly into the VisionForge platform.

---

## Overview

The Plugin SDK lets you write a new vision/robotics task and deploy it to VisionForge without touching any platform code. You write two Python files and a JSON manifest, drop them in `plugins/`, and the platform discovers them automatically at startup.

Your plugin receives the **real** `CameraClient` and `ArmController` objects — the exact same hardware interfaces used by all built-in tasks. No abstractions, no wrappers, no simulation layer.

---

## Prerequisites

- Python 3.10+
- Real Baumer VAX-50C camera running the ZMQ server (ports 5555 / 5556)
- Real UFACTORY xArm5 with xArm Python SDK installed
- Dependencies: `pip install -r requirements-sdk.txt`

---

## Getting started

### 1 — Get the SDK

```
unzip visionforge-sdk-1.0.0.zip
cd visionforge-sdk-1.0.0
pip install -r requirements-sdk.txt
```

### 2 — Copy the template

```powershell
xcopy plugins\example_difference plugins\my_plugin /E /I
```

Edit `plugins\my_plugin\plugin.json` — set `name`, `label`, `icon`, `panel_class`.

### 3 — Write your processor

```python
# plugins/my_plugin/processor.py
from VisionForge.app.plugin_sdk import TaskProcessor

class MyProcessor(TaskProcessor):
    def process_frame(self, frame_rgb, meta):
        # frame_rgb: HxWx3 uint8 RGB numpy array — real camera data
        # do your CV work here (runs in background QThread)
        self.display_ready.emit(qimg)     # annotated QImage for the feed
        self.result_ready.emit(my_data)   # any Python object to the panel
```

### 4 — Write your panel

```python
# plugins/my_plugin/panel.py
from VisionForge.app.plugin_sdk import TaskPanel
from processor import MyProcessor

class MyPanel(TaskPanel):
    def on_attach(self):
        self._processor = MyProcessor()
        self._processor.display_ready.connect(self._on_display)
        # build your Qt UI here
        # self._cam  → real CameraClient
        # self._arm  → real ArmController (may be None if not connected)

    def cleanup(self):
        super().cleanup()   # stops processor + disconnects camera signal
```

### 5 — Test with real hardware

```powershell
python -m VisionForge.app.plugin_sdk.dev_runner plugins\my_plugin `
    --camera 192.168.1.100 `
    --arm    192.168.1.200
```

A full-size window opens with your panel connected to live hardware. Close it to stop.

### 6 — Deploy to VisionForge

```powershell
xcopy plugins\my_plugin  ..\VisionForge\plugins\my_plugin  /E /I
python ..\VisionForge\main.py
```

Your plugin appears in the sidebar Tasks group automatically.

---

## plugin.json reference

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Unique slug — no spaces. Used as module key. |
| `label` | string | yes | Sidebar button text. |
| `icon` | string | yes | Single Unicode glyph (◈ ⬡ ◉ etc.). |
| `version` | string | yes | Semantic version string. |
| `panel_module` | string | yes | Python filename without `.py` (e.g. `"panel"`). |
| `panel_class` | string | yes | Class name in that module (must subclass `TaskPanel`). |
| `description` | string | no | Human-readable summary. |

Full example:

```json
{
    "name":         "my_plugin",
    "label":        "My Task",
    "icon":         "◈",
    "version":      "1.0.0",
    "panel_module": "panel",
    "panel_class":  "MyPanel",
    "description":  "Does something useful."
}
```

---

## TaskProcessor API

```python
class TaskProcessor(QThread):
    display_ready = Signal(QImage)    # emit annotated frame for feed widget
    result_ready  = Signal(object)    # emit any per-frame result

    def submit_frame(self, frame, meta=None): ...  # called automatically by TaskPanel
    def stop(self, timeout_ms=3000):          ...  # called by TaskPanel.cleanup()

    def process_frame(self, frame_rgb: np.ndarray, meta: dict) -> None:
        raise NotImplementedError   # YOU implement this
```

- Runs in its own `QThread` — never touch Qt widgets inside `process_frame`.
- The bounded 1-frame queue ensures you always process the latest frame, never a backlog.

---

## TaskPanel API

```python
class TaskPanel(QWidget):
    def __init__(self, camera_client=None, arm_controller=None, parent=None): ...

    # YOU implement:
    def on_attach(self) -> None: ...   # build UI, create processor, wire signals
    def cleanup(self) -> None:   ...   # call super().cleanup() first

    # Handled automatically (override only if you need extra connections):
    def showEvent(self, event): ...    # connects raw_frame_received → submit_frame, starts processor
    def hideEvent(self, event): ...    # disconnects raw_frame_received → submit_frame

    # Called by platform on hardware reconnection:
    def attach_camera(self, cam): ...
    def attach_arm(self, arm):    ...
```

### Hardware access

| Attribute | Type | Notes |
|---|---|---|
| `self._cam` | `CameraClient` or `None` | May be None if camera not connected at startup |
| `self._arm` | `ArmController` or `None` | May be None if arm not connected at startup |

Always guard: `if self._cam: self._cam.some_signal.connect(...)`.

---

## CameraClient signals and methods

| Signal | Payload | Description |
|---|---|---|
| `raw_frame_received` | `(np.ndarray, dict)` | RGB frame + metadata. Used by TaskPanel base to feed the processor. |
| `frame_received` | `QImage` | Debayered, ready-to-display frame. |
| `connection_changed` | `bool` | True = connected. |
| `fps_updated` | `float` | Current capture FPS. |
| `resolution_updated` | `int, int` | Width, height. |

| Method | Description |
|---|---|
| `send_params(params: dict) -> dict` | Send camera parameter update over ZMQ control socket. |

---

## ArmController signals and methods

| Signal | Payload | Description |
|---|---|---|
| `position_updated` | `float x, y, z, roll, pitch, yaw` | TCP position (mm / degrees), polled at 10 Hz. |
| `connection_changed` | `bool` | True = connected. |
| `enabled_changed` | `bool` | True = motion enabled. |
| `error_occurred` | `str` | Error message from xArm SDK. |
| `scan_state_changed` | `bool` | True = valve scan running. |

| Method | Description |
|---|---|
| `get_position()` | Returns `(code, [x,y,z,roll,pitch,yaw])`. |
| `send_servo_cartesian(pose, mvvelo, mvacc)` | Send one servo-cartesian target. |
| `go_zero_start()` | Move to all-zeros joint pose. |
| `go_initial_start()` | Move to default initial pose. |
| `reset_arm()` | Clear errors, re-enable motion. |
| `start_valve_scan(pos, amplitude_mm, speed_mmps)` | Start oscillating valve scan. |
| `stop_valve_scan()` | Stop valve scan immediately. |

---

## Utilities

```python
from VisionForge.app.plugin_sdk import save_frame, resolve_path

# Save a captured frame
save_frame(frame_rgb, "/path/to/output.png")   # converts RGB→BGR internally

# Locate a bundled asset relative to your plugin file
WEIGHTS = resolve_path(__file__, "weights/model.pt")
```

---

## dev_runner reference

```
python -m VisionForge.app.plugin_sdk.dev_runner <plugin_dir> --camera IP --arm IP
```

| Argument | Required | Description |
|---|---|---|
| `plugin_dir` | yes | Path to the plugin folder |
| `--camera IP` | yes | IP of the camera ZMQ server |
| `--arm IP` | yes | IP of the xArm controller |

Both `--camera` and `--arm` are required. Plugins always run against real hardware.

---

## Import styles available in plugin code

| Style | Example | Why it works |
|---|---|---|
| Local bare import | `import processor` | Plugin folder is on `sys.path` |
| Local sub-package | `from core.utils import helper` | Plugin folder is on `sys.path` |
| SDK import | `from VisionForge.app.plugin_sdk import TaskPanel` | VisionForge package on `sys.path` |
| Platform core | `from VisionForge.app.core.camera_client import CameraClient` | Same path in dev zip and platform |

Relative imports (`from .processor import X`) are not supported — the loader does not register plugins as packages.

---

## Error handling

A broken plugin never crashes VisionForge. If any step of loading fails (missing `plugin.json`, import error, wrong class name), the error is printed to stderr and the plugin is skipped. All other plugins and the platform itself continue normally.

---

## Plugin discovery rules

The platform scans `plugins/` at startup and loads a folder if ALL of the following are true:

1. It is a directory (not a file)
2. It does **not** start with `.` or `_`
3. It contains `plugin.json`

Folders are processed in alphabetical order. Prefix with `01_`, `02_` to control sidebar order.
