"""
Core logic for valve orientation detection.
Contains shared constants, math utilities, config management, and state tracking.
"""

import json
import os
import cv2
import numpy as np
from collections import deque, defaultdict

# ── Constants ─────────────────────────────────────────────────────────────────

TAG_SIZE_M    = 0.015   # 15 mm black-border-to-black-border
AXIS_LENGTH   = 0.008
SAMPLE_WINDOW = 30      # last N samples used for state voting

# Placeholder intrinsics — replace with calibrated values for your camera
CAMERA_MATRIX = np.array([
    [800, 0, 320],
    [0, 800, 240],
    [0, 0,   1],
], dtype=np.float64)

DIST_COEFFS = np.zeros((5, 1), dtype=np.float64)


# ── Math utilities ─────────────────────────────────────────────────────────────

def angular_distance(rvec1, rvec2) -> float:
    """Geodesic angular distance (degrees) between two Rodrigues rotation vectors."""
    R1, _ = cv2.Rodrigues(np.array(rvec1, dtype=np.float64))
    R2, _ = cv2.Rodrigues(np.array(rvec2, dtype=np.float64))
    R_diff = R2 @ R1.T
    cos_angle = np.clip((np.trace(R_diff) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_angle)))


# ── Valve config manager ───────────────────────────────────────────────────────

class ValveConfigManager:
    """Loads and saves per-valve calibration data (open/closed rotation vectors)."""

    def __init__(self):
        self.valves: dict = {}   # str(marker_id) -> {name, open_rvec, closed_rvec}

    def load(self, filepath: str):
        if not os.path.exists(filepath):
            return
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            self.valves = data.get("valves", {})
        except (json.JSONDecodeError, IOError):
            self.valves = {}

    def save(self, filepath: str):
        with open(filepath, "w") as f:
            json.dump({"valves": self.valves}, f, indent=2)

    def set_open(self, marker_id: int, rvec: np.ndarray):
        key = str(marker_id)
        if key not in self.valves:
            self.valves[key] = {"name": f"Valve {marker_id}", "open_rvec": None, "closed_rvec": None}
        self.valves[key]["open_rvec"] = rvec.flatten().tolist()

    def set_closed(self, marker_id: int, rvec: np.ndarray):
        key = str(marker_id)
        if key not in self.valves:
            self.valves[key] = {"name": f"Valve {marker_id}", "open_rvec": None, "closed_rvec": None}
        self.valves[key]["closed_rvec"] = rvec.flatten().tolist()

    def clear(self, marker_id: int):
        self.valves.pop(str(marker_id), None)

    def rename(self, marker_id: int, name: str):
        key = str(marker_id)
        if key in self.valves:
            self.valves[key]["name"] = name

    def get_valve(self, marker_id: int) -> dict | None:
        return self.valves.get(str(marker_id))

    def is_fully_configured(self, marker_id: int) -> bool:
        v = self.get_valve(marker_id)
        return (
            v is not None
            and v.get("open_rvec") is not None
            and v.get("closed_rvec") is not None
        )

    def get_all_ids(self) -> list[int]:
        return [int(k) for k in self.valves]

    def has_open(self, marker_id: int) -> bool:
        v = self.get_valve(marker_id)
        return v is not None and v.get("open_rvec") is not None

    def has_closed(self, marker_id: int) -> bool:
        v = self.get_valve(marker_id)
        return v is not None and v.get("closed_rvec") is not None

    def config_status(self, marker_id: int) -> str:
        """'full' | 'partial_open' | 'partial_closed' | 'none'"""
        ho, hc = self.has_open(marker_id), self.has_closed(marker_id)
        if ho and hc: return "full"
        if ho:        return "partial_open"
        if hc:        return "partial_closed"
        return "none"

    def get_name(self, marker_id: int) -> str:
        v = self.get_valve(marker_id)
        return v["name"] if v else f"Valve {marker_id}"


# ── Valve state tracker ────────────────────────────────────────────────────────

class ValveStateTracker:
    """Maintains a sliding window of orientation votes per valve."""

    def __init__(self, window_size: int = SAMPLE_WINDOW):
        self.window_size = window_size
        self.votes: dict = defaultdict(lambda: deque(maxlen=window_size))
        self.last_rvec: dict = {}
        self.visible: set = set()

    def update(self, marker_id: int, rvec: np.ndarray, config_mgr: ValveConfigManager):
        self.last_rvec[marker_id] = rvec
        if not config_mgr.is_fully_configured(marker_id):
            return
        v = config_mgr.get_valve(marker_id)
        d_open   = angular_distance(rvec, v["open_rvec"])
        d_closed = angular_distance(rvec, v["closed_rvec"])
        self.votes[marker_id].append("open" if d_open < d_closed else "closed")

    def get_state(self, marker_id: int) -> str:
        history = self.votes.get(marker_id)
        if not history:
            return "unknown"
        open_count = sum(1 for v in history if v == "open")
        return "open" if open_count >= len(history) - open_count else "closed"

    def get_confidence(self, marker_id: int) -> float:
        history = self.votes.get(marker_id)
        if not history:
            return 0.0
        open_count = sum(1 for v in history if v == "open")
        return max(open_count, len(history) - open_count) / len(history)

    def get_sample_count(self, marker_id: int) -> int:
        return len(self.votes.get(marker_id, []))

    def set_visible(self, visible_ids: set):
        self.visible = set(visible_ids)
