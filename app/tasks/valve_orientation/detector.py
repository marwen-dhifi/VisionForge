"""
ValveDetector — background QThread for AprilTag detection.

Key design: emits only a lightweight list of detections (no frame).
Display happens independently at full camera FPS in the panel, using
the last known detection results as an overlay.

Queue is size 1 — always processes the freshest frame, older ones are dropped.
"""

import queue
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from VisionForge.app.tasks.valve_orientation.core import (
    TAG_SIZE_M, CAMERA_MATRIX, DIST_COEFFS,
)


class ValveDetector(QThread):
    """
    Signals
    -------
    detections_ready(list[dict])
        Emitted after each frame is processed.
        Each dict: { id, corners, rvec, tvec }
        No frame is carried — caller draws overlays at its own rate.
    """

    detections_ready = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = False

        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_25h9)
        params = cv2.aruco.DetectorParameters()

        params.cornerRefinementMethod        = cv2.aruco.CORNER_REFINE_SUBPIX
        params.cornerRefinementWinSize       = 5
        params.cornerRefinementMaxIterations = 30
        params.cornerRefinementMinAccuracy   = 0.01

        params.adaptiveThreshWinSizeMin  = 3
        params.adaptiveThreshWinSizeMax  = 23
        params.adaptiveThreshWinSizeStep = 10
        params.adaptiveThreshConstant    = 7

        params.minMarkerPerimeterRate = 0.02

        self._detector = cv2.aruco.ArucoDetector(aruco_dict, params)

        half = TAG_SIZE_M / 2.0
        self._obj_points = np.array([
            [-half,  half, 0],
            [ half,  half, 0],
            [ half, -half, 0],
            [-half, -half, 0],
        ], dtype=np.float64)

    # ── Public API ────────────────────────────────────────────────────────────

    def submit_frame(self, frame: np.ndarray, _meta: dict = None):
        """Drop any queued frame and replace with the latest one."""
        try:
            self._queue.get_nowait()          # evict stale frame
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(frame.copy())
        except queue.Full:
            pass

    def stop(self):
        self._running = False
        self.wait(2000)

    # ── QThread run ───────────────────────────────────────────────────────────

    def run(self):
        self._running = True
        while self._running:
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Downscale to 50 % for detection — 4× fewer pixels → ~4× faster.
            # Corners are scaled back to original coordinates for solvePnP.
            fh, fw = frame.shape[:2]
            small  = cv2.resize(frame, (fw // 2, fh // 2),
                                interpolation=cv2.INTER_NEAREST)

            corners, ids, _ = self._detector.detectMarkers(small)
            detections = []

            if ids is not None:
                for i, marker_id in enumerate(ids.flatten()):
                    # Scale corners back to full-res space so CAMERA_MATRIX applies
                    img_points = corners[i].reshape(4, 2).astype(np.float64) * 2.0

                    success, rvec, tvec = cv2.solvePnP(
                        self._obj_points, img_points,
                        CAMERA_MATRIX, DIST_COEFFS,
                        flags=cv2.SOLVEPNP_IPPE_SQUARE,
                    )

                    if success:
                        rvec, tvec = cv2.solvePnPRefineLM(
                            self._obj_points, img_points,
                            CAMERA_MATRIX, DIST_COEFFS,
                            rvec, tvec,
                        )
                        detections.append({
                            "id":      int(marker_id),
                            "corners": img_points.reshape(4, 2),  # full-res coords
                            "rvec":    rvec,
                            "tvec":    tvec,
                        })

            self.detections_ready.emit(detections)
