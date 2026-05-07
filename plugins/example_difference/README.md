# example_difference — VisionForge Plugin Template

A minimal frame-difference motion detector. Copy this folder to build your own plugin.

---

## What it does

Compares each camera frame against the previous one. Changed pixels are highlighted red. Motion level (%) is shown live. When the arm is connected, its TCP position is displayed. Clicking the feed (or the Save button) captures the current frame to `captures/`.

---

## Prerequisites

- Real Baumer VAX-50C camera running the ZMQ server (ports 5555 / 5556)
- Real UFACTORY xArm5 with the xArm Python SDK installed

---

## Running standalone (dev_runner)

```powershell
# From the VisionForge repo root:
python -m VisionForge.app.plugin_sdk.dev_runner plugins\example_difference `
    --camera 192.168.1.100 `
    --arm    192.168.1.200
```

Both `--camera` and `--arm` are required. The runner opens a full-size window with the live camera feed. Close the window to stop.

---

## Deploying to VisionForge

Copy the plugin folder into the platform's `plugins/` directory and restart VisionForge:

```
xcopy plugins\example_difference  VisionForge\plugins\example_difference  /E /I
python main.py
```

The "Difference" entry appears automatically in the sidebar Tasks group.

---

## Making your own plugin — what to change

### 1. `plugin.json`

| Field | Change to |
|---|---|
| `name` | unique slug for your plugin, e.g. `"my_detector"` |
| `label` | sidebar text, e.g. `"My Detector"` |
| `icon` | any single Unicode glyph |
| `panel_class` | your panel class name |

### 2. `processor.py`

Subclass `TaskProcessor`. Override `process_frame(frame_rgb, meta)`:

```python
from VisionForge.app.plugin_sdk import TaskProcessor

class MyProcessor(TaskProcessor):
    def process_frame(self, frame_rgb, meta):
        # frame_rgb: HxWx3 uint8 RGB numpy array — real camera data
        # meta: dict with camera metadata
        # ... do your CV work ...
        self.display_ready.emit(qimg)    # send annotated frame to panel
        self.result_ready.emit(my_data)  # send any Python object to panel
```

### 3. `panel.py`

Subclass `TaskPanel`. Implement `on_attach()` and `cleanup()`:

```python
from VisionForge.app.plugin_sdk import TaskPanel
from processor import MyProcessor

class MyPanel(TaskPanel):
    def on_attach(self):
        self._processor = MyProcessor()
        self._processor.display_ready.connect(self._on_display)
        # build your UI here
        # self._cam  → real CameraClient (signals + methods)
        # self._arm  → real ArmController (signals + methods)

    def cleanup(self):
        super().cleanup()   # stops processor, disconnects camera signal
```

`showEvent` and `hideEvent` are handled by the base class — they connect/disconnect `raw_frame_received → submit_frame` and start the processor automatically.

---

## SDK reference

```python
from VisionForge.app.plugin_sdk import (
    TaskPanel,      # base class for panels
    TaskProcessor,  # base class for background CV workers
    save_frame,     # save_frame(frame_rgb, filepath) → bool
    resolve_path,   # resolve_path(__file__, "weights/model.pt") → abs path
)
```

### CameraClient signals (self._cam)
| Signal | Payload |
|---|---|
| `raw_frame_received` | `(np.ndarray RGB, dict meta)` |
| `frame_received` | `QImage` |
| `connection_changed` | `bool` |
| `fps_updated` | `float` |
| `resolution_updated` | `int, int` |

### ArmController signals (self._arm)
| Signal | Payload |
|---|---|
| `position_updated` | `float x, y, z, roll, pitch, yaw` |
| `connection_changed` | `bool` |
| `enabled_changed` | `bool` |
| `error_occurred` | `str` |
| `scan_state_changed` | `bool` |

### ArmController methods (self._arm)
`get_position()`, `send_servo_cartesian(pose)`, `go_zero_start()`, `go_initial_start()`, `reset_arm()`, `start_valve_scan(pos, amplitude_mm, speed_mmps)`, `stop_valve_scan()`
