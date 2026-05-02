"""
SevenSegProcessor — background QThread for all heavy processing:
  1. YOLO-OBB detection
  2. ByteTrack multi-object tracking
  3. OBB crop extraction
  4. PARSeq OCR in a dedicated thread at configurable rate
  5. Emits FramePacket to the UI thread

OCR runs in a separate thread so YOLO never stalls waiting for PARSeq.
The OCR cache is updated asynchronously; the main loop always emits the
most recent cached result for each tracked ID.
"""

import queue
import threading
import time
import traceback
from typing import Dict, Tuple

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from VisionForge.app.tasks.seven_segment.core import (
    FramePacket,
    batch_read_displays,
    crop_obb_local,
    load_yolo,
    load_parseq,
)


class SevenSegProcessor(QThread):

    frame_ready = Signal(object)   # emits FramePacket

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = False

        # UI state — updated from UI thread, read in worker thread
        self._lock               = threading.Lock()
        self._flip_map:          Dict[int, bool] = {}
        self._measurement_flip:  Dict[str, bool] = {}
        self._tid_to_measurement: Dict[int, str] = {}
        self._ocr_rate: int = 2

    # ── Public API (UI thread) ────────────────────────────────────────────────

    def submit_frame(self, frame: np.ndarray, _meta=None):
        """Drop any stale queued frame and enqueue the latest one."""
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass

    def update_state(self, flip_map: dict, measurement_flip: dict,
                     tid_to_measurement: dict, ocr_rate: int):
        with self._lock:
            self._flip_map           = dict(flip_map)
            self._measurement_flip   = dict(measurement_flip)
            self._tid_to_measurement = dict(tid_to_measurement)
            self._ocr_rate           = int(ocr_rate)

    def stop(self):
        self._running = False
        self.wait(5000)

    # ── Worker loop ───────────────────────────────────────────────────────────

    def run(self):
        try:
            self._run()
        except Exception:
            traceback.print_exc()

    def _run(self):
        import supervision as sv

        model = load_yolo()
        tracker = sv.ByteTrack()
        parseq, img_transform, device = load_parseq()

        # ── OCR cache shared between main loop and OCR thread ─────────────────
        ocr_cache:      Dict[int, Tuple[str, float]] = {}
        ocr_cache_lock  = threading.Lock()
        ocr_fired       = [False]   # set by OCR thread, consumed by main loop

        # ── OCR input queue (latest crops only) ───────────────────────────────
        # Payload: (crops_list, flip_flags, tid_order)
        ocr_input: queue.Queue = queue.Queue(maxsize=1)

        def _ocr_worker():
            last_ocr_time = 0.0
            while self._running:
                with self._lock:
                    ocr_rate = self._ocr_rate
                ocr_interval = 1.0 / max(ocr_rate, 1)

                try:
                    payload = ocr_input.get(timeout=0.05)
                except queue.Empty:
                    continue

                now = time.perf_counter()
                if (now - last_ocr_time) < ocr_interval:
                    continue   # rate-limit: discard this batch

                crops_list, flip_flags, tid_order = payload
                if not crops_list:
                    continue

                ocr_out = batch_read_displays(
                    crops_list, parseq, img_transform, device, flip_flags
                )
                with ocr_cache_lock:
                    for j, tid_key in enumerate(tid_order):
                        if j < len(ocr_out):
                            ocr_cache[tid_key] = ocr_out[j]
                    ocr_fired[0] = True
                last_ocr_time = now

        ocr_thread = threading.Thread(target=_ocr_worker, daemon=True)

        self._running = True
        ocr_thread.start()

        prev_time = time.perf_counter()

        while self._running:
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Camera sends RGB — convert to BGR for YOLO and all cv2 operations
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # ── YOLO-OBB detection + ByteTrack ────────────────────────────────
            infer_device = 0 if device == "cuda" else "cpu"
            results    = model.predict(frame_bgr, conf=0.5, device=infer_device,
                                       verbose=False, imgsz=640)
            detections = sv.Detections.from_ultralytics(results[0])
            detections = tracker.update_with_detections(detections=detections)

            obb_points:  np.ndarray = np.empty((0, 4, 2))
            obb_xywhr:   np.ndarray = np.empty((0, 5))
            tids:        np.ndarray = np.array([], dtype=int)
            crops:       Dict[int, np.ndarray]          = {}
            ocr_results: Dict[int, Tuple[str, float]]   = {}
            ran_ocr      = False

            # ── Read current UI state (thread-safe snapshot) ──────────────────
            with self._lock:
                flip_map    = dict(self._flip_map)
                meas_flip   = dict(self._measurement_flip)
                tid_to_meas = dict(self._tid_to_measurement)

            if results[0].obb is not None and len(results[0].obb) > 0:
                obb_points = results[0].obb.xyxyxyxy.cpu().numpy()
                obb_xywhr  = results[0].obb.xywhr.cpu().numpy()
                raw_tids   = detections.tracker_id
                tids       = raw_tids if raw_tids is not None else np.array([], dtype=int)

                crops_list: list = []
                flip_flags: list = []
                tid_order:  list = []

                for i in range(len(obb_points)):
                    cx, cy, bw, bh, angle_rad = obb_xywhr[i]
                    tid  = int(tids[i]) if i < len(tids) else -1
                    crop = crop_obb_local(frame_bgr, cx, cy, bw, bh, angle_rad)
                    if crop is None or crop.size == 0:
                        continue
                    crops[tid] = crop
                    crops_list.append(crop)
                    tid_order.append(tid)

                    should_flip = flip_map.get(tid, False)
                    if not should_flip:
                        mname = tid_to_meas.get(tid)
                        if mname:
                            should_flip = meas_flip.get(mname, False)
                    flip_flags.append(should_flip)

                # Push latest crops to OCR thread (drop stale batch if busy)
                if crops_list:
                    try:
                        ocr_input.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        ocr_input.put_nowait((crops_list, flip_flags, tid_order))
                    except queue.Full:
                        pass

                # Attach latest cached OCR results, consume ran_ocr flag
                with ocr_cache_lock:
                    ran_ocr = ocr_fired[0]
                    ocr_fired[0] = False
                    for tid_key in crops:
                        if tid_key in ocr_cache:
                            ocr_results[tid_key] = ocr_cache[tid_key]

            now       = time.perf_counter()
            elapsed   = now - prev_time
            prev_time = now

            pkt = FramePacket(
                frame        = frame_bgr,
                obb_points   = obb_points,
                obb_xywhr    = obb_xywhr,
                tracker_ids  = tids,
                crops        = crops,
                ocr_results  = ocr_results,
                fps          = 1.0 / max(elapsed, 1e-6),
                ran_ocr      = ran_ocr,
            )
            self.frame_ready.emit(pkt)
