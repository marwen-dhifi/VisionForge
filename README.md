# VisionForge

A Python desktop application that combines industrial computer vision, robot arm control, and real-time data logging into a unified operator interface. Built for the DAAD Project 1 research environment.

---

## What Is VisionForge?

VisionForge is a multi-purpose vision-robotics control station. An operator connects it to a Baumer VAX-50C industrial camera and a UFACTORY xArm5 collaborative robot arm, then uses three specialized computer vision pipelines to perform automated measurement and tracking tasks on physical equipment.

The application streams live camera frames via ZeroMQ, runs deep-learning models for detection and OCR, allows direct robot arm control via gamepad, logs all measurements to an InfluxDB time-series database, and supports third-party plugins through a built-in Plugin SDK.

---

## Hardware Requirements

| Component | Model | Connection |
|-----------|-------|------------|
| Camera | Baumer VAX-50C (BayerRG8, 30 FPS) | ZMQ over TCP (port 5555/5556) |
| Robot arm | UFACTORY xArm5 | TCP via xArm SDK |
| Gamepad | PS4 / Xbox-compatible USB controller | USB HID (via Pygame) |
| Database | InfluxDB 2.x | localhost:8086 |

---

## Software Stack

- **GUI:** PySide6 (Qt 6)
- **Computer vision:** OpenCV 4
- **Deep learning:** PyTorch + Ultralytics (YOLO)
- **Text recognition:** PARSeq (custom strhub implementation included)
- **Multi-object tracking:** Supervision / ByteTrack
- **Camera streaming:** ZeroMQ (PUB-SUB)
- **Robotics:** xArm Python SDK
- **Gamepad input:** Pygame
- **Time-series storage:** InfluxDB client
- **Gesture recognition:** MediaPipe (≥ 0.10.14)

---

## Getting Started

### 1. Install dependencies

```bash
pip install pyside6 opencv-python numpy torch torchvision zmq pygame \
            supervision ultralytics pillow influxdb-client mediapipe
```

Also install the xArm Python SDK from UFACTORY.

### 2. Start the camera server

The Baumer camera must be running a ZMQ publisher on ports 5555 (stream) and 5556 (control) before launching VisionForge.

### 3. Run

```bash
python main.py
```

On startup:
1. Splash screen loads YOLO + PARSeq weights and scans the `plugins/` folder
2. Connection dialog prompts for camera IP and arm IP
3. Main window opens — five built-in tabs plus a sidebar entry for each loaded plugin

---

## Project Structure

```
VisionForge/
├── main.py                          # Entry point
├── app/
│   ├── main_window.py               # Tabbed shell + plugin integration
│   ├── splash.py                    # Startup screen (loads models + scans plugins)
│   ├── connection_dialog.py         # IP configuration & connection test
│   ├── styles/theme.py              # Dark theme stylesheet
│   ├── core/
│   │   ├── camera_client.py         # ZMQ camera subscriber (QThread)
│   │   ├── arm_controller.py        # xArm5 SDK wrapper (QThread)
│   │   ├── gamepad_controller.py    # Gamepad input thread
│   │   └── media_manager.py         # Video/image recording
│   ├── widgets/                     # Reusable UI components
│   ├── plugin_sdk/                  # Plugin SDK
│   │   ├── base.py                  # TaskPanel + TaskProcessor ABCs
│   │   ├── manifest.py              # PluginManifest + load_manifest()
│   │   ├── loader.py                # PluginLoader singleton
│   │   ├── utils.py                 # save_frame(), resolve_path()
│   │   └── dev_runner.py            # Standalone plugin test runner
│   └── tasks/
│       ├── seven_segment/           # YOLO + ByteTrack + PARSeq pipeline
│       ├── valve_orientation/       # AprilTag pose estimation pipeline
│       └── module_tracker/          # ArUco 3D localization pipeline
├── plugins/
│   ├── arm_spin/                    # Arm Y-axis oscillation tutorial plugin
│   ├── hand_pointer/                # Gesture-controlled arm movement
│   └── example_difference/          # Frame-difference motion detector
└── media/
    ├── images/                      # Captured screenshots
    └── videos/                      # Recorded clips
```

Model weights (excluded from repo) go here:

```
app/tasks/seven_segment/weights/yolo/best.pt
app/tasks/seven_segment/weights/parseq/parseq_7seg.ckpt
```

---

## The Three Vision Pipelines

### Seven-Segment Display Reader

Reads numeric values off industrial seven-segment displays.

- YOLO-OBB locates each display; ByteTrack assigns persistent IDs across frames
- PARSeq OCR reads the digit string from each cropped display
- Logs to InfluxDB bucket `7Segments_Measurments` at a user-configurable rate (1–10 Hz)

### Valve Orientation Detection

Classifies industrial valves as open or closed using AprilTag markers.

- Attach a small AprilTag sticker to each valve handle
- Camera estimates the marker's 3D rotation (solvePnP)
- Operator calibrates each valve once (fully-open + fully-closed reference poses)
- System classifies state automatically using a 30-frame voting window
- Supports up to 32 valves simultaneously (marker IDs 0–31)

Configuration saved to: `app/tasks/valve_orientation/valve_config.json`

### Module Tracker (3D Localization)

Builds a live overhead map of large lab modules using 250 mm ArUco markers.

- Detects ArUco markers (6×6 dictionary), computes 3D pose relative to camera
- Projects into a lab coordinate frame, renders a top-down map
- Logs positions to InfluxDB bucket `Modules_Tracking`

Configuration saved to: `app/tasks/module_tracker/module_tracker_config.json`

---

## Arm Control (Gamepad)

| Input | Action |
|-------|--------|
| Left stick | XY motion in Cartesian space |
| L1 / R1 | Z down / up |
| L2 / R2 | Pitch / Yaw |
| X button | Speed −5% |
| Y button | Speed +5% |
| START | Return to safe position |

Speed range: 20–500 mm/s, adjustable via the UI slider.

---

## Architecture

### Threading model

All hardware I/O runs in dedicated `QThread` workers. The Qt signal/slot system keeps the UI thread unblocked. ML models are loaded once at splash screen and globally cached.

### Boot sequence

```
main.py
  └─ SplashScreen
       ├─ ModelLoader (QThread) — loads YOLO + PARSeq
       ├─ get_plugin_loader().scan() — discovers plugins/
       └─ ConnectionDialog → MainWindow
            ├─ CameraClient.start()
            ├─ ArmController.start()
            ├─ Built-in panels: stack indices 0–4
            └─ Plugin panels: stack indices 5+
```

### Camera configuration

The camera server owns the physical acquisition (resolution, FPS, exposure, gain, white balance). VisionForge can adjust these at runtime via the Camera Configuration panel, which sends commands through `CameraClient.send_params()` over a ZMQ REQ socket back to the server.

### Arm modes

- **Mode 0 (position mode)** — `set_position()` commands, used by valve scan and go-to-position functions
- **Mode 1 (servo mode)** — `set_servo_cartesian()` commands, used for continuous real-time control (gamepad, plugins)

---

## Plugin SDK

Plugins are folders dropped into `plugins/`. They are discovered and loaded automatically at startup. A broken plugin is skipped and logged — it never crashes the platform.

### Plugin structure

```
plugins/my_plugin/
├── plugin.json      # manifest
├── panel.py         # UI widget  (subclasses TaskPanel)
└── processor.py     # CV worker  (subclasses TaskProcessor)
```

**`plugin.json`**
```json
{
  "name":         "my_plugin",
  "label":        "My Plugin",
  "icon":         "⬡",
  "version":      "1.0.0",
  "panel_module": "panel",
  "panel_class":  "MyPanel"
}
```

### TaskProcessor

Runs in a background `QThread`. Receives camera frames through a `Queue(maxsize=1)` — always the most recent frame, never falls behind.

```python
from VisionForge.app.plugin_sdk import TaskProcessor

class MyProcessor(TaskProcessor):
    def process_frame(self, frame_rgb, meta):
        # frame_rgb: HxWx3 uint8 RGB numpy array
        # emit results — never touch Qt widgets here
        self.display_ready.emit(qimage)
        self.result_ready.emit(my_data)
```

### TaskPanel

UI widget running on the Qt main thread. The base class automatically connects the camera feed to the processor when the panel is shown and disconnects it when hidden.

```python
from VisionForge.app.plugin_sdk import TaskPanel
from processor import MyProcessor

class MyPanel(TaskPanel):
    def on_attach(self):
        # called once at load time — build UI and wire processor
        self._processor = MyProcessor()
        self._processor.display_ready.connect(self._on_display)
        # build the rest of your UI...

    def cleanup(self):
        super().cleanup()   # always call super
```

Guards: `self._cam` and `self._arm` may be `None` if hardware was not connected at startup. Always check before use.

### Loading .pt model weights from a plugin

```python
from VisionForge.app.plugin_sdk import resolve_path

WEIGHTS = resolve_path(__file__, "weights/my_model.pt")
# resolves relative to the plugin folder regardless of working directory
```

Load in `__init__`, never in `process_frame`.

### Dev runner

Test a plugin against real hardware without launching the full platform:

```bash
python -m VisionForge.app.plugin_sdk.dev_runner plugins/my_plugin \
    --camera 192.168.1.100 --arm 192.168.1.200
```

Opens three windows: the plugin panel (maximized), a hardware status monitor, and the camera configuration panel.

### SDK zip

```bash
python tools/build_sdk_zip.py
# → dist/visionforge-sdk-1.0.0.zip
```

The zip mirrors the `VisionForge/` package structure so `from VisionForge.app.plugin_sdk import TaskPanel` resolves identically in the dev environment and in the deployed platform.

---

## Available Plugins

### `arm_spin`

Tutorial plugin. Displays a 90°-rotated camera feed and oscillates the arm ±60 mm in the Y axis at 0.3 Hz using servo mode. Motion runs in a plain `threading.Thread` at 20 Hz, independent of the camera frame rate.

### `hand_pointer`

Gesture-controlled arm movement using the MediaPipe Tasks API.

| Gesture | Action |
|---------|--------|
| Index finger extended (pointing) | Arm moves in the screen direction of the finger |
| Fist | Arm holds position |
| Anything else | No movement |

Screen X maps to arm Y, screen Y maps to arm Z. A QTimer at 20 Hz drives commands — movement is time-based, not frame-rate-dependent. The `hand_landmarker.task` model is downloaded automatically to the plugin folder on first run.

### `example_difference`

Reference plugin. Computes frame-to-frame difference, applies a threshold mask, and reports a motion percentage. Demonstrates the complete TaskPanel + TaskProcessor lifecycle.
