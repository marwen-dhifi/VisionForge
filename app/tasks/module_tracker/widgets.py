"""
Module Tracker widgets.

ModuleTrackerFeedWidget — live camera feed (subclasses FeedWidget)
MapWidget               — top-down map rendered with QPainter at native resolution.
                          No OpenCV, no fixed bitmap, no upscaling.
                          Call set_data() to update.
"""

import math

from PySide6.QtCore    import Signal, Qt, QPointF, QRectF
from PySide6.QtGui     import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter,
    QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

from VisionForge.app.widgets.feed_widget import FeedWidget
from VisionForge.app.tasks.module_tracker.core import SWAP_XY


# ── Colour palette (RGB) — mirrors the app dark theme ────────────────────────
_BG         = QColor("#060612")
_BG_HEADER  = QColor("#0A080E")
_GRID_MINOR = QColor(28, 14, 14)
_GRID_MAJOR = QColor(48, 24, 24)
_BORDER     = QColor(56, 26, 26)
_CAMERA     = QColor(0, 207, 255)       # #00CFFF accent
_CAM_DIR    = QColor(0, 170, 210)
_AXIS_X     = QColor(90, 160, 255)
_AXIS_Y     = QColor(70, 225, 100)
_MOD_FRONT  = QColor(50, 220, 180)
_MARKER_DOT = QColor(255, 55, 55)
_MOD_TEXT   = QColor(235, 235, 235)
_DIST_TEXT  = QColor(136, 144, 184)
_SCALE_COL  = QColor(110, 100, 80)
_MUTED      = QColor(69, 72, 120)

_MODULE_COLORS = [
    QColor(  0, 207, 255),   # cyan   #00CFFF
    QColor(  0, 230, 118),   # green  #00E676
    QColor( 80, 140, 255),   # blue
    QColor(200,  80, 210),   # purple
    QColor(255, 200,  20),   # yellow
    QColor(255, 130,  50),   # orange
]


# ── Helper: draw an arrowed line ──────────────────────────────────────────────

def _arrowed_line(painter: QPainter, x0: float, y0: float,
                  x1: float, y1: float, tip: float = 0.16):
    painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    if L < 1:
        return
    ux, uy = dx / L, dy / L
    px, py = -uy, ux
    tl = L * tip
    head = QPolygonF([
        QPointF(x1, y1),
        QPointF(x1 - ux * tl + px * tl * 0.38, y1 - uy * tl + py * tl * 0.38),
        QPointF(x1 - ux * tl - px * tl * 0.38, y1 - uy * tl - py * tl * 0.38),
    ])
    saved = painter.pen()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPolygon(head)
    painter.setPen(saved)


# ── Feed widget ───────────────────────────────────────────────────────────────

class ModuleTrackerFeedWidget(FeedWidget):
    """Feed widget that accepts pre-rendered QImages from the processor."""

    size_changed = Signal(int, int, float)

    def set_display(self, qimg: QImage):
        self._pixmap    = QPixmap.fromImage(qimg)
        self._connected = True
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.size_changed.emit(self.width(), self.height(), self.devicePixelRatioF())


# ── Map widget ────────────────────────────────────────────────────────────────

class MapWidget(QWidget):
    """
    Resolution-independent top-down map.
    Renders with QPainter at native widget resolution — no bitmap, no blur.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._modules_data:    dict | None = None
        self._map_scale_m:     float = 8.0
        self._camera_angle:    float = 60.0
        self._camera_height_m: float = 0.0
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, modules_data: dict | None,
                 map_scale_m: float,
                 camera_angle_deg: float,
                 camera_height_m: float):
        self._modules_data    = modules_data
        self._map_scale_m     = map_scale_m
        self._camera_angle    = camera_angle_deg
        self._camera_height_m = camera_height_m
        self.update()

    # Legacy no-op so old set_map(None) calls don't crash
    def set_map(self, _):
        self._modules_data = None
        self.update()

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _to_pt(self, lx: float, ly: float,
               scale: float, ox: float, oy: float) -> QPointF:
        if SWAP_XY:
            lx, ly = ly, lx
        return QPointF(ox + lx / scale, oy - ly / scale)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing |
            QPainter.RenderHint.SmoothPixmapTransform,
        )

        W, H = self.width(), self.height()
        qp.fillRect(0, 0, W, H, _BG)

        # ── Placeholder ───────────────────────────────────────────────────────
        if not self._modules_data:
            qp.setPen(QPen(_GRID_MINOR, 1))
            step = 28
            for gx in range(0, W, step):
                for gy in range(0, H, step):
                    qp.drawPoint(gx, gy)
            qp.setPen(_MUTED)
            qp.setFont(QFont("Segoe UI", 12, QFont.Weight.Light))
            qp.drawText(self.rect(),
                        Qt.AlignmentFlag.AlignCenter,
                        "◈  Waiting for ArUco markers…")
            qp.end()
            return

        # ── Layout ────────────────────────────────────────────────────────────
        HEADER = 34
        MARGIN = max(44, int(min(W, H) * 0.075))
        draw_w = W - 2 * MARGIN
        draw_h = H - MARGIN - HEADER
        draw   = min(draw_w, draw_h)
        if draw < 20:
            qp.end()
            return

        scale = self._map_scale_m / draw
        ox = float(MARGIN)
        oy = float(H - MARGIN)

        # ── Header ────────────────────────────────────────────────────────────
        qp.fillRect(0, 0, W, HEADER, _BG_HEADER)
        qp.setPen(QPen(_BORDER, 1))
        qp.drawLine(0, HEADER, W, HEADER)

        qp.setPen(_MOD_TEXT)
        qp.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        qp.drawText(QRectF(MARGIN, 0, W * 0.5, HEADER),
                    Qt.AlignmentFlag.AlignVCenter, "LAB TOP-DOWN MAP")

        qp.setPen(_DIST_TEXT)
        qp.setFont(QFont("Segoe UI", 8))
        info = (f"angle {self._camera_angle:.1f}°   "
                f"h {self._camera_height_m:.2f} m   "
                f"{len(self._modules_data)} module{'s' if len(self._modules_data) != 1 else ''}")
        qp.drawText(QRectF(W * 0.5, 0, W * 0.5 - MARGIN, HEADER),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    info)

        # ── Grid ──────────────────────────────────────────────────────────────
        step_px = 0.25 / scale      # pixels per 0.25 m minor interval
        if step_px >= 7:
            i = 0
            while True:
                x = ox + i * step_px
                if x > ox + draw_w + 1:
                    break
                col = _GRID_MAJOR if i % 2 == 0 else _GRID_MINOR
                qp.setPen(QPen(col, 1))
                qp.drawLine(QPointF(x, HEADER + 1), QPointF(x, oy))
                i += 1
            j = 0
            while True:
                y = oy - j * step_px
                if y < HEADER:
                    break
                col = _GRID_MAJOR if j % 2 == 0 else _GRID_MINOR
                qp.setPen(QPen(col, 1))
                qp.drawLine(QPointF(ox, y), QPointF(ox + draw_w, y))
                j += 1

        # Drawable-area border
        qp.setPen(QPen(_BORDER, 1))
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawRect(QRectF(ox, HEADER, draw_w, H - HEADER - MARGIN))

        # ── Camera origin ──────────────────────────────────────────────────────
        ar  = math.radians(self._camera_angle)
        cxf, cyf = ox, oy

        # View cone
        cone_len = 1.1 / scale
        for da in (-math.radians(18), math.radians(18)):
            ex = cxf + cone_len * math.cos(ar + da)
            ey = cyf - cone_len * math.sin(ar + da)
            qp.setPen(QPen(QColor(40, 35, 20, 55), 1))
            qp.drawLine(QPointF(cxf, cyf), QPointF(ex, ey))

        # Direction arrow
        arl = 0.55 / scale
        qp.setPen(QPen(_CAM_DIR, 1.5))
        qp.setBrush(QBrush(_CAM_DIR))
        _arrowed_line(qp, cxf, cyf,
                      cxf + arl * math.cos(ar),
                      cyf - arl * math.sin(ar), tip=0.2)

        # Rings
        qp.setPen(QPen(QColor(0, 100, 140), 1.5))
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawEllipse(QPointF(cxf, cyf), 12, 12)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QBrush(_CAMERA))
        qp.drawEllipse(QPointF(cxf, cyf), 7, 7)

        qp.setPen(_CAMERA)
        qp.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        qp.drawText(QPointF(cxf + 15, cyf - 3), "CAM")

        # ── Axis arrows ───────────────────────────────────────────────────────
        ax = 0.5 / scale
        qp.setPen(QPen(_AXIS_X, 1.5))
        qp.setBrush(QBrush(_AXIS_X))
        _arrowed_line(qp, ox, oy, ox + ax, oy, tip=0.14)
        qp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        qp.setPen(_AXIS_X)
        qp.drawText(QPointF(ox + ax + 5, oy + 5), "X")

        qp.setPen(QPen(_AXIS_Y, 1.5))
        qp.setBrush(QBrush(_AXIS_Y))
        _arrowed_line(qp, ox, oy, ox, oy - ax, tip=0.14)
        qp.setPen(_AXIS_Y)
        qp.drawText(QPointF(ox + 5, oy - ax - 3), "Y")

        # ── Modules ───────────────────────────────────────────────────────────
        for idx, (mid, data) in enumerate(self._modules_data.items()):
            mcol = _MODULE_COLORS[idx % len(_MODULE_COLORS)]

            corners_lab = data["corners_lab"]
            front_dir   = data["front_dir"]
            marker_lab  = data["marker_lab"]
            distance    = data["distance"]

            pts = QPolygonF([
                self._to_pt(float(c[0]), float(c[1]), scale, ox, oy)
                for c in corners_lab
            ])
            cx = sum(pt.x() for pt in pts) / 4
            cy = sum(pt.y() for pt in pts) / 4
            cen = QPointF(cx, cy)

            # Semi-transparent body fill
            fill_col = QColor(mcol.red(), mcol.green(), mcol.blue(), 22)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QBrush(fill_col))
            qp.drawPolygon(pts)

            # Outline
            edge_col = QColor(mcol.red(), mcol.green(), mcol.blue(), 160)
            qp.setPen(QPen(edge_col, 1.2))
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.drawPolygon(pts)

            # Front face — bright teal, thick
            qp.setPen(QPen(_MOD_FRONT, 3.0))
            qp.drawLine(pts[0], pts[1])

            # Front direction arrow from centre
            alen = max(12.0, 0.08 / scale)
            fa_x = cen.x() + front_dir[0] * alen
            fa_y = cen.y() - front_dir[1] * alen
            qp.setPen(QPen(_MOD_FRONT, 1.5))
            qp.setBrush(QBrush(_MOD_FRONT))
            _arrowed_line(qp, cen.x(), cen.y(), fa_x, fa_y, tip=0.35)

            # Marker dot
            mp = self._to_pt(float(marker_lab[0]), float(marker_lab[1]), scale, ox, oy)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QBrush(_MARKER_DOT))
            qp.drawEllipse(mp, 5, 5)
            qp.setPen(QPen(mcol, 1.2))
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.drawEllipse(mp, 8, 8)

            # ID text
            qp.setPen(mcol)
            id_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
            qp.setFont(id_font)
            id_str = f"ID {mid}"
            id_w = QFontMetricsF(id_font).horizontalAdvance(id_str)
            qp.drawText(QPointF(cen.x() - id_w / 2, cen.y() - 5), id_str)

            # Distance text
            qp.setPen(_DIST_TEXT)
            dist_font = QFont("Segoe UI", 8)
            qp.setFont(dist_font)
            dist_str = f"{distance:.2f} m"
            dist_w = QFontMetricsF(dist_font).horizontalAdvance(dist_str)
            qp.drawText(QPointF(cen.x() - dist_w / 2, cen.y() + 13), dist_str)

        # ── Scale bar ─────────────────────────────────────────────────────────
        bar = 0.5 / scale
        bx  = W - MARGIN - bar
        by  = float(H - MARGIN // 2)
        qp.setPen(QPen(_SCALE_COL, 2))
        qp.drawLine(QPointF(bx, by), QPointF(bx + bar, by))
        qp.drawLine(QPointF(bx, by - 5), QPointF(bx, by + 5))
        qp.drawLine(QPointF(bx + bar, by - 5), QPointF(bx + bar, by + 5))
        qp.setPen(_SCALE_COL)
        qp.setFont(QFont("Segoe UI", 8))
        bl_str = "0.5 m"
        bl_w = QFontMetricsF(qp.font()).horizontalAdvance(bl_str)
        qp.drawText(QPointF(bx + bar / 2 - bl_w / 2, by - 8), bl_str)

        qp.end()
