"""
ModuleTrackerPanel — ArUco-based lab module tracker.

Layout:
  ┌──────────────────────────────────────────────────────────────┐
  │  Header: title  •  InfluxDB  •  [FEED] [MAP] [HISTORY]       │
  ├──────────────────────────────────┬───────────────────────────┤
  │  QStackedWidget (left)           │  Config panel (right)     │
  │   [0] live camera + AR overlays  │   angle / offset          │
  │   [1] top-down map (live)        │   map scale               │
  │   [2] history browser            │   modules table           │
  └──────────────────────────────────┴───────────────────────────┘
"""

import copy
import os
import threading
import time

from PySide6.QtCore    import Qt, QObject, Signal as _Signal
from PySide6.QtGui     import QFont, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox,
    QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from VisionForge.app.tasks.module_tracker.core import (
    DEFAULT_CAMERA_ANGLE_DEG, DEFAULT_CAMERA_HEIGHT_OFFSET, DEFAULT_MAP_SCALE_M,
    MODULE_PALETTE,
    ModuleEntry, ModuleInfluxWriter, ModuleTrackerConfig, PositionHistory,
    load_config, save_config,
)
from VisionForge.app.tasks.module_tracker.processor import ModuleTrackerProcessor
from VisionForge.app.tasks.module_tracker.widgets   import MapWidget, ModuleTrackerFeedWidget

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "module_tracker_config.json")

# ── Colour tokens ────────────────────────────────────────────────────────────
_C = {
    "bg":     "#060612",
    "bg2":    "#0C0C1E",
    "bg3":    "#111128",
    "border": "#1A1A38",
    "accent": "#00CFFF",
    "green":  "#00E676",
    "red":    "#FF4466",
    "text":   "#E8EAFF",
    "muted":  "#8890B8",
    "dim":    "#454878",
}

_PANEL_STYLE = f"""
    QWidget {{ color: {_C['text']}; font-size: 12px; }}
    QFrame#mtHeader {{
        background-color: {_C['bg2']};
        border-bottom: 1px solid {_C['border']};
    }}
    QFrame#mtRight {{
        background-color: {_C['bg2']};
        border-left: 1px solid {_C['border']};
    }}
    QTableWidget {{
        background-color: {_C['bg']};
        color: {_C['text']};
        gridline-color: {_C['border']};
        border: 1px solid {_C['border']};
        border-radius: 4px;
        font-size: 11px;
    }}
    QTableWidget::item:selected {{
        background-color: rgba(0,207,255,0.15);
        color: {_C['accent']};
    }}
    QHeaderView::section {{
        background-color: {_C['bg3']};
        color: {_C['muted']};
        border: none;
        border-right: 1px solid {_C['border']};
        padding: 4px;
        font-size: 11px;
        font-weight: 600;
    }}
    QDoubleSpinBox {{
        background-color: {_C['bg']};
        color: {_C['text']};
        border: 1px solid {_C['border']};
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 12px;
    }}
    QDoubleSpinBox:focus {{ border-color: {_C['accent']}; }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        background: {_C['bg3']}; border: none;
    }}
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
    QPushButton#mtBtn {{
        background-color: {_C['bg3']}; color: {_C['muted']};
        border: 1px solid {_C['border']}; border-radius: 5px;
        padding: 4px 12px; font-size: 11px;
    }}
    QPushButton#mtBtn:hover {{ background-color: {_C['bg2']}; color: {_C['text']}; }}
    QPushButton#mtAddBtn {{
        background-color: rgba(0,230,118,0.08); color: {_C['green']};
        border: 1px solid {_C['green']}; border-radius: 5px;
        padding: 4px 12px; font-size: 11px;
    }}
    QPushButton#mtAddBtn:hover {{ background-color: {_C['green']}; color: #000; }}
    QPushButton#mtDelBtn {{
        background-color: rgba(255,68,102,0.08); color: {_C['red']};
        border: 1px solid {_C['red']}; border-radius: 5px;
        padding: 4px 12px; font-size: 11px;
    }}
    QPushButton#mtDelBtn:hover {{ background-color: {_C['red']}; color: #fff; }}
    QScrollArea {{ border: none; background: transparent; }}
    QLabel#sectionLabel {{
        color: {_C['muted']}; font-size: 10px; font-weight: 600;
    }}
"""

_VIEW_FEED    = 0
_VIEW_MAP     = 1
_VIEW_HISTORY = 2

_BTN_ACTIVE = lambda accent, left, right: (
    f"QPushButton {{ background: rgba(0,207,255,0.12); color: {accent};"
    f" border: 1px solid {accent}; padding: 0 14px; font-size: 11px; font-weight: 700;"
    f" border-radius: 0; border-top-left-radius: {left}px; border-bottom-left-radius: {left}px;"
    f" border-top-right-radius: {right}px; border-bottom-right-radius: {right}px; }}"
)
_BTN_INACTIVE = lambda bg3, muted, border, left, right, no_left_border=False: (
    f"QPushButton {{ background: {bg3}; color: {muted};"
    f" border: 1px solid {border};"
    + ("border-left: none;" if no_left_border else "")
    + f" padding: 0 14px; font-size: 11px; font-weight: 700;"
    f" border-radius: 0; border-top-left-radius: {left}px; border-bottom-left-radius: {left}px;"
    f" border-top-right-radius: {right}px; border-bottom-right-radius: {right}px; }}"
    f"QPushButton:hover {{ color: {_C['text']}; }}"
)


class ModuleTrackerPanel(QWidget):

    def __init__(self, camera_client=None, arm_controller=None, parent=None):
        super().__init__(parent)
        self._cam  = camera_client
        self._arm  = arm_controller

        self._cfg: ModuleTrackerConfig = load_config(_CONFIG_FILE)
        self._influx   = ModuleInfluxWriter()
        self._history  = PositionHistory()
        self._last_write: dict[int, float] = {}
        self._detections: list = []
        self._arm_live = False   # True when arm is providing real data

        self._processor = ModuleTrackerProcessor()
        self._processor_started = False
        self._processor.update_config(copy.deepcopy(self._cfg))

        self._build_ui()

        # Start in manual mode; arm signals will switch to live when data arrives
        self._set_arm_source(live=False)

        # Processor signals
        self._processor.display_ready.connect(self._feed.set_display)
        self._processor.map_data_ready.connect(self._live_map.set_data)
        self._processor.detections_ready.connect(self._on_detections)
        self._processor.frame_size_changed.connect(self._on_frame_size)
        self._feed.size_changed.connect(self._processor.set_widget_size)

        # Arm — use signals instead of polling from the main thread.
        # Polling via QTimer called get_position() under a lock which could
        # block the main thread (and freeze the camera) if the SDK call hung.
        if self._arm is not None:
            self._arm.position_updated.connect(self._on_arm_position)
            self._arm.connection_changed.connect(self._on_arm_connection_changed)

    # ── Page lifecycle ────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self._cam:
            self._cam.raw_frame_received.connect(self._processor.submit_frame)
        if not self._processor_started:
            self._processor.start()
            self._processor_started = True
            self._processor.set_widget_size(
                self._feed.width(), self._feed.height(),
                self._feed.devicePixelRatioF(),
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
        self.setStyleSheet(_PANEL_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_header())
        root.addWidget(self._make_body(), 1)

    def _make_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("mtHeader")
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(0)

        title = QLabel("◈  MODULE TRACKER")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {_C['accent']};")
        hl.addWidget(title)
        hl.addStretch()

        # ── View toggle buttons ───────────────────────────────────────────
        self._btn_feed    = QPushButton("FEED")
        self._btn_map     = QPushButton("MAP")
        self._btn_history = QPushButton("HISTORY")
        for btn in (self._btn_feed, self._btn_map, self._btn_history):
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_feed.clicked.connect(lambda:    self._set_view(_VIEW_FEED))
        self._btn_map.clicked.connect(lambda:     self._set_view(_VIEW_MAP))
        self._btn_history.clicked.connect(lambda: self._set_view(_VIEW_HISTORY))

        hl.addWidget(self._btn_feed)
        hl.addWidget(self._btn_map)
        hl.addWidget(self._btn_history)
        self._apply_toggle_styles(_VIEW_FEED)

        hl.addSpacing(16)

        # InfluxDB dot
        self._influx_dot = QLabel("●")
        self._influx_dot.setFont(QFont("Segoe UI", 14))
        col = _C["green"] if self._influx.connected else _C["red"]
        self._influx_dot.setStyleSheet(f"color: {col};")
        self._influx_dot.setToolTip(
            "InfluxDB connected" if self._influx.connected else "InfluxDB unavailable"
        )
        hl.addWidget(self._influx_dot)
        lbl = QLabel("InfluxDB")
        lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 11px; margin-left: 4px;")
        hl.addWidget(lbl)

        return header

    def _make_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {_C['border']}; }}"
            f"QSplitter::handle:hover {{ background: {_C['accent']}; }}"
        )

        # ── Left: stacked views ───────────────────────────────────────────
        self._view_stack = QStackedWidget()
        self._view_stack.setStyleSheet(f"background-color: {_C['bg']};")

        self._feed     = ModuleTrackerFeedWidget()
        self._live_map = MapWidget()
        self._hist_view = self._make_history_view()

        self._view_stack.addWidget(self._feed)       # 0
        self._view_stack.addWidget(self._live_map)   # 1
        self._view_stack.addWidget(self._hist_view)  # 2
        self._view_stack.setCurrentIndex(_VIEW_FEED)

        splitter.addWidget(self._view_stack)

        # ── Right: config ─────────────────────────────────────────────────
        right = QFrame()
        right.setObjectName("mtRight")
        right.setMinimumWidth(260)
        right.setMaximumWidth(340)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._make_config_panel(), 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        return splitter

    # ── History view ──────────────────────────────────────────────────────────

    def _make_history_view(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet(f"background: {_C['bg']};")
        lo = QHBoxLayout(container)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # ── Left panel: snapshot list ─────────────────────────────────────
        left = QFrame()
        left.setFixedWidth(300)
        left.setStyleSheet(
            f"QFrame {{ background: {_C['bg2']}; border-right: 1px solid {_C['border']}; }}"
        )
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.setSpacing(8)

        # Header row
        row_h = QHBoxLayout()
        lbl_hist = QLabel("SNAPSHOTS")
        lbl_hist.setObjectName("sectionLabel")
        row_h.addWidget(lbl_hist)
        row_h.addStretch()
        self._hist_count_lbl = QLabel("0")
        self._hist_count_lbl.setStyleSheet(
            f"color: {_C['accent']}; font-size: 11px; font-weight: 700;"
        )
        row_h.addWidget(self._hist_count_lbl)
        ll.addLayout(row_h)

        # Snapshot table
        self._snap_table = QTableWidget(0, 2)
        self._snap_table.setHorizontalHeaderLabels(["Time", "Modules"])
        self._snap_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._snap_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._snap_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._snap_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._snap_table.verticalHeader().setVisible(False)
        self._snap_table.setAlternatingRowColors(False)
        self._snap_table.currentCellChanged.connect(
            lambda cur_row, _cc, _pr, _pc: self._on_snapshot_row_changed(cur_row)
        )
        ll.addWidget(self._snap_table, 1)

        # Timeline slider
        slider_row = QHBoxLayout()
        lbl_tl = QLabel("TIMELINE")
        lbl_tl.setObjectName("sectionLabel")
        slider_row.addWidget(lbl_tl)
        ll.addLayout(slider_row)

        self._hist_slider = QSlider(Qt.Orientation.Horizontal)
        self._hist_slider.setMinimum(0)
        self._hist_slider.setMaximum(0)
        self._hist_slider.valueChanged.connect(self._on_slider_changed)
        ll.addWidget(self._hist_slider)

        self._hist_time_lbl = QLabel("—")
        self._hist_time_lbl.setStyleSheet(
            f"color: {_C['muted']}; font-size: 10px; text-align: center;"
        )
        self._hist_time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self._hist_time_lbl)

        # Export / Clear
        btn_row = QHBoxLayout()
        btn_export = QPushButton("Export CSV")
        btn_export.setObjectName("mtBtn")
        btn_export.clicked.connect(self._export_csv)
        btn_row.addWidget(btn_export)

        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("mtDelBtn")
        btn_clear.clicked.connect(self._clear_history)
        btn_row.addWidget(btn_clear)
        ll.addLayout(btn_row)

        # ── InfluxDB query section ────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_C['border']};")
        ll.addWidget(sep)

        lbl_load = QLabel("LOAD FROM INFLUXDB")
        lbl_load.setObjectName("sectionLabel")
        ll.addWidget(lbl_load)

        range_row = QHBoxLayout()
        range_row.setSpacing(4)

        range_row.addWidget(QLabel("h"))
        self._load_hours_spin = QSpinBox()
        self._load_hours_spin.setRange(0, 720)
        self._load_hours_spin.setValue(1)
        self._load_hours_spin.setFixedWidth(56)
        self._load_hours_spin.setStyleSheet(
            f"QSpinBox {{ background: {_C['bg']}; color: {_C['text']};"
            f" border: 1px solid {_C['border']}; border-radius: 4px; padding: 2px 4px; }}"
            f"QSpinBox:focus {{ border-color: {_C['accent']}; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ background: {_C['bg3']}; border: none; }}"
        )
        range_row.addWidget(self._load_hours_spin)

        range_row.addSpacing(6)
        range_row.addWidget(QLabel("min"))
        self._load_mins_spin = QSpinBox()
        self._load_mins_spin.setRange(0, 59)
        self._load_mins_spin.setValue(0)
        self._load_mins_spin.setFixedWidth(56)
        self._load_mins_spin.setStyleSheet(self._load_hours_spin.styleSheet())
        range_row.addWidget(self._load_mins_spin)

        range_row.addStretch()

        self._btn_load_influx = QPushButton("Confirm")
        self._btn_load_influx.setObjectName("mtBtn")
        self._btn_load_influx.setFixedWidth(72)
        self._btn_load_influx.clicked.connect(self._load_from_influx)
        range_row.addWidget(self._btn_load_influx)
        ll.addLayout(range_row)

        self._load_status_lbl = QLabel("")
        self._load_status_lbl.setStyleSheet(
            f"color: {_C['muted']}; font-size: 10px;"
        )
        self._load_status_lbl.setWordWrap(True)
        ll.addWidget(self._load_status_lbl)

        lo.addWidget(left)

        # ── Right panel: snapshot map + module cards ──────────────────────
        right = QWidget()
        right.setStyleSheet(f"background: {_C['bg']};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.setHandleWidth(4)
        right_split.setStyleSheet(
            f"QSplitter::handle {{ background: {_C['border']}; }}"
        )

        self._hist_map = MapWidget()
        right_split.addWidget(self._hist_map)

        # Module detail table
        self._mod_detail = QTableWidget(0, 6)
        self._mod_detail.setHorizontalHeaderLabels(
            ["ID", "Dist (m)", "Marker X", "Marker Y", "Front dX", "Front dY"]
        )
        self._mod_detail.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._mod_detail.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._mod_detail.verticalHeader().setVisible(False)
        self._mod_detail.setMaximumHeight(160)
        self._mod_detail.setStyleSheet(
            f"QTableWidget {{ border-top: 1px solid {_C['border']}; border-radius: 0; }}"
        )
        right_split.addWidget(self._mod_detail)
        right_split.setStretchFactor(0, 1)
        right_split.setStretchFactor(1, 0)

        rl.addWidget(right_split, 1)
        lo.addWidget(right, 1)
        return container

    # ── Config panel ──────────────────────────────────────────────────────────

    def _make_config_panel(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setStyleSheet(f"background-color: {_C['bg2']};")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(10)

        # CAMERA header row with live/manual source indicator
        cam_hdr = QHBoxLayout()
        cam_hdr.addWidget(self._section_label("CAMERA"))
        cam_hdr.addStretch()
        self._lbl_arm_source = QLabel("● MANUAL")
        self._lbl_arm_source.setStyleSheet(
            f"color: {_C['muted']}; font-size: 10px; font-weight: 700;"
        )
        cam_hdr.addWidget(self._lbl_arm_source)
        cl.addLayout(cam_hdr)

        row_angle = QHBoxLayout()
        row_angle.addWidget(QLabel("Angle Ry (°)"))
        row_angle.addStretch()
        self._spin_angle = QDoubleSpinBox()
        self._spin_angle.setRange(-360.0, 360.0)
        self._spin_angle.setDecimals(1)
        self._spin_angle.setSingleStep(1.0)
        self._spin_angle.setValue(self._cfg.camera_angle_deg)
        self._spin_angle.setFixedWidth(90)
        self._spin_angle.valueChanged.connect(self._on_angle_changed)
        row_angle.addWidget(self._spin_angle)
        cl.addLayout(row_angle)

        row_offset = QHBoxLayout()
        row_offset.addWidget(QLabel("Height offset (m)"))
        row_offset.addStretch()
        self._spin_offset = QDoubleSpinBox()
        self._spin_offset.setRange(0.0, 5.0)
        self._spin_offset.setDecimals(2)
        self._spin_offset.setSingleStep(0.05)
        self._spin_offset.setValue(self._cfg.camera_height_offset)
        self._spin_offset.setFixedWidth(90)
        self._spin_offset.valueChanged.connect(self._on_offset_changed)
        row_offset.addWidget(self._spin_offset)
        cl.addLayout(row_offset)

        row_height = QHBoxLayout()
        row_height.addWidget(QLabel("Camera height (m)"))
        row_height.addStretch()
        self._spin_height = QDoubleSpinBox()
        self._spin_height.setRange(0.0, 5.0)
        self._spin_height.setDecimals(3)
        self._spin_height.setSingleStep(0.01)
        self._spin_height.setValue(self._cfg.camera_height_m)
        self._spin_height.setFixedWidth(90)
        self._spin_height.valueChanged.connect(self._on_height_changed)
        row_height.addWidget(self._spin_height)
        cl.addLayout(row_height)

        cl.addWidget(self._section_label("MAP"))

        row_scale = QHBoxLayout()
        row_scale.addWidget(QLabel("Scale (m)"))
        row_scale.addStretch()
        self._spin_scale = QDoubleSpinBox()
        self._spin_scale.setRange(1.0, 50.0)
        self._spin_scale.setDecimals(1)
        self._spin_scale.setSingleStep(0.5)
        self._spin_scale.setValue(self._cfg.map_scale_m)
        self._spin_scale.setFixedWidth(90)
        self._spin_scale.valueChanged.connect(self._on_scale_changed)
        row_scale.addWidget(self._spin_scale)
        cl.addLayout(row_scale)

        cl.addWidget(self._section_label("DETECTION"))

        # Toggle: Downscaled vs Full Resolution
        det_toggle_row = QHBoxLayout()
        det_toggle_row.setSpacing(0)

        self._btn_det_down = QPushButton("Downscaled")
        self._btn_det_down.setFixedHeight(26)
        self._btn_det_down.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_det_down.clicked.connect(lambda: self._set_detection_mode(True))

        self._btn_det_full = QPushButton("Full Res")
        self._btn_det_full.setFixedHeight(26)
        self._btn_det_full.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_det_full.clicked.connect(lambda: self._set_detection_mode(False))

        det_toggle_row.addWidget(self._btn_det_down)
        det_toggle_row.addWidget(self._btn_det_full)
        cl.addLayout(det_toggle_row)

        self._det_desc = QLabel()
        self._det_desc.setWordWrap(True)
        self._det_desc.setStyleSheet(f"color: {_C['muted']}; font-size: 10px;")
        cl.addWidget(self._det_desc)

        self._set_detection_mode(True)   # default: downscaled

        cl.addWidget(self._section_label("MODULES"))

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["ID", "Name", "W (m)", "H (m)", "L (m)"])
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        for col in (2, 3, 4):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.SelectedClicked
        )
        self._table.setMinimumHeight(120)
        self._table.itemChanged.connect(self._on_table_item_changed)
        self._table.verticalHeader().setVisible(False)
        cl.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add")
        btn_add.setObjectName("mtAddBtn")
        btn_add.clicked.connect(self._on_add_module)
        btn_row.addWidget(btn_add)
        btn_del = QPushButton("Remove")
        btn_del.setObjectName("mtDelBtn")
        btn_del.clicked.connect(self._on_remove_module)
        btn_row.addWidget(btn_del)
        cl.addLayout(btn_row)

        cl.addStretch()
        scroll.setWidget(container)
        self._refresh_table()
        return scroll

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sectionLabel")
        lbl.setFixedHeight(20)
        return lbl

    # ── View toggle ───────────────────────────────────────────────────────────

    def _set_view(self, idx: int):
        self._view_stack.setCurrentIndex(idx)
        self._apply_toggle_styles(idx)

    def _apply_toggle_styles(self, active: int):
        configs = [
            (self._btn_feed,    _VIEW_FEED,    5, 0),
            (self._btn_map,     _VIEW_MAP,     0, 0),
            (self._btn_history, _VIEW_HISTORY, 0, 5),
        ]
        for btn, view_idx, r_left, r_right in configs:
            is_active = (view_idx == active)
            accent = _C['accent']
            if is_active:
                style = (
                    f"QPushButton {{ background: rgba(0,207,255,0.12); color: {accent};"
                    f" border: 1px solid {accent};"
                    + ("border-left: none;" if view_idx != _VIEW_FEED else "")
                    + f" padding: 0 14px; font-size: 11px; font-weight: 700;"
                    f" border-radius: 0;"
                    f" border-top-left-radius: {r_left}px;"
                    f" border-bottom-left-radius: {r_left}px;"
                    f" border-top-right-radius: {r_right}px;"
                    f" border-bottom-right-radius: {r_right}px; }}"
                )
            else:
                style = (
                    f"QPushButton {{ background: {_C['bg3']}; color: {_C['muted']};"
                    f" border: 1px solid {_C['border']};"
                    + ("border-left: none;" if view_idx != _VIEW_FEED else "")
                    + f" padding: 0 14px; font-size: 11px; font-weight: 700;"
                    f" border-radius: 0;"
                    f" border-top-left-radius: {r_left}px;"
                    f" border-bottom-left-radius: {r_left}px;"
                    f" border-top-right-radius: {r_right}px;"
                    f" border-bottom-right-radius: {r_right}px; }}"
                    f"QPushButton:hover {{ color: {_C['text']}; }}"
                )
            btn.setStyleSheet(style)

    # ── Config handlers ───────────────────────────────────────────────────────

    def _on_angle_changed(self, val: float):
        self._cfg.camera_angle_deg = val
        self._push_config()

    def _on_height_changed(self, val: float):
        self._cfg.camera_height_m = val
        self._push_config()

    def _on_offset_changed(self, val: float):
        self._cfg.camera_height_offset = val
        self._push_config()

    def _on_scale_changed(self, val: float):
        self._cfg.map_scale_m = val
        self._push_config()

    def _set_detection_mode(self, downscale: bool):
        self._processor.set_downscale(downscale)
        _active   = (f"background: rgba(0,207,255,0.12); color: {_C['accent']};"
                     f" border: 1px solid {_C['accent']};")
        _inactive = (f"background: {_C['bg3']}; color: {_C['muted']};"
                     f" border: 1px solid {_C['border']};")
        base = "font-size: 11px; font-weight: 700; padding: 2px 0;"
        self._btn_det_down.setStyleSheet(
            f"QPushButton {{ {_active if downscale else _inactive} {base}"
            f" border-radius: 0; border-top-left-radius: 4px; border-bottom-left-radius: 4px; }}"
        )
        self._btn_det_full.setStyleSheet(
            f"QPushButton {{ {_inactive if downscale else _active} {base}"
            f" border-left: none; border-radius: 0;"
            f" border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}"
        )
        if downscale:
            self._det_desc.setText(
                "Resizes the frame to 640 px before detection. "
                "Faster ArUco processing — best for large or close markers."
            )
        else:
            self._det_desc.setText(
                "Runs ArUco on the full camera frame. "
                "Slower but can detect small or distant markers more reliably."
            )

    def _on_arm_position(self, x, y, z, roll, pitch, yaw):
        """Receives live position from ArmController.position_updated (background thread → main thread via signal)."""
        z_m = z / 1000.0   # mm → m

        self._cfg.camera_height_m  = z_m
        self._cfg.camera_angle_deg = float(yaw)

        self._spin_angle.blockSignals(True)
        self._spin_angle.setValue(float(yaw))
        self._spin_angle.blockSignals(False)

        self._spin_height.blockSignals(True)
        self._spin_height.setValue(z_m)
        self._spin_height.blockSignals(False)

        if not self._arm_live:
            self._set_arm_source(live=True)

        self._push_config()

    def _on_arm_connection_changed(self, connected: bool):
        if not connected:
            self._set_arm_source(live=False)

    def _set_arm_source(self, live: bool):
        self._arm_live = live
        if live:
            self._lbl_arm_source.setText("● LIVE")
            self._lbl_arm_source.setStyleSheet(
                f"color: {_C['green']}; font-size: 10px; font-weight: 700;"
            )
            self._spin_angle.setEnabled(False)
            self._spin_height.setEnabled(False)
            self._spin_angle.setToolTip("Controlled by arm — unavailable in manual mode")
            self._spin_height.setToolTip("Controlled by arm — unavailable in manual mode")
        else:
            self._lbl_arm_source.setText("● MANUAL")
            self._lbl_arm_source.setStyleSheet(
                f"color: {_C['muted']}; font-size: 10px; font-weight: 700;"
            )
            self._spin_angle.setEnabled(True)
            self._spin_height.setEnabled(True)
            self._spin_angle.setToolTip("Set camera Ry angle manually")
            self._spin_height.setToolTip("Set camera height manually")

    def _push_config(self):
        self._processor.update_config(copy.deepcopy(self._cfg))

    # ── Modules table ─────────────────────────────────────────────────────────

    def _refresh_table(self):
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for mid, entry in sorted(self._cfg.modules.items()):
            self._table_add_row(entry)
        self._table.blockSignals(False)

    def _table_add_row(self, entry: ModuleEntry):
        row = self._table.rowCount()
        self._table.insertRow(row)
        id_item = QTableWidgetItem(str(entry.id))
        id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        id_item.setForeground(QColor(_C["accent"]))
        self._table.setItem(row, 0, id_item)
        self._table.setItem(row, 1, QTableWidgetItem(entry.name))
        self._table.setItem(row, 2, QTableWidgetItem(f"{entry.width:.3f}"))
        self._table.setItem(row, 3, QTableWidgetItem(f"{entry.height:.3f}"))
        self._table.setItem(row, 4, QTableWidgetItem(f"{entry.length:.3f}"))

    def _on_table_item_changed(self, item: QTableWidgetItem):
        row = item.row()
        id_item = self._table.item(row, 0)
        if id_item is None:
            return
        try:
            mid = int(id_item.text())
        except ValueError:
            return
        if mid not in self._cfg.modules:
            return
        col = item.column()
        try:
            if col == 1:
                self._cfg.modules[mid].name = item.text().strip() or f"Module {mid}"
            elif col == 2:
                self._cfg.modules[mid].width  = max(0.01, float(item.text()))
            elif col == 3:
                self._cfg.modules[mid].height = max(0.01, float(item.text()))
            elif col == 4:
                self._cfg.modules[mid].length = max(0.01, float(item.text()))
        except ValueError:
            pass
        self._push_config()

    def _on_add_module(self):
        new_id, ok = QInputDialog.getInt(
            self, "Add Module", "Enter ArUco marker ID:", 0, 0, 9999, 1
        )
        if not ok:
            return
        if new_id in self._cfg.modules:
            QMessageBox.warning(
                self, "ID already exists",
                f"A module with ID {new_id} already exists.\n"
                "Please choose a different ID.",
            )
            return
        entry = ModuleEntry(id=new_id, name=f"Module {new_id}",
                            width=0.40, height=0.30, length=0.20)
        self._cfg.modules[new_id] = entry
        self._table.blockSignals(True)
        self._table_add_row(entry)
        self._table.blockSignals(False)
        self._push_config()

    def _on_remove_module(self):
        if not self._table.selectedItems():
            return
        row = self._table.currentRow()
        id_item = self._table.item(row, 0)
        if id_item is None:
            return
        try:
            mid = int(id_item.text())
        except ValueError:
            return
        self._cfg.modules.pop(mid, None)
        self._table.removeRow(row)
        self._push_config()

    # ── Detection / InfluxDB / history ────────────────────────────────────────

    def _on_frame_size(self, fw: int, fh: int):
        pass

    def _on_detections(self, detections: list):
        self._detections = detections
        now = time.time()

        modules_data = {}
        for det in detections:
            mid = det["id"]
            lab = det.get("lab")
            if lab is None:
                continue
            modules_data[mid] = lab

            # InfluxDB — 1 write/second per module
            last = self._last_write.get(mid, 0.0)
            if (now - last) >= 1.0:
                self._last_write[mid] = now
                name = (self._cfg.modules[mid].name
                        if mid in self._cfg.modules else f"Module {mid}")
                self._influx.write(mid, name, lab)

        # History recording
        if modules_data and self._history.maybe_record(modules_data):
            self._append_snapshot_row(self._history.snapshots[-1])
            n = len(self._history)
            self._hist_count_lbl.setText(str(n))
            self._hist_slider.setMaximum(max(0, n - 1))
            # Auto-scroll to latest if history view is active
            if self._view_stack.currentIndex() == _VIEW_HISTORY:
                self._snap_table.scrollToBottom()

    # ── History view helpers ──────────────────────────────────────────────────

    def _append_snapshot_row(self, snap: dict):
        row = self._snap_table.rowCount()
        self._snap_table.insertRow(row)
        t_str = snap["datetime"].split(" ")[1]   # HH:MM:SS
        n_mod = len(snap["modules"])
        self._snap_table.setItem(row, 0, QTableWidgetItem(t_str))
        mod_item = QTableWidgetItem(str(n_mod))
        mod_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._snap_table.setItem(row, 1, mod_item)

    def _show_snapshot(self, idx: int):
        if not self._history.snapshots:
            return
        idx = max(0, min(idx, len(self._history) - 1))
        snap = self._history.snapshots[idx]

        # Update time label
        self._hist_time_lbl.setText(snap["datetime"])

        # Render snapshot map
        modules_data = self._history.snapshot_to_modules(snap)
        self._hist_map.set_data(
            modules_data if modules_data else None,
            self._cfg.map_scale_m,
            self._cfg.camera_angle_deg,
            self._cfg.camera_height_m + self._cfg.camera_height_offset,
        )

        # Populate module detail table
        self._mod_detail.blockSignals(True)
        self._mod_detail.setRowCount(0)
        for i, (mid, md) in enumerate(sorted(snap["modules"].items())):
            r = self._mod_detail.rowCount()
            self._mod_detail.insertRow(r)

            col_bgr = MODULE_PALETTE[i % len(MODULE_PALETTE)]
            col_hex = "#{:02X}{:02X}{:02X}".format(col_bgr[2], col_bgr[1], col_bgr[0])

            id_item = QTableWidgetItem(str(mid))
            id_item.setForeground(QColor(col_hex))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._mod_detail.setItem(r, 0, id_item)

            for col_i, val in enumerate([
                f"{md['distance']:.3f}",
                f"{md['marker_x']:+.4f}",
                f"{md['marker_y']:+.4f}",
                f"{md['front_dx']:+.3f}",
                f"{md['front_dy']:+.3f}",
            ], start=1):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._mod_detail.setItem(r, col_i, item)

        self._mod_detail.blockSignals(False)

    def _on_snapshot_row_changed(self, row: int):
        if row < 0:
            return
        self._hist_slider.blockSignals(True)
        self._hist_slider.setValue(row)
        self._hist_slider.blockSignals(False)
        self._show_snapshot(row)

    def _on_slider_changed(self, value: int):
        self._snap_table.blockSignals(True)
        self._snap_table.selectRow(value)
        self._snap_table.blockSignals(False)
        self._show_snapshot(value)

    def _export_csv(self):
        if not self._history.snapshots:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export History CSV",
            f"aruco_history_{len(self._history)}.csv",
            "CSV files (*.csv)",
        )
        if path:
            result = self._history.export_csv(path)
            if result:
                print(f"[ModuleTracker] CSV exported → {result}", flush=True)

    def _clear_history(self):
        self._history.clear()
        self._snap_table.setRowCount(0)
        self._hist_count_lbl.setText("0")
        self._hist_slider.setMaximum(0)
        self._hist_time_lbl.setText("—")
        self._hist_map.set_data(None, self._cfg.map_scale_m,
                               self._cfg.camera_angle_deg,
                               self._cfg.camera_height_m + self._cfg.camera_height_offset)
        self._mod_detail.setRowCount(0)

    # ── InfluxDB load ─────────────────────────────────────────────────────────

    def _load_from_influx(self):
        hours   = self._load_hours_spin.value()
        minutes = self._load_mins_spin.value()
        if hours == 0 and minutes == 0:
            self._load_status_lbl.setText("Set at least 1 minute.")
            return

        self._btn_load_influx.setEnabled(False)
        self._btn_load_influx.setText("…")
        self._load_status_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 10px;")
        self._load_status_lbl.setText(f"Querying last {hours}h {minutes}min…")

        # Use a dedicated QObject so the signal is delivered on the main thread
        # even though it's emitted from a daemon thread.
        class _Relay(QObject):
            done = _Signal(list, str)   # (snapshots, error_message)

        relay = _Relay()
        relay.done.connect(self._on_influx_query_done)
        self._influx_relay = relay   # keep alive until callback fires

        def do_query():
            try:
                snaps = self._influx.query_history(hours, minutes)
                relay.done.emit(snaps, "")
            except Exception as exc:
                relay.done.emit([], str(exc))

        threading.Thread(target=do_query, daemon=True).start()

    def _on_influx_query_done(self, snapshots: list, err: str):
        self._influx_relay = None   # release the relay object
        self._btn_load_influx.setEnabled(True)
        self._btn_load_influx.setText("Confirm")

        if err:
            self._load_status_lbl.setStyleSheet(f"color: {_C['red']}; font-size: 10px;")
            self._load_status_lbl.setText(f"Error: {err}")
            return
        if not snapshots:
            self._load_status_lbl.setStyleSheet(f"color: {_C['muted']}; font-size: 10px;")
            self._load_status_lbl.setText("No data found in that range.")
            return

        added = self._history.load_snapshots(snapshots)
        self._rebuild_snapshot_table()
        self._load_status_lbl.setStyleSheet(f"color: {_C['green']}; font-size: 10px;")
        self._load_status_lbl.setText(
            f"Loaded {added} new snapshots  ({len(self._history)} total)"
        )

    def _rebuild_snapshot_table(self):
        """Repopulate the snapshot table from scratch (used after InfluxDB load)."""
        self._snap_table.blockSignals(True)
        self._snap_table.setRowCount(0)
        for snap in self._history.snapshots:
            self._append_snapshot_row(snap)
        self._snap_table.blockSignals(False)
        n = len(self._history)
        self._hist_count_lbl.setText(str(n))
        self._hist_slider.setMaximum(max(0, n - 1))
        if n > 0:
            self._snap_table.scrollToBottom()
            self._snap_table.selectRow(n - 1)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        save_config(self._cfg, _CONFIG_FILE)
        if self._cam:
            try:
                self._cam.raw_frame_received.disconnect(self._processor.submit_frame)
            except RuntimeError:
                pass
        if self._arm is not None:
            try:
                self._arm.position_updated.disconnect(self._on_arm_position)
            except RuntimeError:
                pass
            try:
                self._arm.connection_changed.disconnect(self._on_arm_connection_changed)
            except RuntimeError:
                pass
        if self._processor_started:
            self._processor.stop()
        self._influx.close()
