"""
ArmController — QThread wrapping the xArm5 SDK.
"""

import time
import threading
from PySide6.QtCore import QThread, Signal

POLL_INTERVAL = 0.1


class ArmController(QThread):
    connection_changed = Signal(bool)
    enabled_changed    = Signal(bool)
    position_updated   = Signal(float, float, float, float, float, float)
    error_occurred     = Signal(str)
    scan_state_changed = Signal(bool)   # True = running, False = stopped

    def __init__(self, ip: str, parent=None):
        super().__init__(parent)
        self._ip        = ip
        self._arm       = None
        self._running   = False
        self._gamepad   = None
        self._lock      = threading.Lock()   # guards SDK calls across threads
        self._scan_stop: threading.Event | None = None

    def set_gamepad(self, gamepad):
        self._gamepad = gamepad

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _sdk(self, fn, *args, **kwargs):
        """Call any SDK function under the lock."""
        with self._lock:
            return fn(*args, **kwargs)

    def _run_bg(self, fn):
        """Run fn in a daemon thread so we never block the main/Qt thread."""
        t = threading.Thread(target=fn, daemon=True)
        t.start()

    # ── Public API ──────────────────────────────────────────────────────────

    def go_zero_start(self):
        if not self._arm: return
        def _do():
            try:
                self._sdk(self._arm.set_mode, 0)
                self._sdk(self._arm.set_state, 0)
                time.sleep(0.1)
                self._sdk(self._arm.set_servo_angle,
                          angle=[0,0,0,0,0], speed=30, mvacc=200,
                          wait=False, is_radian=False)
            except Exception as e:
                self.error_occurred.emit(str(e))
        self._run_bg(_do)

    def go_zero_stop(self):
        if not self._arm: return
        def _do():
            try:
                self._sdk(self._arm.set_state, 4)
                time.sleep(0.1)
                self._sdk(self._arm.set_state, 0)
                time.sleep(0.05)
                self._sdk(self._arm.set_mode, 1)
                self._sdk(self._arm.set_state, 0)
            except Exception as e:
                self.error_occurred.emit(str(e))
        self._run_bg(_do)

    def go_initial_start(self):
        if not self._arm: return
        def _do():
            try:
                self._sdk(self._arm.set_mode, 0)
                self._sdk(self._arm.set_state, 0)
                time.sleep(0.1)
                self._sdk(self._arm.set_position,
                          300, 0, 300, 180, 0, 0,
                          speed=80, mvacc=500,
                          wait=False, is_radian=False)
            except Exception as e:
                self.error_occurred.emit(str(e))
        self._run_bg(_do)

    def go_initial_stop(self):
        if not self._arm: return
        def _do():
            try:
                self._sdk(self._arm.set_state, 4)
                time.sleep(0.1)
                self._sdk(self._arm.set_state, 0)
                time.sleep(0.05)
                self._sdk(self._arm.set_mode, 1)
                self._sdk(self._arm.set_state, 0)
            except Exception as e:
                self.error_occurred.emit(str(e))
        self._run_bg(_do)

    def reset_arm(self):
        if not self._arm: return
        def _do():
            try:
                self._sdk(self._arm.clean_warn)
                self._sdk(self._arm.clean_error)
                time.sleep(0.3)
                self._sdk(self._arm.motion_enable, enable=True)
                time.sleep(0.2)
                self._sdk(self._arm.set_mode, 1)
                self._sdk(self._arm.set_state, 0)
                time.sleep(0.2)
                enabled = self._arm.error_code == 0
                self.enabled_changed.emit(enabled)
            except Exception as e:
                self.error_occurred.emit(str(e))
        self._run_bg(_do)

    def start_valve_scan(self, pos: list, amplitude_mm: float, speed_mmps: float):
        """
        Move to pos=[x, y, z, roll, pitch, yaw], go up by amplitude_mm, then
        oscillate between z+amplitude_mm and z-amplitude_mm until stop_valve_scan().

        amplitude_mm : half-stroke — the arm travels ±amplitude_mm from the centre Z.
        speed_mmps   : TCP speed in mm/s (caller enforces safe range).
        """
        if not self._arm:
            return
        self._scan_stop = threading.Event()

        def _do():
            self.scan_state_changed.emit(True)
            x, y, z, roll, pitch, yaw = pos
            spd   = max(5, int(speed_mmps))
            z_top = z + amplitude_mm
            z_bot = z - amplitude_mm

            def _move_to(target_z) -> bool:
                """Issue one cartesian move and poll until done or stop requested."""
                if self._scan_stop.is_set():
                    return False
                with self._lock:
                    self._arm.set_position(x, y, target_z, roll, pitch, yaw,
                                           speed=spd, mvacc=500,
                                           wait=False, is_radian=False)
                while not self._scan_stop.is_set():
                    if self._arm.state != 1:   # 1 = arm in motion
                        break
                    time.sleep(0.05)
                return not self._scan_stop.is_set()

            try:
                # Switch to position mode
                with self._lock:
                    self._arm.set_mode(0)
                    self._arm.set_state(0)
                time.sleep(0.15)

                # 1. Go to the chosen centre point
                if not _move_to(z):
                    return

                # 2. First move: up by amplitude
                if not _move_to(z_top):
                    return

                # 3. Oscillate: down to z_bot → up to z_top → repeat
                while not self._scan_stop.is_set():
                    if not _move_to(z_bot):
                        break
                    if not _move_to(z_top):
                        break

            except Exception as e:
                self.error_occurred.emit(str(e))
            finally:
                # Restore servo mode regardless of how we exited
                try:
                    with self._lock:
                        self._arm.set_state(4)
                    time.sleep(0.15)
                    with self._lock:
                        self._arm.set_state(0)
                    time.sleep(0.05)
                    with self._lock:
                        self._arm.set_mode(1)
                        self._arm.set_state(0)
                except Exception:
                    pass
                self.scan_state_changed.emit(False)

        threading.Thread(target=_do, daemon=True).start()

    def stop_valve_scan(self):
        """Signal the scan loop to exit and halt the arm immediately."""
        if self._scan_stop is not None:
            self._scan_stop.set()
        if self._arm:
            try:
                with self._lock:
                    self._arm.set_state(4)   # immediate hardware halt
            except Exception:
                pass

    # Keep old aliases
    def go_zero(self):    self.go_zero_start()
    def go_initial(self): self.go_initial_start()

    def stop(self):
        self._running = False

    def get_arm(self):
        return self._arm

    def get_position(self):
        """Return (code, [x, y, z, roll, pitch, yaw]) from the xArm SDK.
        Uses a 1-second lock timeout so callers on the main thread never block
        indefinitely if the background thread is stuck in a hanging SDK call."""
        if not self._arm:
            return -1, None
        acquired = self._lock.acquire(timeout=1.0)
        if not acquired:
            return -1, None
        try:
            return self._arm.get_position(is_radian=False)
        finally:
            self._lock.release()

    def send_servo_cartesian(self, pose, mvvelo=100, mvacc=500):
        """Send a single servo-cartesian target pose [x,y,z,roll,pitch,yaw].
        Uses a short lock timeout so the main thread never stalls."""
        if not self._arm:
            return False
        acquired = self._lock.acquire(timeout=0.05)
        if not acquired:
            return False
        try:
            self._arm.set_servo_cartesian(pose, mvvelo=mvvelo, mvacc=mvacc,
                                          is_radian=False)
            return True
        except Exception as e:
            self.error_occurred.emit(str(e))
            return False
        finally:
            self._lock.release()

    # ── QThread entry point ─────────────────────────────────────────────────

    def run(self):
        self._running = True
        try:
            from xarm.wrapper import XArmAPI
            self._arm = XArmAPI(self._ip)

            if not self._arm.connected:
                self.connection_changed.emit(False)
                self.error_occurred.emit(f"Could not connect to xArm at {self._ip}")
                return

            if self._arm.error_code != 0:
                self.connection_changed.emit(True)
                self.enabled_changed.emit(False)
            else:
                with self._lock:
                    self._arm.motion_enable(enable=True)
                    self._arm.set_mode(1)
                    self._arm.set_state(0)
                self.connection_changed.emit(True)
                self.enabled_changed.emit(True)

        except Exception as e:
            self.connection_changed.emit(False)
            self.error_occurred.emit(str(e))
            return

        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5

        while self._running:
            try:
                if not self._arm.connected:
                    print("[ArmController] arm.connected = False — disconnected")
                    break
                with self._lock:
                    code, pos = self._arm.get_position(is_radian=False)
                if code == 0 and pos and len(pos) >= 6:
                    consecutive_errors = 0
                    self.position_updated.emit(*pos[:6])
                else:
                    consecutive_errors += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        print(f"[ArmController] {MAX_CONSECUTIVE_ERRORS} consecutive bad "
                              f"responses — treating as disconnected")
                        break
            except Exception as e:
                self.error_occurred.emit(str(e))
                break
            time.sleep(POLL_INTERVAL)

        try:
            if self._arm:
                self._arm.disconnect()
        except Exception:
            pass

        self.connection_changed.emit(False)

    def cleanup(self):
        self.stop()
        self.wait(3000)