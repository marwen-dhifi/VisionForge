"""
MediaManager — image capture and video recording at full resolution.

Video recording runs in a dedicated background thread with a bounded queue.
Frames are dropped (not buffered) if the encoder falls behind — the camera
thread never blocks.
"""

import os
import time
import queue
import threading

import cv2
import numpy as np

from PySide6.QtCore import QObject, Signal

MEDIA_ROOT  = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "media"
)
IMAGES_ROOT = os.path.join(MEDIA_ROOT, "images")
VIDEOS_ROOT = os.path.join(MEDIA_ROOT, "videos")


def _ensure_roots():
    os.makedirs(IMAGES_ROOT, exist_ok=True)
    os.makedirs(VIDEOS_ROOT, exist_ok=True)


class _VideoWriter(threading.Thread):
    """
    Dedicated thread that owns the cv2.VideoWriter.
    Accepts frames via a bounded queue — drops if full so callers never block.
    Sends None as sentinel to stop.
    """
    _QUEUE_MAX = 4   # max buffered frames — beyond this, drop

    def __init__(self, path: str, fps: float, width: int, height: int):
        super().__init__(daemon=True)
        self.path    = path
        self._queue  = queue.Queue(maxsize=self._QUEUE_MAX)
        self._writer = cv2.VideoWriter(
            path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height)
        )
        self._ok = self._writer.isOpened()

    def is_ok(self) -> bool:
        return self._ok

    def push(self, bgr: np.ndarray):
        """Non-blocking push. Drops frame silently if queue is full."""
        try:
            self._queue.put_nowait(bgr)
        except queue.Full:
            pass   # drop frame — better than blocking the camera thread

    def stop(self):
        self._queue.put(None)   # sentinel
        self.join(timeout=10)

    def run(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                self._writer.write(item)
            except Exception as e:
                print(f"[VideoWriter] write error: {e}")
        self._writer.release()


class MediaManager(QObject):
    image_saved          = Signal(str)
    recording_started    = Signal(str)
    recording_stopped    = Signal(str)
    error_occurred       = Signal(str)
    directories_changed  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        _ensure_roots()
        self._vw          = None      # _VideoWriter instance
        self._rec_path    = None
        self._lock        = threading.Lock()
        self.is_recording = False

    # ── Image capture ─────────────────────────────────────────────────────────

    def capture_image(self, frame: np.ndarray, subdir: str = "") -> str | None:
        """Save full-res RGB numpy frame as PNG. No resizing."""
        try:
            dest = os.path.join(IMAGES_ROOT, subdir) if subdir else IMAGES_ROOT
            os.makedirs(dest, exist_ok=True)
            ts   = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time()*1000)%1000:03d}"
            path = os.path.join(dest, f"capture_{ts}.png")
            bgr  = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            cv2.imwrite(path, bgr)
            self.image_saved.emit(path)
            return path
        except Exception as e:
            self.error_occurred.emit(f"Capture failed: {e}")
            return None

    # ── Video recording ───────────────────────────────────────────────────────

    def start_recording(self, frame: np.ndarray, subdir: str = "",
                        fps: float = 10.0):
        with self._lock:
            if self.is_recording:
                return
            try:
                dest = os.path.join(VIDEOS_ROOT, subdir) if subdir else VIDEOS_ROOT
                os.makedirs(dest, exist_ok=True)
                ts   = time.strftime("%Y%m%d_%H%M%S")
                path = os.path.join(dest, f"video_{ts}.mp4")
                h, w = frame.shape[:2]

                vw = _VideoWriter(path, fps, w, h)
                if not vw.is_ok():
                    self.error_occurred.emit(
                        f"VideoWriter failed to open: {path}"
                    )
                    return

                vw.start()
                self._vw          = vw
                self._rec_path    = path
                self.is_recording = True
                self.recording_started.emit(path)
            except Exception as e:
                self.error_occurred.emit(f"Recording start failed: {e}")

    def write_frame(self, frame: np.ndarray):
        """
        Non-blocking. Converts RGB→BGR then pushes to the writer queue.
        Called from the camera signal — must never block.
        """
        with self._lock:
            if not self.is_recording or self._vw is None:
                return
        try:
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            self._vw.push(bgr)
        except Exception:
            pass

    def stop_recording(self):
        with self._lock:
            if not self.is_recording:
                return
            vw             = self._vw
            path           = self._rec_path
            self._vw       = None
            self._rec_path = None
            self.is_recording = False

        # Stop the writer thread outside the lock
        if vw:
            vw.stop()
        self.recording_stopped.emit(path or "")

    # ── Directory operations ──────────────────────────────────────────────────

    def list_dirs(self, root: str) -> list:
        try:
            return sorted([
                d for d in os.listdir(root)
                if os.path.isdir(os.path.join(root, d))
                and not d.startswith(".")
            ])
        except Exception:
            return []

    def create_dir(self, root: str, name: str) -> bool:
        name = name.strip().replace("/", "_").replace("\\", "_")
        if not name:
            return False
        try:
            os.makedirs(os.path.join(root, name), exist_ok=True)
            self.directories_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Create dir failed: {e}")
            return False

    def rename_dir(self, root: str, old_name: str, new_name: str) -> bool:
        new_name = new_name.strip().replace("/", "_").replace("\\", "_")
        if not new_name or old_name == new_name:
            return False
        try:
            os.rename(
                os.path.join(root, old_name),
                os.path.join(root, new_name)
            )
            self.directories_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Rename failed: {e}")
            return False

    def delete_dir(self, root: str, name: str) -> bool:
        import shutil
        try:
            shutil.rmtree(os.path.join(root, name))
            self.directories_changed.emit()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Delete failed: {e}")
            return False