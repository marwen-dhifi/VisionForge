"""
ValveProcessor — background QThread for ArUco/AprilTag detection and display.
Runs a single loop: get frame → detect → resize + draw overlays → emit QImage.
"""

import queue
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui  import QImage

from VisionForge.app.tasks.valve_orientation.core import (
    TAG_SIZE_M, CAMERA_MATRIX, DIST_COEFFS, AXIS_LENGTH,
)


class ValveProcessor(QThread):
    display_ready      = Signal(QImage)   # emitted every processed frame
    detections_ready   = Signal(list)     # emitted with detection results
    frame_size_changed = Signal(int, int) # emitted when camera resolution changes

    def __init__(self, parent=None):
        super().__init__(parent)

        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = False

        # Widget size — set from UI thread
        self._lw  = 640
        self._lh  = 480
        self._dpr = 1.0

        self._prev_fw = 0
        self._prev_fh = 0

        # Overlay state — set from UI thread
        self._detections  = []
        self._mode        = "overview"
        self._selected_id = None
        self._config_mgr  = None
        self._tracker     = None

        # ── ArUco detector ────────────────────────────────────────────────────
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_25h9)
        params = cv2.aruco.DetectorParameters()
        self._aruco = cv2.aruco.ArucoDetector(aruco_dict, params)

        half = TAG_SIZE_M / 2.0
        self._obj_pts = np.array([
            [-half,  half, 0],
            [ half,  half, 0],
            [ half, -half, 0],
            [-half, -half, 0],
        ], dtype=np.float64)

    # ── Public API (called from UI thread) ───────────────────────────────────

    def submit_frame(self, frame: np.ndarray, _meta: dict = None):
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass

    def set_widget_size(self, lw: int, lh: int, dpr: float):
        self._lw, self._lh, self._dpr = lw, lh, dpr

    def update_overlay_state(self, detections, mode, selected_id, config_mgr, tracker):
        self._detections  = detections
        self._mode        = mode
        self._selected_id = selected_id
        self._config_mgr  = config_mgr
        self._tracker     = tracker

    def stop(self):
        self._running = False
        self.wait(3000)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        self._running = True

        while self._running:
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                fh, fw = frame.shape[:2]

                if fw != self._prev_fw or fh != self._prev_fh:
                    self._prev_fw, self._prev_fh = fw, fh
                    self.frame_size_changed.emit(fw, fh)

                # ── Detection ─────────────────────────────────────────────────
                detections = self._detect(frame, fw, fh)
                self.detections_ready.emit(detections)

                # ── Display ───────────────────────────────────────────────────
                lw, lh, dpr = self._lw, self._lh, self._dpr
                pw = max(1, int(lw * dpr))
                ph = max(1, int(lh * dpr))
                scale = min(pw / fw, ph / fh)
                nw = max(1, int(fw * scale))
                nh = max(1, int(fh * scale))

                display = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
                display = cv2.cvtColor(display, cv2.COLOR_RGB2BGR)

                if self._config_mgr is not None and detections:
                    self._draw_overlays(display, detections, scale)

                display = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
                qimg = QImage(
                    display.data, nw, nh, nw * 3,
                    QImage.Format.Format_RGB888,
                ).copy()
                qimg.setDevicePixelRatio(dpr)
                self.display_ready.emit(qimg)

            except Exception as e:
                print(f"[ValveProcessor] Error: {e}", flush=True)

    # ── Detection ─────────────────────────────────────────────────────────────

    def _detect(self, frame: np.ndarray, fw: int, fh: int) -> list:
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        corners, ids, _ = self._aruco.detectMarkers(gray)
        detections = []

        if ids is None:
            return detections

        for i, marker_id in enumerate(ids.flatten()):
            img_points = corners[i].reshape(4, 2).astype(np.float64)

            success, rvec, tvec = cv2.solvePnP(
                self._obj_pts, img_points,
                CAMERA_MATRIX, DIST_COEFFS,
                flags=cv2.SOLVEPNP_IPPE_SQUARE,
            )
            if success:
                detections.append({
                    "id":      int(marker_id),
                    "corners": img_points.reshape(4, 2),
                    "rvec":    rvec,
                    "tvec":    tvec,
                })
        return detections

    # ── Overlay drawing ───────────────────────────────────────────────────────

    def _draw_overlays(self, display: np.ndarray, detections: list, scale: float):
        sm = CAMERA_MATRIX.copy()
        sm[0, 0] *= scale;  sm[1, 1] *= scale
        sm[0, 2] *= scale;  sm[1, 2] *= scale

        mode        = self._mode
        selected_id = self._selected_id
        config_mgr  = self._config_mgr
        tracker     = self._tracker

        circles = []

        for det in detections:
            mid        = det["id"]
            corners    = (det["corners"] * scale).reshape(4, 2).astype(int)
            rvec, tvec = det["rvec"], det["tvec"]

            if mode == "overview":
                color, label, thickness = (80, 80, 80), f"ID:{mid}", 1

            elif mode == "calibration":
                status      = config_mgr.config_status(mid)
                is_selected = (mid == selected_id)
                if is_selected:
                    color, label, thickness = (255, 207, 0), f"ID:{mid} [SEL]", 3
                elif status == "full":
                    color, label, thickness = (118, 230, 0), f"ID:{mid} \u2713", 2
                elif status in ("partial_open", "partial_closed"):
                    color, label, thickness = (0, 179, 255), f"ID:{mid} ~", 2
                else:
                    color, label, thickness = (102, 68, 255), f"ID:{mid}", 2

            else:  # "tracking"
                is_conf = config_mgr.is_fully_configured(mid)
                if is_conf:
                    state = tracker.get_state(mid)
                    color = (80, 220, 80) if state == "open" else \
                            (70, 70, 245) if state == "closed" else (50, 180, 220)
                    label = state.upper() if state in ("open", "closed") else "?"
                else:
                    color, label = (50, 180, 220), "?"
                thickness = 2

            for j in range(4):
                cv2.line(display, tuple(corners[j]),
                         tuple(corners[(j + 1) % 4]), color, thickness)

            cv2.drawFrameAxes(display, sm, DIST_COEFFS, rvec, tvec, AXIS_LENGTH)

            cx = int(np.mean(corners[:, 0]))
            ty = max(int(np.min(corners[:, 1])) - 12, 15)
            ts = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)[0]
            tx = cx - ts[0] // 2
            cv2.rectangle(display,
                          (tx - 4, ty - ts[1] - 4), (tx + ts[0] + 4, ty + 4),
                          (0, 0, 0), -1)
            cv2.putText(display, label, (tx, ty),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            if mode == "tracking" and config_mgr.is_fully_configured(mid):
                state = tracker.get_state(mid)
                if state in ("open", "closed"):
                    mcx    = int(np.mean(corners[:, 0]))
                    mcy    = int(np.mean(corners[:, 1]))
                    radius = max(1, int(np.linalg.norm(corners[0] - corners[2]) / 4))
                    fill   = (80, 220, 80) if state == "open" else (70, 70, 245)
                    circles.append((mcx, mcy, radius, fill))

        if circles:
            ovl = display.copy()
            for mcx, mcy, radius, fill in circles:
                cv2.circle(ovl, (mcx, mcy), radius, fill, -1)
            cv2.addWeighted(ovl, 0.35, display, 0.65, 0, display)
