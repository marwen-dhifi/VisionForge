import math
import time
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy

from VisionForge.app.plugin_sdk import TaskPanel
from processor import RotateProcessor

AMPLITUDE_MM = 60
FREQUENCY_HZ = 0.3
STEP_S       = 0.05   # 20 Hz motion update rate


class ArmSpinPanel(TaskPanel):

    _status_changed = Signal(str)   # emitted from motion thread → queued to UI thread

    def on_attach(self):
        self._processor = RotateProcessor()
        self._processor.display_ready.connect(self._on_display)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Arm Spin + 90° Rotation")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: #00CFFF;")
        root.addWidget(title)

        self._feed = QLabel("Waiting for camera…")
        self._feed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._feed.setStyleSheet(
            "background: #0C0C1E; border: 1px solid #1A1A38; color: #8890B8;"
        )
        self._feed.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        root.addWidget(self._feed, 1)

        btn_row = QHBoxLayout()
        self._start_btn  = QPushButton("Start arm")
        self._stop_btn   = QPushButton("Stop arm")
        self._status_lbl = QLabel("Arm idle")
        self._stop_btn.setEnabled(False)
        self._status_lbl.setStyleSheet("color: #8890B8;")

        for btn in (self._start_btn, self._stop_btn):
            btn.setStyleSheet(
                "background: #111128; color: #00CFFF;"
                "border: 1px solid #00CFFF; border-radius: 4px; padding: 6px 18px;"
            )
        self._start_btn.clicked.connect(self._start_arm)
        self._stop_btn.clicked.connect(self._stop_arm)

        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._status_lbl)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_changed.connect(self._status_lbl.setText)

        self._stop_event:    threading.Event  | None = None
        self._motion_thread: threading.Thread | None = None
        self._center_pos: list | None = None

    # ── Arm control ───────────────────────────────────────────────────────────

    def _start_arm(self):
        if not self._arm:
            self._status_lbl.setText("No arm connected")
            print("[arm_spin] _start_arm: self._arm is None", flush=True)
            return
        code, pos = self._arm.get_position()
        print(f"[arm_spin] get_position → code={code}  pos={pos}", flush=True)
        if code != 0 or not pos:
            self._status_lbl.setText("Could not read arm position")
            return
        self._center_pos = list(pos[:6])
        print(f"[arm_spin] center_pos = {self._center_pos}", flush=True)
        self._stop_event    = threading.Event()
        self._motion_thread = threading.Thread(
            target=self._motion_loop, daemon=True
        )
        self._motion_thread.start()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_lbl.setText("Running…")

    def _stop_arm(self):
        if self._stop_event:
            self._stop_event.set()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._status_lbl.setText("Arm idle")

    def _motion_loop(self):
        print("[arm_spin] motion loop started", flush=True)
        start = time.monotonic()
        i = 0
        while not self._stop_event.is_set():
            t       = time.monotonic() - start
            y_delta = AMPLITUDE_MM * math.sin(2 * math.pi * FREQUENCY_HZ * t)
            pose    = list(self._center_pos)
            pose[1] += y_delta
            ok = self._arm.send_servo_cartesian(pose, mvvelo=200)
            if i % 20 == 0:
                print(f"[arm_spin] t={t:.1f}s  y_delta={y_delta:+.1f}mm  pose={pose}  ok={ok}", flush=True)
            i += 1
            self._status_changed.emit(f"Y offset: {y_delta:+.1f} mm")
            time.sleep(STEP_S)
        print("[arm_spin] motion loop stopped", flush=True)

    # ── Camera feed ───────────────────────────────────────────────────────────

    def _on_display(self, qimg):
        pix = QPixmap.fromImage(qimg)
        self._feed.setPixmap(
            pix.scaled(self._feed.size(),
                       Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        )

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        if self._stop_event:
            self._stop_event.set()
        super().cleanup()
