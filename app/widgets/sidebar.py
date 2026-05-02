"""
Sidebar — left navigation panel.
Emits page_changed(int) when the user selects a section.

Layout:
  ◉  Camera
  ⬡  xArm Control
  ◫  Tasks  ▸          ← click to expand
       ◈  Valve Orientation
       ⬡  7-Seg Detection
       ◈  Module Tracker
  [collapse strip]
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from PySide6.QtCore    import Qt, Signal
from PySide6.QtGui     import QPainter, QColor, QFont, QFontMetrics

# ── Item definitions ──────────────────────────────────────────────────────────

_TOP_ITEMS = [
    {"icon": "◉", "label": "Camera",       "index": 0},
    {"icon": "⬡", "label": "xArm Control", "index": 1},
]

_TASK_ITEMS = [
    {"icon": "◈", "label": "Valve Orientation", "index": 2},
    {"icon": "⬡", "label": "7-Seg Detection",   "index": 3},
    {"icon": "◈", "label": "Module Tracker",    "index": 4},
]

# ── Layout constants ──────────────────────────────────────────────────────────

_STRIP_W     = 10
_COLLAPSED_W = 48
_ICON_X      = 13
_ICON_W      = 24
_LABEL_X     = 44
_RIGHT_PAD   = 12
_SUB_ICON_X  = 30     # indented icon position for sub-items
_SUB_LABEL_X = 52     # indented label position for sub-items


def _nav_width() -> int:
    fm = QFontMetrics(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
    all_labels = [it["label"] for it in _TOP_ITEMS + _TASK_ITEMS] + ["Tasks"]
    max_text = max(fm.horizontalAdvance(lbl) for lbl in all_labels)
    return _LABEL_X + max_text + _RIGHT_PAD + 18   # +18 for the arrow glyph


# ── Regular nav button ────────────────────────────────────────────────────────

class _NavButton(QWidget):
    clicked = Signal(int)

    def __init__(self, icon: str, label: str, index: int, parent=None):
        super().__init__(parent)
        self._icon      = icon
        self._label     = label
        self._index     = index
        self._selected  = False
        self._collapsed = False
        self._hovered   = False
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_selected(self, v: bool):  self._selected  = v; self.update()
    def set_collapsed(self, v: bool): self._collapsed = v; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)

    def enterEvent(self, e): self._hovered = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hovered = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._selected:
            p.fillRect(self.rect(), QColor(0, 207, 255, 14))
            p.fillRect(0, 0, 3, self.height(), QColor("#00CFFF"))
        elif self._hovered:
            p.fillRect(self.rect(), QColor(255, 255, 255, 7))

        col = QColor("#00CFFF") if self._selected else QColor("#8890B8")
        p.setPen(col)

        if self._collapsed:
            p.setFont(QFont("Segoe UI", 15))
            p.drawText(0, 0, self.width(), self.height(),
                       Qt.AlignmentFlag.AlignCenter, self._icon)
        else:
            p.setFont(QFont("Segoe UI", 15))
            p.drawText(_ICON_X, 0, _ICON_W, self.height(),
                       Qt.AlignmentFlag.AlignVCenter, self._icon)
            p.setFont(QFont("Segoe UI", 12,
                       QFont.Weight.DemiBold if self._selected else QFont.Weight.Normal))
            p.drawText(_LABEL_X, 0, self.width() - _LABEL_X - _RIGHT_PAD,
                       self.height(), Qt.AlignmentFlag.AlignVCenter, self._label)
        p.end()


# ── Tasks group button ────────────────────────────────────────────────────────

class _GroupButton(QWidget):
    """Collapsible group header for the task pages."""
    toggled = Signal(bool)   # True = expanded

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded      = False
        self._collapsed     = False   # sidebar-level collapse
        self._hovered       = False
        self._child_selected = False
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Tasks")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_collapsed(self, v: bool):       self._collapsed = v;      self.update()
    def set_child_selected(self, v: bool):  self._child_selected = v; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._expanded = not self._expanded
            self.toggled.emit(self._expanded)
            self.update()

    def enterEvent(self, e): self._hovered = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hovered = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._child_selected:
            p.fillRect(self.rect(), QColor(0, 207, 255, 8))
            p.fillRect(0, 0, 3, self.height(), QColor(0, 207, 255, 70))
        elif self._hovered:
            p.fillRect(self.rect(), QColor(255, 255, 255, 7))

        col = QColor("#00CFFF") if self._child_selected else (
              QColor("#C0E8FF") if self._hovered else QColor("#8890B8"))
        p.setPen(col)

        if self._collapsed:
            p.setFont(QFont("Segoe UI", 15))
            p.drawText(0, 0, self.width(), self.height(),
                       Qt.AlignmentFlag.AlignCenter, "◫")
        else:
            p.setFont(QFont("Segoe UI", 15))
            p.drawText(_ICON_X, 0, _ICON_W, self.height(),
                       Qt.AlignmentFlag.AlignVCenter, "◫")
            p.setFont(QFont("Segoe UI", 12))
            p.drawText(_LABEL_X, 0, self.width() - _LABEL_X - _RIGHT_PAD - 16,
                       self.height(), Qt.AlignmentFlag.AlignVCenter, "Tasks")
            arrow = "▾" if self._expanded else "▸"
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(self.width() - _RIGHT_PAD - 14, 0,
                       14, self.height(),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       arrow)
        p.end()


# ── Task sub-button ───────────────────────────────────────────────────────────

class _SubNavButton(QWidget):
    clicked = Signal(int)

    def __init__(self, icon: str, label: str, index: int, parent=None):
        super().__init__(parent)
        self._icon      = icon
        self._label     = label
        self._index     = index
        self._selected  = False
        self._collapsed = False
        self._hovered   = False
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_selected(self, v: bool):  self._selected  = v; self.update()
    def set_collapsed(self, v: bool): self._collapsed = v; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)

    def enterEvent(self, e): self._hovered = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hovered = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._selected:
            p.fillRect(self.rect(), QColor(0, 207, 255, 14))
            p.fillRect(0, 0, 3, self.height(), QColor("#00CFFF"))
        elif self._hovered:
            p.fillRect(self.rect(), QColor(255, 255, 255, 6))

        if not self._collapsed:
            # Subtle tree connector line
            p.setPen(QColor(69, 72, 120, 80))
            mid_y = self.height() // 2
            p.drawLine(_ICON_X + 6, 0, _ICON_X + 6, mid_y)
            p.drawLine(_ICON_X + 6, mid_y, _SUB_ICON_X - 2, mid_y)

        col = QColor("#00CFFF") if self._selected else (
              QColor("#B0C8E8") if self._hovered else QColor("#6870A0"))
        p.setPen(col)

        if self._collapsed:
            p.setFont(QFont("Segoe UI", 13))
            p.drawText(0, 0, self.width(), self.height(),
                       Qt.AlignmentFlag.AlignCenter, self._icon)
        else:
            p.setFont(QFont("Segoe UI", 12))
            p.drawText(_SUB_ICON_X, 0, _ICON_W, self.height(),
                       Qt.AlignmentFlag.AlignVCenter, self._icon)
            p.setFont(QFont("Segoe UI", 11,
                       QFont.Weight.DemiBold if self._selected else QFont.Weight.Normal))
            p.drawText(_SUB_LABEL_X, 0, self.width() - _SUB_LABEL_X - _RIGHT_PAD,
                       self.height(), Qt.AlignmentFlag.AlignVCenter, self._label)
        p.end()


# ── Collapse strip ────────────────────────────────────────────────────────────

class _CollapseStrip(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._hovered   = False
        self.setFixedWidth(_STRIP_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Collapse sidebar")

    def set_collapsed(self, v: bool):
        self._collapsed = v
        self.setToolTip("Expand sidebar" if v else "Collapse sidebar")
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def enterEvent(self, e): self._hovered = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hovered = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            p.fillRect(self.rect(), QColor(0, 207, 255, 20))
        else:
            p.fillRect(self.rect(), QColor(26, 26, 56, 80))
        p.setPen(QColor("#1A1A38"))
        p.drawLine(0, 0, 0, self.height())
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        cy = self.height() // 2
        col = QColor("#00CFFF") if self._hovered else QColor("#454878")
        p.setPen(col)
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(0, cy - 10, self.width(), 20,
                   Qt.AlignmentFlag.AlignCenter,
                   "▶" if self._collapsed else "◀")
        p.end()


# ── Sidebar ───────────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    page_changed = Signal(int)

    _TASK_INDICES = {it["index"] for it in _TASK_ITEMS}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nav_btns:  list[_NavButton]    = []
        self._sub_btns:  list[_SubNavButton] = []
        self._collapsed  = False
        self._nav_w      = _nav_width()
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("background-color: #060612;")
        self.setFixedWidth(self._nav_w + _STRIP_W)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._nav_area = QWidget()
        self._nav_area.setStyleSheet("background-color: transparent;")
        nav_lo = QVBoxLayout(self._nav_area)
        nav_lo.setContentsMargins(0, 8, 0, 8)
        nav_lo.setSpacing(2)

        # Top-level items
        for item in _TOP_ITEMS:
            btn = _NavButton(item["icon"], item["label"], item["index"])
            btn.clicked.connect(self._select)
            self._nav_btns.append(btn)
            nav_lo.addWidget(btn)

        # Separator line before Tasks group
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #1A1A38;")
        nav_lo.addSpacing(4)
        nav_lo.addWidget(sep)
        nav_lo.addSpacing(4)

        # Tasks group button
        self._group_btn = _GroupButton()
        self._group_btn.toggled.connect(self._on_tasks_toggled)
        nav_lo.addWidget(self._group_btn)

        # Task sub-buttons (hidden until group is expanded)
        for item in _TASK_ITEMS:
            btn = _SubNavButton(item["icon"], item["label"], item["index"])
            btn.clicked.connect(self._select)
            btn.setVisible(False)
            self._sub_btns.append(btn)
            nav_lo.addWidget(btn)

        nav_lo.addStretch()
        root.addWidget(self._nav_area, 1)

        self._strip = _CollapseStrip()
        self._strip.clicked.connect(self._toggle_collapse)
        root.addWidget(self._strip)

        self._select(0)

    # ── Expand / collapse tasks group ─────────────────────────────────────────

    def _on_tasks_toggled(self, expanded: bool):
        for btn in self._sub_btns:
            btn.setVisible(expanded)

    # ── Sidebar collapse ──────────────────────────────────────────────────────

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._strip.set_collapsed(self._collapsed)

        if self._collapsed:
            self.setFixedWidth(_COLLAPSED_W)
        else:
            self.setFixedWidth(self._nav_w + _STRIP_W)

        for btn in self._nav_btns:
            btn.set_collapsed(self._collapsed)
        self._group_btn.set_collapsed(self._collapsed)
        for btn in self._sub_btns:
            btn.set_collapsed(self._collapsed)

    # ── Selection ─────────────────────────────────────────────────────────────

    def _select(self, index: int):
        for btn in self._nav_btns:
            btn.set_selected(btn._index == index)
        for btn in self._sub_btns:
            btn.set_selected(btn._index == index)

        is_task = index in self._TASK_INDICES
        self._group_btn.set_child_selected(is_task)

        # Auto-expand the group when a task is selected
        if is_task and not self._group_btn._expanded:
            self._group_btn._expanded = True
            self._group_btn.update()
            self._on_tasks_toggled(True)

        self.page_changed.emit(index)
