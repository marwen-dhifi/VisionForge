"""
GamepadController — QThread that runs the gamepad control loop.
"""

import time
import pygame
from PySide6.QtCore import QThread, Signal


LOOP_DELAY   = 0.01
DEADZONE     = 0.1
DECEL_STEPS  = 8
MVACC        = 500

SPEED_MIN_MMS  =  20    # mm/s at 0%
SPEED_MAX_MMS  = 500    # mm/s at 100%
PCT_STEP       =   5    # % per button press

def _pct_to_mms(pct: float) -> float:
    return SPEED_MIN_MMS + (SPEED_MAX_MMS - SPEED_MIN_MMS) * pct / 100.0

def _mms_to_pct(mms: float) -> float:
    return (mms - SPEED_MIN_MMS) / (SPEED_MAX_MMS - SPEED_MIN_MMS) * 100.0

# If no command sent for this many seconds, re-read real arm position.
# This handles go_zero/go_initial, error recovery, everything automatically.
RESYNC_AFTER = 0.3

BTN_R1, BTN_L1     = 5, 4
BTN_R2, BTN_L2     = 7, 6
BTN_SPEED_UP       = 0
BTN_SPEED_DOWN     = 2
BTN_RECOVER        = 9   # START button
AXIS_LEFT_X        = 0
AXIS_LEFT_Y        = 1


def _dz(v, d=DEADZONE):
    if abs(v) < d:
        return 0.0
    s = 1.0 if v > 0 else -1.0
    return s * (abs(v) - d) / (1.0 - d)


class GamepadController(QThread):
    speed_changed     = Signal(int)
    gamepad_connected = Signal(bool)

    def __init__(self, arm_controller=None, parent=None):
        super().__init__(parent)
        self._arm           = arm_controller
        self._running       = False
        self._speed         = 100
        self._joystick_name = None   # None = not connected
        self._do_reset      = False  # set True when START pressed
        self._speed_pct     = 20    # percentage 0-100

    def set_arm(self, arm_controller):
        self._arm = arm_controller

    def set_speed_pct(self, pct: int):
        """Called from UI slider."""
        self._speed_pct = max(0, min(100, pct))
        self.speed_changed.emit(self._speed_pct)

    def stop(self):
        self._running = False

    def run(self):
        self._running = True

        if not pygame.get_init():
            pygame.init()
        pygame.joystick.init()

        joystick        = None
        x = y = z = yaw = None
        buttons_held    = set()
        last_delta      = (0.0, 0.0, 0.0, 0.0)
        decel_counter   = 0
        last_cmd_time   = 0.0   # monotonic time of last sent command

        while self._running:
            t0 = time.monotonic()

            # ── Detect joystick ───────────────────────────────────────
            if joystick is None:
                pygame.joystick.quit()
                pygame.joystick.init()
                if pygame.joystick.get_count() > 0:
                    joystick = pygame.joystick.Joystick(0)
                    joystick.init()
                    self._joystick_name = joystick.get_name()
                    self.gamepad_connected.emit(True)
                else:
                    self._joystick_name = None
                    self.gamepad_connected.emit(False)
                    time.sleep(1.0)
                    continue

            # ── Pygame events — always processed ─────────────────────
            try:
                for event in pygame.event.get():
                    if event.type == pygame.JOYDEVICEREMOVED:
                        joystick = None
                        self._joystick_name = None
                        x = None
                        self.gamepad_connected.emit(False)
                        break
                    if event.type == pygame.JOYBUTTONDOWN:
                        buttons_held.add(event.button)
                        if event.button == BTN_RECOVER:
                            self._do_reset = True
                        elif event.button == BTN_SPEED_UP:
                            self._speed_pct = min(self._speed_pct + PCT_STEP, 100)
                            self.speed_changed.emit(self._speed_pct)
                        elif event.button == BTN_SPEED_DOWN:
                            self._speed_pct = max(self._speed_pct - PCT_STEP, 0)
                            self.speed_changed.emit(self._speed_pct)
                    elif event.type == pygame.JOYBUTTONUP:
                        buttons_held.discard(event.button)
            except Exception:
                joystick = None
                self._joystick_name = None
                x = None
                self.gamepad_connected.emit(False)
                continue

            if joystick is None:
                continue

            # ── Arm must be ready ─────────────────────────────────────
            arm = self._arm
            if arm is None or arm.get_arm() is None:
                x = None
                time.sleep(LOOP_DELAY)
                continue

            raw_arm = arm.get_arm()
            if raw_arm.error_code != 0:
                x = None
                time.sleep(LOOP_DELAY)
                continue

            # ── Handle START button reset directly ──────────────────────
            if self._do_reset:
                self._do_reset = False
                try:
                    raw_arm.clean_warn()
                    raw_arm.clean_error()
                    time.sleep(0.3)
                    raw_arm.motion_enable(enable=True)
                    time.sleep(0.2)
                    raw_arm.set_mode(1)
                    raw_arm.set_state(0)
                    time.sleep(0.2)
                    x = None
                except Exception:
                    pass
                continue

            # ── Re-read real position if idle too long ────────────────
            # Covers: go_zero, go_initial, error recovery, startup.
            # No flags, no race conditions — just reads reality.
            idle = (t0 - last_cmd_time) > RESYNC_AFTER
            if x is None or idle:
                code, pos = raw_arm.get_position(is_radian=False)
                if code == 0 and pos and len(pos) >= 6:
                    x, y, z, yaw = pos[0], pos[1], pos[2], pos[5]
                    decel_counter = 0
                    last_delta    = (0.0, 0.0, 0.0, 0.0)
                else:
                    time.sleep(LOOP_DELAY)
                    continue

            # ── Build deltas ──────────────────────────────────────────
            _mms     = _pct_to_mms(self._speed_pct)
            step     = _mms * LOOP_DELAY
            yaw_step = _mms / 100.0 * LOOP_DELAY * 20

            try:
                lx = _dz(joystick.get_axis(AXIS_LEFT_X))
                ly = _dz(joystick.get_axis(AXIS_LEFT_Y))
            except Exception:
                joystick = None; self._joystick_name = None; x = None
                continue

            dx   = -ly * step
            dy   = -lx * step
            dz   = +step if BTN_R1 in buttons_held else (-step if BTN_L1 in buttons_held else 0.0)
            dyaw = -yaw_step if BTN_R2 in buttons_held else (yaw_step if BTN_L2 in buttons_held else 0.0)

            active = any([dx, dy, dz, dyaw])

            if active:
                last_delta    = (dx, dy, dz, dyaw)
                decel_counter = DECEL_STEPS
                fdx, fdy, fdz, fdyaw = dx, dy, dz, dyaw
            elif decel_counter > 0:
                taper = decel_counter / DECEL_STEPS
                decel_counter -= 1
                fdx   = last_delta[0] * taper
                fdy   = last_delta[1] * taper
                fdz   = last_delta[2] * taper
                fdyaw = last_delta[3] * taper
            else:
                fdx = fdy = fdz = fdyaw = 0.0

            # ── Send command ──────────────────────────────────────────
            if any([fdx, fdy, fdz, fdyaw]):
                nx = x + fdx; ny = y + fdy
                nz = z + fdz; nyaw = yaw + fdyaw
                try:
                    code = raw_arm.set_servo_cartesian(
                        mvpose=[nx, ny, nz, 180.0, 0.0, nyaw],
                        mvvelo=_mms,
                        mvacc=MVACC,
                        is_radian=False,
                    )
                    if code in (0, None):
                        x, y, z, yaw = nx, ny, nz, nyaw
                        last_cmd_time = t0   # update only on successful send
                    else:
                        decel_counter = 0
                except Exception:
                    pass

            elapsed = time.monotonic() - t0
            sleep_t = LOOP_DELAY - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

        pygame.joystick.quit()