"""
Module Tracker — shared constants, geometry, config persistence, and InfluxDB writer.

Geometry is ported verbatim from the verified standalone script
Production/DepthEstimationAndDistanceMeasurement/5-main2+history.py
with the two geometry fixes applied:
  1. Front direction uses R[:,0] (marker X-axis = module front direction).
  2. Right direction: rlx, rly = -fly, flx   (to_lab has det=-1 → orientation-reversing).
"""

import csv
import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import cv2
import numpy as np

# ── ArUco ─────────────────────────────────────────────────────────────────────

MARKER_SIZE    = 0.25                   # 250 mm physical side length
ARUCO_DICT_ID  = cv2.aruco.DICT_6X6_50
SWAP_XY        = True                  # lab X → screen X (right), lab Y → screen Y (up)

# ── Camera defaults (all configurable from the UI) ────────────────────────────

DEFAULT_CAMERA_ANGLE_DEG    = 60.0   # Ry / yaw of camera optical axis from lab X
DEFAULT_CAMERA_HEIGHT_OFFSET = 0.5   # metres added to arm Z for display label

# ── Map defaults ──────────────────────────────────────────────────────────────

DEFAULT_MAP_SCALE_M = 8.0            # metres represented by the drawable map area
MAP_W_PX            = 640
MAP_H_PX            = 640
MAP_MARGIN_PX       = 58

# ── InfluxDB ──────────────────────────────────────────────────────────────────

INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "0FvQ4oKTsdke0QZz6uiEMiMTTuXDJFaBnfrLpCfiODt4eoQHRPPd-71Enhk6kklxNsbHhdXJ2D7QMzod56a6NQ=="
INFLUX_ORG    = "ESDperformance"
INFLUX_BUCKET = "Modules_Tracking"

RECORD_INTERVAL_S = 1.0


# ── Colour palette (BGR) matching the app theme (#060612 bg, #00CFFF accent) ──

# Background & structure
COL_BG           = ( 18,   6,   6)   # #060612
COL_GRID_MINOR   = ( 30,  16,  16)   # very subtle grid
COL_GRID_MAJOR   = ( 50,  26,  26)   # 0.5 m grid

# Axes & camera
COL_AXIS_X       = (255, 100,  80)   # blue X
COL_AXIS_Y       = (100, 230,  80)   # green Y
COL_CAMERA       = (255, 207,   0)   # #00CFFF cyan — camera origin
COL_CAM_DIR      = (200, 180,   0)   # slightly dimmer for camera arrow

# Modules
COL_MODULE_BODY  = ( 40,  28,  16)   # very dark fill
COL_MODULE_FRONT = (180, 220,  50)   # teal front face
COL_MODULE_TEXT  = (235, 235, 235)   # bright label text
COL_MARKER_DOT   = ( 60,  60, 255)   # red marker circle
COL_DIST_TEXT    = (184, 144, 136)   # #8890B8 muted

MODULE_PALETTE = [
    (255, 207,   0),   # cyan  #00CFFF
    (118, 230,   0),   # green #00E676
    (255, 140,  50),   # blue
    (200,  80, 200),   # purple
    (  0, 200, 255),   # yellow
    ( 60, 180, 255),   # light blue
]

FONT = cv2.FONT_HERSHEY_SIMPLEX


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ModuleEntry:
    id:     int
    name:   str
    width:  float = 0.40
    height: float = 0.30
    length: float = 0.20


@dataclass
class ModuleTrackerConfig:
    camera_angle_deg:    float = DEFAULT_CAMERA_ANGLE_DEG
    camera_height_m:     float = 0.0          # arm Z coordinate (live, not persisted)
    camera_height_offset: float = DEFAULT_CAMERA_HEIGHT_OFFSET
    map_scale_m:         float = DEFAULT_MAP_SCALE_M
    modules:             Dict[int, ModuleEntry] = field(default_factory=dict)
    default_module:      ModuleEntry = field(
        default_factory=lambda: ModuleEntry(id=-1, name="DEFAULT",
                                            width=0.40, height=0.30, length=0.20)
    )

    def get_module_cfg(self, marker_id: int) -> dict:
        """Return {'width', 'height', 'length'} for a marker ID."""
        if marker_id in self.modules:
            m = self.modules[marker_id]
        else:
            m = self.default_module
        return {"width": m.width, "height": m.height, "length": m.length}


# ── JSON persistence ──────────────────────────────────────────────────────────

def load_config(path: str) -> ModuleTrackerConfig:
    cfg = ModuleTrackerConfig()
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, "r") as f:
            data = json.load(f)
        cfg.camera_angle_deg     = float(data.get("camera_angle_deg",     DEFAULT_CAMERA_ANGLE_DEG))
        cfg.camera_height_offset = float(data.get("camera_height_offset", DEFAULT_CAMERA_HEIGHT_OFFSET))
        cfg.map_scale_m          = float(data.get("map_scale_m",          DEFAULT_MAP_SCALE_M))

        dm = data.get("default_module", {})
        cfg.default_module = ModuleEntry(
            id=-1, name="DEFAULT",
            width=float(dm.get("width", 0.40)),
            height=float(dm.get("height", 0.30)),
            length=float(dm.get("length", 0.20)),
        )

        for k, v in data.get("modules", {}).items():
            mid = int(k)
            cfg.modules[mid] = ModuleEntry(
                id=mid,
                name=str(v.get("name", f"Module {mid}")),
                width=float(v.get("width", 0.40)),
                height=float(v.get("height", 0.30)),
                length=float(v.get("length", 0.20)),
            )
    except Exception as e:
        print(f"[ModuleTracker] Failed to load config from {path}: {e}")
    return cfg


def save_config(cfg: ModuleTrackerConfig, path: str):
    data = {
        "camera_angle_deg":     cfg.camera_angle_deg,
        "camera_height_offset": cfg.camera_height_offset,
        "map_scale_m":          cfg.map_scale_m,
        "default_module": {
            "width":  cfg.default_module.width,
            "height": cfg.default_module.height,
            "length": cfg.default_module.length,
        },
        "modules": {
            str(mid): {
                "name":   m.name,
                "width":  m.width,
                "height": m.height,
                "length": m.length,
            }
            for mid, m in cfg.modules.items()
        },
    }
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[ModuleTracker] Failed to save config to {path}: {e}")


# ── Camera matrix helper ──────────────────────────────────────────────────────

def make_camera_matrix(w: int, h: int) -> np.ndarray:
    """Rough pinhole estimate when no calibration is available."""
    fx = fy = float(max(w, h))
    return np.array([[fx, 0, w / 2], [0, fy, h / 2], [0, 0, 1]], dtype=np.float64)


# ── Core geometry (ported verbatim from fixed standalone) ─────────────────────

def marker_pose_to_lab(tvec_cam: np.ndarray, rvec_cam: np.ndarray,
                       mod_cfg: dict, camera_angle_deg: float) -> dict:
    """
    Convert ArUco pose (tvec/rvec in camera frame) to lab-frame module geometry.

    Returns dict with keys:
      corners_lab  — [tfr, tfl, tbl, tbr]  (4 np.ndarray [x,y])
      front_dir    — (flx, fly)  unit vector pointing toward module front
      marker_lab   — (lxm, lym)  marker centre in lab
      corner_lab   — (lxc, lyc)  marker top-right corner in lab
      distance     — distance from camera/origin to module centre (metres)
    """
    R, _ = cv2.Rodrigues(rvec_cam)
    local_offset = np.array([MARKER_SIZE / 2, MARKER_SIZE / 2, 0], dtype=np.float64)
    corner_cam = tvec_cam + R @ local_offset

    # Marker +X axis = module front direction.
    # Proof: marker top-right corner (R[:,0] side) = module top-FRONT-right corner.
    fx_cam = float(R[0, 0])
    fz_cam = float(R[2, 0])

    # SWAP_XY=True means screen X = lab Y, screen Y = lab X.
    # To make angle=0 point along screen X (lab Y direction), rotate by -90°:
    ar = math.pi / 2 - math.radians(camera_angle_deg)
    ca, sa = math.cos(ar), math.sin(ar)

    def to_lab(cx, cz):
        rr = ar + math.pi / 2
        return cx * math.cos(rr) + cz * ca, cx * math.sin(rr) + cz * sa

    lxc, lyc = to_lab(float(corner_cam[0]), float(corner_cam[2]))
    lxm, lym = to_lab(float(tvec_cam[0]),   float(tvec_cam[2]))
    flx, fly  = to_lab(fx_cam, fz_cam)
    fl = math.hypot(flx, fly)
    if fl > 1e-6:
        flx /= fl
        fly /= fl

    # to_lab has det=-1 (orientation-reversing), so physical right = CCW rotation in lab
    rlx, rly = -fly, flx

    w = mod_cfg["width"]
    L = mod_cfg["length"]
    tfr = np.array([lxc, lyc])
    tfl = tfr - np.array([rlx, rly]) * w
    tbr = tfr - np.array([flx, fly]) * L
    tbl = tfl - np.array([flx, fly]) * L

    lx_c = (tfr[0] + tfl[0] + tbl[0] + tbr[0]) / 4
    ly_c = (tfr[1] + tfl[1] + tbl[1] + tbr[1]) / 4

    return {
        "corners_lab": [tfr, tfl, tbl, tbr],
        "front_dir":   (flx, fly),
        "marker_lab":  (lxm, lym),
        "corner_lab":  (lxc, lyc),
        "distance":    float(np.linalg.norm([lx_c, ly_c])),
    }


# ── Map renderer ──────────────────────────────────────────────────────────────

def lab_to_px(lx: float, ly: float, scale: float, origin: tuple) -> tuple:
    if SWAP_XY:
        lx, ly = ly, lx
    return int(origin[0] + lx / scale), int(origin[1] - ly / scale)


def _text_shadow(img, text, pos, font, scale, col, thickness=1):
    """Draw text with a dark drop-shadow for readability."""
    sx, sy = pos[0] + 1, pos[1] + 1
    cv2.putText(img, text, (sx, sy), font, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
    cv2.putText(img, text, pos,      font, scale, col,       thickness,     cv2.LINE_AA)


def render_map(modules_data: dict, map_scale_m: float,
               camera_angle_deg: float, camera_height_m: float) -> np.ndarray:
    """
    Render a polished top-down map (MAP_W_PX × MAP_H_PX, BGR).
    modules_data: {marker_id: {corners_lab, front_dir, marker_lab, corner_lab, distance}}
    """
    img = np.full((MAP_H_PX, MAP_W_PX, 3), COL_BG, dtype=np.uint8)

    drawable = min(MAP_W_PX, MAP_H_PX) - 2 * MAP_MARGIN_PX
    scale    = map_scale_m / drawable
    origin   = (MAP_MARGIN_PX, MAP_H_PX - MAP_MARGIN_PX)

    # ── Grid ────────────────────────────────────────────────────────────────
    step_minor = int(0.25 / scale)
    step_major = int(0.5  / scale)

    if step_minor > 6:
        for gx in range(origin[0] % step_minor, MAP_W_PX, step_minor):
            col_g = COL_GRID_MAJOR if (gx - origin[0]) % step_major == 0 else COL_GRID_MINOR
            cv2.line(img, (gx, 0), (gx, MAP_H_PX), col_g, 1)
        for gy in range(origin[1] % step_minor, MAP_H_PX, step_minor):
            col_g = COL_GRID_MAJOR if (origin[1] - gy) % step_major == 0 else COL_GRID_MINOR
            cv2.line(img, (0, gy), (MAP_W_PX, gy), col_g, 1)

    # ── Outer border ─────────────────────────────────────────────────────────
    cv2.rectangle(img, (1, 1), (MAP_W_PX - 2, MAP_H_PX - 2), (56, 26, 26), 1)

    # ── Camera origin ─────────────────────────────────────────────────────────
    ar = math.radians(camera_angle_deg)

    # camera view cone (subtle)
    cone_len = int(1.2 / scale)
    cone_half = math.radians(20)
    for dangle in (-cone_half, cone_half):
        ex = origin[0] + int(cone_len * math.cos(ar + dangle))
        ey = origin[1] - int(cone_len * math.sin(ar + dangle))
        cv2.line(img, origin, (ex, ey), (40, 35, 20), 1, cv2.LINE_AA)

    # camera direction arrow
    arrow_len = int(0.6 / scale)
    cam_end = (
        origin[0] + int(arrow_len * math.cos(ar)),
        origin[1] - int(arrow_len * math.sin(ar)),
    )
    cv2.arrowedLine(img, origin, cam_end, COL_CAM_DIR, 2,
                    cv2.LINE_AA, tipLength=0.18)

    # camera dot — double ring for elegance
    cv2.circle(img, origin, 10, (30, 20, 10), -1)
    cv2.circle(img, origin,  8, COL_CAMERA,   -1)
    cv2.circle(img, origin, 10, COL_CAMERA,    1, cv2.LINE_AA)
    cv2.circle(img, origin, 14, (100, 80, 0),  1, cv2.LINE_AA)

    _text_shadow(img, "CAM",
                 (origin[0] + 16, origin[1] - 3),
                 FONT, 0.38, COL_CAMERA)

    # ── Axis arrows ──────────────────────────────────────────────────────────
    ax_len = int(0.5 / scale)
    xe = (origin[0] + ax_len, origin[1])
    ye = (origin[0], origin[1] - ax_len)
    cv2.arrowedLine(img, origin, xe, COL_AXIS_X, 2, cv2.LINE_AA, tipLength=0.15)
    cv2.arrowedLine(img, origin, ye, COL_AXIS_Y, 2, cv2.LINE_AA, tipLength=0.15)
    _text_shadow(img, "X", (xe[0] + 4, xe[1] + 5),  FONT, 0.42, COL_AXIS_X)
    _text_shadow(img, "Y", (ye[0] + 4, ye[1] + 2),  FONT, 0.42, COL_AXIS_Y)

    # ── Modules ───────────────────────────────────────────────────────────────
    for i, (mid, data) in enumerate(modules_data.items()):
        corners_lab = data["corners_lab"]
        front_dir   = data["front_dir"]
        marker_lab  = data["marker_lab"]
        distance    = data["distance"]

        col = MODULE_PALETTE[i % len(MODULE_PALETTE)]

        pts = np.array(
            [lab_to_px(c[0], c[1], scale, origin) for c in corners_lab],
            dtype=np.int32,
        )
        cen = (int(pts[:, 0].mean()), int(pts[:, 1].mean()))

        # Filled body with semi-transparent overlay via blending
        overlay = img.copy()
        cv2.fillPoly(overlay, [pts], COL_MODULE_BODY)
        cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)

        # Module outline — dim colour
        dim_col = tuple(max(0, c - 80) for c in col)
        cv2.polylines(img, [pts], True, dim_col, 1, cv2.LINE_AA)

        # Bright outer glow line
        cv2.polylines(img, [pts], True, col, 1, cv2.LINE_AA)

        # Front face — thick + bright
        cv2.line(img, tuple(pts[0]), tuple(pts[1]), COL_MODULE_FRONT, 3, cv2.LINE_AA)

        # Front direction arrow from centre
        alen = max(14, int(0.1 / scale))
        fa = (
            int(cen[0] + front_dir[0] * alen),
            int(cen[1] - front_dir[1] * alen),
        )
        cv2.arrowedLine(img, cen, fa, COL_MODULE_FRONT, 2, cv2.LINE_AA, tipLength=0.30)

        # Marker dot
        mx, my = lab_to_px(marker_lab[0], marker_lab[1], scale, origin)
        cv2.circle(img, (mx, my), 6, (20, 20, 20), -1)
        cv2.circle(img, (mx, my), 5, COL_MARKER_DOT, -1, cv2.LINE_AA)
        cv2.circle(img, (mx, my), 7, col, 1, cv2.LINE_AA)

        # ID label — centred on module body
        id_str   = f"ID {mid}"
        dist_str = f"{distance:.2f} m"
        _text_shadow(img, id_str,
                     (cen[0] - 18, cen[1] - 5),
                     FONT, 0.50, COL_MODULE_TEXT, 1)
        _text_shadow(img, dist_str,
                     (cen[0] - 18, cen[1] + 14),
                     FONT, 0.38, COL_DIST_TEXT)

    # ── Scale bar ─────────────────────────────────────────────────────────────
    bar_len = int(0.5 / scale)
    bx  = MAP_W_PX - MAP_MARGIN_PX - bar_len
    by  = MAP_H_PX - 22
    bar_col = (120, 110, 90)
    cv2.line(img,  (bx, by),         (bx + bar_len, by), bar_col, 2, cv2.LINE_AA)
    cv2.line(img,  (bx, by - 5),     (bx, by + 5),       bar_col, 2, cv2.LINE_AA)
    cv2.line(img,  (bx + bar_len, by - 5),
                   (bx + bar_len, by + 5),                bar_col, 2, cv2.LINE_AA)
    _text_shadow(img, "0.5 m",
                 (bx + bar_len // 2 - 18, by - 8),
                 FONT, 0.35, bar_col)

    # ── Header strip ──────────────────────────────────────────────────────────
    cv2.rectangle(img, (1, 1), (MAP_W_PX - 2, 36), (28, 12, 10), -1)
    cv2.line(img, (1, 36), (MAP_W_PX - 2, 36), (56, 26, 26), 1)
    _text_shadow(img, "LAB TOP-DOWN MAP",
                 (MAP_MARGIN_PX, 24), FONT, 0.52, (235, 235, 235), 1)
    _text_shadow(img,
                 f"angle {camera_angle_deg:.0f}\u00b0   h {camera_height_m:.2f} m",
                 (MAP_W_PX - 220, 24), FONT, 0.38, (184, 144, 136))

    return img


# ── InfluxDB writer ───────────────────────────────────────────────────────────

class ModuleInfluxWriter:
    """
    Writes ArUco module pose data to InfluxDB bucket Modules_Tracking.
    Measurement name = str(marker_id).  Tag = module_name.
    """

    def __init__(self):
        self._ok = False
        try:
            from influxdb_client import InfluxDBClient
            from influxdb_client.client.write_api import SYNCHRONOUS
            self._Point     = None   # imported lazily below
            self._client    = InfluxDBClient(
                url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG,
                timeout=15_000,   # 15 s connection + read timeout (ms)
            )
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            from influxdb_client import Point
            self._Point = Point
            self._ok = True
        except Exception as e:
            print(f"[ModuleTracker] InfluxDB unavailable: {e}")

    @property
    def connected(self) -> bool:
        return self._ok

    def write(self, marker_id: int, module_name: str, data: dict):
        """
        data must contain:
          marker_lab, corner_lab, distance, front_dir, corners_lab (4 entries)
        """
        if not self._ok:
            return
        try:
            lxm, lym     = data["marker_lab"]
            lxc, lyc     = data["corner_lab"]
            dist         = data["distance"]
            flx, fly     = data["front_dir"]
            corners      = data["corners_lab"]

            p = (
                self._Point(str(marker_id))
                .tag("module_name", module_name)
                .field("marker_x",  round(lxm, 4))
                .field("marker_y",  round(lym, 4))
                .field("center_x",  round(sum(c[0] for c in corners) / 4, 4))
                .field("center_y",  round(sum(c[1] for c in corners) / 4, 4))
                .field("distance",  round(dist, 4))
                .field("front_dx",  round(flx, 4))
                .field("front_dy",  round(fly, 4))
                .field("corner_lab_x", round(lxc, 4))
                .field("corner_lab_y", round(lyc, 4))
            )
            for i, c in enumerate(corners):
                p = p.field(f"corner{i}_x", round(float(c[0]), 4))
                p = p.field(f"corner{i}_y", round(float(c[1]), 4))

            self._write_api.write(bucket=INFLUX_BUCKET, record=p)
        except Exception as e:
            print(f"[ModuleTracker] InfluxDB write error: {e}")

    def query_history(self, hours: int, minutes: int) -> list:
        """
        Query InfluxDB for recorded module positions over the last (hours*60 + minutes) minutes.
        Returns a list of snapshot dicts compatible with PositionHistory.snapshots format.
        Raises an exception on query failure (caller should handle in a background thread).
        """
        if not self._ok:
            raise RuntimeError("InfluxDB not connected")

        total_min = hours * 60 + minutes
        if total_min <= 0:
            return []

        # Pivot: one row per (timestamp, marker_id) with all fields as columns
        query = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{total_min}m)
  |> filter(fn: (r) => r._measurement =~ /^[0-9]+$/)
  |> pivot(rowKey: ["_time", "_measurement"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
        query_api = self._client.query_api()
        tables    = query_api.query(query, org=INFLUX_ORG)

        # Group rows by floor(unix_second) so modules detected in the same
        # recording cycle end up in the same snapshot.
        from collections import defaultdict
        buckets: dict = defaultdict(dict)   # t_sec → {mid: module_dict}

        for table in tables:
            for rec in table.records:
                t_sec = int(rec.get_time().timestamp())
                mid   = int(rec.get_measurement())
                v     = rec.values
                buckets[t_sec][mid] = {
                    "marker_x":    float(v.get("marker_x",    0.0)),
                    "marker_y":    float(v.get("marker_y",    0.0)),
                    "center_x":    float(v.get("center_x",    0.0)),
                    "center_y":    float(v.get("center_y",    0.0)),
                    "distance":    float(v.get("distance",    0.0)),
                    "front_dx":    float(v.get("front_dx",    0.0)),
                    "front_dy":    float(v.get("front_dy",    0.0)),
                    "corners_lab": [
                        (float(v.get("corner0_x", 0.0)), float(v.get("corner0_y", 0.0))),
                        (float(v.get("corner1_x", 0.0)), float(v.get("corner1_y", 0.0))),
                        (float(v.get("corner2_x", 0.0)), float(v.get("corner2_y", 0.0))),
                        (float(v.get("corner3_x", 0.0)), float(v.get("corner3_y", 0.0))),
                    ],
                    "corner_lab": (
                        float(v.get("corner_lab_x", 0.0)),
                        float(v.get("corner_lab_y", 0.0)),
                    ),
                }

        snapshots = []
        for t_sec in sorted(buckets.keys()):
            dt = datetime.fromtimestamp(t_sec)
            snapshots.append({
                "timestamp": float(t_sec),
                "datetime":  dt.strftime("%Y-%m-%d %H:%M:%S"),
                "modules":   buckets[t_sec],
            })
        return snapshots

    def close(self):
        if self._ok:
            try:
                self._client.close()
            except Exception:
                pass


# ── Position History ──────────────────────────────────────────────────────────

class PositionHistory:
    """
    Records timestamped snapshots of all visible modules at a fixed interval.
    Each snapshot stores the full lab-frame geometry so it can be re-rendered
    on the map or exported to CSV later.
    """

    RECORD_INTERVAL_S = 1.0

    def __init__(self):
        self.snapshots: list = []
        self._last_time = 0.0

    # ── Recording ─────────────────────────────────────────────────────────────

    def maybe_record(self, modules_data: dict) -> bool:
        """
        Record a snapshot if RECORD_INTERVAL_S has elapsed since the last one.
        modules_data: {marker_id: lab_dict} (format returned by marker_pose_to_lab)
        Returns True if a new snapshot was added.
        """
        now = time.time()
        if now - self._last_time < self.RECORD_INTERVAL_S:
            return False
        self._last_time = now

        snap = {
            "timestamp": now,
            "datetime":  datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
            "modules":   {},
        }
        for mid, data in modules_data.items():
            lx, ly = data["marker_lab"]
            cx = sum(float(c[0]) for c in data["corners_lab"]) / 4
            cy = sum(float(c[1]) for c in data["corners_lab"]) / 4
            snap["modules"][int(mid)] = {
                "marker_x":    round(float(lx), 4),
                "marker_y":    round(float(ly), 4),
                "center_x":    round(float(cx), 4),
                "center_y":    round(float(cy), 4),
                "distance":    round(float(data["distance"]), 4),
                "front_dx":    round(float(data["front_dir"][0]), 4),
                "front_dy":    round(float(data["front_dir"][1]), 4),
                "corners_lab": [
                    (round(float(c[0]), 4), round(float(c[1]), 4))
                    for c in data["corners_lab"]
                ],
                "corner_lab": (
                    round(float(data["corner_lab"][0]), 4),
                    round(float(data["corner_lab"][1]), 4),
                ),
            }
        self.snapshots.append(snap)
        return True

    def clear(self):
        self.snapshots.clear()
        self._last_time = 0.0

    def load_snapshots(self, incoming: list) -> int:
        """
        Merge incoming snapshots (from InfluxDB query) with the current session list.
        Deduplicates by integer unix-second timestamp, sorts chronologically.
        Returns the number of newly added snapshots.
        """
        existing_ts = {int(s["timestamp"]) for s in self.snapshots}
        added = [s for s in incoming if int(s["timestamp"]) not in existing_ts]
        self.snapshots = sorted(self.snapshots + added, key=lambda s: s["timestamp"])
        return len(added)

    # ── Snapshot → modules_data conversion (for re-rendering) ─────────────────

    def snapshot_to_modules(self, snap: dict) -> dict:
        """Convert a stored snapshot back to the modules_data format for render_map."""
        out = {}
        for mid, md in snap["modules"].items():
            out[mid] = {
                "corners_lab": [np.array(c, dtype=np.float64) for c in md["corners_lab"]],
                "front_dir":   (md["front_dx"], md["front_dy"]),
                "marker_lab":  (md["marker_x"], md["marker_y"]),
                "corner_lab":  md["corner_lab"],
                "distance":    md["distance"],
            }
        return out

    # ── CSV export ────────────────────────────────────────────────────────────

    FIELDS = [
        "timestamp", "datetime", "module_id",
        "marker_x_m", "marker_y_m", "center_x_m", "center_y_m",
        "distance_m", "front_dx", "front_dy",
        "corner0_x", "corner0_y", "corner1_x", "corner1_y",
        "corner2_x", "corner2_y", "corner3_x", "corner3_y",
    ]

    def export_csv(self, path: str | None = None) -> str | None:
        if not self.snapshots:
            return None
        if path is None:
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"aruco_history_{ts}.csv"
        rows = []
        for snap in self.snapshots:
            base = {"timestamp": snap["timestamp"], "datetime": snap["datetime"]}
            if snap["modules"]:
                for mid, md in snap["modules"].items():
                    rows.append({
                        **base,
                        "module_id":  mid,
                        "marker_x_m": md["marker_x"],
                        "marker_y_m": md["marker_y"],
                        "center_x_m": md["center_x"],
                        "center_y_m": md["center_y"],
                        "distance_m": md["distance"],
                        "front_dx":   md["front_dx"],
                        "front_dy":   md["front_dy"],
                        "corner0_x":  md["corners_lab"][0][0],
                        "corner0_y":  md["corners_lab"][0][1],
                        "corner1_x":  md["corners_lab"][1][0],
                        "corner1_y":  md["corners_lab"][1][1],
                        "corner2_x":  md["corners_lab"][2][0],
                        "corner2_y":  md["corners_lab"][2][1],
                        "corner3_x":  md["corners_lab"][3][0],
                        "corner3_y":  md["corners_lab"][3][1],
                    })
            else:
                empty = {k: "" for k in self.FIELDS}
                rows.append({**empty, **base})

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return os.path.abspath(path)

    def __len__(self):
        return len(self.snapshots)
