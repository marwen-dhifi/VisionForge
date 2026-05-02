"""
ValveOrientationPanel — AprilTag-based valve state detection panel.

Three modes
───────────
  Overview    : All 32 valves listed. Checkbox filter. Clear-only action.
  Calibration : Only camera-visible valves listed. Set Open/Closed/Clear.
  Tracking    : Live open/closed state for fully configured valves.

Display pipeline (ALL heavy work off UI thread):
  raw_frame_received ──► ValveProcessor.submit_frame (background QThread)
  ValveProcessor.display_ready    ──► feed.set_display   (QImage, trivial)
  ValveProcessor.detections_ready ──► _on_detections     (state + cards update)
  feed.size_changed               ──► processor.set_widget_size
"""

import os
import cv2
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QLineEdit, QCheckBox, QSplitter,
    QSlider, QDoubleSpinBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from VisionForge.app.tasks.valve_orientation.core import (
    ValveConfigManager, ValveStateTracker,
)
from VisionForge.app.tasks.valve_orientation.processor import ValveProcessor
from VisionForge.app.tasks.valve_orientation.widgets import ValveFeedWidget, ValveCard

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "valve_config.json")
_NUM_VALVES  = 32

_C = {
    "bg":     "#060612",
    "bg2":    "#0C0C1E",
    "bg3":    "#111128",
    "border": "#1A1A38",
    "accent": "#00CFFF",
    "green":  "#00E676",
    "red":    "#FF4466",
    "orange": "#FFB300",
    "text":   "#E8EAFF",
    "muted":  "#8890B8",
    "dim":    "#454878",
}

_BTN_STYLE = f"""
    QPushButton#valveModeBtn {{
        background-color: {_C['bg3']};
        color: {_C['muted']};
        border: 1px solid {_C['border']};
        border-radius: 6px;
        padding: 5px 18px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#valveModeBtn:hover {{
        background-color: {_C['bg2']};
        color: {_C['text']};
    }}
    QPushButton#valveModeBtn[active="true"] {{
        background-color: rgba(0, 207, 255, 0.15);
        border-color: {_C['accent']};
        color: {_C['accent']};
    }}
    QPushButton#valveOpenBtn {{
        background-color: #0A1F12;
        border: 1px solid {_C['green']};
        color: {_C['green']};
        border-radius: 6px;
        padding: 5px 14px;
        font-weight: 600;
    }}
    QPushButton#valveOpenBtn:hover {{
        background-color: {_C['green']};
        color: #000000;
    }}
    QPushButton#valveOpenBtn:disabled {{
        background-color: #0C0C1E;
        border: 1px solid #1A3322;
        color: #1A3322;
    }}
    QPushButton#valveClosedBtn {{
        background-color: #1F0A10;
        border: 1px solid {_C['red']};
        color: {_C['red']};
        border-radius: 6px;
        padding: 5px 14px;
        font-weight: 600;
    }}
    QPushButton#valveClosedBtn:hover {{
        background-color: {_C['red']};
        color: #ffffff;
    }}
    QPushButton#valveClosedBtn:disabled {{
        background-color: #0C0C1E;
        border: 1px solid #331A22;
        color: #331A22;
    }}
    QPushButton#valveClearBtn {{
        background-color: #1A1200;
        border: 1px solid {_C['orange']};
        color: {_C['orange']};
        border-radius: 6px;
        padding: 5px 14px;
        font-weight: 600;
    }}
    QPushButton#valveClearBtn:hover {{
        background-color: {_C['orange']};
        color: #000000;
    }}
    QLineEdit {{
        background-color: {_C['bg']};
        color: {_C['text']};
        border: 1px solid {_C['border']};
        border-radius: 5px;
        padding: 5px 8px;
        font-size: 12px;
    }}
    QLineEdit:focus {{
        border-color: {_C['accent']};
    }}
    QCheckBox {{
        color: {_C['text']};
        font-size: 11px;
        spacing: 5px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {_C['border']};
        border-radius: 3px;
        background: {_C['bg']};
    }}
    QCheckBox::indicator:checked {{
        background: {_C['accent']};
        border-color: {_C['accent']};
    }}
"""


_MAX_SCAN_SPEED = 150        # mm/s — 30 % of xArm5 max TCP speed
_DEFAULT_SCAN_X =  420.74   # mm
_DEFAULT_SCAN_Y =  -26.06   # mm
_DEFAULT_SCAN_Z =  218.78   # mm
_FIXED_ROLL     = -180.0    # deg  — locked, not user-editable
_FIXED_PITCH    =    0.0    # deg
_FIXED_YAW      =    0.92   # deg


class ValveOrientationPanel(QWidget):

    def __init__(self, camera_client=None, arm_controller=None, parent=None):
        super().__init__(parent)
        self._cam = camera_client
        self._arm = arm_controller

        # Scan path state (X/Y/Z only; orientation is fixed)
        self._scan_x = _DEFAULT_SCAN_X
        self._scan_y = _DEFAULT_SCAN_Y
        self._scan_z = _DEFAULT_SCAN_Z

        self.mode = "overview"
        self.config_mgr = ValveConfigManager()
        self.config_mgr.load(_CONFIG_FILE)
        self.tracker = ValveStateTracker()
        self.selected_marker_id: int | None = None
        self.current_detections: list       = []

        self._cam_w = 0
        self._cam_h = 0

        self._processor = ValveProcessor()
        self._processor.detections_ready.connect(self._on_detections)
        self._processor.frame_size_changed.connect(self._on_frame_size)
        self._processor_started = False

        # Pre-create all 32 valve cards
        self.valve_cards: dict[int, ValveCard] = {}
        for mid in range(_NUM_VALVES):
            card = ValveCard(mid, self.config_mgr.get_name(mid))
            card.clicked.connect(self._on_card_clicked)
            self.valve_cards[mid] = card

        self._build_ui()

        # Wire processor ↔ feed (feed created inside _build_ui)
        self._processor.display_ready.connect(self._feed.set_display)
        self._feed.size_changed.connect(self._processor.set_widget_size)

        self._refresh_sidebar()
        self._update_mode_buttons()
        self._update_config_panel()
        self._push_overlay_state()

        if self._arm is not None:
            self._arm.scan_state_changed.connect(self._on_scan_state_changed)

    def set_arm(self, arm):
        if self._arm is not None:
            try:
                self._arm.scan_state_changed.disconnect(self._on_scan_state_changed)
            except RuntimeError:
                pass
        self._arm = arm
        if arm is not None:
            arm.scan_state_changed.connect(self._on_scan_state_changed)
        self._scan_bar.setVisible(arm is not None)

    # ── Page lifecycle ────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self._cam:
            self._cam.raw_frame_received.connect(self._processor.submit_frame)
        if not self._processor_started:
            self._processor.start()
            self._processor_started = True
            self._processor.set_widget_size(
                self._feed.width(), self._feed.height(), self._feed.devicePixelRatioF()
            )

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._cam:
            try:
                self._cam.raw_frame_received.disconnect(self._processor.submit_frame)
            except RuntimeError:
                pass

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(_BTN_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_body(), 1)
        root.addWidget(self._make_config_panel())
        self._scan_bar = self._make_scan_bar()
        root.addWidget(self._scan_bar)
        self._scan_bar.setVisible(self._arm is not None)

    def _make_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"background-color: {_C['bg2']}; border-bottom: 1px solid {_C['border']};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(8)

        title = QLabel("⚙  VALVE ORIENTATION")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {_C['accent']};")
        hl.addWidget(title)
        hl.addStretch()

        self._btn_overview = QPushButton("Overview")
        self._btn_overview.setObjectName("valveModeBtn")
        self._btn_overview.clicked.connect(lambda: self._set_mode("overview"))
        hl.addWidget(self._btn_overview)

        self._btn_calibration = QPushButton("Calibration")
        self._btn_calibration.setObjectName("valveModeBtn")
        self._btn_calibration.clicked.connect(lambda: self._set_mode("calibration"))
        hl.addWidget(self._btn_calibration)

        self._btn_tracking = QPushButton("Tracking")
        self._btn_tracking.setObjectName("valveModeBtn")
        self._btn_tracking.clicked.connect(lambda: self._set_mode("tracking"))
        hl.addWidget(self._btn_tracking)

        return header

    def _make_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {_C['border']}; }}"
            f"QSplitter::handle:hover {{ background: {_C['accent']}; }}"
        )

        self._feed = ValveFeedWidget()
        self._feed.mousePressEvent = self._on_video_click
        splitter.addWidget(self._feed)

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("valveSidebar")
        sidebar.setMinimumWidth(200)
        sidebar.setStyleSheet(
            f"QFrame#valveSidebar {{ background-color: {_C['bg2']}; border-left: 1px solid {_C['border']}; }}"
        )
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.setSpacing(8)

        self._sidebar_title = QLabel("VALVES")
        self._sidebar_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._sidebar_title.setStyleSheet(f"color: {_C['muted']}; padding-bottom: 2px;")
        sl.addWidget(self._sidebar_title)

        # Checkbox filter (hidden in Tracking mode)
        self._filter_frame = QFrame()
        fl = QHBoxLayout(self._filter_frame)
        fl.setContentsMargins(0, 0, 0, 4)
        fl.setSpacing(6)

        filter_lbl = QLabel("Show:")
        filter_lbl.setFont(QFont("Segoe UI", 9))
        filter_lbl.setStyleSheet(f"color: {_C['muted']};")
        fl.addWidget(filter_lbl)

        self._cb_open   = QCheckBox("Open")
        self._cb_closed = QCheckBox("Closed")
        self._cb_open.stateChanged.connect(self._on_filter_changed)
        self._cb_closed.stateChanged.connect(self._on_filter_changed)
        fl.addWidget(self._cb_open)
        fl.addWidget(self._cb_closed)
        fl.addStretch()
        sl.addWidget(self._filter_frame)

        # Scroll area containing all pre-created cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        valve_list_widget = QWidget()
        self._valve_list_layout = QVBoxLayout(valve_list_widget)
        self._valve_list_layout.setContentsMargins(0, 0, 4, 0)
        self._valve_list_layout.setSpacing(6)

        for mid in range(_NUM_VALVES):
            self._valve_list_layout.addWidget(self.valve_cards[mid])
            self.valve_cards[mid].hide()

        self._valve_list_layout.addStretch()
        scroll.setWidget(valve_list_widget)
        sl.addWidget(scroll, 1)

        self._valve_count_label = QLabel("")
        self._valve_count_label.setFont(QFont("Segoe UI", 9))
        self._valve_count_label.setStyleSheet(f"color: {_C['dim']};")
        self._valve_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(self._valve_count_label)

        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 70)
        splitter.setStretchFactor(1, 30)
        self._splitter = splitter
        return splitter

    def _make_config_panel(self) -> QFrame:
        self._config_panel = QFrame()
        self._config_panel.setObjectName("valveConfigPanel")
        self._config_panel.setFixedHeight(60)
        self._config_panel.setStyleSheet(
            f"QFrame#valveConfigPanel {{ background-color: {_C['bg2']}; border-top: 1px solid {_C['border']}; }}"
        )
        cp = QHBoxLayout(self._config_panel)
        cp.setContentsMargins(20, 8, 20, 8)
        cp.setSpacing(10)

        self._selected_label = QLabel("Select a valve from the list")
        self._selected_label.setFont(QFont("Segoe UI", 11))
        self._selected_label.setStyleSheet(f"color: {_C['muted']};")
        cp.addWidget(self._selected_label, 1)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Valve name…")
        self._name_input.setFixedWidth(150)
        self._name_input.setVisible(False)
        self._name_input.editingFinished.connect(self._on_rename)
        cp.addWidget(self._name_input)

        self._btn_set_open = QPushButton("Set OPEN")
        self._btn_set_open.setObjectName("valveOpenBtn")
        self._btn_set_open.setVisible(False)
        self._btn_set_open.clicked.connect(self._on_set_open)
        cp.addWidget(self._btn_set_open)

        self._btn_set_closed = QPushButton("Set CLOSED")
        self._btn_set_closed.setObjectName("valveClosedBtn")
        self._btn_set_closed.setVisible(False)
        self._btn_set_closed.clicked.connect(self._on_set_closed)
        cp.addWidget(self._btn_set_closed)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setObjectName("valveClearBtn")
        self._btn_clear.setVisible(False)
        self._btn_clear.clicked.connect(self._on_clear)
        cp.addWidget(self._btn_clear)

        return self._config_panel

    # ── Mode ──────────────────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self.mode = mode
        if mode == "tracking":
            self.selected_marker_id = None
        self._update_mode_buttons()
        self._filter_frame.setVisible(mode != "tracking")
        self._config_panel.setVisible(mode != "tracking")
        self._refresh_sidebar()
        self._update_config_panel()
        self._push_overlay_state()

    def _update_mode_buttons(self):
        for btn, m in [
            (self._btn_overview,    "overview"),
            (self._btn_calibration, "calibration"),
            (self._btn_tracking,    "tracking"),
        ]:
            btn.setProperty("active", self.mode == m)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Checkbox filter ───────────────────────────────────────────────────────

    def _on_filter_changed(self):
        # If current selection is hidden by new filter, deselect
        if (self.selected_marker_id is not None
                and not self._passes_filter(self.selected_marker_id)):
            self.selected_marker_id = None
            self._update_config_panel()
            self._push_overlay_state()
        self._refresh_sidebar()

    def _passes_filter(self, mid: int) -> bool:
        """
        Strict partition: the two checkboxes describe exactly which
        config-status category to display.

          neither  → "none"          (not configured, red)
          open     → "partial_open"  (open set only, orange)
          closed   → "partial_closed"(closed set only, orange)
          both     → "full"          (fully configured, green)
        """
        open_chk   = self._cb_open.isChecked()
        closed_chk = self._cb_closed.isChecked()
        status     = self.config_mgr.config_status(mid)
        if open_chk and closed_chk:
            return status == "full"
        elif open_chk:
            return status == "partial_open"
        elif closed_chk:
            return status == "partial_closed"
        else:
            return status == "none"

    # ── Sidebar refresh ───────────────────────────────────────────────────────

    def _refresh_sidebar(self):
        for card in self.valve_cards.values():
            card.hide()

        visible_ids = {det["id"] for det in self.current_detections}
        shown = 0

        if self.mode == "overview":
            for mid in range(_NUM_VALVES):
                if self._passes_filter(mid):
                    card = self.valve_cards[mid]
                    card.set_name(self.config_mgr.get_name(mid))
                    card.set_config_status(
                        self.config_mgr.config_status(mid),
                        mid == self.selected_marker_id,
                    )
                    card.show()
                    shown += 1
            self._valve_count_label.setText(
                f"{shown} valve{'s' if shown != 1 else ''} shown"
            )

        elif self.mode == "calibration":
            for mid in sorted(visible_ids):
                if mid >= _NUM_VALVES:
                    continue
                if self._passes_filter(mid):
                    card = self.valve_cards[mid]
                    card.set_name(self.config_mgr.get_name(mid))
                    card.set_config_status(
                        self.config_mgr.config_status(mid),
                        mid == self.selected_marker_id,
                    )
                    card.show()
                    shown += 1
            self._valve_count_label.setText(
                f"{len(visible_ids)} visible  •  {shown} shown"
            )

        else:  # "tracking"
            for mid in range(_NUM_VALVES):
                if self.config_mgr.is_fully_configured(mid):
                    card = self.valve_cards[mid]
                    card.set_name(self.config_mgr.get_name(mid))
                    card.set_tracking_state(
                        self.tracker.get_state(mid),
                        mid in visible_ids,
                        self.tracker.get_confidence(mid),
                        self.tracker.get_sample_count(mid),
                    )
                    card.show()
                    shown += 1
            self._valve_count_label.setText(
                f"{shown} configured valve{'s' if shown != 1 else ''}"
            )

    # ── Selection from list ───────────────────────────────────────────────────

    def _on_card_clicked(self, marker_id: int):
        if self.mode not in ("overview", "calibration"):
            return
        self.selected_marker_id = marker_id
        self._refresh_sidebar()
        self._update_config_panel()
        self._push_overlay_state()

    # ── Selection from video feed (calibration only) ──────────────────────────

    def _on_frame_size(self, fw: int, fh: int):
        self._cam_w, self._cam_h = fw, fh

    def _on_video_click(self, event):
        if self.mode != "calibration" or not self.current_detections:
            return

        fw, fh = self._feed.width(), self._feed.height()
        dpr    = self._feed.devicePixelRatioF()
        pw, ph = int(fw * dpr), int(fh * dpr)

        cam_w, cam_h = self._cam_w, self._cam_h
        if cam_w == 0 or cam_h == 0:
            return

        scale  = min(pw / cam_w, ph / cam_h)
        disp_w = cam_w * scale / dpr
        disp_h = cam_h * scale / dpr
        ox     = (fw - disp_w) / 2
        oy     = (fh - disp_h) / 2

        cx = (event.position().x() - ox) / (scale / dpr)
        cy = (event.position().y() - oy) / (scale / dpr)

        for det in self.current_detections:
            pts = det["corners"].reshape(4, 2).astype(np.float32)
            if cv2.pointPolygonTest(pts, (float(cx), float(cy)), False) >= 0:
                self.selected_marker_id = det["id"]
                self._refresh_sidebar()
                self._update_config_panel()
                self._push_overlay_state()
                return

        self.selected_marker_id = None
        self._refresh_sidebar()
        self._update_config_panel()
        self._push_overlay_state()

    # ── Config panel state ────────────────────────────────────────────────────

    def _update_config_panel(self):
        has_sel     = self.selected_marker_id is not None
        visible_ids = {det["id"] for det in self.current_detections}

        if self.mode == "overview":
            self._name_input.setVisible(False)
            self._btn_set_open.setVisible(False)
            self._btn_set_closed.setVisible(False)
            self._btn_clear.setVisible(has_sel)

            if has_sel:
                mid    = self.selected_marker_id
                status = self.config_mgr.config_status(mid)
                label_map = {
                    "full":           "Fully configured",
                    "partial_open":   "Open only",
                    "partial_closed": "Closed only",
                    "none":           "Not configured",
                }
                self._selected_label.setText(
                    f"<b style='color:{_C['accent']};'>"
                    f"ID {mid} — {self.config_mgr.get_name(mid)}</b>"
                    f"  •  {label_map.get(status, status)}"
                )
                self._selected_label.setStyleSheet(f"color: {_C['text']};")
            else:
                self._selected_label.setText(
                    "Select a valve from the list to clear its calibration"
                )
                self._selected_label.setStyleSheet(f"color: {_C['muted']};")

        elif self.mode == "calibration":
            is_vis = has_sel and (self.selected_marker_id in visible_ids)

            self._name_input.setVisible(has_sel)
            self._btn_set_open.setVisible(has_sel)
            self._btn_set_closed.setVisible(has_sel)
            self._btn_clear.setVisible(has_sel)
            self._btn_set_open.setEnabled(is_vis)
            self._btn_set_closed.setEnabled(is_vis)

            if has_sel:
                mid = self.selected_marker_id
                v   = self.config_mgr.get_valve(mid)
                has_open   = v is not None and v.get("open_rvec")   is not None
                has_closed = v is not None and v.get("closed_rvec") is not None
                parts    = ["✓ Open"   if has_open   else "✗ Open",
                            "✓ Closed" if has_closed else "✗ Closed"]
                vis_note = "" if is_vis else "  <span style='color:#FFB300;'>⚠ not visible</span>"
                self._selected_label.setText(
                    f"<b style='color:{_C['accent']};'>"
                    f"ID {mid} — {self.config_mgr.get_name(mid)}</b>"
                    f"  •  {'  │  '.join(parts)}{vis_note}"
                )
                self._selected_label.setStyleSheet(f"color: {_C['text']};")
                self._name_input.setText(v["name"] if v else f"Valve {mid}")
            else:
                self._selected_label.setText(
                    "Click a marker in the feed or list to select it"
                )
                self._selected_label.setStyleSheet(f"color: {_C['muted']};")

        # tracking — config panel is hidden; nothing to update

    # ── Config actions ────────────────────────────────────────────────────────

    def _get_selected_rvec(self) -> np.ndarray | None:
        if self.selected_marker_id is None:
            return None
        for det in self.current_detections:
            if det["id"] == self.selected_marker_id:
                return det["rvec"]
        return None

    def _on_set_open(self):
        rvec = self._get_selected_rvec()
        if rvec is None:
            return
        self.config_mgr.set_open(self.selected_marker_id, rvec)
        self.tracker.votes.pop(self.selected_marker_id, None)
        self.config_mgr.save(_CONFIG_FILE)
        self._refresh_sidebar()
        self._update_config_panel()
        self._push_overlay_state()

    def _on_set_closed(self):
        rvec = self._get_selected_rvec()
        if rvec is None:
            return
        self.config_mgr.set_closed(self.selected_marker_id, rvec)
        self.tracker.votes.pop(self.selected_marker_id, None)
        self.config_mgr.save(_CONFIG_FILE)
        self._refresh_sidebar()
        self._update_config_panel()
        self._push_overlay_state()

    def _on_clear(self):
        if self.selected_marker_id is None:
            return
        self.config_mgr.clear(self.selected_marker_id)
        self.tracker.votes.pop(self.selected_marker_id, None)
        self.config_mgr.save(_CONFIG_FILE)
        self.selected_marker_id = None
        self._refresh_sidebar()
        self._update_config_panel()
        self._push_overlay_state()

    def _on_rename(self):
        if self.selected_marker_id is None:
            return
        name = self._name_input.text().strip()
        if not name:
            return
        key = str(self.selected_marker_id)
        if key not in self.config_mgr.valves:
            self.config_mgr.valves[key] = {
                "name": name, "open_rvec": None, "closed_rvec": None
            }
        else:
            self.config_mgr.rename(self.selected_marker_id, name)
        self.valve_cards[self.selected_marker_id].set_name(name)

    # ── Detection results ─────────────────────────────────────────────────────

    def _on_detections(self, detections: list):
        self.current_detections = detections

        new_visible: set[int] = set()
        for det in detections:
            mid = det["id"]
            if mid < _NUM_VALVES:
                new_visible.add(mid)
                self.tracker.update(mid, det["rvec"], self.config_mgr)

        prev_visible = set(self.tracker.visible)
        self.tracker.set_visible(new_visible)

        if self.mode == "tracking":
            # Only update state labels — no layout changes needed
            for mid in range(_NUM_VALVES):
                if self.config_mgr.is_fully_configured(mid):
                    card = self.valve_cards[mid]
                    if card.isVisible():
                        card.set_tracking_state(
                            self.tracker.get_state(mid),
                            mid in new_visible,
                            self.tracker.get_confidence(mid),
                            self.tracker.get_sample_count(mid),
                        )
        elif self.mode == "calibration" and new_visible != prev_visible:
            # Visible set changed → sidebar needs layout update
            self._refresh_sidebar()
        # overview: detections don't change config status → no sidebar update

        self._update_config_panel()
        self._push_overlay_state()

    def _push_overlay_state(self):
        """Sync current detection + UI state to the processor for overlay drawing."""
        self._processor.update_overlay_state(
            self.current_detections,
            self.mode,
            self.selected_marker_id,
            self.config_mgr,
            self.tracker,
        )

    # ── Scan control bar ──────────────────────────────────────────────────────

    _COORD_LABEL_W = 70   # px — fixed width for each X/Y/Z value label

    def _make_scan_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background-color: {_C['bg2']}; border-top: 1px solid {_C['border']}; }}"
        )
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(20, 8, 20, 8)
        outer.setSpacing(6)

        # ── Row 1: title + start/stop ─────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        icon = QLabel("⬡")
        icon.setFont(QFont("Segoe UI", 14))
        icon.setStyleSheet(f"color: {_C['accent']}; border: none;")
        row1.addWidget(icon)

        title = QLabel("Detection Scan")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {_C['text']}; border: none;")
        row1.addWidget(title)
        row1.addStretch()

        self._btn_start_scan = QPushButton("▶  Start Detection")
        self._btn_start_scan.setFixedHeight(30)
        self._btn_start_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start_scan.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(0,230,118,0.10); color: {_C['green']};
                border: 1px solid {_C['green']}; border-radius: 5px;
                padding: 0 16px; font-size: 11px; font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {_C['green']}; color: #000; }}
            QPushButton:disabled {{
                background-color: {_C['bg3']}; color: {_C['dim']}; border-color: {_C['dim']};
            }}
        """)
        self._btn_start_scan.clicked.connect(self._on_start_scan)
        row1.addWidget(self._btn_start_scan)

        self._btn_stop_scan = QPushButton("■  Stop")
        self._btn_stop_scan.setFixedHeight(30)
        self._btn_stop_scan.setEnabled(False)
        self._btn_stop_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop_scan.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(255,68,102,0.10); color: {_C['red']};
                border: 1px solid {_C['red']}; border-radius: 5px;
                padding: 0 16px; font-size: 11px; font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {_C['red']}; color: #fff; }}
            QPushButton:disabled {{
                background-color: {_C['bg3']}; color: {_C['dim']}; border-color: {_C['dim']};
            }}
        """)
        self._btn_stop_scan.clicked.connect(self._on_stop_scan)
        row1.addWidget(self._btn_stop_scan)

        outer.addLayout(row1)

        # ── Separator ─────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_C['border']}; border: none; border-top: 1px solid {_C['border']};")
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        # ── Row 2: path config label + X/Y/Z + capture/reset ─────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        path_lbl = QLabel("PATH CONFIGURATION")
        path_lbl.setStyleSheet(
            f"color: {_C['muted']}; font-size: 10px; font-weight: 700; border: none;"
        )
        row2.addWidget(path_lbl)
        row2.addSpacing(6)

        _coord_style = (
            f"background: {_C['bg']}; color: {_C['accent']};"
            f" border: 1px solid {_C['border']}; border-radius: 3px;"
            f" font-size: 11px; font-weight: 700; padding: 1px 5px;"
        )
        for axis, val in (("X", self._scan_x), ("Y", self._scan_y), ("Z", self._scan_z)):
            ax_lbl = QLabel(f"{axis}:")
            ax_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 11px; border: none;")
            row2.addWidget(ax_lbl)
            val_lbl = QLabel(f"{val:+.2f}")
            val_lbl.setFixedWidth(self._COORD_LABEL_W)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(_coord_style)
            row2.addWidget(val_lbl)
            setattr(self, f"_lbl_scan_{axis.lower()}", val_lbl)

        row2.addSpacing(8)

        self._btn_capture = QPushButton("⊙  Capture Point")
        self._btn_capture.setFixedHeight(26)
        self._btn_capture.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_capture.setStyleSheet(f"""
            QPushButton {{
                background-color: {_C['bg3']}; color: {_C['muted']};
                border: 1px solid {_C['border']}; border-radius: 4px;
                padding: 0 12px; font-size: 11px;
            }}
            QPushButton:hover {{ color: {_C['text']}; border-color: {_C['accent']}; }}
            QPushButton:disabled {{
                color: {_C['dim']}; border-color: {_C['dim']};
            }}
        """)
        self._btn_capture.clicked.connect(self._on_capture_point)
        row2.addWidget(self._btn_capture)

        self._btn_reset_pos = QPushButton("↺  Default")
        self._btn_reset_pos.setFixedHeight(26)
        self._btn_reset_pos.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_reset_pos.setStyleSheet(f"""
            QPushButton {{
                background-color: {_C['bg3']}; color: {_C['muted']};
                border: 1px solid {_C['border']}; border-radius: 4px;
                padding: 0 10px; font-size: 11px;
            }}
            QPushButton:hover {{ color: {_C['text']}; border-color: {_C['accent']}; }}
            QPushButton:disabled {{
                color: {_C['dim']}; border-color: {_C['dim']};
            }}
        """)
        self._btn_reset_pos.clicked.connect(self._on_reset_pos)
        row2.addWidget(self._btn_reset_pos)

        row2.addStretch()
        outer.addLayout(row2)

        # ── Row 3: oscillation amplitude + speed slider ───────────────────────
        row3 = QHBoxLayout()
        row3.setSpacing(8)

        amp_lbl = QLabel("Oscillation ±")
        amp_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 11px; border: none;")
        row3.addWidget(amp_lbl)

        self._spin_amplitude = QDoubleSpinBox()
        self._spin_amplitude.setRange(10.0, 1000.0)
        self._spin_amplitude.setDecimals(0)
        self._spin_amplitude.setSingleStep(10.0)
        self._spin_amplitude.setValue(200.0)
        self._spin_amplitude.setSuffix(" mm")
        self._spin_amplitude.setFixedWidth(90)
        self._spin_amplitude.setStyleSheet(f"""
            QDoubleSpinBox {{
                background: {_C['bg']}; color: {_C['text']};
                border: 1px solid {_C['border']}; border-radius: 4px; padding: 2px 4px;
                font-size: 11px;
            }}
            QDoubleSpinBox:focus {{ border-color: {_C['accent']}; }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                background: {_C['bg3']}; border: none;
            }}
        """)
        row3.addWidget(self._spin_amplitude)

        row3.addSpacing(20)

        spd_lbl = QLabel("Speed:")
        spd_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 11px; border: none;")
        row3.addWidget(spd_lbl)

        self._scan_slider = QSlider(Qt.Orientation.Horizontal)
        self._scan_slider.setRange(5, _MAX_SCAN_SPEED)
        self._scan_slider.setValue(30)
        self._scan_slider.setFixedWidth(130)
        self._scan_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {_C['border']}; height: 4px; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {_C['accent']}; width: 14px; height: 14px;
                margin: -5px 0; border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {_C['accent']}; border-radius: 2px;
            }}
        """)
        self._scan_slider.valueChanged.connect(
            lambda v: self._scan_speed_lbl.setText(f"{v} mm/s")
        )
        row3.addWidget(self._scan_slider)

        self._scan_speed_lbl = QLabel("30 mm/s")
        self._scan_speed_lbl.setFixedWidth(58)
        self._scan_speed_lbl.setStyleSheet(
            f"color: {_C['accent']}; font-size: 11px; font-weight: 700; border: none;"
        )
        row3.addWidget(self._scan_speed_lbl)

        row3.addStretch()
        outer.addLayout(row3)

        # Fix the bar height after all rows are known
        bar.setFixedHeight(outer.sizeHint().height() + 16)

        return bar

    # ── Scan slot handlers ────────────────────────────────────────────────────

    def _on_capture_point(self):
        """Read current arm X/Y/Z and store as the scan start position."""
        if self._arm is None:
            return
        code, pos = self._arm.get_position()
        if code != 0 or pos is None or len(pos) < 3:
            return
        self._scan_x, self._scan_y, self._scan_z = pos[0], pos[1], pos[2]
        self._lbl_scan_x.setText(f"{self._scan_x:+.2f}")
        self._lbl_scan_y.setText(f"{self._scan_y:+.2f}")
        self._lbl_scan_z.setText(f"{self._scan_z:+.2f}")

    def _on_reset_pos(self):
        """Restore scan position to the hard-coded default."""
        self._scan_x, self._scan_y, self._scan_z = (
            _DEFAULT_SCAN_X, _DEFAULT_SCAN_Y, _DEFAULT_SCAN_Z
        )
        self._lbl_scan_x.setText(f"{self._scan_x:+.2f}")
        self._lbl_scan_y.setText(f"{self._scan_y:+.2f}")
        self._lbl_scan_z.setText(f"{self._scan_z:+.2f}")

    def _on_start_scan(self):
        if self._arm is None:
            return
        pos = [self._scan_x, self._scan_y, self._scan_z,
               _FIXED_ROLL, _FIXED_PITCH, _FIXED_YAW]
        amplitude = self._spin_amplitude.value()
        speed     = self._scan_slider.value()
        self._arm.start_valve_scan(pos, amplitude, speed)

    def _on_stop_scan(self):
        if self._arm is None:
            return
        self._arm.stop_valve_scan()

    def _on_scan_state_changed(self, running: bool):
        self._btn_start_scan.setEnabled(not running)
        self._btn_stop_scan.setEnabled(running)
        self._scan_slider.setEnabled(not running)
        self._spin_amplitude.setEnabled(not running)
        self._btn_capture.setEnabled(not running)
        self._btn_reset_pos.setEnabled(not running)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        if self._arm is not None:
            self._arm.stop_valve_scan()
        self.config_mgr.save(_CONFIG_FILE)
        if self._cam:
            try:
                self._cam.raw_frame_received.disconnect(self._processor.submit_frame)
            except RuntimeError:
                pass
        if self._processor_started:
            self._processor.stop()
