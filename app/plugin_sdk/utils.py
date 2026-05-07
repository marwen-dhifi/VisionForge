"""
Plugin utility helpers.
"""
import os
import cv2
import numpy as np


def save_frame(frame_rgb: np.ndarray, filepath: str) -> bool:
    """
    Write an HxWx3 uint8 RGB numpy array to <filepath>.
    Format is inferred from the file extension (PNG, JPEG, etc.).
    Creates parent directories if they do not exist.
    Returns True on success, False if frame is empty or write fails.
    """
    if frame_rgb is None or frame_rgb.size == 0:
        return False
    parent = os.path.dirname(os.path.abspath(filepath))
    if parent:
        os.makedirs(parent, exist_ok=True)
    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    return bool(cv2.imwrite(filepath, bgr))


def resolve_path(plugin_file: str, relative_path: str) -> str:
    """
    Resolve <relative_path> against the directory containing <plugin_file>.

    Typical usage at module level in a plugin file:
        WEIGHTS = resolve_path(__file__, "weights/best.pt")
    """
    base = os.path.dirname(os.path.abspath(plugin_file))
    return os.path.abspath(os.path.join(base, relative_path))
