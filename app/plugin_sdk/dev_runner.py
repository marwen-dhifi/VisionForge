"""
VisionForge Plugin Dev Runner.

Run a plugin standalone against real hardware for development and testing.

Usage:
    python -m VisionForge.app.plugin_sdk.dev_runner <plugin_dir> --camera IP --arm IP

Both --camera and --arm are REQUIRED. Plugins always run against real hardware.

Options:
    --no-status     Hide the hardware status monitor window (shown by default)
    --no-config     Hide the camera configuration window (shown by default)

Example:
    python -m VisionForge.app.plugin_sdk.dev_runner plugins/my_plugin \\
        --camera 192.168.1.100 --arm 192.168.1.200
"""
import argparse
import importlib.util
import os
import sys


def _ensure_visionforge_on_path():
    this_file = os.path.abspath(__file__)
    sdk_dir   = os.path.dirname(this_file)
    app_dir   = os.path.dirname(sdk_dir)
    vf_dir    = os.path.dirname(app_dir)
    repo_root = os.path.dirname(vf_dir)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


# ── Hardware Status Window ────────────────────────────────────────────────────

def _build_status_window(camera, arm):
    """
    Floating monitor: live camera + arm status with reconnect and reset controls.
    Replicates the same state logic used by the main platform.
    """
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    )
    from PySide6.QtCore import Qt, QTimer, QPointF
    from PySide6.QtGui  import QFont, QPainter, QColor, QPen, QBrush

    C = {
        "bg":     "#060612",
        "card":   "#0C0C1E",
        "border": "#1A1A38",
        "accent": "#00CFFF",
        "green":  "#00E676",
        "red":    "#FF4466",
        "orange": "#FFB300",
        "text":   "#E8EAFF",
        "muted":  "#8890B8",
        "dim":    "#454878",
    }

    # ── Pulsing dot (matches arm_panel._Dot) ──────────────────────────────────

    class _Dot(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedSize(12, 12)
            self._color   = QColor(C["dim"])
            self._pulse_r = 0.0
            self._pulsing = False
            t = QTimer(self)
            t.timeout.connect(self._tick)
            t.start(30)

        def set(self, color: str, pulsing: bool = False):
            self._color   = QColor(color)
            self._pulsing = pulsing
            if not pulsing:
                self._pulse_r = 0.0
            self.update()

        def _tick(self):
            if self._pulsing:
                self._pulse_r = (self._pulse_r + 0.8) % 20
            self.update()

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx, cy = 6.0, 6.0
            if self._pulsing and self._pulse_r > 0:
                fade = max(0.0, 1.0 - self._pulse_r / 20)
                rc = QColor(self._color)
                rc.setAlpha(int(fade * 140))
                p.setPen(QPen(rc, 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), self._pulse_r * 0.4, self._pulse_r * 0.4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._color))
            p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)

    # ── Helper builders ───────────────────────────────────────────────────────

    def _card(parent_lo):
        f = QFrame()
        f.setStyleSheet(
            f"background: {C['card']}; border: 1px solid {C['border']}; border-radius: 8px;"
        )
        lo = QVBoxLayout(f)
        lo.setContentsMargins(12, 10, 12, 12)
        lo.setSpacing(5)
        parent_lo.addWidget(f)
        return lo, f

    def _section_title(lo, text):
        lbl = QLabel(text.upper())
        lbl.setFixedHeight(16)
        lbl.setStyleSheet(
            f"color: {C['dim']}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 2px; background: transparent; border: none;"
        )
        lo.addWidget(lbl)

    def _status_row(lo):
        """Dot + label + reconnect button in one horizontal row."""
        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        rlo = QHBoxLayout(row)
        rlo.setContentsMargins(0, 2, 0, 2)
        rlo.setSpacing(6)
        dot = _Dot()
        lbl = QLabel("Connecting…")
        lbl.setStyleSheet(
            f"color: {C['orange']}; font-size: 12px; font-weight: 600;"
            "background: transparent; border: none;"
        )
        btn = QPushButton("Reconnect")
        btn.setFixedHeight(20)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: #111128; color: {C['accent']};"
            f"border: 1px solid {C['accent']}; border-radius: 3px;"
            "font-size: 10px; padding: 0 8px; }}"
            f"QPushButton:hover {{ background: #1A1A38; }}"
        )
        btn.setVisible(False)
        rlo.addWidget(dot)
        rlo.addWidget(lbl, 1)
        rlo.addWidget(btn)
        lo.addWidget(row)
        return dot, lbl, btn

    def _kv_label(lo, key):
        row = QWidget()
        row.setFixedHeight(20)
        row.setStyleSheet("background: transparent; border: none;")
        rlo = QHBoxLayout(row)
        rlo.setContentsMargins(0, 0, 0, 0)
        rlo.setSpacing(0)
        k = QLabel(key)
        k.setFixedSize(72, 20)
        k.setStyleSheet(
            f"color: {C['dim']}; font-size: 11px;"
            "background: transparent; border: none;"
        )
        v = QLabel("—")
        v.setFixedSize(110, 20)
        v.setStyleSheet(
            f"color: {C['muted']}; font-size: 11px;"
            "background: transparent; border: none;"
        )
        rlo.addWidget(k)
        rlo.addWidget(v)
        lo.addWidget(row)
        return v

    # ── Window ────────────────────────────────────────────────────────────────

    win = QWidget()
    win.setWindowTitle("Dev Monitor — VisionForge")
    win.setMinimumSize(290, 460)
    win.resize(300, 560)
    win.setStyleSheet(f"background: {C['bg']};")
    win.setWindowFlags(
        Qt.WindowType.Window |
        Qt.WindowType.WindowStaysOnTopHint |
        Qt.WindowType.WindowCloseButtonHint
    )

    root = QVBoxLayout(win)
    root.setContentsMargins(10, 10, 10, 10)
    root.setSpacing(8)

    title = QLabel("⬡  Dev Monitor")
    title.setFixedHeight(28)
    title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    title.setStyleSheet(f"color: {C['accent']}; letter-spacing: 1px;")
    root.addWidget(title)

    # ── Camera card ───────────────────────────────────────────────────────────

    cam_lo, _ = _card(root)
    _section_title(cam_lo, "Camera")
    cam_dot, cam_lbl, cam_reconnect_btn = _status_row(cam_lo)
    fps_val = _kv_label(cam_lo, "FPS")
    res_val = _kv_label(cam_lo, "Resolution")

    def _on_cam_conn(connected: bool):
        if connected:
            cam_dot.set(C["green"], True)
            cam_lbl.setText("Connected")
            cam_lbl.setStyleSheet(
                f"color: {C['green']}; font-size: 12px; font-weight: 600;"
                "background: transparent; border: none;"
            )
            cam_reconnect_btn.setVisible(False)
        else:
            cam_dot.set(C["red"], False)
            cam_lbl.setText("Disconnected")
            cam_lbl.setStyleSheet(
                f"color: {C['red']}; font-size: 12px; font-weight: 600;"
                "background: transparent; border: none;"
            )
            cam_reconnect_btn.setVisible(True)
            fps_val.setText("—")

    def _reconnect_camera():
        cam_dot.set(C["orange"], True)
        cam_lbl.setText("Reconnecting…")
        cam_lbl.setStyleSheet(
            f"color: {C['orange']}; font-size: 12px; font-weight: 600;"
            "background: transparent; border: none;"
        )
        cam_reconnect_btn.setVisible(False)
        if camera.isRunning():
            def _on_cam_done():
                try:
                    camera.finished.disconnect(_on_cam_done)
                except Exception:
                    pass
                camera.start()
            camera.finished.connect(_on_cam_done)
            camera.stop()
        else:
            camera.start()

    cam_reconnect_btn.clicked.connect(_reconnect_camera)
    camera.connection_changed.connect(_on_cam_conn)
    camera.fps_updated.connect(lambda fps: fps_val.setText(f"{fps:.1f} Hz"))
    camera.resolution_updated.connect(lambda w, h: res_val.setText(f"{w} × {h}"))

    # ── Arm card ──────────────────────────────────────────────────────────────

    arm_lo, _ = _card(root)
    _section_title(arm_lo, "xArm")
    arm_dot, arm_lbl, arm_reconnect_btn = _status_row(arm_lo)

    x_val     = _kv_label(arm_lo, "X (mm)")
    y_val     = _kv_label(arm_lo, "Y (mm)")
    z_val     = _kv_label(arm_lo, "Z (mm)")
    roll_val  = _kv_label(arm_lo, "Roll °")
    pitch_val = _kv_label(arm_lo, "Pitch °")
    yaw_val   = _kv_label(arm_lo, "Yaw °")

    arm_reset_btn = QPushButton("Reset Arm")
    arm_reset_btn.setFixedHeight(24)
    arm_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    arm_reset_btn.setEnabled(False)
    arm_reset_btn.setStyleSheet(
        "QPushButton { background: #181830; color: #FF6B35;"
        "border: 1px solid #FF6B35; border-radius: 4px;"
        "font-size: 11px; font-weight: 600; padding: 0 10px; }"
        "QPushButton:hover:enabled { background: #22222A; }"
        "QPushButton:disabled { color: #2A2A48; border-color: #2A2A48; }"
    )
    arm_lo.addWidget(arm_reset_btn)

    # Position updates via signal (setText only — no layout impact)
    def _on_pos(x, y, z, roll, pitch, yaw):
        x_val.setText(f"{x:+.1f}")
        y_val.setText(f"{y:+.1f}")
        z_val.setText(f"{z:+.1f}")
        roll_val.setText(f"{roll:+.1f}")
        pitch_val.setText(f"{pitch:+.1f}")
        yaw_val.setText(f"{yaw:+.1f}")

    arm.position_updated.connect(_on_pos)

    # Poll-based arm state — same logic as arm_panel._ControlPanel._poll_arm()
    _last_arm_state = [None]

    def _poll_arm():
        raw = arm.get_arm()
        if raw is None or not getattr(raw, "connected", False):
            state = "disconnected"
        elif raw.error_code != 0:
            state = "not_enabled"
        else:
            state = "ready"

        if state == _last_arm_state[0]:
            return
        _last_arm_state[0] = state

        if state == "disconnected":
            arm_dot.set(C["red"], False)
            arm_lbl.setText("Disconnected")
            arm_lbl.setStyleSheet(
                f"color: {C['red']}; font-size: 12px; font-weight: 600;"
                "background: transparent; border: none;"
            )
            arm_reconnect_btn.setVisible(True)
            arm_reset_btn.setEnabled(False)
            for v in (x_val, y_val, z_val, roll_val, pitch_val, yaw_val):
                v.setText("—")
        elif state == "not_enabled":
            arm_dot.set(C["orange"], True)
            arm_lbl.setText("Not Enabled")
            arm_lbl.setStyleSheet(
                f"color: {C['orange']}; font-size: 12px; font-weight: 600;"
                "background: transparent; border: none;"
            )
            arm_reconnect_btn.setVisible(False)
            arm_reset_btn.setEnabled(True)
        else:
            arm_dot.set(C["green"], True)
            arm_lbl.setText("Ready")
            arm_lbl.setStyleSheet(
                f"color: {C['green']}; font-size: 12px; font-weight: 600;"
                "background: transparent; border: none;"
            )
            arm_reconnect_btn.setVisible(False)
            arm_reset_btn.setEnabled(True)

    arm_poll = QTimer(win)
    arm_poll.setInterval(1000)
    arm_poll.timeout.connect(_poll_arm)
    arm_poll.start()
    _poll_arm()

    def _reconnect_arm():
        arm_dot.set(C["orange"], True)
        arm_lbl.setText("Reconnecting…")
        arm_lbl.setStyleSheet(
            f"color: {C['orange']}; font-size: 12px; font-weight: 600;"
            "background: transparent; border: none;"
        )
        arm_reconnect_btn.setVisible(False)
        if arm.isRunning():
            def _on_arm_done():
                try:
                    arm.finished.disconnect(_on_arm_done)
                except Exception:
                    pass
                arm.start()
            arm.finished.connect(_on_arm_done)
            arm.stop()
        else:
            arm.start()

    def _reset_arm():
        arm.reset_arm()
        QTimer.singleShot(600, _poll_arm)

    arm_reconnect_btn.clicked.connect(_reconnect_arm)
    arm_reset_btn.clicked.connect(_reset_arm)

    return win


# ── Camera Configuration Window ──────────────────────────────────────────────

def _build_config_window(camera):
    """
    Floating camera configuration panel — identical controls to the main app.
    Wraps CameraConfigPanel and wires it to the live CameraClient.
    """
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
    from PySide6.QtCore    import Qt
    from PySide6.QtGui     import QFont
    from VisionForge.app.widgets.camera_config import CameraConfigPanel

    win = QWidget()
    win.setWindowTitle("Camera Configuration — VisionForge")
    win.setMinimumSize(360, 500)
    win.resize(400, 660)
    win.setStyleSheet("background: #060612;")
    win.setWindowFlags(
        Qt.WindowType.Window |
        Qt.WindowType.WindowStaysOnTopHint |
        Qt.WindowType.WindowCloseButtonHint
    )

    outer = QVBoxLayout(win)
    outer.setContentsMargins(10, 10, 10, 10)
    outer.setSpacing(6)

    title = QLabel("◈  Camera Configuration")
    title.setFixedHeight(28)
    title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    title.setStyleSheet("color: #00CFFF; letter-spacing: 1px;")
    outer.addWidget(title)

    config = CameraConfigPanel(camera_client=camera)
    outer.addWidget(config, 1)

    return win


# ── Main entry point ──────────────────────────────────────────────────────────

def main():
    _ensure_visionforge_on_path()

    parser = argparse.ArgumentParser(
        prog="python -m VisionForge.app.plugin_sdk.dev_runner",
        description="Run a VisionForge plugin standalone against real hardware.",
    )
    parser.add_argument(
        "plugin_dir",
        help="Path to the plugin folder (must contain plugin.json)",
    )
    parser.add_argument(
        "--camera",
        required=True,
        metavar="IP",
        help="IP address of the camera ZMQ server (port 5555/5556)",
    )
    parser.add_argument(
        "--arm",
        required=True,
        metavar="IP",
        help="IP address of the xArm controller",
    )
    parser.add_argument(
        "--no-status",
        action="store_true",
        default=False,
        help="Hide the hardware status monitor window",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        default=False,
        help="Hide the camera configuration window",
    )
    args = parser.parse_args()

    # ── Validate plugin directory ─────────────────────────────────────────────
    plugin_dir = os.path.abspath(args.plugin_dir)
    if not os.path.isdir(plugin_dir):
        print(f"ERROR: plugin directory not found: {plugin_dir}", file=sys.stderr)
        sys.exit(1)

    # ── Load manifest ─────────────────────────────────────────────────────────
    from VisionForge.app.plugin_sdk.manifest import load_manifest
    try:
        manifest = load_manifest(plugin_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Qt application ────────────────────────────────────────────────────────
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtCore    import Qt

    app = QApplication.instance() or QApplication(sys.argv)

    try:
        from VisionForge.app.styles.theme import STYLESHEET
        app.setStyleSheet(STYLESHEET)
    except Exception:
        pass

    # ── Real hardware ─────────────────────────────────────────────────────────
    from VisionForge.app.core.camera_client  import CameraClient
    from VisionForge.app.core.arm_controller import ArmController

    camera = CameraClient(args.camera)
    arm    = ArmController(args.arm)
    camera.start()
    arm.start()

    # ── Status monitor window ─────────────────────────────────────────────────
    status_win = None
    if not args.no_status:
        status_win = _build_status_window(camera, arm)
        status_win.show()

    # ── Camera configuration window ───────────────────────────────────────────
    config_win = None
    if not args.no_config:
        config_win = _build_config_window(camera)
        config_win.show()

    # ── Load plugin panel class ───────────────────────────────────────────────
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)

    entry_path = os.path.join(plugin_dir, manifest.panel_module + ".py")
    if not os.path.isfile(entry_path):
        print(f"ERROR: panel module not found: {entry_path}", file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    module_key = f"_vf_devrun_{manifest.name}_{manifest.panel_module}"
    try:
        spec   = importlib.util.spec_from_file_location(module_key, entry_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"ERROR: failed to import {entry_path}: {exc}", file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    PanelClass = getattr(module, manifest.panel_class, None)
    if PanelClass is None:
        print(f"ERROR: class '{manifest.panel_class}' not found in {entry_path}", file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    # ── Instantiate panel ─────────────────────────────────────────────────────
    try:
        panel = PanelClass(camera_client=camera, arm_controller=arm)
        panel.on_attach()
    except Exception as exc:
        import traceback
        print(f"ERROR: failed to instantiate panel: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    # ── Main window ───────────────────────────────────────────────────────────
    class _DevWindow(QMainWindow):
        def closeEvent(self, event):
            try: panel.cleanup()
            except Exception: pass
            try: camera.cleanup()
            except Exception: pass
            try: arm.cleanup()
            except Exception: pass
            if status_win:
                status_win.close()
            if config_win:
                config_win.close()
            event.accept()

    win = _DevWindow()
    win.setWindowTitle(f"[dev] {manifest.label}  —  VisionForge Plugin Runner")
    win.setCentralWidget(panel)
    win.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
