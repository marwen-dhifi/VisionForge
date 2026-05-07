"""
MainWindow — the main application shell of VisionForge.

Structure:
  ┌──────────────────────────────────────────────┐
  │  TopBar  (always visible)                     │
  ├───────────┬──────────────────────────────────┤
  │  Sidebar  │  QStackedWidget (pages)           │
  │  (col.)   │   0 → CameraPanel                │
  │           │   1 → ArmPanel                   │
  └───────────┴──────────────────────────────────┘
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget
)
from PySide6.QtCore import Qt

from VisionForge.app.widgets.top_bar      import TopBar
from VisionForge.app.widgets.sidebar      import Sidebar
from VisionForge.app.widgets.camera_panel import CameraPanel
from VisionForge.app.widgets.arm_panel    import ArmPanel
from VisionForge.app.core.gamepad_controller import GamepadController
from VisionForge.app.tasks.valve_orientation.panel import ValveOrientationPanel
from VisionForge.app.tasks.seven_segment.panel    import SevenSegmentPanel
from VisionForge.app.tasks.module_tracker.panel   import ModuleTrackerPanel
from VisionForge.app.plugin_sdk.loader import get_plugin_loader


class MainWindow(QMainWindow):

    def __init__(self, camera_client=None, arm_controller=None,
                 cam_ip: str = "", arm_ip: str = ""):
        super().__init__()
        self._cam     = camera_client
        self._arm     = arm_controller
        self._cam_ip  = cam_ip
        self._arm_ip  = arm_ip

        self.setWindowTitle("VisionForge v1.0")
        self.setMinimumSize(1100, 700)

        self._gamepad = GamepadController(arm_controller=self._arm)
        self._gamepad.start()

        self._setup_ui()
        self._wire_signals()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        # Root container (gives us a solid dark background for the whole window)
        root = QWidget()
        root.setStyleSheet("background-color: #060612;")
        self.setCentralWidget(root)

        root_lo = QVBoxLayout(root)
        root_lo.setContentsMargins(0, 0, 0, 0)
        root_lo.setSpacing(0)

        # ── Top bar ──────────────────────────────────────────────────────────
        self._topbar = TopBar()
        root_lo.addWidget(self._topbar)

        # ── Body: sidebar + content ───────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background-color: #060612;")
        body_lo = QHBoxLayout(body)
        body_lo.setContentsMargins(0, 0, 0, 0)
        body_lo.setSpacing(0)

        # ── Page stack ───────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background-color: #060612;")

        self._camera_panel = CameraPanel(camera_client=self._cam)
        self._arm_panel    = ArmPanel(
            camera_client  = self._cam,
            arm_controller = self._arm,
        )
        self._valve_panel   = ValveOrientationPanel(camera_client=self._cam,
                                                    arm_controller=self._arm)
        self._seg_panel     = SevenSegmentPanel(camera_client=self._cam,
                                                arm_controller=self._arm)
        self._tracker_panel = ModuleTrackerPanel(
            camera_client=self._cam,
            arm_controller=self._arm,
        )

        self._stack.addWidget(self._camera_panel)   # index 0
        self._stack.addWidget(self._arm_panel)      # index 1
        self._stack.addWidget(self._valve_panel)    # index 2
        self._stack.addWidget(self._seg_panel)      # index 3
        self._stack.addWidget(self._tracker_panel)  # index 4

        # ── Plugin panels (indices 5+) ────────────────────────────────────────
        self._plugin_panels: list = []
        _plugin_sidebar_items: list = []

        for descriptor in get_plugin_loader().plugins:
            try:
                panel = descriptor.PanelClass(
                    camera_client=self._cam,
                    arm_controller=self._arm,
                )
                panel.on_attach()
                idx = self._stack.addWidget(panel)
                self._plugin_panels.append(panel)
                _plugin_sidebar_items.append({
                    "icon":  descriptor.manifest.icon,
                    "label": descriptor.manifest.label,
                    "index": idx,
                })
            except Exception as exc:
                print(
                    f"[MainWindow] Plugin '{descriptor.manifest.name}' failed to init: {exc}",
                    flush=True,
                )

        # Sidebar built AFTER all plugin indices are known
        self._sidebar = Sidebar(plugin_items=_plugin_sidebar_items)
        body_lo.addWidget(self._sidebar)
        body_lo.addWidget(self._stack, 1)
        root_lo.addWidget(body, 1)

    # ── Wiring ────────────────────────────────────────────────────────────────

    def _wire_signals(self):
        # Sidebar page switching
        self._sidebar.page_changed.connect(self._stack.setCurrentIndex)

        # Camera status
        if self._cam:
            self._cam.connection_changed.connect(
                self._topbar.cam_indicator.set_connected
            )
            self._topbar.cam_indicator.set_connected(True)
        else:
            self._topbar.cam_indicator.set_connected(False)

        # Arm status
        if self._arm:
            self._attach_arm(self._arm)
            self._topbar.arm_indicator.set_connected(True)   # arm was confirmed connected at startup
        else:
            self._topbar.arm_indicator.set_connected(False)

        # Gamepad → UI (arm wired inside _attach_arm)
        self._arm_panel.attach_gamepad(self._gamepad)

        # Reconnect buttons
        self._topbar.cam_indicator.reconnect_requested.connect(
            self._reconnect_camera
        )
        self._topbar.arm_indicator.reconnect_requested.connect(
            self._reconnect_arm
        )

    # ── Camera wiring ─────────────────────────────────────────────────────────

    def _attach_camera(self, cam):
        """Wire a new CameraClient to all UI components."""
        self._cam = cam
        cam.connection_changed.connect(self._topbar.cam_indicator.set_connected)
        self._camera_panel.attach_camera(cam)
        self._arm_panel.attach_camera(cam)
        # Panels without attach_camera just store _cam and use it in showEvent
        self._valve_panel._cam  = cam
        self._seg_panel._cam    = cam
        self._tracker_panel._cam = cam
        # If tracker panel is already visible, connect it now
        if self._tracker_panel.isVisible() and self._tracker_panel._cam:
            try:
                cam.raw_frame_received.connect(self._tracker_panel._processor.submit_frame)
            except Exception:
                pass
        for panel in self._plugin_panels:
            try: panel.attach_camera(cam)
            except Exception: pass

    # ── Arm wiring ────────────────────────────────────────────────────────────

    def _attach_arm(self, arm):
        """Wire a (new or existing) ArmController to all UI components."""
        self._arm = arm
        arm.connection_changed.connect(self._topbar.arm_indicator.set_connected)
        arm.enabled_changed.connect(self._on_arm_enabled)
        self._gamepad.set_arm(arm)
        self._arm_panel.attach_arm(arm)
        self._valve_panel.set_arm(arm)
        self._seg_panel.set_arm(arm)
        self._tracker_panel._arm = arm
        arm.position_updated.connect(self._tracker_panel._on_arm_position)
        arm.connection_changed.connect(self._tracker_panel._on_arm_connection_changed)
        for panel in self._plugin_panels:
            try: panel.attach_arm(arm)
            except Exception: pass

    # ── Reconnection ─────────────────────────────────────────────────────────

    def _on_arm_enabled(self, enabled: bool):
        if enabled:
            self._topbar.arm_indicator.set_connected(True)
        else:
            self._topbar.arm_indicator.set_warning("Not Enabled")

    def _reconnect_camera(self):
        """Reconnect the camera. If it was never connected, create a new client."""
        self._topbar.cam_indicator.set_warning("Reconnecting…")

        if self._cam is None:
            if not self._cam_ip:
                self._topbar.cam_indicator.set_connected(False)
                return
            from VisionForge.app.core.camera_client import CameraClient
            self._attach_camera(CameraClient(self._cam_ip))
            self._cam.start()
            return

        if self._cam.isRunning():
            def _on_cam_finished():
                try:
                    self._cam.finished.disconnect(_on_cam_finished)
                except Exception:
                    pass
                self._cam.start()
            self._cam.finished.connect(_on_cam_finished)
            self._cam.stop()
        else:
            self._cam.start()

    def _reconnect_arm(self):
        """Reconnect the arm. If it was never connected, create a new controller."""
        self._topbar.arm_indicator.set_warning("Reconnecting…")

        if self._arm is None:
            # Arm was not connected at startup — create a fresh controller now
            if not self._arm_ip:
                self._topbar.arm_indicator.set_connected(False)
                return
            from VisionForge.app.core.arm_controller import ArmController
            self._attach_arm(ArmController(self._arm_ip))
            self._arm.start()
            return

        # Arm existed before — stop then restart
        if self._arm.isRunning():
            def _on_arm_finished():
                try:
                    self._arm.finished.disconnect(_on_arm_finished)
                except Exception:
                    pass
                self._arm.start()
            self._arm.finished.connect(_on_arm_finished)
            self._arm.stop()
        else:
            self._arm.start()

    # ── Close ─────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._gamepad.stop()
        self._gamepad.wait(1000)
        self._valve_panel.cleanup()
        self._seg_panel.cleanup()
        self._tracker_panel.cleanup()
        for panel in self._plugin_panels:
            try: panel.cleanup()
            except Exception: pass
        if self._cam:
            self._cam.cleanup()
        if self._arm:
            self._arm.cleanup()
        event.accept()