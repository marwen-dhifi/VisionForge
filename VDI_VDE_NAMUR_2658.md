# VDI/VDE/NAMUR 2658 — MTP Inspection Module

## What This Is

This document describes the architecture and implementation plan for integrating the **VDI/VDE/NAMUR 2658 (MTP — Module Type Package)** standard into VisionForge.

VisionForge becomes a **PEA (Process Equipment Assembly)** — a self-contained modular unit that exposes its vision-inspection capabilities as **MTP-compliant services** over **OPC UA**. An external **POL (Plant Orchestration Layer)** can connect, discover all available inspection services, send START/STOP commands, read live measurement data, and retrieve final results — without touching the VisionForge UI.

---

## Background: What is MTP?

The MTP standard defines how industrial modules expose their capabilities for plug-and-produce integration into a plant. Key concepts:

| Term | Meaning |
|------|---------|
| **PEA** | Process Equipment Assembly — the module (VisionForge itself) |
| **POL** | Plant Orchestration Layer — the external system that controls PEAs |
| **Service** | A named, stateful capability with a 16-state lifecycle |
| **Procedure** | A specific way to run a service (different modes/configurations) |
| **Procedure Parameter** | Input locked at START, set by POL before starting |
| **Report Value** | Live output published during EXECUTE |
| **Process Value Out** | Final result available after COMPLETED |
| **OPC UA** | The communication protocol used for all data exchange |
| **AML Manifest** | Machine-readable XML description of the PEA, imported by the POL |

### The 16-State Service Lifecycle

```
          ┌─────────────────────────────────────────────┐
          │                                             │
     ┌────▼─────┐  START   ┌──────────┐  auto   ┌──────▼───────┐
     │   IDLE   ├─────────►│ STARTING ├────────►│   EXECUTE    │
     └──────────┘          └──────────┘         └──┬───────────┘
          ▲                                         │
          │  RESET   ┌──────────┐  auto             │ COMPLETE / auto
          └──────────┤RESETTING │◄──────────────────┤
                     └──────────┘         ┌─────────▼──────────┐
                                          │    COMPLETING      │
                                          └─────────┬──────────┘
                                                    │ auto
                                          ┌─────────▼──────────┐
                                          │    COMPLETED       │
                                          └────────────────────┘

Emergency:  any state ──ABORT──► ABORTING ──auto──► ABORTED
Orderly:    any state ──STOP───► STOPPING ──auto──► STOPPED
Pause:      EXECUTE   ──PAUSE──► PAUSING  ──auto──► PAUSED ──RESUME──► RESUMING ──► EXECUTE
Hold:       EXECUTE   ──HOLD───► HOLDING  ──auto──► HELD   ──UNHOLD──► UNHOLDING ──► EXECUTE
```

**State codes (bitmask, powers of 2):**

| State | Code | State | Code |
|-------|------|-------|------|
| stopped | 4 | starting | 8 |
| idle | 16 | paused | 32 |
| execute | 64 | stopping | 128 |
| aborting | 256 | aborted | 512 |
| holding | 1024 | held | 2048 |
| unholding | 4096 | pausing | 8192 |
| resuming | 16384 | resetting | 32768 |
| completing | 65536 | completed | 131072 |

**Command codes:**

| Command | Code | Allowed from |
|---------|------|-------------|
| reset | 2 | stopped, aborted, completed |
| start | 4 | idle |
| stop | 8 | execute, paused, held, starting, resuming |
| hold | 16 | execute, starting, resuming |
| unhold | 32 | held |
| pause | 64 | execute |
| resume | 128 | paused |
| abort | 256 | almost any state |
| restart | 512 | execute |
| complete | 1024 | execute |

---

## Architecture Overview

```
VisionForge Application
│
├── app/inspection/                ← NEW: MTP integration layer
│   ├── inspection_service.py      ← Base class task authors subclass
│   ├── inspection_module.py       ← Owns OPC UA server, enforces constraints
│   ├── inspection_tab.py          ← UI tab added to each task panel
│   └── service_aware_panel.py     ← Wrapper adding Inspection tab to existing panels
│
├── app/tasks/
│   ├── seven_segment/
│   │   └── service.py             ← Task author writes this (optional)
│   ├── valve_orientation/
│   │   └── service.py             ← Task author writes this (optional)
│   └── module_tracker/
│       └── service.py             ← Task author writes this (optional)
│
└── plugins/<any_plugin>/
    └── service.py                 ← Plugin author writes this (optional)
```

---

## Key Design Decisions

### 1. One PEA, One OPC UA Server
VisionForge is one machine — all task services are registered in a single OPC UA server (one PEA). The endpoint is configurable (default: `opc.tcp://0.0.0.0:48050/`), set in the connection dialog.

### 2. One Service Active at a Time
Hardware constraint: one camera, one processor. Only one service can be in EXECUTE simultaneously. If a second service attempts to start while one is active, a warning is logged. Full enforcement (rejection) is a Phase 2 enhancement.

### 3. Shared Processor — No Double Processing
The service and the task panel share the **same** `TaskProcessor`. The processor runs persistently (not tied to panel visibility). The service taps into `result_ready` signal. No second processor is ever created.

```
CameraClient ──► TaskProcessor ──► display_ready ──► TaskPanel (UI)
                               └──► result_ready ──► InspectionService (OPC UA)
```

### 4. Auto-Switch: POL Always Wins
When the POL sends START to a service, VisionForge automatically switches to that task's panel. Always — no confirmation needed for the switch itself.

### 5. Abort on Navigate
If the user tries to switch to a different panel while a service is in EXECUTE, a confirmation dialog appears: **"Switching will ABORT the active service. Continue?"**
- Yes → service sent ABORT, tab switches
- No → stays on current panel, service continues

### 6. Inspection Tab per Task
Each task panel with a `service.py` gets an **Inspection** tab added to its existing tab bar (always last). Tasks without `service.py` are unchanged.

---

## New File Structure

### `app/inspection/inspection_service.py`
**The base class task authors subclass.**

```python
from app.inspection.inspection_service import InspectionService

class MyTaskService(InspectionService):

    def __init__(self):
        super().__init__(
            tag_name='my_task_service',
            tag_description='Inspects my task outputs',
        )
        # Define inputs (locked at START by POL)
        self.add_parameter('ana', 'threshold',
                           v_min=0.0, v_max=1.0)
        self.add_parameter('dint', 'max_count',
                           v_min=1, v_max=100)

        # Define live outputs (updated during EXECUTE)
        self.add_report_value('str',  'current_reading')
        self.add_report_value('ana',  'confidence', v_scl_min=0.0, v_scl_max=1.0)
        self.add_report_value('dint', 'detection_count', v_min=0, v_max=100)

    def on_starting(self):
        """Read locked parameters before EXECUTE begins."""
        self._threshold = self.get_param('threshold') or 0.5

    def on_result(self, result):
        """Called every frame. Update report values here. Do NOT block."""
        self.set_report('confidence', result.get('confidence', 0.0))
        self.set_report('detection_count', len(result.get('detections', [])))

    def on_completing(self):
        """Optional final actions before COMPLETED."""
        pass
```

**Parameter types (`kind`):**

| kind | MTP type | Python type | Use for |
|------|----------|-------------|---------|
| `'ana'` | AnaServParam / AnaView | float | Analog values (temperature, confidence, score) |
| `'dint'` | DIntServParam / DIntView | int | Integer values (count, index, code) |
| `'bin'` | BinServParam / BinView | bool | Boolean flags (pass/fail, enabled/disabled) |
| `'str'` | StringServParam / StringView | str | Text (reading, label, status message) |

**`add_parameter` kwargs:**

| kwarg | Applies to | Meaning |
|-------|-----------|---------|
| `v_min` | ana, dint | Hard minimum (writes outside range are rejected) |
| `v_max` | ana, dint | Hard maximum |
| `v_scl_min` | ana, dint | Display scaling minimum |
| `v_scl_max` | ana, dint | Display scaling maximum |
| `v_unit` | ana, dint | UNECE unit code (23=°C, 2073=s, 0=dimensionless) |
| `v_state_0` | bin | Name for False state (e.g. `'fail'`) |
| `v_state_1` | bin | Name for True state (e.g. `'pass'`) |

**All 16 MTPPy state methods are auto-implemented** by the base class. Authors never write them.

---

### `app/inspection/inspection_module.py`
**Owns the OPC UA server. Created once by MainWindow.**

Responsibilities:
- Accept service registrations with their stack index
- Start `OPCUAServerPEA` after all services registered
- Enforce one-active-service constraint
- Detect when a service enters EXECUTE and emit `auto_switch_requested`
- Detect POL vs operator control and emit `pol_control_changed`
- Stop the server on app close

**Qt signals:**

| Signal | Type | Description |
|--------|------|-------------|
| `auto_switch_requested` | `Signal(int)` | MainWindow should switch to this stack index |
| `pol_control_changed` | `Signal(bool)` | True = POL is driving an active service |
| `service_state_changed` | `Signal(str, str)` | (tag_name, state_str) for InspectionTab |

---

### `app/inspection/inspection_tab.py`
**The Inspection sub-tab widget added to task panels.**

Contents:
- **POL warning banner** — hidden by default; amber warning when POL is controlling
- **State indicator** — large colored label showing current MTP state
- **Manual control buttons** — START / STOP / RESET / ABORT (for testing without a POL)
- **Report values table** — live-updating 2-column table (Tag / Value)

State color scheme:

| State | Color |
|-------|-------|
| idle | grey `#8890B8` |
| execute | green `#00E676` |
| completed | cyan `#00CFFF` |
| held, stopped, aborted | red `#FF4466` |
| transitions (starting, completing, etc.) | amber `#FFB300` |

---

### `app/inspection/service_aware_panel.py`
**Wraps an existing TaskPanel in a QTabWidget.**

```
ServiceAwareWrapper
└── QTabWidget
    ├── Tab 0: original TaskPanel  (e.g. "Seven Segment")
    └── Tab 1: InspectionTab       ("Inspection")
```

Proxies `attach_camera()`, `attach_arm()`, `cleanup()` to the inner panel. Applied by MainWindow automatically when a service is discovered.

---

## Plugin System Extension

### `plugin.json` (extended, optional fields)

```json
{
  "name": "my_plugin",
  "label": "My Plugin",
  "icon": "⬡",
  "version": "1.0.0",
  "panel_module": "panel",
  "panel_class": "MyPanel",
  "service_module": "service",
  "service_class": "MyInspectionService"
}
```

If `service_module` / `service_class` are absent, the plugin works exactly as before — no inspection service, no Inspection tab.

### PluginDescriptor (extended)

```python
@dataclass
class PluginDescriptor:
    manifest:     PluginManifest
    PanelClass:   type
    ServiceClass: type | None = None    # None if no service.py
```

---

## Processor Lifecycle Change

**Current behavior:** `TaskProcessor` starts when panel becomes visible (`showEvent`), stops when hidden (`hideEvent`).

**New behavior:** Processor starts once in `on_attach()` via `_start_processor_persistent()` and runs until `cleanup()`. Panel visibility has no effect on the processor.

```python
# New method added to TaskPanel base class:
def _start_processor_persistent(self) -> None:
    """
    Connect camera → processor and start it. Call once from on_attach().
    Processor runs until cleanup() regardless of panel visibility.
    """
    if self._cam and self._processor:
        self._cam.raw_frame_received.connect(self._processor.submit_frame)
    if self._processor and not self._processor.isRunning():
        self._processor.start()
```

**Affected panels (remove showEvent/hideEvent camera wiring, call `_start_processor_persistent` instead):**
- `app/tasks/seven_segment/panel.py`
- `app/tasks/valve_orientation/panel.py`
- `app/tasks/module_tracker/panel.py`

---

## Connection Dialog Changes

A new **OPC UA Port** field is added (default: `48050`), styled to match existing camera/arm IP fields. The `connection_established` signal gains a 5th argument (int port):

```python
connection_established = Signal(object, object, str, str, int)
# (camera_client, arm_controller, cam_ip, arm_ip, opc_port)
```

---

## MainWindow Changes

### Startup sequence addition (after all panels added to stack)

```
1. Create InspectionModule(opc_port)
2. For each built-in task with a service.py:
   a. Instantiate service
   b. Connect processor.result_ready → service.on_result
   c. Create InspectionTab(service)
   d. Wrap panel in ServiceAwareWrapper(panel, inspection_tab)
   e. Replace panel in stack with wrapper (same index)
   f. Register: inspection_module.register_service(service, stack_index)
3. For each plugin with ServiceClass != None: same steps (a–f)
4. inspection_module.start_server()   ← OPC UA server starts
5. Wire signals:
   inspection_module.auto_switch_requested → _on_auto_switch
   inspection_module.pol_control_changed   → _on_pol_control_changed
```

### Tab switching guard

All sidebar navigation is routed through `_on_page_change_requested()`:
- If no active service → switch freely
- If switching away from active service's panel → confirmation dialog → ABORT or cancel

### Auto-switch slot

```python
def _on_auto_switch(self, index: int) -> None:
    # POL always wins — no confirmation
    self._stack.setCurrentIndex(index)
    self._sidebar._select(index)
```

---

## Complete Data Flow Diagrams

### VisionForge → POL (data publication)

```
Camera hardware (ZMQ)
        │ raw_frame_received(np.ndarray, meta)
        ▼
TaskProcessor.submit_frame()   [bounded queue]
        │
        ▼ process_frame()      [TaskProcessor QThread]
        │
        ├──► display_ready(QImage) ─────────────────► TaskPanel live feed (main thread)
        │
        └──► result_ready(object)
                    │
                    ▼ on_result(result)   [TaskProcessor QThread]
             InspectionService
                    │ self.set_report('key', value)
                    ▼
             MTPPy AnaView.set_v(value)
                    │
                    ▼
             OPC UA node value updated
                    │
                    ▼ OPC UA subscription notification
             POL reads live report values
```

### POL → VisionForge (command flow)

```
POL writes CommandExt = 4 (START) to OPC UA node
        │ opcua subscription callback
        ▼
StateMachine.set_command_ext(4)
        │ ThreadControl spawns new thread
        ▼
InspectionService.starting()     [plain thread]
        │ state_changed.emit('starting')   [QueuedConnection]
        ▼                                  [main thread]
InspectionModule._on_service_state_changed('tag', 'starting')
        │
        ├──► auto_switch_requested.emit(stack_index)
        │         ▼
        │    MainWindow._on_auto_switch(index)   ← panel switches
        │
        └──► (service auto-advances: starting → execute)
                    │ state_changed.emit('execute')
                    ▼
             InspectionModule detects execute
             pol_control_changed.emit(True)
                    │
                    ▼
             InspectionTab shows POL warning banner
```

---

## MTPPy Bug Fix Required

**File:** `MTPPy/src/mtppy/state_codes.py`

Two lines contain a typo: `32678` instead of `32768` (= 2^15, the correct power-of-two for the `resetting` state).

```python
# Fix line ~20:
self.resetting = 32768           # was 32678

# Fix line ~39:
self.int_code[32768] = 'resetting'  # was 32678
```

This bug causes an external POL checking `StateCur` against the standard's bitmask scheme to never recognize the RESETTING state, breaking the reset flow.

---

## Complete Example: Seven Segment Service

**File:** `app/tasks/seven_segment/service.py`

```python
from app.inspection.inspection_service import InspectionService


class SevenSegInspectionService(InspectionService):
    """
    Exposes the seven-segment OCR pipeline to a POL via OPC UA.

    Parameters (set by POL before START):
        confidence_threshold (float, 0.0–1.0)  minimum OCR confidence to publish

    Report values (live during EXECUTE):
        ocr_value       (str)   most recent OCR reading e.g. "123.4"
        ocr_confidence  (float) confidence of last reading, 0.0–1.0
        detection_count (int)   number of displays currently tracked
    """

    def __init__(self):
        super().__init__(
            tag_name='seven_segment_inspection',
            tag_description='Seven-segment OCR inspection via YOLO-OBB + PARSeq',
        )
        self.add_parameter(
            'ana', 'confidence_threshold',
            tag_description='Minimum OCR confidence to publish (0.0–1.0)',
            v_min=0.0, v_max=1.0, v_scl_min=0.0, v_scl_max=1.0,
        )
        self.add_report_value('str',  'ocr_value',
                              tag_description='Last OCR reading')
        self.add_report_value('ana',  'ocr_confidence',
                              tag_description='OCR confidence 0–1',
                              v_scl_min=0.0, v_scl_max=1.0)
        self.add_report_value('dint', 'detection_count',
                              tag_description='Tracked display count',
                              v_min=0, v_max=100)

    def on_starting(self):
        self._threshold = self.get_param('confidence_threshold') or 0.5

    def on_result(self, result):
        if result is None:
            return
        n = len(result.tracker_ids) if hasattr(result, 'tracker_ids') else 0
        self.set_report('detection_count', n)
        best_text, best_conf = '', 0.0
        for tid, (text, conf) in result.ocr_results.items():
            if conf >= self._threshold and conf > best_conf:
                best_text, best_conf = text, conf
        if best_text:
            self.set_report('ocr_value',      best_text)
            self.set_report('ocr_confidence', best_conf)
```

---

## Files Modified Summary

| File | Change |
|------|--------|
| `MTPPy/src/mtppy/state_codes.py` | Fix `32678` → `32768` (2 lines) — do this first |
| `app/inspection/__init__.py` | New package |
| `app/inspection/inspection_service.py` | New — base class for task authors |
| `app/inspection/inspection_module.py` | New — OPC UA server owner |
| `app/inspection/inspection_tab.py` | New — UI tab widget |
| `app/inspection/service_aware_panel.py` | New — QTabWidget wrapper |
| `app/plugin_sdk/base.py` | Add `_start_processor_persistent()`; make showEvent/hideEvent no-ops |
| `app/plugin_sdk/manifest.py` | Add `service_module`, `service_class` optional fields |
| `app/plugin_sdk/loader.py` | Add `ServiceClass` to `PluginDescriptor`; load `service.py` |
| `app/connection_dialog.py` | Add OPC UA port field; 5-arg signal |
| `app/main.py` | Pass `opc_port` to `MainWindow` |
| `app/main_window.py` | `InspectionModule`; service registration; auto-switch routing |
| `app/tasks/seven_segment/panel.py` | Use `_start_processor_persistent()` |
| `app/tasks/valve_orientation/panel.py` | Same |
| `app/tasks/module_tracker/panel.py` | Same |
| `app/tasks/seven_segment/service.py` | New — example service implementation |

---

## Verification Steps

1. **MTPPy bug fix** — `StateCodes().resetting == 32768` ✓
2. **InspectionService unit test** — instantiate, call `set_report`, verify `AnaView.attributes['V'].value`
3. **OPC UA startup** — connect UaExpert to `opc.tcp://localhost:48050/`; verify all service nodes present
4. **Manual operator test (no POL)** — click START → EXECUTE → live table updates → STOP → RESET
5. **Auto-switch test** — navigate to different panel; send `CommandExt=4` via UaExpert → VisionForge switches panel; POL banner appears
6. **Abort-on-navigate** — service in EXECUTE; click different tab → dialog appears → Yes aborts, No stays
7. **Mutual exclusion** — two services registered; start one; try to start second → console warning
8. **Processor persistence** — service in EXECUTE; navigate away from panel → processor keeps running
