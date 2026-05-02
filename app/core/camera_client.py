"""
CameraClient — QThread that subscribes to the Baumer VAX-50C ZMQ server.

Signals:
  frame_received(QImage)              — debayered, flipped, ready to display
  raw_frame_received(np.ndarray, dict)— raw RGB numpy + meta, for CV pipeline
  connection_changed(bool)
  fps_updated(float)
  resolution_updated(int, int)        — width, height on first frame / change
"""

import json
import time
import threading

import cv2
import numpy as np
import zmq

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui  import QImage

STREAM_PORT  = 5555
CONTROL_PORT = 5556


class CameraClient(QThread):
    frame_received      = Signal(QImage)
    raw_frame_received  = Signal(object, dict)   # np.ndarray, meta dict
    connection_changed  = Signal(bool)
    fps_updated         = Signal(float)
    resolution_updated  = Signal(int, int)

    def __init__(self, ip: str, parent=None):
        super().__init__(parent)
        self._ip       = ip
        self._running  = False
        self._context  = zmq.Context()
        self._req      = None          # persistent control socket
        self._req_lock = threading.Lock()
        self._last_res = (0, 0)        # track resolution changes

    # ── Control socket (persistent) ─────────────────────────────────────────

    def _ensure_req(self):
        """Create the REQ socket if not already open."""
        if self._req is None:
            self._req = self._context.socket(zmq.REQ)
            self._req.setsockopt(zmq.RCVTIMEO, 5000)
            self._req.setsockopt(zmq.SNDTIMEO, 5000)
            self._req.setsockopt(zmq.LINGER,   0)
            self._req.connect(f"tcp://{self._ip}:{CONTROL_PORT}")

    def send_params(self, params: dict) -> dict:
        """Send a parameter update to the camera server. Thread-safe."""
        with self._req_lock:
            try:
                self._ensure_req()
                print(f"[CameraClient] Sending: {params}")
                self._req.send_json(params)
                response = self._req.recv_json()
                print(f"[CameraClient] Response: {response}")
                return response
            except Exception as e:
                print(f"[CameraClient] Control error: {e}")
                # Reset socket so next call rebuilds it
                try:
                    self._req.close()
                except Exception:
                    pass
                self._req = None
                return {"status": "error", "message": str(e)}

    def stop(self):
        self._running = False

    # ── Stream thread ────────────────────────────────────────────────────────

    def run(self):
        self._running = True

        sub = self._context.socket(zmq.SUB)
        sub.setsockopt(zmq.RCVHWM,  2)       # tiny buffer — always get latest
        sub.setsockopt(zmq.RCVTIMEO, 2000)
        sub.setsockopt(zmq.LINGER,  0)
        sub.connect(f"tcp://{self._ip}:{STREAM_PORT}")
        sub.subscribe(b"frame")

        # Do NOT emit connected yet — wait for the first real frame.
        # This keeps the "Reconnecting…" indicator visible until data actually flows.
        connected_emitted  = False
        frame_count        = 0
        fps_timer          = time.monotonic()
        consecutive_timeouts = 0
        MAX_TIMEOUTS       = 3   # 3 × 2 s RCVTIMEO = 6 s without a frame → disconnected

        while self._running:
            try:
                topic, meta_bytes, raw_bytes = sub.recv_multipart()
                consecutive_timeouts = 0   # good frame — reset counter
                if not connected_emitted:
                    self.connection_changed.emit(True)
                    connected_emitted = True
            except zmq.Again:
                consecutive_timeouts += 1
                if consecutive_timeouts >= MAX_TIMEOUTS:
                    print("[CameraClient] No frames for ~6 s — treating as disconnected")
                    break
                continue
            except Exception as e:
                print(f"[CameraClient] Recv error: {e}")
                break

            try:
                meta = json.loads(meta_bytes.decode())
                w    = meta["width"]
                h    = meta["height"]

                # Reconstruct raw BayerRG8 → debayer
                # NOTE: BayerRG8 sensor maps to COLOR_BayerBG2BGR in OpenCV
                bayer = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(h, w)
                bgr   = cv2.cvtColor(bayer, cv2.COLOR_BayerBG2BGR)

                # 180° flip (camera is mounted upside down)
                bgr   = cv2.flip(bgr, -1)

                # BGR → RGB for Qt and CV pipeline
                rgb   = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

                # Notify if resolution changed
                if (w, h) != self._last_res:
                    self._last_res = (w, h)
                    self.resolution_updated.emit(w, h)

                # Emit raw numpy for CV pipeline
                self.raw_frame_received.emit(rgb, meta)

                # FPS counter
                frame_count += 1
                elapsed = time.monotonic() - fps_timer
                if elapsed >= 1.0:
                    self.fps_updated.emit(frame_count / elapsed)
                    frame_count = 0
                    fps_timer   = time.monotonic()

            except Exception as e:
                print(f"[CameraClient] Frame processing error: {e}")
                continue

        sub.close()
        self.connection_changed.emit(False)
        print("[CameraClient] Stopped.")

    def cleanup(self):
        self.stop()
        self.wait(3000)
        with self._req_lock:
            if self._req:
                self._req.close()
                self._req = None
        self._context.term()