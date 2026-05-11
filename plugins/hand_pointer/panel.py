"""
HandPointerPanel — gesture-controlled arm movement.

    POINTING  → arm moves continuously in the screen direction of the index finger
                screen X  maps to arm Y axis
                screen Y  maps to arm Z axis (screen-down = arm-down)
    FIST      → arm holds its current position (no new commands sent)
    anything else → no movement

A QTimer at 20 Hz drives arm commands so movement is time-based,
independent of the camera frame rate.
"""

from PySide6.QtCore    import Qt, QTimer, Signal
from PySide6.QtGui     import QFont, QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QWidget, QSizePolicy,
)

from VisionForge.app.plugin_sdk import TaskPanel
from processor import HandPointerProcessor

# Arm movement speed: mm added to the target per timer tick (20 Hz)
_STEP_MIN = 1.0
_STEP_MAX = 10.0
_STEP_DEF = 4.0

# Soft position limits (mm) — tune to your physical setup
_Y_MIN, _Y_MAX =  -450.0,  450.0
_Z_MIN, _Z_MAX =    80.0,  500.0


class HandPointerPanel(TaskPanel):

    def on_attach(self):
        self._processor = HandPointerProcessor()
        self._processor.display_ready.connect(self._on_display)
        # result_ready is emitted from a QThread → Qt queues delivery to the UI thread
        self._processor.result_ready.connect(self._on_result)

        self._gesture   = "none"
        self._direction = (0.0, 0.0)
        self._step      = _STEP_DEF
        self._active    = False
        self._target    = None   # [x, y, z, roll, pitch, yaw] captured at enable time

        self._build_ui()

        if self._arm:
            self._arm.position_updated.connect(self._on_arm_position)

        self._timer = QTimer(self)
        self._timer.setInterval(50)          # 20 Hz
        self._timer.timeout.connect(self._tick)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Hand Pointer Control")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: #00CFFF;")
        root.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # ── Camera feed ───────────────────────────────────────────────────────
        self._feed = QLabel("Waiting for camera…")
        self._feed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._feed.setStyleSheet(
            "background: #0C0C1E; border: 1px solid #1A1A38; color: #8890B8;"
        )
        self._feed.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        body.addWidget(self._feed, 3)

        # ── Side panel ────────────────────────────────────────────────────────
        side = QWidget()
        side.setStyleSheet("background: #0C0C1E; border: 1px solid #1A1A38;")
        side.setMinimumWidth(200)
        side_lo = QVBoxLayout(side)
        side_lo.setContentsMargins(14, 14, 14, 14)
        side_lo.setSpacing(10)

        # Gesture
        side_lo.addWidget(_section("Gesture"))
        self._gesture_lbl = QLabel("NONE")
        self._gesture_lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self._gesture_lbl.setStyleSheet(
            "color: #8890B8; background: transparent; border: none;"
        )
        side_lo.addWidget(self._gesture_lbl)

        # Direction
        side_lo.addWidget(_section("Direction"))
        self._dir_lbl = QLabel("—")
        self._dir_lbl.setStyleSheet(
            "color: #E8EAFF; font-size: 12px; background: transparent; border: none;"
        )
        side_lo.addWidget(self._dir_lbl)

        # Speed slider
        side_lo.addWidget(_section("Speed (mm / tick)"))
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(int(_STEP_MIN), int(_STEP_MAX))
        self._speed_slider.setValue(int(_STEP_DEF))
        self._speed_slider.setStyleSheet("background: transparent; border: none;")
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        side_lo.addWidget(self._speed_slider)
        self._speed_lbl = QLabel(f"{int(_STEP_DEF)} mm/tick")
        self._speed_lbl.setStyleSheet(
            "color: #8890B8; font-size: 11px; background: transparent; border: none;"
        )
        side_lo.addWidget(self._speed_lbl)

        # Arm readout
        side_lo.addWidget(_section("Arm position"))
        self._arm_lbl = QLabel("not connected" if not self._arm else "idle")
        self._arm_lbl.setWordWrap(True)
        self._arm_lbl.setStyleSheet(
            "color: #8890B8; font-size: 11px; background: transparent; border: none;"
        )
        side_lo.addWidget(self._arm_lbl)

        side_lo.addStretch()

        # Enable / Disable button
        self._enable_btn = QPushButton("Enable Control")
        self._enable_btn.setCheckable(True)
        self._enable_btn.setEnabled(bool(self._arm))
        self._enable_btn.setStyleSheet(_btn_style("#00CFFF"))
        self._enable_btn.toggled.connect(self._on_enable_toggled)
        side_lo.addWidget(self._enable_btn)

        body.addWidget(side, 1)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_display(self, qimg):
        pix = QPixmap.fromImage(qimg)
        self._feed.setPixmap(
            pix.scaled(self._feed.size(),
                       Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        )

    def _on_result(self, result: dict):
        self._gesture   = result.get("gesture",   "none")
        self._direction = result.get("direction",  (0.0, 0.0))

        color = {
            "pointing": "#00E676",
            "fist":     "#FF4466",
            "open":     "#FFB300",
            "none":     "#8890B8",
            "error":    "#FF4466",
        }.get(self._gesture, "#8890B8")

        self._gesture_lbl.setText(self._gesture.upper())
        self._gesture_lbl.setStyleSheet(
            f"color: {color}; font-size: 20px; font-weight: bold;"
            "background: transparent; border: none;"
        )

        if self._gesture == "pointing":
            dx, dy = self._direction
            self._dir_lbl.setText(f"dx  {dx:+.2f}\ndy  {dy:+.2f}")
        else:
            self._dir_lbl.setText("—")

    def _on_arm_position(self, x, y, z, roll, pitch, yaw):
        if not self._active:
            self._arm_lbl.setText(f"X {x:+.0f}  Y {y:+.0f}  Z {z:+.0f}")

    def _on_speed_changed(self, value: int):
        self._step = float(value)
        self._speed_lbl.setText(f"{value} mm/tick")

    def _on_enable_toggled(self, checked: bool):
        if checked:
            if not self._arm:
                self._enable_btn.setChecked(False)
                return
            code, pos = self._arm.get_position()
            if code != 0 or not pos:
                self._enable_btn.setChecked(False)
                self._arm_lbl.setText("Could not read arm position")
                return
            self._target = list(pos[:6])
            self._active = True
            self._enable_btn.setText("Disable Control")
            self._enable_btn.setStyleSheet(_btn_style("#FF4466"))
            self._timer.start()
        else:
            self._active = False
            self._timer.stop()
            self._target = None
            self._enable_btn.setText("Enable Control")
            self._enable_btn.setStyleSheet(_btn_style("#00CFFF"))

    # ── Motion tick (20 Hz, UI thread) ─────────────────────────────────────────

    def _tick(self):
        if not self._active or not self._arm or self._target is None:
            return

        if self._gesture == "fist":
            self._arm_lbl.setText("FIST — holding position")
            return

        if self._gesture == "pointing":
            dx, dy = self._direction
            # Non-mirrored camera: pointing right in user space = dx negative in image.
            # Negate dx so user-right → arm +Y, user-left → arm -Y.
            self._target[1] = max(_Y_MIN, min(_Y_MAX, self._target[1] - dx * self._step))
            self._target[2] = max(_Z_MIN, min(_Z_MAX, self._target[2] - dy * self._step))
            self._arm.send_servo_cartesian(self._target, mvvelo=150)
            self._arm_lbl.setText(
                f"Y  {self._target[1]:+.0f} mm\nZ  {self._target[2]:+.0f} mm"
            )

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def cleanup(self):
        self._timer.stop()
        if self._arm:
            try:
                self._arm.position_updated.disconnect(self._on_arm_position)
            except (RuntimeError, TypeError):
                pass
        super().cleanup()


# ── UI helpers ─────────────────────────────────────────────────────────────────

def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "color: #454878; font-size: 10px; font-weight: 600; letter-spacing: 2px;"
        "background: transparent; border: none;"
    )
    return lbl


def _btn_style(color: str) -> str:
    return (
        f"QPushButton {{ background: #111128; color: {color};"
        f"border: 1px solid {color}; border-radius: 4px; padding: 6px 12px; }}"
        f"QPushButton:hover {{ background: #1A1A38; }}"
        f"QPushButton:checked {{ background: #1A1A38; }}"
    )
