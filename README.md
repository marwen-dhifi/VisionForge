# VisionForge

A Python desktop application that combines industrial computer vision, robot arm control, and real-time data logging into a unified operator interface. Built for the DAAD Project 1 research environment.

---

## What Is VisionForge?

VisionForge is a multi-purpose vision-robotics control station. An operator connects it to a Baumer VAX-50C industrial camera and a UFACTORY xArm5 collaborative robot arm, then uses three specialized computer vision pipelines to perform automated measurement and tracking tasks on physical equipment.

The application streams live camera frames via ZeroMQ, runs deep-learning models for detection and OCR, allows direct robot arm control via gamepad, and logs all measurements to an InfluxDB time-series database.

---

## The Three Vision Pipelines

### 1. Seven-Segment Display Reader
Automatically reads numeric values off industrial seven-segment displays in the camera field of view.

- **Detection:** YOLO-OBB (oriented bounding box) model locates each display in the frame
- **Tracking:** ByteTrack assigns a persistent ID to each display across frames
- **OCR:** PARSeq (scene text recognition) reads the digit string from each cropped display
- **Output:** Live annotated feed + measurement logging to InfluxDB at a user-configurable rate (1–10 Hz)

Use this to continuously record pressure gauges, counters, flow meters, or any numeric display without manual reading.

### 2. Valve Orientation Detection
Determines whether industrial valves are open or closed using AprilTag markers.

- A small AprilTag sticker is attached to each valve handle
- The camera detects the marker and estimates its 3D rotation (PnP pose estimation)
- The operator calibrates each valve once by setting its fully-open and fully-closed reference poses
- From that point, the system classifies state automatically using a 30-frame voting window for stability

Supports up to 32 simultaneously tracked valves (marker IDs 0–31).

### 3. Module Tracker (3D Localization)
Builds a top-down 2D map of large physical modules in the lab using 250 mm ArUco markers.

- Detects ArUco markers (6×6 dictionary) attached to each module
- Computes 3D position and orientation relative to the camera
- Projects results into a lab coordinate frame and renders a live overhead map
- Logs module positions to InfluxDB for historical tracking

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

---

## Project Structure

```
VisionForge/
├── main.py                        # Entry point
├── app/
│   ├── main_window.py             # 5-page tabbed shell
│   ├── splash.py                  # Startup screen (loads ML models)
│   ├── connection_dialog.py       # IP configuration & connection test
│   ├── styles/theme.py            # Dark theme stylesheet
│   ├── core/
│   │   ├── camera_client.py       # ZMQ camera subscriber thread
│   │   ├── arm_controller.py      # xArm5 SDK wrapper (QThread)
│   │   ├── gamepad_controller.py  # Gamepad input thread
│   │   └── media_manager.py       # Video/image recording
│   ├── widgets/                   # Reusable UI components
│   └── tasks/
│       ├── seven_segment/         # YOLO + ByteTrack + PARSeq pipeline
│       ├── valve_orientation/     # AprilTag pose estimation pipeline
│       └── module_tracker/        # ArUco 3D localization pipeline
├── media/
│   ├── images/                    # Captured screenshots
│   └── videos/                    # Recorded clips
```

Model weights are not included in the repository (excluded by `.gitignore`). Place them at:

```
weights/yolo/best.pt               # YOLO-OBB seven-segment detector
weights/parseq/parseq_7seg.ckpt    # PARSeq OCR checkpoint
```

---

## Getting Started

### 1. Install dependencies

```bash
pip install pyside6 opencv-python numpy torch torchvision zmq pygame \
            supervision ultralytics pillow influxdb-client
```

Also install the xArm Python SDK from UFACTORY.

### 2. Start the camera server

The Baumer camera must be running a ZMQ publisher on ports 5555 (stream) and 5556 (control) before launching VisionForge.

### 3. Run the application

```bash
python main.py
```

On startup:
1. A splash screen appears while YOLO and PARSeq models load from disk
2. A connection dialog prompts for the camera IP and arm IP
3. The main window opens with five tabs: Camera, Arm, Valve, 7-Segment, Modules

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

Speed range: 20–500 mm/s, adjustable via UI slider.

---

## Data Logging

Both the Seven-Segment and Module Tracker pipelines write to InfluxDB:

| Pipeline | Bucket |
|----------|--------|
| Seven-Segment | `7Segments_Measurments` |
| Module Tracker | `Modules_Tracking` |

Default URL: `http://localhost:8086` — configure credentials in `app/tasks/seven_segment/core.py`.

---

## Configuration Files

Runtime calibration is automatically saved to JSON files inside each task directory:

- `app/tasks/valve_orientation/valve_config.json` — open/closed reference poses per valve marker ID
- `app/tasks/module_tracker/module_tracker_config.json` — camera angle, height offset, map scale, module definitions

---

## Architecture Notes

- All hardware I/O runs in dedicated `QThread` workers; the Qt signal/slot system keeps the UI thread unblocked
- ML models are loaded once at startup and cached globally — no reload penalty when switching tabs
- The Seven-Segment pipeline runs YOLO detection and PARSeq OCR in separate threads; OCR rate is user-configurable to trade CPU load for update frequency
- Valve state uses a 30-frame voting window to suppress flickering from single-frame pose estimation noise
