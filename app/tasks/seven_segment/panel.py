"""
SevenSegmentPanel — YOLO-OBB + PARSeq OCR + InfluxDB page.

Layout (QSplitter):
  Left  (~70%)  SevenSegFeedWidget  — annotated live feed, click to select box
  Right (~30%)  Sidebar             — mode toggle, FPS, OCR rate, detail panel,
                                      InfluxDB measurement list
"""

import threading
import time
import webbrowser
from typing import Dict, List, Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui  import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSlider, QSplitter,
    QVBoxLayout, QWidget,
)

from VisionForge.app.tasks.seven_segment.core import (
    FramePacket, InfluxDBManager, INFLUX_URL, is_valid_numeric,
)
from VisionForge.app.tasks.seven_segment.processor import SevenSegProcessor
from VisionForge.app.tasks.seven_segment.widgets import (
    DetailPanel, NamingDialog, SevenSegFeedWidget,
)

# ── Theme ─────────────────────────────────────────────────────────────────────

_C = {
    "bg":     "#060612",
    "bg2":    "#0C0C1E",
    "bg3":    "#111128",
    "border": "#1A1A38",
    "accent": "#00CFFF",
    "green":  "#00E676",
    "red":    "#FF4466",
    "orange": "#FFB300",
    "blue":   "#3B82F6",
    "text":   "#E8EAFF",
    "muted":  "#8890B8",
    "dim":    "#454878",
}

_STYLE = f"""
    QPushButton#modeBtn {{
        background: {_C['bg3']};
        color: {_C['muted']};
        border: 1px solid {_C['border']};
        border-radius: 6px;
        padding: 5px 18px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#modeBtn:hover {{
        background: {_C['bg2']};
        color: {_C['text']};
    }}
    QPushButton#modeBtn[active="true"] {{
        background: rgba(0, 207, 255, 0.15);
        border-color: {_C['accent']};
        color: {_C['accent']};
    }}
    QPushButton#balayageBtn {{
        background: #1A0D00;
        color: {_C['orange']};
        border: 1px solid {_C['orange']};
        border-radius: 6px;
        padding: 5px 14px;
        font-size: 12px;
        font-weight: 700;
    }}
    QPushButton#balayageBtn:hover {{
        background: #2A1500;
    }}
    QPushButton#balayageBtn:pressed {{
        background: rgba(255, 179, 0, 0.25);
        border-color: #FFD740;
        color: #FFD740;
    }}
    QPushButton#balayageBtn:disabled {{
        color: {_C['dim']};
        border-color: {_C['border']};
        background: {_C['bg']};
    }}
    QSlider::groove:horizontal {{
        background: {_C['bg3']}; height: 5px; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {_C['accent']}; width: 13px; height: 13px;
        margin: -4px 0; border-radius: 6px;
    }}
    QSlider::sub-page:horizontal {{
        background: rgba(0,207,255,0.35); border-radius: 2px;
    }}
    QListWidget {{
        background: {_C['bg']};
        border: 1px solid {_C['border']};
        border-radius: 6px;
        outline: none;
        font-size: 11px;
    }}
    QListWidget::item {{
        padding: 5px 8px;
        border-radius: 4px;
        color: {_C['muted']};
    }}
    QListWidget::item:selected {{
        background: {_C['bg3']};
        color: {_C['text']};
    }}
    QScrollBar:vertical {{
        background: transparent; width: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {_C['dim']}; border-radius: 2px; min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


_BALAYAGE_HZ     = 50          # control loop rate — must be high for smooth servo cartesian
_BALAYAGE_MVVELO = 100         # mm/s (≈ 20 % of 500 max)
_BALAYAGE_MVACC  = 500
_BALAYAGE_ALPHA  = 0.20        # EMA weight for centroid smoothing


class _BalayageWorker:
    """Background thread that runs the visual-servo loop at 50 Hz.
    Mirrors the gamepad pattern: direct raw_arm access, internal position
    accumulator seeded once at start, no repeated get_position() calls."""

    def __init__(self, raw_arm, get_pkt_fn, initial_pos):
        self._raw_arm  = raw_arm
        self._get_pkt  = get_pkt_fn
        self._pos      = list(initial_pos)
        self._cx = self._cy = None
        self._running  = False
        self._thread   = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._running = True
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread.join(timeout=1.0)

    def _loop(self):
        interval = 1.0 / _BALAYAGE_HZ
        while self._running:
            t0 = time.monotonic()
            self._tick()
            sleep_t = interval - (time.monotonic() - t0)
            if sleep_t > 0:
                time.sleep(sleep_t)

    def _tick(self):
        pkt = self._get_pkt()
        if pkt is None or len(pkt.obb_points) == 0 or len(pkt.obb_xywhr) == 0:
            return

        fh, fw = pkt.frame.shape[:2]
        n = min(len(pkt.obb_points), len(pkt.obb_xywhr))

        cx_raw = float(np.mean([pkt.obb_points[i][:, 0].mean() for i in range(n)]))
        cy_raw = float(np.mean([pkt.obb_points[i][:, 1].mean() for i in range(n)]))

        if self._cx is None:
            self._cx, self._cy = cx_raw, cy_raw
        else:
            self._cx = _BALAYAGE_ALPHA * cx_raw + (1 - _BALAYAGE_ALPHA) * self._cx
            self._cy = _BALAYAGE_ALPHA * cy_raw + (1 - _BALAYAGE_ALPHA) * self._cy

        dx = self._cx - fw / 2.0   # + → centroid right of center
        dy = self._cy - fh / 2.0   # + → centroid below center

        avg_area    = float(np.mean([pkt.obb_xywhr[i][2] * pkt.obb_xywhr[i][3]
                                     for i in range(n)]))
        target_area = 0.20 * fw * fh
        area_ratio  = avg_area / max(target_area, 1.0)

        # Per-tick deltas scaled for 50 Hz (≈ 0.6 mm/tick → 30 mm/s max approach)
        #   X+ = forward (approach)    boxes too small → move forward
        #   Y+ = left                  centroid right  → decrease Y
        #   Z+ = up                    centroid below  → decrease Z
        delta_x = float(np.clip(1.5 * (1.0 - area_ratio), -0.6, 0.6))
        delta_y = float(np.clip(-dx * 0.006, -0.4, 0.4))
        delta_z = float(np.clip(-dy * 0.006, -0.4, 0.4))

        self._pos[0] += delta_x
        self._pos[1] += delta_y
        self._pos[2] += delta_z

        try:
            self._raw_arm.set_servo_cartesian(
                mvpose=self._pos,
                mvvelo=_BALAYAGE_MVVELO,
                mvacc=_BALAYAGE_MVACC,
                is_radian=False,
            )
        except Exception:
            pass


class SevenSegmentPanel(QWidget):

    _meas_loaded      = Signal(list, int)   # (existing_measurements, tid)
    _meas_list_loaded = Signal(list)        # (measurement_names,)

    def __init__(self, camera_client=None, arm_controller=None, parent=None):
        super().__init__(parent)
        self._cam = camera_client
        self._arm = arm_controller

        # ── Runtime state ─────────────────────────────────────────────────────
        self.mode                 = "tracking"    # "tracking" | "verification"
        self.tid_to_measurement:  Dict[int, str]  = {}
        self.measurement_flip:    Dict[str, bool] = {}
        self.tid_flip:            Dict[int, bool] = {}
        self.active_measurements: set             = set()
        self.latest_pkt: Optional[FramePacket]   = None

        # ── Services ──────────────────────────────────────────────────────────
        self.influx      = InfluxDBManager()
        self._processor  = SevenSegProcessor()
        self._processor.frame_ready.connect(self._on_frame)
        self._processor_started = False

        self._meas_loaded.connect(self._open_naming_dialog)
        self._meas_list_loaded.connect(self._populate_meas_list)

        self._balayage_worker: "_BalayageWorker | None" = None

        self._build_ui()
        self._update_mode_buttons()
        self._update_balayage_btn()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self._cam:
            self._cam.raw_frame_received.connect(self._processor.submit_frame)
            self._cam.raw_frame_received.connect(self._feed.show_raw_frame)
        if not self._processor_started:
            self._processor.start()
            self._processor_started = True

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._cam:
            for slot in (self._processor.submit_frame, self._feed.show_raw_frame):
                try:
                    self._cam.raw_frame_received.disconnect(slot)
                except RuntimeError:
                    pass

    def cleanup(self):
        self._stop_balayage()
        if self._cam:
            for slot in (self._processor.submit_frame, self._feed.show_raw_frame):
                try:
                    self._cam.raw_frame_received.disconnect(slot)
                except RuntimeError:
                    pass
        if self._processor_started:
            self._processor.stop()
        self.influx.close()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_header())
        root.addWidget(self._make_body(), 1)

    def _make_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"background: {_C['bg2']}; border-bottom: 1px solid {_C['border']};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(8)

        title = QLabel("⬡  7-SEGMENT DETECTION")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {_C['accent']};")
        hl.addWidget(title)
        hl.addStretch()

        self.btn_balayage = QPushButton("⟳  AUTO-BALAYAGE")
        self.btn_balayage.setObjectName("balayageBtn")
        self.btn_balayage.pressed.connect(self._start_balayage)
        self.btn_balayage.released.connect(self._stop_balayage)
        hl.addWidget(self.btn_balayage)

        # separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {_C['border']};")
        sep.setFixedHeight(24)
        hl.addWidget(sep)

        self.btn_tracking = QPushButton("Tracking")
        self.btn_tracking.setObjectName("modeBtn")
        self.btn_tracking.clicked.connect(lambda: self._set_mode("tracking"))

        self.btn_verif = QPushButton("Verification")
        self.btn_verif.setObjectName("modeBtn")
        self.btn_verif.clicked.connect(lambda: self._set_mode("verification"))

        hl.addWidget(self.btn_tracking)
        hl.addWidget(self.btn_verif)

        # separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"color: {_C['border']};")
        sep2.setFixedHeight(24)
        hl.addWidget(sep2)

        btn_influx = QPushButton("◈  InfluxDB")
        btn_influx.setObjectName("modeBtn")
        btn_influx.clicked.connect(lambda: webbrowser.open(INFLUX_URL))
        hl.addWidget(btn_influx)
        return header

    def _make_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {_C['border']}; }}"
            f"QSplitter::handle:hover {{ background: {_C['accent']}; }}"
        )

        # ── Left: annotated feed ──────────────────────────────────────────────
        self._feed = SevenSegFeedWidget()
        self._feed.box_clicked.connect(self._on_box_clicked)
        splitter.addWidget(self._feed)

        # ── Right: sidebar ────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("segSidebar")
        sidebar.setMinimumWidth(200)
        sidebar.setStyleSheet(
            f"QFrame#segSidebar {{ background: {_C['bg2']};"
            f" border-left: 1px solid {_C['border']}; }}"
        )
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.setSpacing(8)

        # FPS indicator
        self.fps_label = QLabel("FPS  —")
        self.fps_label.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self.fps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fps_label.setStyleSheet(
            f"color: {_C['green']}; background: {_C['bg']};"
            f" border-radius: 6px; padding: 6px;"
            f" border: 1px solid {_C['border']};"
        )
        sl.addWidget(self.fps_label)

        # OCR rate section
        sl.addWidget(self._section_label("PARSEQ RATE"))

        self.ocr_rate_label = QLabel("2 passes / sec")
        self.ocr_rate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ocr_rate_label.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        self.ocr_rate_label.setStyleSheet(f"color: {_C['accent']};")
        sl.addWidget(self.ocr_rate_label)

        slider_row = QHBoxLayout()
        for lbl_text in ("1", "15"):
            lbl = QLabel(lbl_text)
            lbl.setStyleSheet(f"color: {_C['dim']}; font-size: 10px;")
            slider_row.addWidget(lbl) if lbl_text == "1" else None
            if lbl_text == "15":
                self.ocr_slider = QSlider(Qt.Orientation.Horizontal)
                self.ocr_slider.setMinimum(1)
                self.ocr_slider.setMaximum(15)
                self.ocr_slider.setValue(2)
                self.ocr_slider.valueChanged.connect(self._on_ocr_rate_changed)
                slider_row.addWidget(self.ocr_slider, 1)
                slider_row.addWidget(lbl)
        sl.addLayout(slider_row)

        sl.addWidget(self._separator())

        # Selected box detail
        sl.addWidget(self._section_label("SELECTED BOX"))
        self.detail = DetailPanel()
        self.detail.flip_changed.connect(self._on_flip_changed)
        self.detail.assign_request.connect(self._do_assign)
        self.detail.unassign_request.connect(self._do_unassign)
        self.detail.reassign_request.connect(self._do_reassign)
        sl.addWidget(self.detail, 1)

        sl.addWidget(self._separator())

        # InfluxDB measurements
        sl.addWidget(self._section_label("INFLUXDB BUCKET"))

        self.refresh_btn = QPushButton("↻  Refresh")
        self.refresh_btn.setStyleSheet(
            f"QPushButton {{ background: {_C['bg3']}; color: {_C['muted']};"
            f" border: 1px solid {_C['border']}; border-radius: 5px; padding: 5px; }}"
            f"QPushButton:hover {{ color: {_C['text']}; }}"
        )
        self.refresh_btn.clicked.connect(self._refresh_meas_list)
        sl.addWidget(self.refresh_btn)

        self.meas_list = QListWidget()
        self.meas_list.setMaximumHeight(120)
        sl.addWidget(self.meas_list)

        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setStyleSheet(
            f"QPushButton {{ background: #2D0A0A; color: {_C['red']};"
            f" font-weight: 600; border: 1px solid {_C['red']};"
            f" border-radius: 5px; padding: 5px; }}"
            f"QPushButton:hover {{ background: #450A0A; }}"
        )
        self.delete_btn.clicked.connect(self._on_delete)
        sl.addWidget(self.delete_btn)

        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 70)
        splitter.setStretchFactor(1, 30)
        self._splitter = splitter
        return splitter

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {_C['dim']}; font-size: 9px;"
            " letter-spacing: 1px; font-weight: 700;"
        )
        return lbl

    @staticmethod
    def _separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: #1A1A38;")
        return sep

    # ── Mode ──────────────────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self.mode = mode
        self._update_mode_buttons()
        self.detail.deselect()
        self._push_state()

    def _update_mode_buttons(self):
        self.btn_tracking.setProperty("active", self.mode == "tracking")
        self.btn_verif.setProperty("active",    self.mode == "verification")
        for btn in (self.btn_tracking, self.btn_verif):
            btn.style().unpolish(btn)
            btn.style().polish(btn)


    def _on_ocr_rate_changed(self, val: int):
        self.ocr_rate_label.setText(f"{val} pass{'es' if val != 1 else ''} / sec")
        self._push_state()

    # ── Frame handler ─────────────────────────────────────────────────────────

    def _on_frame(self, pkt: FramePacket):
        self.latest_pkt = pkt
        is_verif = self.mode == "verification"

        self._push_state()

        # ── InfluxDB writes (only on OCR frames, only in tracking mode) ───────
        if not is_verif and pkt.ran_ocr:
            for tid, mname in list(self.tid_to_measurement.items()):
                if tid in pkt.ocr_results:
                    text, _ = pkt.ocr_results[tid]
                    if is_valid_numeric(text):
                        try:
                            self.influx.write_value(mname, float(text))
                        except Exception as e:
                            print(f"[InfluxDB] write error: {e}")

        # ── Drop stale tracker IDs ────────────────────────────────────────────
        alive = (
            set(int(t) for t in pkt.tracker_ids)
            if len(pkt.tracker_ids) else set()
        )
        for tid in [t for t in list(self.tid_to_measurement) if t not in alive]:
            mname = self.tid_to_measurement.pop(tid)
            self.active_measurements.discard(mname)
            if self.detail.selected_tid == tid:
                self.detail.deselect()

        # ── Compute display size first ────────────────────────────────────────
        self.fps_label.setText(f"FPS  {pkt.fps:.1f}")
        lw, lh = self._feed.width(), self._feed.height()
        dpr    = self._feed.devicePixelRatioF()
        pw, ph = max(1, int(lw * dpr)), max(1, int(lh * dpr))
        fh, fw = pkt.frame.shape[:2]
        scale  = min(pw / fw, ph / fh)
        nw     = max(1, int(fw * scale))
        nh     = max(1, int(fh * scale))

        # ── Resize FIRST — annotate on the small image (no full-res copy) ─────
        ann = cv2.resize(pkt.frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        sel = self.detail.selected_tid

        for i, quad in enumerate(pkt.obb_points):
            if i >= len(pkt.tracker_ids):
                continue
            tid = int(pkt.tracker_ids[i])
            # Scale OBB corner coordinates to display resolution
            pts = (quad * scale).astype(np.int32)

            if is_verif:
                color = (255, 160, 30)          # amber
            elif tid in self.tid_to_measurement:
                color = (0, 210, 80)            # green
            else:
                color = (60, 60, 220)           # blue

            thick = 3 if tid == sel else 2
            cv2.polylines(ann, [pts], True, color, thick)

            # subtle fill highlight on selected box
            if tid == sel:
                ov = ann.copy()
                cv2.fillPoly(ov, [pts], tuple(min(c + 50, 255) for c in color))
                cv2.addWeighted(ov, 0.12, ann, 0.88, 0, ann)

            text, conf = pkt.ocr_results.get(tid, ("---", 0.0))
            mname      = self.tid_to_measurement.get(tid, "")
            numeric    = is_valid_numeric(text) if text and text != "---" else True
            label      = f"{mname}: {text}" if mname else f"{text}  ID:{tid}"
            if not numeric and text and text != "---":
                label += " [!]"

            lx = int(quad[0][0] * scale)
            ly = max(int(quad[0][1] * scale) - 10, 12)
            label_color = (0, 165, 255) if (not numeric and text and text != "---") else color
            cv2.putText(ann, label, (lx, ly),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, label_color, 2, cv2.LINE_AA)

        # ── Convert BGR→RGB, emit ─────────────────────────────────────────────
        rgb  = cv2.cvtColor(ann, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, nw, nh, nw * 3, QImage.Format.Format_RGB888).copy()
        qimg.setDevicePixelRatio(dpr)
        self._feed.update_frame(qimg, pkt)

        # ── Live refresh of detail panel ──────────────────────────────────────
        if self.detail.selected_tid is not None:
            if self.detail.selected_tid in alive:
                tid  = self.detail.selected_tid
                crop = pkt.crops.get(tid)
                text, conf = pkt.ocr_results.get(tid, ("---", 0.0))
                ig   = tid in self.tid_to_measurement
                mn   = self.tid_to_measurement.get(tid, "")
                self.detail.refresh(crop, text, conf, ig, mn, is_verif)
            else:
                self.detail.deselect()

    # ── Box click ─────────────────────────────────────────────────────────────

    def _on_box_clicked(self, tid: int):
        ig = tid in self.tid_to_measurement
        mn = self.tid_to_measurement.get(tid, "")
        fl = self._get_flip(tid)
        self.detail.select(tid, ig, mn, fl)

    # ── Assign / unassign / reassign ──────────────────────────────────────────

    def _do_assign(self, tid: int):
        """Fetch existing measurements off the UI thread, then open the dialog."""
        def _fetch():
            existing = self.influx.get_measurements()
            self._meas_loaded.emit(existing, tid)

        threading.Thread(target=_fetch, daemon=True).start()

    def _open_naming_dialog(self, existing: List[str], tid: int):
        dlg = NamingDialog(existing, self.active_measurements, parent=self)
        if dlg.exec() == NamingDialog.DialogCode.Accepted and dlg.chosen_name:
            name = dlg.chosen_name
            self.tid_to_measurement[tid] = name
            self.active_measurements.add(name)
            if self.tid_flip.get(tid, False):
                self.measurement_flip[name] = True

    def _do_unassign(self, tid: int):
        mname = self.tid_to_measurement.pop(tid, None)
        if mname:
            self.active_measurements.discard(mname)

    def _do_reassign(self, tid: int):
        old = self.tid_to_measurement.pop(tid, None)
        if old:
            self.active_measurements.discard(old)
        self._do_assign(tid)

    # ── Flip ──────────────────────────────────────────────────────────────────

    def _get_flip(self, tid: int) -> bool:
        mname = self.tid_to_measurement.get(tid)
        if mname:
            return self.measurement_flip.get(mname, False)
        return self.tid_flip.get(tid, False)

    def _on_flip_changed(self, tid: int, flipped: bool):
        self.tid_flip[tid] = flipped
        mname = self.tid_to_measurement.get(tid)
        if mname:
            self.measurement_flip[mname] = flipped

    # ── Measurement list ──────────────────────────────────────────────────────

    def _refresh_meas_list(self):
        def _fetch():
            names = self.influx.get_measurements()
            self._meas_list_loaded.emit(names)

        threading.Thread(target=_fetch, daemon=True).start()

    def _populate_meas_list(self, names: List[str]):
        self.meas_list.clear()
        for name in names:
            active = name in self.active_measurements
            icon   = "●" if active else "○"
            tag    = "STORING" if active else "idle"
            item   = QListWidgetItem(f"  {icon}  {name}   [{tag}]")
            item.setForeground(QColor(_C['green']) if active else QColor(_C['dim']))
            self.meas_list.addItem(item)

    def _on_delete(self):
        item = self.meas_list.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Select a measurement first.")
            return
        raw  = item.text().strip()
        name = raw.split("  ", 2)[-1].split("   [")[0].strip()
        if name in self.active_measurements:
            QMessageBox.warning(self, "Active",
                                f"'{name}' is currently storing. Stop it first.")
            return
        r = QMessageBox.question(
            self, "Delete",
            f"Delete ALL data for '{name}'?  This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self.influx.delete_measurement(name)
            self.measurement_flip.pop(name, None)
            self._refresh_meas_list()

    # ── Auto-balayage ─────────────────────────────────────────────────────────

    def set_arm(self, arm):
        self._arm = arm
        self._update_balayage_btn()

    def _update_balayage_btn(self):
        self.btn_balayage.setEnabled(self._arm is not None)

    def _start_balayage(self):
        if self._arm is None:
            return
        raw_arm = self._arm.get_arm()
        if raw_arm is None:
            return
        code, pos = self._arm.get_position()
        if code != 0 or pos is None:
            return
        self._stop_balayage()   # stop any previous worker
        self._balayage_worker = _BalayageWorker(raw_arm, lambda: self.latest_pkt, pos[:6])
        self._balayage_worker.start()

    def _stop_balayage(self):
        if self._balayage_worker is not None:
            self._balayage_worker.stop()
            self._balayage_worker = None

    # ── State sync ────────────────────────────────────────────────────────────

    def _push_state(self):
        self._processor.update_state(
            self.tid_flip,
            self.measurement_flip,
            self.tid_to_measurement,
            self.ocr_slider.value(),
        )
