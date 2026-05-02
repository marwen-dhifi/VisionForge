"""
ModuleTrackerProcessor — background QThread that handles:
  1. Display loop  (QThread.run)      — resize + overlay using cached detections
                                        → emit display_ready at camera FPS
  2. Detection loop (daemon thread)   — ArUco + solvePnP + geometry + map
                                        → emit map_ready / detections_ready

Separating the two loops means slow ArUco detection no longer throttles
the live camera feed.
"""

import queue
import threading
import time
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui  import QImage

from VisionForge.app.tasks.module_tracker.core import (
    MARKER_SIZE, ARUCO_DICT_ID,
    make_camera_matrix, marker_pose_to_lab,
    ModuleTrackerConfig,
)

_AXIS_LENGTH = MARKER_SIZE * 0.8


class ModuleTrackerProcessor(QThread):

    display_ready      = Signal(QImage)              # resized + overlaid camera frame
    map_data_ready     = Signal(object, float, float, float)  # modules_data, scale, angle, height
    detections_ready   = Signal(list)                # list of detection dicts
    frame_size_changed = Signal(int, int)            # fw, fh when resolution changes

    def __init__(self, parent=None):
        super().__init__(parent)

        # Separate queues so display never waits for detection
        self._display_queue: queue.Queue = queue.Queue(maxsize=1)
        self._detect_queue:  queue.Queue = queue.Queue(maxsize=1)

        self._running = False

        # Widget size (written by UI thread, read by display thread — GIL-safe)
        self._lw  = 640
        self._lh  = 480
        self._dpr = 1.0

        self._prev_fw = 0
        self._prev_fh = 0

        # Current config snapshot (replaced atomically)
        self._config: ModuleTrackerConfig = ModuleTrackerConfig()

        # Latest detections from detection thread → consumed by display thread
        self._last_dets: list = []
        self._dets_lock = threading.Lock()

        # Detection resolution mode (True = downscale to 640px, False = full res)
        self._downscale: bool = True

        # FPS counters (GIL-safe plain assignments)
        self._feed_fps:   float = 0.0
        self._detect_fps: float = 0.0
        self._feed_t:   float = 0.0
        self._feed_n:   int   = 0
        self._detect_t: float = 0.0
        self._detect_n: int   = 0

        # ArUco detector
        aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_ID)
        params     = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_CONTOUR
        self._aruco = cv2.aruco.ArucoDetector(aruco_dict, params)

        half = MARKER_SIZE / 2.0
        self._obj_pts = np.array([
            [-half,  half, 0],
            [ half,  half, 0],
            [ half, -half, 0],
            [-half, -half, 0],
        ], dtype=np.float32)

    # ── Public API ────────────────────────────────────────────────────────────

    def submit_frame(self, frame: np.ndarray, _meta: dict = None):
        """Drop stale frames, push latest to both queues."""
        for q in (self._display_queue, self._detect_queue):
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(frame)
            except queue.Full:
                pass

    def set_widget_size(self, lw: int, lh: int, dpr: float):
        self._lw, self._lh, self._dpr = lw, lh, dpr

    def update_config(self, cfg: ModuleTrackerConfig):
        """Atomically replace the config snapshot."""
        self._config = cfg

    def set_downscale(self, enabled: bool):
        self._downscale = enabled

    def stop(self):
        self._running = False
        self.wait(3000)

    # ── Display loop (QThread.run) ────────────────────────────────────────────

    def run(self):
        self._running = True

        # Start slow detection as a daemon thread
        det_thread = threading.Thread(target=self._detection_loop, daemon=True)
        det_thread.start()

        while self._running:
            try:
                frame = self._display_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                cfg = self._config
                fh, fw = frame.shape[:2]

                if fw != self._prev_fw or fh != self._prev_fh:
                    self._prev_fw, self._prev_fh = fw, fh
                    self.frame_size_changed.emit(fw, fh)

                lw, lh, dpr = self._lw, self._lh, self._dpr
                pw = max(1, int(lw * dpr))
                ph = max(1, int(lh * dpr))
                scale = min(pw / fw, ph / fh)
                nw = max(1, int(fw * scale))
                nh = max(1, int(fh * scale))

                display = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
                display = cv2.cvtColor(display, cv2.COLOR_RGB2BGR)

                # ── Feed FPS ──────────────────────────────────────────────
                now = time.monotonic()
                self._feed_n += 1
                if self._feed_t == 0.0:
                    self._feed_t = now
                elif now - self._feed_t >= 1.0:
                    self._feed_fps = self._feed_n / (now - self._feed_t)
                    self._feed_n   = 0
                    self._feed_t   = now

                with self._dets_lock:
                    dets_snap = list(self._last_dets)

                if dets_snap:
                    self._draw_overlays(display, dets_snap, scale, cfg)

                self._draw_fps(display)

                display = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
                qimg = QImage(
                    display.data, nw, nh, nw * 3,
                    QImage.Format.Format_RGB888,
                ).copy()
                qimg.setDevicePixelRatio(dpr)
                self.display_ready.emit(qimg)

            except Exception as e:
                print(f"[ModuleTracker] Display error: {e}", flush=True)

        det_thread.join(timeout=2.0)

    # ── Detection loop (daemon thread) ────────────────────────────────────────

    def _detection_loop(self):
        while self._running:
            try:
                frame = self._detect_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                cfg = self._config
                fh, fw = frame.shape[:2]

                dets = self._detect(frame, fw, fh, cfg)

                # ── Detect FPS ────────────────────────────────────────────
                now = time.monotonic()
                self._detect_n += 1
                if self._detect_t == 0.0:
                    self._detect_t = now
                elif now - self._detect_t >= 1.0:
                    self._detect_fps = self._detect_n / (now - self._detect_t)
                    self._detect_n   = 0
                    self._detect_t   = now

                with self._dets_lock:
                    self._last_dets = dets

                self.detections_ready.emit(dets)

                if dets:
                    modules_data = {
                        d["id"]: d["lab"]
                        for d in dets if d.get("lab") is not None
                    }
                    if modules_data:
                        self.map_data_ready.emit(
                            modules_data,
                            cfg.map_scale_m,
                            cfg.camera_angle_deg,
                            cfg.camera_height_m + cfg.camera_height_offset,
                        )

            except Exception as e:
                print(f"[ModuleTracker] Detection error: {e}", flush=True)

    # ── Detection ─────────────────────────────────────────────────────────────

    def _detect(self, frame: np.ndarray, fw: int, fh: int,
                cfg: ModuleTrackerConfig) -> list:
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        if self._downscale and fw > 640:
            # Downscale for faster detection, then scale corners back up
            DETECT_W   = 640
            scale_d    = DETECT_W / fw
            gray_small = cv2.resize(gray, (DETECT_W, int(fh * scale_d)),
                                    interpolation=cv2.INTER_LINEAR)
            corners, ids, _ = self._aruco.detectMarkers(gray_small)
            if ids is not None:
                corners = [c / scale_d for c in corners]
        else:
            corners, ids, _ = self._aruco.detectMarkers(gray)

        detections = []

        if ids is None:
            return detections

        cam_mat     = make_camera_matrix(fw, fh)
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        for i, marker_id in enumerate(ids.flatten()):
            img_pts = corners[i].reshape(4, 2).astype(np.float32)

            success, rvec, tvec = cv2.solvePnP(
                self._obj_pts, img_pts,
                cam_mat, dist_coeffs,
            )
            if not success:
                continue

            mid = int(marker_id)
            if mid not in cfg.modules:
                continue
            mod_cfg = cfg.get_module_cfg(mid)
            lab = marker_pose_to_lab(
                tvec.flatten(), rvec.flatten(),
                mod_cfg, cfg.camera_angle_deg,
            )

            detections.append({
                "id":      mid,
                "corners": img_pts.reshape(4, 2),
                "rvec":    rvec,
                "tvec":    tvec,
                "cam_mat": cam_mat,
                "lab":     lab,
            })

        return detections

    # ── Overlay drawing ───────────────────────────────────────────────────────

    def _draw_overlays(self, display: np.ndarray, dets: list,
                       scale: float, cfg: ModuleTrackerConfig):
        for det in dets:
            corners = (det["corners"] * scale).reshape(4, 2).astype(int)
            mid = det["id"]

            # Marker outline
            for j in range(4):
                cv2.line(display, tuple(corners[j]),
                         tuple(corners[(j + 1) % 4]), (50, 220, 180), 2)

            # ID / name label
            cx = int(np.mean(corners[:, 0]))
            ty = max(int(np.min(corners[:, 1])) - 12, 15)
            name  = cfg.modules[mid].name if mid in cfg.modules else f"ID:{mid}"
            ts    = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)[0]
            tx    = cx - ts[0] // 2
            cv2.rectangle(display,
                          (tx - 4, ty - ts[1] - 4), (tx + ts[0] + 4, ty + 4),
                          (0, 0, 0), -1)
            cv2.putText(display, name, (tx, ty),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 220, 180), 2)

            # Distance
            lab = det.get("lab")
            if lab:
                dist_str = f"{lab['distance']:.2f}m"
                cv2.putText(display, dist_str, (cx - 20, ty + 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

    def _draw_fps(self, display: np.ndarray):
        """Overlay feed FPS and ArUco detection FPS in the top-left corner."""
        feed_str   = f"Feed:   {self._feed_fps:5.1f} fps"
        detect_str = f"ArUco:  {self._detect_fps:5.1f} fps"
        font       = cv2.FONT_HERSHEY_SIMPLEX
        scale      = 0.50
        thickness  = 1
        pad        = 6

        # Background pill
        (tw, th), _ = cv2.getTextSize(feed_str, font, scale, thickness)
        box_w = tw + pad * 2
        box_h = (th + pad) * 2 + pad
        overlay = display.copy()
        cv2.rectangle(overlay, (8, 8), (8 + box_w, 8 + box_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, display, 0.45, 0, display)

        # Feed FPS — white
        cv2.putText(display, feed_str,
                    (8 + pad, 8 + pad + th),
                    font, scale, (220, 220, 220), thickness, cv2.LINE_AA)
        # ArUco FPS — cyan
        cv2.putText(display, detect_str,
                    (8 + pad, 8 + pad * 2 + th * 2),
                    font, scale, (0, 207, 255), thickness, cv2.LINE_AA)
