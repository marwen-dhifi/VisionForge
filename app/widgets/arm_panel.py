"""
ArmPanel — xArm Control page of VisionForge.
State is polled every second directly from the objects — no missed signals.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QFrame, QPushButton, QSlider
)
from PySide6.QtCore import Qt, QTimer, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont

from VisionForge.app.widgets.feed_widget import FeedWidget


# ── Pulsing dot ───────────────────────────────────────────────────────────────

class _Dot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._color   = QColor("#454878")
        self._pulse_r = 0.0
        self._pulsing = False
        t = QTimer(self); t.timeout.connect(self._tick); t.start(30)

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
            rc = QColor(self._color); rc.setAlpha(int(fade * 140))
            p.setPen(QPen(rc, 1.0)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), self._pulse_r * 0.4, self._pulse_r * 0.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._color))
        p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)


def _row(dot, lbl):
    r = QHBoxLayout(); r.setSpacing(8); r.setContentsMargins(0, 0, 0, 0)
    r.addWidget(dot); r.addWidget(lbl); r.addStretch()
    return r


# ── Position readout ──────────────────────────────────────────────────────────

class _PositionReadout(QWidget):
    _AXES = [("X","mm"),("Y","mm"),("Z","mm"),
             ("Roll","°"),("Pitch","°"),("Yaw","°")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 10)
        lo.setSpacing(6)
        hdr = QLabel("LIVE POSITION")
        hdr.setStyleSheet(
            "color: #454878; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
        )
        lo.addWidget(hdr)
        lo.addSpacing(2)
        for axis, unit in self._AXES:
            row = QHBoxLayout(); row.setSpacing(8)
            ax  = QLabel(axis); ax.setFixedWidth(42)
            ax.setStyleSheet("color: #8890B8; font-size: 12px;")
            val = QLabel("—")
            val.setStyleSheet(
                "color: #00CFFF; font-family: Consolas, monospace;"
                "font-size: 14px; font-weight: bold;"
            )
            self._labels[axis] = val
            unt = QLabel(unit); unt.setFixedWidth(24)
            unt.setStyleSheet("color: #454878; font-size: 11px;")
            row.addWidget(ax); row.addWidget(val, 1); row.addWidget(unt)
            lo.addLayout(row)

    def update_position(self, x, y, z, roll, pitch, yaw):
        for axis, val in zip(
            ["X","Y","Z","Roll","Pitch","Yaw"], [x,y,z,roll,pitch,yaw]
        ):
            self._labels[axis].setText(f"{val:+.2f}")


# ── Styled button ─────────────────────────────────────────────────────────────

class _Btn(QPushButton):
    def __init__(self, label: str, sub: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label = label; self._sub = sub; self._color = color
        self._hover = False

    def enterEvent(self, e): self._hover = True;  self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        bg  = QColor("#22224A" if self._hover and enabled else "#181830")
        bdr = QColor(self._color if enabled else "#2A2A48")
        bdr.setAlpha(180 if self._hover and enabled else 60)
        p.setBrush(QBrush(bg)); p.setPen(QPen(bdr, 1.0))
        p.drawRoundedRect(self.rect().adjusted(1,1,-1,-1), 8, 8)
        p.setPen(QColor(self._color if enabled else "#454878"))
        p.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        p.drawText(0, 0, self.width(), self.height()//2+4,
                   Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignBottom,
                   self._label)
        p.setPen(QColor("#8890B8" if enabled else "#2A2A48"))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(0, self.height()//2+2, self.width(), self.height()//2-4,
                   Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop,
                   self._sub)


# ── Right control panel ───────────────────────────────────────────────────────

class _ControlPanel(QWidget):
    zero_pressed      = Signal()
    zero_released     = Signal()
    initial_pressed   = Signal()
    initial_released  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0C0C1E;")
        self._arm     = None   # set later via attach_arm()
        self._gamepad = None   # set later via attach_gamepad()

        # Last known states — used to avoid redundant UI updates
        self._last_arm_state = None    # "disconnected" | "not_enabled" | "ready"
        self._last_pad_state = None    # True | False

        self._build()

        # Poll every 1 second — reads actual state directly from objects
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(1000)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # Status section
        sf = QFrame()
        sf.setStyleSheet(
            "background-color: #111128; border-bottom: 1px solid #1A1A38;"
        )
        sf_lo = QVBoxLayout(sf)
        sf_lo.setContentsMargins(16, 14, 16, 14)
        sf_lo.setSpacing(10)

        hdr = QLabel("STATUS")
        hdr.setStyleSheet(
            "color: #454878; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
        )
        sf_lo.addWidget(hdr)

        self._arm_dot = _Dot(); self._arm_dot.set("#454878", False)
        self._arm_lbl = QLabel("xArm 5  ·  —")
        self._arm_lbl.setStyleSheet("color: #454878; font-size: 12px; font-weight: 600;")
        sf_lo.addLayout(_row(self._arm_dot, self._arm_lbl))

        self._pad_dot = _Dot(); self._pad_dot.set("#454878", False)
        self._pad_lbl = QLabel("Gamepad  ·  —")
        self._pad_lbl.setStyleSheet("color: #454878; font-size: 12px;")
        sf_lo.addLayout(_row(self._pad_dot, self._pad_lbl))

        # Speed row + slider
        spd_dot = _Dot(); spd_dot.set("#FFB300", False)
        self._speed_lbl = QLabel("Speed  ·  20%")
        self._speed_lbl.setStyleSheet("color: #FFB300; font-size: 12px; font-weight: 600;")
        sf_lo.addLayout(_row(spd_dot, self._speed_lbl))

        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setMinimum(0)
        self._speed_slider.setMaximum(100)
        self._speed_slider.setValue(20)
        self._speed_slider.setStyleSheet(
            "QSlider::groove:horizontal {"
            "  height: 4px; background: #1A1A38; border-radius: 2px;"
            "}"
            "QSlider::sub-page:horizontal {"
            "  background: #FFB300; border-radius: 2px;"
            "}"
            "QSlider::handle:horizontal {"
            "  width: 14px; height: 14px; margin: -5px 0;"
            "  background: #FFB300; border-radius: 7px;"
            "}"
        )
        self._speed_slider.valueChanged.connect(self._on_slider_speed)
        sf_lo.addWidget(self._speed_slider)

        lo.addWidget(sf)

        # Position readout
        pf = QFrame()
        pf.setStyleSheet(
            "background-color: #111128; border-bottom: 1px solid #1A1A38;"
        )
        pf_lo = QVBoxLayout(pf)
        pf_lo.setContentsMargins(0, 0, 0, 0)
        self._readout = _PositionReadout()
        pf_lo.addWidget(self._readout)
        lo.addWidget(pf)

        lo.addStretch()

        # Buttons
        bf = QWidget(); bf.setStyleSheet("background-color: #0C0C1E;")
        bf_lo = QVBoxLayout(bf)
        bf_lo.setContentsMargins(16, 14, 16, 18)
        bf_lo.setSpacing(10)

        ql = QLabel("QUICK ACTIONS")
        ql.setStyleSheet(
            "color: #454878; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
        )
        bf_lo.addWidget(ql)
        bf_lo.addSpacing(2)

        self._btn_reset = _Btn("Reset Arm", "Clear errors and re-enable", "#FF6B35")
        self._btn_reset.setEnabled(False)
        self._btn_reset.clicked.connect(self._do_reset)

        self._btn_zero = _Btn("Zero Position", "Hold to move, release to stop", "#7C3AED")
        self._btn_zero.setEnabled(False)
        self._btn_zero.pressed.connect(self.zero_pressed.emit)
        self._btn_zero.released.connect(self.zero_released.emit)

        self._btn_init = _Btn("Initial Position", "Hold to move, release to stop", "#00CFFF")
        self._btn_init.setEnabled(False)
        self._btn_init.pressed.connect(self.initial_pressed.emit)
        self._btn_init.released.connect(self.initial_released.emit)

        bf_lo.addWidget(self._btn_reset)
        bf_lo.addWidget(self._btn_zero)
        bf_lo.addWidget(self._btn_init)
        lo.addWidget(bf)

    # ── Attach objects ────────────────────────────────────────────────────────

    def attach_arm(self, arm):
        self._arm = arm
        arm.position_updated.connect(self._readout.update_position)
        self.zero_pressed.connect(arm.go_zero_start)
        self.zero_released.connect(arm.go_zero_stop)
        self.initial_pressed.connect(arm.go_initial_start)
        self.initial_released.connect(arm.go_initial_stop)
        self._poll()  # immediate update

    def attach_gamepad(self, gamepad):
        self._gamepad = gamepad
        gamepad.speed_changed.connect(self._on_speed)
        self._poll()  # immediate update

    # ── Poll ──────────────────────────────────────────────────────────────────

    def _poll(self):
        self._poll_arm()
        self._poll_gamepad()

    def _poll_arm(self):
        if self._arm is None:
            state = "disconnected"
        else:
            raw = self._arm.get_arm()
            if raw is None or not getattr(raw, 'connected', False):
                state = "disconnected"
            elif raw.error_code != 0:
                state = "not_enabled"
            else:
                state = "ready"

        if state == self._last_arm_state:
            return  # no change — skip redraw
        self._last_arm_state = state

        if state == "disconnected":
            self._arm_dot.set("#FF4466", False)
            self._arm_lbl.setText("xArm 5  ·  Disconnected")
            self._arm_lbl.setStyleSheet("color: #FF4466; font-size: 12px; font-weight: 600;")
            self._btn_reset.setEnabled(False)
            self._btn_zero.setEnabled(False)
            self._btn_init.setEnabled(False)

        elif state == "not_enabled":
            self._arm_dot.set("#FFB300", True)
            self._arm_lbl.setText("xArm 5  ·  Not Enabled")
            self._arm_lbl.setStyleSheet("color: #FFB300; font-size: 12px; font-weight: 600;")
            self._btn_reset.setEnabled(True)
            self._btn_zero.setEnabled(False)
            self._btn_init.setEnabled(False)

        else:  # ready
            self._arm_dot.set("#00E676", True)
            self._arm_lbl.setText("xArm 5  ·  Ready")
            self._arm_lbl.setStyleSheet("color: #00E676; font-size: 12px; font-weight: 600;")
            self._btn_reset.setEnabled(True)
            self._btn_zero.setEnabled(True)
            self._btn_init.setEnabled(True)

    def _poll_gamepad(self):
        if self._gamepad is None:
            connected = False
            name = ""
        else:
            connected = getattr(self._gamepad, '_joystick_name', None) is not None
            name = getattr(self._gamepad, '_joystick_name', "") or ""

        if connected == self._last_pad_state:
            return
        self._last_pad_state = connected

        if connected:
            self._pad_dot.set("#00E676", True)
            self._pad_lbl.setText(f"Gamepad  ·  {name}")
            self._pad_lbl.setStyleSheet("color: #00E676; font-size: 12px;")
        else:
            self._pad_dot.set("#FF4466", False)
            self._pad_lbl.setText("Gamepad  ·  Not detected")
            self._pad_lbl.setStyleSheet("color: #FF4466; font-size: 12px;")

    # ── Speed ─────────────────────────────────────────────────────────────────

    def _on_speed(self, pct: int):
        # Gamepad changed speed — sync label and slider
        self._speed_lbl.setText(f"Speed  ·  {pct}%")
        self._speed_slider.blockSignals(True)
        self._speed_slider.setValue(pct)
        self._speed_slider.blockSignals(False)

    def _on_slider_speed(self, pct: int):
        # Slider moved — sync label and gamepad
        self._speed_lbl.setText(f"Speed  ·  {pct}%")
        if self._gamepad:
            self._gamepad.set_speed_pct(pct)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def _do_reset(self):
        if self._arm:
            self._arm.reset_arm()
            # Force poll after 600ms to reflect new state
            QTimer.singleShot(600, self._poll)


# ── Public panel ──────────────────────────────────────────────────────────────

class ArmPanel(QWidget):

    def __init__(self, camera_client=None, arm_controller=None, parent=None):
        super().__init__(parent)
        self._cam = camera_client
        self._arm = arm_controller
        self._setup_ui()
        if camera_client:
            self._wire_camera(camera_client)
        if arm_controller:
            self._right.attach_arm(arm_controller)

    def _setup_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #1A1A38; }")

        self._feed  = FeedWidget()
        self._right = _ControlPanel()

        splitter.addWidget(self._feed)
        splitter.addWidget(self._right)
        splitter.setStretchFactor(0, 55)
        splitter.setStretchFactor(1, 45)
        lo.addWidget(splitter)

    def _wire_camera(self, cam):
        # raw_frame_received is managed by showEvent/hideEvent to avoid
        # processing frames while this panel is not visible.
        cam.connection_changed.connect(self._feed.set_camera_connected)
        cam.fps_updated.connect(self._feed.set_fps)

    def showEvent(self, event):
        super().showEvent(event)
        if self._cam:
            self._cam.raw_frame_received.connect(self._feed.on_frame)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._cam:
            try:
                self._cam.raw_frame_received.disconnect(self._feed.on_frame)
            except RuntimeError:
                pass

    def attach_camera(self, cam):
        self._cam = cam
        self._wire_camera(cam)
        if self.isVisible():
            cam.raw_frame_received.connect(self._feed.on_frame)

    def attach_arm(self, arm):
        self._arm = arm
        self._right.attach_arm(arm)

    def attach_gamepad(self, gamepad):
        self._right.attach_gamepad(gamepad)