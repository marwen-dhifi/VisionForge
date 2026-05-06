# VisionForge Plugin SDK — Implementation Plan

> Status: design-complete, ready for implementation
> Target: VisionForge v1.0 (PySide6 vision-robotics control station)
> Repo root: `D:\ProjectDAAD\Project1_Number_Detection_Arm_Movement\VisionForge\`

---

## 1. Project Overview

### 1.1 What VisionForge Is

VisionForge is a PySide6 desktop application that orchestrates an industrial vision and robotics workstation. It consumes frames from a Baumer VAX-50C camera (over ZeroMQ) and drives a UFACTORY xArm5 (over the xArm Python SDK), exposing both through a single dark-themed UI:

- A **Camera** page (live feed + parameter control).
- An **xArm Control** page (jog, gamepad, scan).
- A **Tasks** group containing three task pages:
  - `valve_orientation` — AprilTag-based valve open/closed state tracking.
  - `seven_segment` — YOLO-OBB + PARSeq OCR readout of seven-segment displays, written to InfluxDB.
  - `module_tracker` — ArUco-based lab-module pose tracking with map view, history and InfluxDB.

The application starts via `main.py` → `SplashScreen` (which loads YOLO + PARSeq weights in a background `ModelLoader` `QThread`) → `ConnectionDialog` (camera/arm IPs) → `MainWindow`.

### 1.2 What This Plan Adds

A **Plugin SDK** that lets a developer write a new task page (a "plugin") in a separate folder, drop it into VisionForge, and have it appear in the sidebar and stack — without modifying any platform code.

The SDK is:

- **Embedded** at `app/plugin_sdk/` inside VisionForge (the running platform imports from there).
- **Distributed** as a standalone zip that mirrors VisionForge's directory layout, so the import path `from VisionForge.app.plugin_sdk import TaskPanel, TaskProcessor` resolves identically in the dev environment and in the deployed platform.
- **Backed by a dev runner** (`python -m VisionForge.app.plugin_sdk.dev_runner <plugin_folder>`) that lets developers run a plugin standalone with mock camera/arm or with real hardware via CLI flags.

The three existing tasks are **not refactored**. The plugin system is purely additive.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  VisionForge platform (the application that ships)                          │
│                                                                             │
│   main.py                                                                   │
│     └─► SplashScreen ── pre-loads YOLO + PARSeq                             │
│            │             also calls get_plugin_loader().scan() ◄────┐       │
│            ▼                                                        │       │
│     ConnectionDialog                                                │       │
│            │                                                        │       │
│            ▼                                                        │       │
│     MainWindow                                                      │       │
│        ├─ TopBar                                                    │       │
│        ├─ Sidebar  (built from _TOP_ITEMS + dynamic plugin entries) │       │
│        └─ QStackedWidget                                            │       │
│              [0] CameraPanel                                        │       │
│              [1] ArmPanel                                           │       │
│              [2..4] existing task panels (valve/seg/tracker)        │       │
│              [5..N] *plugin panels*  ◄──────────────┐               │       │
│                                                     │               │       │
│  app/plugin_sdk/                                    │               │       │
│     ├─ __init__.py    (re-exports public API)       │               │       │
│     ├─ base.py        (TaskPanel, TaskProcessor)    │               │       │
│     ├─ manifest.py    (PluginManifest dataclass)    │               │       │
│     ├─ loader.py      (PluginLoader, get_plugin_loader singleton)   │       │
│     ├─ utils.py       (save_frame, resolve_path)                    │       │
│     ├─ mocks.py       (MockCameraClient, MockArmController)         │       │
│     └─ dev_runner.py  (standalone runner CLI)                       │       │
│                                                                     │       │
│  plugins/                       ◄── platform scans this at startup          │
│     ├─ my_plugin/                                                           │
│     │    ├─ plugin.json                                                     │
│     │    ├─ panel.py    (subclass of TaskPanel)                             │
│     │    ├─ processor.py (subclass of TaskProcessor)                        │
│     │    ├─ weights/                                                        │
│     │    └─ ...any structure the developer wants                            │
│     └─ another_plugin/ ...                                                  │
└─────────────────────────────────────────────────────────────────────────────┘

                              ──── DEV-TIME ────

┌─────────────────────────────────────────────────────────────────────────────┐
│  Standalone SDK zip (downloaded by plugin developer)                        │
│                                                                             │
│  visionforge-sdk-1.0.0/                                                     │
│    ├── VisionForge/                                                         │
│    │    └── app/                                                            │
│    │         ├── core/                                                      │
│    │         │    ├── camera_client.py    (real ZMQ client)                 │
│    │         │    └── arm_controller.py   (real xArm SDK wrapper)           │
│    │         └── plugin_sdk/  (identical files to platform)                 │
│    ├── plugins/                                                             │
│    │    └── example_difference/  (template to copy)                        │
│    └── requirements-sdk.txt                                                 │
│                                                                             │
│  Developer runs from visionforge-sdk-1.0.0/ root:                          │
│      python -m VisionForge.app.plugin_sdk.dev_runner plugins/my_plugin     │
│                                                                             │
│  Import  `from VisionForge.app.plugin_sdk import TaskPanel`                 │
│  resolves identically in standalone dev AND inside the live platform.       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key invariants

1. **One source of truth**: SDK code lives at `app/plugin_sdk/` in the VisionForge repo. The zip is generated from there. Developers never edit SDK source.
2. **Portable imports**: `from VisionForge.app.plugin_sdk import ...` works in both contexts because the zip preserves the `VisionForge/app/plugin_sdk/` path under its root.
3. **Plugin code is platform-agnostic**: a plugin authored against the SDK runs with zero modification when copied into the running platform's `plugins/` directory.
4. **Real objects passed through**: `self._cam` and `self._arm` inside a `TaskPanel` are the real `CameraClient` and `ArmController` instances (or mocks in dev). The SDK does not wrap, proxy, or restrict them.

---

## 3. Complete File Inventory

### 3.1 New files

| Path | Purpose |
|---|---|
| `app/plugin_sdk/__init__.py` | Public API re-exports: `TaskPanel`, `TaskProcessor`, `PluginManifest`, `get_plugin_loader`, `save_frame`, `resolve_path`. |
| `app/plugin_sdk/base.py` | Abstract base classes `TaskPanel(QWidget)` and `TaskProcessor(QThread)`. |
| `app/plugin_sdk/manifest.py` | `PluginManifest` dataclass + `load_manifest(path)` parser/validator. |
| `app/plugin_sdk/loader.py` | `PluginLoader` (discover, validate, instantiate) + `get_plugin_loader()` singleton. |
| `app/plugin_sdk/utils.py` | `save_frame(frame_rgb, filepath)` and `resolve_path(plugin_file, relative_path)`. |
| `app/plugin_sdk/mocks.py` | `MockCameraClient(QThread)` and `MockArmController(QThread)` mimicking real signals. |
| `app/plugin_sdk/dev_runner.py` | CLI entry point: `python -m VisionForge.app.plugin_sdk.dev_runner ...`. |
| `plugins/` | New top-level directory at repo root. Hosts user plugins. |
| `plugins/.gitkeep` | Keep empty `plugins/` directory in git. |
| `plugins/example_difference/` | Reference template plugin (see §11). |
| `plugins/example_difference/plugin.json` | Manifest for the example. |
| `plugins/example_difference/panel.py` | Example `TaskPanel` subclass. |
| `plugins/example_difference/processor.py` | Example `TaskProcessor` subclass. |
| `plugins/example_difference/README.md` | Walks the developer through what each piece does. |
| `tools/build_sdk_zip.py` | Build script that produces `visionforge-sdk-<version>.zip`. |
| `docs/plugin_sdk.md` | Developer-facing documentation. |

### 3.2 Modified files

| Path | Change summary |
|---|---|
| `app/main_window.py` | After the 5 hard-coded panels (lines 78–96), loop over `get_plugin_loader().plugins` to add dynamic plugin panels. Propagate camera/arm reconnects and closeEvent cleanup to plugin panels. |
| `app/widgets/sidebar.py` | Accept `plugin_items` constructor arg. Build `self._task_items = _TASK_ITEMS + plugin_items`. Use instance attr for `_task_indices`. Update `_nav_width` call. |
| `app/splash.py` | In `_on_loader_finished`, call `get_plugin_loader().scan()` before emitting `finished`. |

---

## 4. Full SDK Specification

All public symbols below are re-exported from `app/plugin_sdk/__init__.py`.

### 4.1 `TaskPanel` (`app/plugin_sdk/base.py`)

```python
from PySide6.QtWidgets import QWidget
from PySide6.QtCore    import Signal

class TaskPanel(QWidget):
    """
    Base class for all plugin panels.

    self._cam  → CameraClient | MockCameraClient | None
    self._arm  → ArmController | MockArmController | None

    These are the real Qt objects used by VisionForge — plugins may
    connect to any of their signals and call any of their methods.

    Lifecycle (called by platform / dev_runner):
        __init__(camera_client, arm_controller, plugin_dir, parent)
        on_attach()       ← build UI, create processor, wire signals
        showEvent(event)  ← connect camera frames, start processor
        hideEvent(event)  ← disconnect camera frames
        cleanup()         ← stop processor, release resources

    Subclasses MUST implement:
        on_attach(self)
        cleanup(self)

    Subclasses MAY override:
        showEvent / hideEvent
    """

    display_changed = Signal(str, str)  # (icon, label) — optional runtime update

    def __init__(
        self,
        camera_client  = None,   # CameraClient | MockCameraClient | None
        arm_controller = None,   # ArmController | MockArmController | None
        plugin_dir: str = "",    # absolute path to the plugin's own folder
        parent = None,
    ):
        super().__init__(parent)
        self._cam        = camera_client
        self._arm        = arm_controller
        self._plugin_dir = plugin_dir
        self._processor  = None   # subclass sets in on_attach

    # ── Mandatory hooks ──────────────────────────────────────────────────
    def on_attach(self) -> None:
        """Build UI, create processor, connect signals. Called once."""
        raise NotImplementedError

    def cleanup(self) -> None:
        """Stop processor thread, disconnect signals, close files."""
        raise NotImplementedError

    # ── Default lifecycle ────────────────────────────────────────────────
    def showEvent(self, event):
        """
        Default: wire camera → processor.submit_frame, start processor.
        Override if you need additional connections (e.g. also wire to feed widget).
        """
        super().showEvent(event)
        if self._cam is not None and self._processor is not None:
            self._cam.raw_frame_received.connect(self._processor.submit_frame)
        if self._processor is not None and not self._processor.isRunning():
            self._processor.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._cam is not None and self._processor is not None:
            try:
                self._cam.raw_frame_received.disconnect(self._processor.submit_frame)
            except (RuntimeError, TypeError):
                pass

    # ── Convenience properties ───────────────────────────────────────────
    @property
    def camera(self):      return self._cam
    @property
    def arm(self):         return self._arm
    @property
    def plugin_dir(self):  return self._plugin_dir
```

**Thread-safety contract**: `self._cam.raw_frame_received` fires from the camera's QThread. Slots connected with the default (auto) connection type from a UI-thread `QWidget` execute on the UI thread. To run heavy work off the UI thread, use `TaskProcessor.submit_frame` as the slot — it is a thread-safe queue push, never blocking.

### 4.2 `TaskProcessor` (`app/plugin_sdk/base.py`)

```python
import queue
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui  import QImage

class TaskProcessor(QThread):
    """
    Base class for background CV workers.

    Mirrors the pattern of ValveProcessor / SevenSegProcessor /
    ModuleTrackerProcessor: a single-slot bounded queue that always
    holds the latest frame.

    Signals:
        display_ready(QImage)   — rendered frame for the panel's feed widget
        result_ready(object)    — generic per-frame result (any Python object)

    Subclasses MUST override:
        process(frame_rgb, meta) → (QImage | None, result | None)

    Subclasses MAY override:
        run(self)   — only if the default loop is unsuitable
    """

    display_ready = Signal(QImage)
    result_ready  = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = False

    # ── Public (UI-thread safe) ──────────────────────────────────────────
    def submit_frame(self, frame: np.ndarray, meta: dict = None):
        """Drop previous queued frame, push latest. Non-blocking."""
        try:    self._queue.get_nowait()
        except  queue.Empty: pass
        try:    self._queue.put_nowait((frame, meta or {}))
        except  queue.Full:  pass

    def stop(self, timeout_ms: int = 3000):
        self._running = False
        self.wait(timeout_ms)

    # ── Mandatory hook ───────────────────────────────────────────────────
    def process(self, frame_rgb: np.ndarray, meta: dict):
        """
        CV work goes here. Returns (QImage | None, result | None).
        Runs in QThread — never touch Qt widgets here.
        """
        raise NotImplementedError

    # ── Default loop ─────────────────────────────────────────────────────
    def run(self):
        self._running = True
        while self._running:
            try:
                frame, meta = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                qimg, result = self.process(frame, meta)
                if qimg   is not None: self.display_ready.emit(qimg)
                if result is not None: self.result_ready.emit(result)
            except Exception:
                import traceback, sys
                traceback.print_exc(file=sys.stderr)
```

**Thread-safety contract**: `submit_frame` runs on the UI thread (queue.Queue is thread-safe). `process` runs on the QThread. Signals cross threads via Qt's queued-connection mechanism.

### 4.3 `PluginManifest` (`app/plugin_sdk/manifest.py`)

```python
from dataclasses import dataclass, field
import json, os

@dataclass(frozen=True)
class PluginManifest:
    plugin_id:    str
    name:         str
    icon:         str
    version:      str
    entry_module: str
    panel_class:  str
    description:  str       = ""
    author:       str       = ""
    requires:     list      = field(default_factory=list)  # informational
    sdk_min:      str       = "1.0.0"
    plugin_dir:   str       = ""   # set at load time, not in JSON

    @staticmethod
    def required_keys():
        return ("plugin_id", "name", "icon",
                "version", "entry_module", "panel_class")


class ManifestError(Exception):
    pass


def load_manifest(plugin_dir: str) -> PluginManifest:
    """Read <plugin_dir>/plugin.json, validate, return PluginManifest."""
    path = os.path.join(plugin_dir, "plugin.json")
    if not os.path.isfile(path):
        raise ManifestError(f"Missing plugin.json in {plugin_dir}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ManifestError(f"Invalid JSON in {path}: {e}") from e

    missing = [k for k in PluginManifest.required_keys() if k not in data]
    if missing:
        raise ManifestError(
            f"{path}: missing required keys: {', '.join(missing)}"
        )

    return PluginManifest(
        plugin_id    = data["plugin_id"],
        name         = data["name"],
        icon         = data["icon"],
        version      = data["version"],
        entry_module = data["entry_module"],
        panel_class  = data["panel_class"],
        description  = data.get("description", ""),
        author       = data.get("author", ""),
        requires     = list(data.get("requires", [])),
        sdk_min      = data.get("sdk_min", "1.0.0"),
        plugin_dir   = os.path.abspath(plugin_dir),
    )
```

### 4.4 `PluginLoader` (`app/plugin_sdk/loader.py`)

```python
import importlib, importlib.util, os, sys, traceback
from dataclasses import dataclass
from typing import Optional

from VisionForge.app.plugin_sdk.manifest import PluginManifest, load_manifest, ManifestError

@dataclass
class LoadedPlugin:
    manifest:   PluginManifest
    panel_cls:  type           # TaskPanel subclass
    error:      Optional[str] = None  # set if broken


class PluginLoader:
    """
    Scans a directory for plugin subfolders. For each valid plugin:
      1. Reads plugin.json
      2. Adds plugin folder to sys.path
      3. Imports entry module via importlib
      4. Resolves and validates the panel class
      5. Stores a LoadedPlugin in self.plugins

    Failures NEVER raise — recorded as LoadedPlugin(error=...).
    """

    def __init__(self, plugins_root: str):
        self._plugins_root = os.path.abspath(plugins_root)
        self.plugins: list[LoadedPlugin] = []
        self._scanned = False

    def scan(self) -> None:
        """Idempotent. Safe to call multiple times."""
        if self._scanned:
            return
        self._scanned = True
        if not os.path.isdir(self._plugins_root):
            return
        for entry in sorted(os.listdir(self._plugins_root)):
            sub = os.path.join(self._plugins_root, entry)
            if not os.path.isdir(sub):                        continue
            if entry.startswith(".") or entry.startswith("_"): continue
            if not os.path.isfile(os.path.join(sub, "plugin.json")): continue
            self._load_one(sub)

    def _load_one(self, plugin_dir: str) -> None:
        try:
            manifest = load_manifest(plugin_dir)
        except ManifestError as e:
            print(f"[PluginLoader] {e}", file=sys.stderr)
            return

        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        pkg_key    = f"vf_plugin_{manifest.plugin_id}"
        entry_path = os.path.join(plugin_dir, manifest.entry_module + ".py")

        if not os.path.isfile(entry_path):
            self._record_error(manifest, f"entry_module not found: {entry_path}")
            return

        try:
            spec   = importlib.util.spec_from_file_location(pkg_key, entry_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[pkg_key] = module
            spec.loader.exec_module(module)
        except Exception:
            self._record_error(manifest, traceback.format_exc())
            return

        cls = getattr(module, manifest.panel_class, None)
        if cls is None:
            self._record_error(manifest,
                f"Class {manifest.panel_class!r} not in {manifest.entry_module}")
            return

        from VisionForge.app.plugin_sdk.base import TaskPanel
        if not (isinstance(cls, type) and issubclass(cls, TaskPanel)):
            self._record_error(manifest,
                f"{manifest.panel_class} must subclass TaskPanel")
            return

        self.plugins.append(LoadedPlugin(manifest=manifest, panel_cls=cls))
        print(f"[PluginLoader] Loaded '{manifest.name}' ({manifest.plugin_id})")

    def _record_error(self, manifest: PluginManifest, msg: str) -> None:
        print(f"[PluginLoader:{manifest.plugin_id}] {msg}", file=sys.stderr)
        self.plugins.append(LoadedPlugin(
            manifest=manifest, panel_cls=None, error=msg
        ))


# ── Module-level singleton ────────────────────────────────────────────────────
_LOADER = None

def get_plugin_loader() -> PluginLoader:
    """Return process-wide singleton. Creates + configures on first call."""
    global _LOADER
    if _LOADER is None:
        # app/plugin_sdk/loader.py → app/plugin_sdk → app → repo root
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
        )
        _LOADER = PluginLoader(os.path.join(repo_root, "plugins"))
    return _LOADER
```

**Discovery rules** (folder is processed only if ALL are true):
- Is a directory under `plugins/`
- Does NOT start with `.` or `_`
- Contains `plugin.json`

Sorted alphabetically — prefix folders with `01_`, `02_` to control sidebar order.

**sys.path note**: Each plugin folder is prepended once. Plugin code may import local modules by bare name (`import processor`), sub-packages by dot notation (`from core.utils import X`), and SDK / platform code by full path (`from VisionForge.app.plugin_sdk import TaskPanel`).

**Synthetic package keys**: Each plugin's entry module is registered as `vf_plugin_<plugin_id>` in `sys.modules`, preventing collisions between two plugins that both have a `panel.py`.

### 4.5 `utils.py`

```python
import os, cv2, numpy as np

def save_frame(frame_rgb: np.ndarray, filepath: str) -> bool:
    """
    Write a HxWx3 uint8 RGB numpy array to <filepath> as PNG (or
    whichever format the suffix indicates). Creates parent dirs.
    Returns True on success.
    """
    if frame_rgb is None or frame_rgb.size == 0:
        return False
    os.makedirs(os.path.dirname(os.path.abspath(filepath)) or ".", exist_ok=True)
    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    return bool(cv2.imwrite(filepath, bgr))


def resolve_path(plugin_file: str, relative_path: str) -> str:
    """
    Resolve <relative_path> against the directory containing <plugin_file>.

    Typical usage (at module level in a plugin file):
        WEIGHTS = resolve_path(__file__, "weights/best.pt")
    """
    base = os.path.dirname(os.path.abspath(plugin_file))
    return os.path.abspath(os.path.join(base, relative_path))
```

### 4.6 `mocks.py`

`MockCameraClient` and `MockArmController` are `QThread` subclasses that emit the same signals with the same payload shapes as the real classes.

```python
class MockCameraClient(QThread):
    frame_received     = Signal(QImage)
    raw_frame_received = Signal(object, dict)   # np.ndarray RGB, meta
    connection_changed = Signal(bool)
    fps_updated        = Signal(float)
    resolution_updated = Signal(int, int)

    def __init__(self, source: str = None, fps: float = 30.0, parent=None):
        """
        source:
            None / "synthetic"  → 640×480 RGB checkerboard pattern
            path to image file  → loops the still at <fps>
            path to video file  → streams the video, loops
            path to directory   → iterates .jpg/.png files alphabetically
        """
        ...

    def send_params(self, params: dict) -> dict:
        return {"status": "ok", "echo": params}

    def stop(self): ...
    def cleanup(self): self.stop(); self.wait(2000)


class MockArmController(QThread):
    connection_changed = Signal(bool)
    enabled_changed    = Signal(bool)
    position_updated   = Signal(float, float, float, float, float, float)
    error_occurred     = Signal(str)
    scan_state_changed = Signal(bool)

    def __init__(self, parent=None): ...

    # Emit gentle oscillating position_updated every 100 ms (for live UI testing)
    def run(self): ...

    # All methods below are no-ops / stubs
    def get_position(self):
        return 0, [400.0, 0.0, 200.0, -180.0, 0.0, 0.0]

    def set_servo_cartesian(self, pose, mvvelo=100, mvacc=500): ...
    def send_servo_cartesian(self, pose, mvvelo=100, mvacc=500): ...
    def start_valve_scan(self, pos, amplitude_mm, speed_mmps): ...
    def stop_valve_scan(self): ...
    def go_zero_start(self): ...
    def go_initial_start(self): ...
    def reset_arm(self): ...
    def cleanup(self): self.stop(); self.wait(2000)
```

The mock method surface mirrors every public method of `ArmController` used by existing task panels (`app/tasks/*/panel.py`).

### 4.7 `dev_runner.py`

```
python -m VisionForge.app.plugin_sdk.dev_runner <plugin_folder>
       [--camera IP]      use real CameraClient at <ip>:5555/5556
       [--arm IP]         use real ArmController at <ip>
       [--source PATH]    frame source for mock: dir | video | image
       [--fps FLOAT]      mock camera fps (default 30)
       [--headless]       no window; run --frames frames then exit
       [--frames INT]     frame count for headless (default 60)
```

| `--camera` | `--arm` | `self._cam` | `self._arm` |
|---|---|---|---|
| set | set | `CameraClient(ip)` | `ArmController(ip)` |
| set | unset | `CameraClient(ip)` | `MockArmController()` |
| unset | set | `MockCameraClient(source, fps)` | `ArmController(ip)` |
| unset | unset | `MockCameraClient(source, fps)` | `MockArmController()` |

**Runner flow**:
1. Parse args.
2. Create `QApplication`, apply `app/styles/theme.py` stylesheet.
3. Add repo/sdk root to `sys.path` (3-line guard so it works from any cwd).
4. Build camera + arm (real or mock); call `.start()`.
5. `load_manifest(plugin_folder)` → import `panel_class`.
6. Instantiate: `panel = PanelClass(camera_client=cam, arm_controller=arm, plugin_dir=manifest.plugin_dir)`; call `panel.on_attach()`.
7. Wrap in a minimal `QMainWindow` (title = manifest.name); show it.
8. On close: `panel.cleanup()`, `cam.cleanup()`, `arm.cleanup()`, `app.quit()`.
9. Headless mode: skip window; `QTimer.singleShot(frames/fps * 1000, app.quit)`.

---

## 5. Plugin Manifest Specification

### 5.1 Required fields

| Key | Type | Description | Example |
|---|---|---|---|
| `plugin_id` | string | Unique slug `[a-z0-9_]+`. Used as synthetic package name in `sys.modules`. | `"frame_diff_demo"` |
| `name` | string | Sidebar label. | `"Frame Difference"` |
| `icon` | string | Single Unicode glyph for sidebar. | `"◈"` |
| `version` | string | Plugin version. | `"1.0.0"` |
| `entry_module` | string | Python filename (no `.py`) containing the panel class. | `"panel"` |
| `panel_class` | string | Class name in `entry_module`. Must subclass `TaskPanel`. | `"FrameDiffPanel"` |

### 5.2 Optional fields

| Key | Type | Default | Description |
|---|---|---|---|
| `description` | string | `""` | Human-readable summary (shown in tooltip). |
| `author` | string | `""` | Free-form. |
| `requires` | array of strings | `[]` | Python package names — informational only. |
| `sdk_min` | string | `"1.0.0"` | Minimum SDK version known to work. Loader logs warning but still loads. |

### 5.3 Full example

```json
{
  "plugin_id":    "frame_diff_demo",
  "name":         "Frame Difference",
  "icon":         "◈",
  "version":      "0.1.0",
  "entry_module": "panel",
  "panel_class":  "FrameDiffPanel",
  "description":  "Highlights pixel-level changes between consecutive frames.",
  "author":       "Marwen Dhifi",
  "requires":     ["opencv-python", "numpy"],
  "sdk_min":      "1.0.0"
}
```

---

## 6. Plugin Loader — Behavioural Detail

### Discovery algorithm

```
for entry in sorted(os.listdir(plugins_root)):
    if not a directory:                    skip
    if starts with '.' or '_':            skip   # hidden / vendored / template
    if no plugin.json:                     skip
    _load_one(entry)
```

### Error handling

| Failure | Reaction |
|---|---|
| Missing `plugin.json` | Folder skipped silently. |
| Invalid JSON | `ManifestError` printed to stderr; folder skipped. |
| Missing required key | `ManifestError` printed; folder skipped. |
| Entry module `.py` not found | `LoadedPlugin(error=...)` recorded. |
| Import raises | `LoadedPlugin(error=traceback)` recorded. |
| `panel_class` missing or not `TaskPanel` subclass | `LoadedPlugin(error=...)` recorded. |
| Exception in `panel.__init__` (in MainWindow) | Caught by MainWindow; logged; sidebar entry disabled. |

**The platform never crashes due to a broken plugin.**

### Import strategies available to plugin code

| Style | Example | Reason it works |
|---|---|---|
| Local bare import | `import processor` | Plugin folder is on `sys.path`. |
| Local sub-package | `from core.utils import helper` | Plugin folder is on `sys.path`. |
| SDK absolute | `from VisionForge.app.plugin_sdk import TaskPanel` | VisionForge package always on `sys.path`. |
| Platform core | `from VisionForge.app.core.camera_client import CameraClient` | Same — identical path in dev zip and platform. |

Relative imports (`from .processor import X`) are **not supported** — the loader does not register the plugin as a package.

---

## 7. Platform Modification Specification

### 7.1 `app/main_window.py`

**Location of change A**: `_setup_ui` method, immediately after line 96 (`self._stack.addWidget(self._tracker_panel)`).

**Insert**:

```python
# ── Dynamic plugin panels ────────────────────────────────────────────────
from VisionForge.app.plugin_sdk.loader import get_plugin_loader
self._plugin_panels: dict[str, "TaskPanel"] = {}
self._plugin_indices: dict[str, int] = {}

for lp in get_plugin_loader().plugins:
    if lp.error or lp.panel_cls is None:
        continue
    try:
        panel = lp.panel_cls(
            camera_client  = self._cam,
            arm_controller = self._arm,
            plugin_dir     = lp.manifest.plugin_dir,
        )
        panel.on_attach()
    except Exception:
        import traceback
        print(f"[MainWindow] Plugin '{lp.manifest.plugin_id}' failed to init:")
        traceback.print_exc()
        continue
    idx = self._stack.addWidget(panel)
    self._plugin_panels[lp.manifest.plugin_id]  = panel
    self._plugin_indices[lp.manifest.plugin_id] = idx
```

**Note**: The `Sidebar(...)` instantiation (line 71) must be moved to AFTER this block so `self._plugin_indices` is populated when building sidebar items (see 7.2).

**Location of change B**: `_attach_camera` method, end of body (after line 151).

**Append**:

```python
for panel in self._plugin_panels.values():
    panel._cam = cam
```

**Location of change C**: `_attach_arm` method, end of body (after line 166).

**Append**:

```python
for panel in self._plugin_panels.values():
    panel._arm = arm
```

**Location of change D**: `closeEvent` method, after `self._tracker_panel.cleanup()`.

**Insert**:

```python
for pid, panel in self._plugin_panels.items():
    try:
        panel.cleanup()
    except Exception as e:
        print(f"[MainWindow] cleanup failed for plugin {pid}: {e}")
```

### 7.2 `app/widgets/sidebar.py`

**Change 1** — class-level `_TASK_INDICES` (line 288):

Remove:
```python
_TASK_INDICES = {it["index"] for it in _TASK_ITEMS}
```

**Change 2** — `__init__` signature (line 290):

```python
def __init__(self, parent=None, plugin_items: list = None):
    super().__init__(parent)
    self._nav_btns:  list = []
    self._sub_btns:  list = []
    self._collapsed  = False
    self._task_items = list(_TASK_ITEMS) + list(plugin_items or [])
    self._task_indices = {it["index"] for it in self._task_items}
    self._nav_w      = _nav_width(self._task_items)
    self._setup_ui()
```

**Change 3** — `_nav_width` function signature (line 44):

```python
def _nav_width(task_items: list = _TASK_ITEMS) -> int:
    fm = QFontMetrics(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
    all_labels = [it["label"] for it in _TOP_ITEMS + task_items] + ["Tasks"]
    max_text = max(fm.horizontalAdvance(lbl) for lbl in all_labels)
    return _LABEL_X + max_text + _RIGHT_PAD + 18
```

**Change 4** — loop in `_setup_ui` (line 333):

```python
for item in self._task_items:      # was: _TASK_ITEMS
```

**Change 5** — consumer of `_TASK_INDICES` (line ~380):

```python
is_task = index in self._task_indices   # was: self._TASK_INDICES
```

**In `MainWindow._setup_ui`**, build sidebar after plugin panels are known:

```python
plugin_items = [
    {"icon": lp.manifest.icon, "label": lp.manifest.name,
     "index": self._plugin_indices[lp.manifest.plugin_id]}
    for lp in get_plugin_loader().plugins
    if not lp.error and lp.manifest.plugin_id in self._plugin_indices
]
self._sidebar = Sidebar(plugin_items=plugin_items)
```

### 7.3 `app/splash.py`

**Change** — `_on_loader_finished` method (line 177):

```python
def _on_loader_finished(self):
    self._bar.setValue(96)
    self._status.setText("Discovering plugins…")
    from VisionForge.app.plugin_sdk.loader import get_plugin_loader
    try:
        get_plugin_loader().scan()
    except Exception as e:
        print(f"[SplashScreen] Plugin scan error: {e}")
    self._bar.setValue(100)
    self._status.setText("Ready.")
    QTimer.singleShot(350, self._finish)
```

The import of `ModelLoader` at line 16 is **unchanged**.

---

## 8. Dev Runner Specification

Full CLI grammar:

```
python -m VisionForge.app.plugin_sdk.dev_runner <plugin_folder>
       [--camera IP]
       [--arm IP]
       [--source PATH]
       [--fps FLOAT]
       [--headless]
       [--frames INT]
```

Hardware matrix: see §4.7 table.

**Headless CI smoke test**:

```bash
python -m VisionForge.app.plugin_sdk.dev_runner plugins/example_difference \
    --headless --frames 30
```
Expected: exits 0 in ~1 s; any exception in `process()` causes exit code 1.

**Real-hardware smoke test** (recommended before deploying to platform):

```bash
python -m VisionForge.app.plugin_sdk.dev_runner plugins/my_plugin \
    --camera 192.168.1.100 --arm 192.168.1.200
```
Plugin uses identical code paths to the live platform.

---

## 9. Zip Packaging Specification

### Output layout

```
visionforge-sdk-<version>/
├── README.md
├── requirements-sdk.txt          # pyside6, numpy, opencv-python, pyzmq, xarm-python-sdk
├── run.bat                       # python -m VisionForge.app.plugin_sdk.dev_runner %*
├── run.sh                        # #!/bin/sh; python3 -m ...
├── VisionForge/
│   ├── __init__.py               # empty
│   └── app/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── camera_client.py  # verbatim from repo
│       │   └── arm_controller.py # verbatim from repo
│       ├── styles/
│       │   ├── __init__.py
│       │   └── theme.py          # for dev_runner stylesheet
│       └── plugin_sdk/           # verbatim from repo
│           ├── __init__.py
│           ├── base.py
│           ├── manifest.py
│           ├── loader.py
│           ├── utils.py
│           ├── mocks.py
│           └── dev_runner.py
├── plugins/
│   ├── .gitkeep
│   └── example_difference/
│       ├── plugin.json
│       ├── panel.py
│       ├── processor.py
│       └── README.md
└── docs/
    └── plugin_sdk.md
```

### Build script (`tools/build_sdk_zip.py`)

Reads `app/plugin_sdk/__init__.__version__` → derives zip name. Copies the listed paths into the zip under the `visionforge-sdk-<version>/` prefix. Run manually: `python tools/build_sdk_zip.py`.

### Version lockstep

- `app/plugin_sdk/__init__.py` contains `__version__ = "1.0.0"`.
- Zip filename = `visionforge-sdk-1.0.0.zip`.
- Folder inside zip = `visionforge-sdk-1.0.0/`.

---

## 10. Developer Workflow (Step-by-Step)

### Step 1 — Get the SDK

```
unzip visionforge-sdk-1.0.0.zip
cd visionforge-sdk-1.0.0
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-sdk.txt
```

### Step 2 — Copy the template

```
xcopy plugins\example_difference plugins\my_plugin /E /I
```

Edit `plugins\my_plugin\plugin.json`:
- Set `plugin_id`, `name`, `icon`, `panel_class` to your values.

### Step 3 — Write your processor

```python
# plugins/my_plugin/processor.py
import cv2, numpy as np
from PySide6.QtGui import QImage
from VisionForge.app.plugin_sdk import TaskProcessor

class MyProcessor(TaskProcessor):

    def process(self, frame_rgb: np.ndarray, meta: dict):
        # frame_rgb: HxWx3 uint8 RGB — identical whether mock or real camera
        result = {"shape": frame_rgb.shape}
        h, w = frame_rgb.shape[:2]
        qimg = QImage(frame_rgb.data, w, h, 3*w,
                      QImage.Format.Format_RGB888).copy()
        return qimg, result
```

### Step 4 — Write your panel

```python
# plugins/my_plugin/panel.py
from PySide6.QtWidgets import QVBoxLayout, QLabel
from PySide6.QtGui     import QPixmap
from VisionForge.app.plugin_sdk import TaskPanel
from processor import MyProcessor   # local import

class MyPanel(TaskPanel):

    def on_attach(self):
        lo = QVBoxLayout(self)
        self._feed  = QLabel("Waiting…")
        self._info  = QLabel("")
        lo.addWidget(self._feed)
        lo.addWidget(self._info)

        self._processor = MyProcessor()
        self._processor.display_ready.connect(
            lambda img: self._feed.setPixmap(QPixmap.fromImage(img)))
        self._processor.result_ready.connect(
            lambda r: self._info.setText(str(r)))

        if self._arm:
            self._arm.position_updated.connect(self._on_arm)

    def cleanup(self):
        if self._processor:
            self._processor.stop()

    def _on_arm(self, x, y, z, r, p, yaw):
        self.setWindowTitle(f"X:{x:.0f} Y:{y:.0f} Z:{z:.0f}")
```

### Step 5 — Test with mocks

```powershell
python -m VisionForge.app.plugin_sdk.dev_runner plugins\my_plugin
```

### Step 6 — Test with real hardware

```powershell
python -m VisionForge.app.plugin_sdk.dev_runner plugins\my_plugin `
    --camera 192.168.1.100 --arm 192.168.1.200
```

The plugin code is identical to what will run inside the platform. If this works, the platform will work.

### Step 7 — Deploy to VisionForge

Copy `plugins\my_plugin\` into `D:\ProjectDAAD\Project1_Number_Detection_Arm_Movement\VisionForge\plugins\`.

Start VisionForge. The sidebar Tasks group shows your plugin. No other changes needed.

---

## 11. Template Plugin (`plugins/example_difference/`)

### Purpose

Demonstrate every SDK touchpoint in the least code possible. Acts as both a verification target and a starting template.

### What it does

Computes `cv2.absdiff` between consecutive frames. When arm is connected, overlays TCP position. Clicking the feed saves the current frame to `captures/<timestamp>.png` via `save_frame`.

### What each part demonstrates

| Element | Demonstrates |
|---|---|
| `plugin.json` | All required + most optional manifest fields. |
| `on_attach()` | UI construction, processor wiring, `self._cam` / `self._arm` signals. |
| `process()` | `frame_rgb` in → `(QImage, result)` out. |
| Click handler | `save_frame` + `resolve_path` usage. |
| `cleanup()` | Proper processor shutdown. |
| `README.md` | Annotated "what to change" guide for cloning. |

---

## 12. Implementation Order

Each phase produces a verifiable artefact. Do not start the next phase until the current passes.

| Phase | Work | Verification |
|---|---|---|
| 1 | `app/plugin_sdk/__init__.py` + empty stubs for all files | `python -c "from VisionForge.app.plugin_sdk import __version__"` |
| 2 | `manifest.py` + `utils.py` | Round-trip a hand-written plugin.json; `save_frame` writes a PNG |
| 3 | `base.py` (`TaskPanel`, `TaskProcessor`) | 10-line throwaway driver: mock frames → processor → `display_ready` fires |
| 4 | `mocks.py` | Small driver: connect to mock signals, print frames + arm poses |
| 5 | `dev_runner.py` (mocks path only) | `dev_runner plugins/example_difference` opens a window |
| 6 | `dev_runner.py` real hardware path (`--camera`, `--arm`) | `dev_runner --camera <ip> --arm <ip>` shows live frames |
| 7 | `loader.py` (`PluginLoader`, `get_plugin_loader`) | `get_plugin_loader().scan(); print(loader.plugins)` lists example |
| 8 | `app/splash.py` change | App boots; splash still works; plugin scan runs |
| 9 | `app/widgets/sidebar.py` changes | Sidebar accepts `plugin_items` arg; extra entries appear |
| 10 | `app/main_window.py` changes | Full app: example plugin appears in sidebar and stack; reconnect + close work |
| 11 | Polish `example_difference` (click-save, arm overlay, README) | Developer following only the README can clone and run |
| 12 | `tools/build_sdk_zip.py` | Extract zip to temp dir; install deps; `dev_runner` on example works |
| 13 | `docs/plugin_sdk.md` | — |

---

## 13. Verification Plan

| Item | Test |
|---|---|
| Manifest parser | Round-trip valid JSON; assert each missing key raises `ManifestError`. |
| `save_frame` | Save 100×100 RGB; read back with `cv2.imread`; assert shape = (100,100,3). |
| `TaskProcessor.submit_frame` | Push 1000 frames as fast as possible; queue size never exceeds 1. |
| `MockCameraClient` synthetic | After `start()`, `raw_frame_received` fires within 200 ms with HxWx3 uint8. |
| `MockArmController` | After `start()`, `position_updated` fires; `get_position()` returns `(0, [...])`. |
| `PluginLoader.scan` | Loads example correctly; broken `plugin.json` recorded as error, no exception. |
| `dev_runner --headless --frames 30` | Exits 0 in ~2 s. |
| Platform sidebar | After integration, 3 legacy entries + N plugin entries appear; each opens its panel. |
| Platform shutdown | `closeEvent` runs all `cleanup()` calls; no Qt warnings or unhandled exceptions. |
| Real-hardware smoke | `dev_runner --camera <ip> --arm <ip>` shows live frames + live arm position. |

A `tests/` directory at repo root holds these as standalone scripts; `python tests/run_all.py` runs them all.

---

## 14. Constraints and Non-Goals

The SDK deliberately does NOT:

1. **Sandbox plugin code** — plugins run with full process privileges.
2. **Manage plugin dependencies** — `requires` is informational; `pip install` is the developer's job.
3. **Provide a permission system** — any plugin can call any method on `self._cam` or `self._arm`.
4. **Hot-reload** — plugins are scanned once at startup; adding one requires restart.
5. **Provide styled UI widgets** — `TaskPanel.setup_ui` has full Qt freedom; no opinionated layout imposed.
6. **Wrap or proxy hardware** — `self._cam` IS the real `CameraClient`; same signals, same methods.
7. **Refactor existing tasks** — `seven_segment`, `valve_orientation`, `module_tracker` remain hardcoded in `MainWindow`.
8. **Cross-process plugins** — everything runs in one Python process.

---

## 15. Future Extensions (Out of Scope for v1)

- **Hot-reload**: `watchdog` on `plugins/`; rescan on change; swap widget in stack.
- **Permissions in manifest**: `"permissions": ["camera.read", "arm.move"]`; enforce in loader.
- **Shared styled widgets**: `app/plugin_sdk/widgets.py` — `FeedWidget`, `StatusBadge`, `ParamSlider`.
- **InfluxDB helper**: thin convenience over `InfluxDBManager` for plugins that want to log.
- **Per-plugin state directory**: `self.state_dir` → `<plugins_root>/<plugin_id>/state/`.
- **Migrate existing tasks** to the SDK once proven; removes special-casing in `MainWindow`.
- **PyPI publication**: `pip install visionforge-sdk` once the API is stable.

---

## 16. Critical File Paths

| File | Role |
|---|---|
| `app/plugin_sdk/base.py` | `TaskPanel`, `TaskProcessor` — the developer-facing API |
| `app/plugin_sdk/loader.py` | `PluginLoader`, `get_plugin_loader` — platform integration point |
| `app/plugin_sdk/dev_runner.py` | Standalone test CLI |
| `app/plugin_sdk/mocks.py` | `MockCameraClient`, `MockArmController` |
| `app/plugin_sdk/manifest.py` | `PluginManifest`, `load_manifest` |
| `app/plugin_sdk/utils.py` | `save_frame`, `resolve_path` |
| `app/main_window.py` | Modified: plugin panel instantiation + wiring (lines 78–96, 136–166, 230–240) |
| `app/widgets/sidebar.py` | Modified: dynamic task items (lines 26–30, 288, 290, 333, ~380) |
| `app/splash.py` | Modified: plugin scan trigger (line 177 `_on_loader_finished`) |
| `plugins/example_difference/` | Template plugin — first thing to run in `dev_runner` |
| `tools/build_sdk_zip.py` | Produces `visionforge-sdk-<version>.zip` |
