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
                 cam_ip: str = "", arm_ip: str = "", opc_port: int = 48050):
        super().__init__()
        self._cam               = camera_client
        self._arm               = arm_controller
        self._cam_ip            = cam_ip
        self._arm_ip            = arm_ip
        self._opc_port          = opc_port
        self._inspection_module = None
        self._last_pol_tab      = None

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

        # ── InspectionModule (owns OPC UA server, created before panels are stacked) ──
        from VisionForge.app.inspection.inspection_module import InspectionModule
        self._inspection_module = InspectionModule(opc_port=self._opc_port)

        self._stack.addWidget(self._camera_panel)   # index 0
        self._stack.addWidget(self._arm_panel)      # index 1
        self._stack.addWidget(
            self._try_wrap_panel(self._valve_panel,   'valve_orientation', 2))  # index 2
        self._stack.addWidget(
            self._try_wrap_panel(self._seg_panel,     'seven_segment',     3))  # index 3
        self._stack.addWidget(
            self._try_wrap_panel(self._tracker_panel, 'module_tracker',    4))  # index 4

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

                widget = panel
                if descriptor.ServiceClass is not None:
                    from VisionForge.app.inspection.inspection_tab      import InspectionTab
                    from VisionForge.app.inspection.service_aware_panel import ServiceAwareWrapper
                    try:
                        service = descriptor.ServiceClass()
                        svc_idx = self._stack.count()
                        self._connect_service_to_processor(panel, service)
                        self._inspection_module.register_service(service, svc_idx)
                        itab   = InspectionTab(service)
                        widget = ServiceAwareWrapper(
                            panel, itab, task_label=descriptor.manifest.label
                        )
                    except Exception:
                        import traceback
                        print(
                            f"[MainWindow] Plugin '{descriptor.manifest.name}' "
                            f"service init failed:\n{traceback.format_exc()}",
                            flush=True,
                        )
                        widget = panel

                idx = self._stack.addWidget(widget)
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

        if self._inspection_module._services:
            self._inspection_module.start_server()

        # Sidebar built AFTER all plugin indices are known
        self._sidebar = Sidebar(plugin_items=_plugin_sidebar_items)
        body_lo.addWidget(self._sidebar)
        body_lo.addWidget(self._stack, 1)
        root_lo.addWidget(body, 1)

    # ── Wiring ────────────────────────────────────────────────────────────────

    def _wire_signals(self):
        # Sidebar page switching (routed through guard for active-service confirmation)
        self._sidebar.page_changed.connect(self._on_page_change_requested)

        # Inspection module signals
        if self._inspection_module is not None:
            self._inspection_module.auto_switch_requested.connect(self._on_auto_switch)
            self._inspection_module.pol_control_changed.connect(self._on_pol_control_changed)

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

        # For task panels: update _cam, reset connection flag, then eagerly re-connect
        # processors that were already started (handles reconnect after disconnect).
        for panel in (self._valve_panel, self._seg_panel, self._tracker_panel):
            panel._cam = cam
            panel._submit_connected = False
            proc = getattr(panel, '_processor', None)
            if proc is not None and getattr(panel, '_processor_started', False):
                try:
                    cam.raw_frame_received.connect(proc.submit_frame)
                    panel._submit_connected = True
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

    # ── Navigation guard ─────────────────────────────────────────────────────

    def _on_page_change_requested(self, index: int) -> None:
        if self._inspection_module is None:
            self._do_switch(index)
            return

        active_tag = self._inspection_module.get_active_service_tag()
        if active_tag is None:
            self._do_switch(index)
            return

        active_idx  = self._inspection_module._service_stack_index.get(active_tag)
        current_idx = self._stack.currentIndex()

        if active_idx is not None and current_idx == active_idx and index != active_idx:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self,
                'Abort Inspection Service?',
                f'Inspection service "{active_tag}" is currently ACTIVE.\n'
                'Navigating away will send an ABORT command. Proceed?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                svc = self._inspection_module.get_service(active_tag)
                if svc is not None:
                    try:
                        svc.op_src_mode.attributes['StateOpOp'].set_value(True)
                        svc.state_machine.set_command_op(256)   # ABORT
                    except Exception as exc:
                        print(f'[MainWindow] ABORT command failed: {exc}', flush=True)
                self._do_switch(index)
        else:
            self._do_switch(index)

    def _do_switch(self, index: int) -> None:
        """Switch page stack and update sidebar visual without re-emitting page_changed."""
        self._stack.setCurrentIndex(index)
        try:
            self._sidebar.blockSignals(True)
            self._sidebar._select(index)
        finally:
            self._sidebar.blockSignals(False)

    def _on_auto_switch(self, index: int) -> None:
        """Called by InspectionModule when POL starts a service — switches without confirmation."""
        self._do_switch(index)

    def _on_pol_control_changed(self, active: bool) -> None:
        """Show/hide POL banner on the InspectionTab of the (last) active service."""
        if active:
            if self._inspection_module is None:
                return
            tag = self._inspection_module.get_active_service_tag()
            if tag is None:
                return
            idx = self._inspection_module._service_stack_index.get(tag)
            if idx is None:
                return
            widget = self._stack.widget(idx)
            tab = getattr(widget, '_inspection_tab', None)
            if tab and hasattr(tab, 'set_pol_banner'):
                self._last_pol_tab = tab
                tab.set_pol_banner(True)
        else:
            if self._last_pol_tab is not None:
                self._last_pol_tab.set_pol_banner(False)
                self._last_pol_tab = None

    def _try_wrap_panel(self, panel, task_name: str, stack_index: int):
        """
        Try to load service.py next to a built-in task panel.
        Returns ServiceAwareWrapper if a service class was found, panel unchanged otherwise.
        """
        import importlib.util
        from pathlib import Path

        svc_path = Path(__file__).resolve().parent / 'tasks' / task_name / 'service.py'
        if not svc_path.is_file():
            return panel

        try:
            from VisionForge.app.inspection.inspection_service import InspectionService
            from VisionForge.app.inspection.inspection_tab     import InspectionTab
            from VisionForge.app.inspection.service_aware_panel import ServiceAwareWrapper

            spec = importlib.util.spec_from_file_location(
                f'_vf_task_{task_name}_service', str(svc_path)
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            ServiceClass = next(
                (v for v in vars(mod).values()
                 if isinstance(v, type)
                 and issubclass(v, InspectionService)
                 and v is not InspectionService),
                None,
            )
            if ServiceClass is None:
                return panel

            service = ServiceClass()
            self._connect_service_to_processor(panel, service)
            self._inspection_module.register_service(service, stack_index)

            itab    = InspectionTab(service)
            wrapper = ServiceAwareWrapper(
                panel, itab,
                task_label=task_name.replace('_', ' ').title(),
            )
            print(f'[MainWindow] Loaded inspection service for task "{task_name}"', flush=True)
            return wrapper

        except Exception:
            import traceback
            print(
                f'[MainWindow] Failed to load service for "{task_name}":\n'
                f'{traceback.format_exc()}',
                flush=True,
            )
            return panel

    def _connect_service_to_processor(self, panel, service) -> None:
        """Connect panel processor's first available result signal → service.on_result."""
        proc = getattr(panel, '_processor', None)
        if proc is None:
            return
        for sig_name in ('result_ready', 'frame_ready', 'detections_ready'):
            sig = getattr(proc, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(service.on_result)
                except Exception as exc:
                    print(
                        f'[MainWindow] connect {sig_name} → on_result failed: {exc}',
                        flush=True,
                    )
                return

    # ── Close ─────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._inspection_module is not None:
            self._inspection_module.stop_server()
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