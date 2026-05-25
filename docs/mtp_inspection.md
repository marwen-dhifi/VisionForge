# MTP Inspection Services

VisionForge implements the **VDI/VDE/NAMUR 2658 Module Type Package (MTP)** standard, making it a compliant **Process Equipment Assembly (PEA)**. Each vision task and plugin can expose its results as an OPC UA inspection service that an external **Process Orchestration Layer (POL)** — or a test client like UaExpert — can start, stop, query, and subscribe to.

---

## Concepts

### Two independent mode dimensions

Every MTP service has two independent mode axes:

| Dimension | States | What it controls |
|---|---|---|
| Operation mode | **Offline** (default) → **Operator** → **Automatic** | Who sends commands |
| Source mode | **Internal** → **External** (only active in Automatic) | Whether Automatic commands come from the POL |

- **Operator mode** (`StateOpAct = True`) — the InspectionTab buttons work. UaExpert/POL `CommandExt` is ignored.
- **Automatic + External** (`StateAutAct = True` AND `SrcExtAct = True`) — `CommandExt` works. Buttons are locked out.

### Service state machine

```
IDLE ──START──► STARTING ──► EXECUTE ──STOP──► STOPPING ──► STOPPED ──RESET──► IDLE
                                      ──COMPLETE──► COMPLETING ──► COMPLETED ──RESET──► IDLE
       ◄──────────────────── ABORT (from any state) ─────────────────────────────────
```

- `on_starting()` is called once before EXECUTE — read locked parameters here.
- `on_result(result)` is called every frame while in EXECUTE — update report values here.
- `on_completing()` is called once before COMPLETED — optional cleanup.

---

## Writing a service.py

Create `service.py` alongside `panel.py` in your task or plugin folder. Subclass `InspectionService` and override only the methods you need.

```python
from VisionForge.app.inspection.inspection_service import InspectionService


class MyInspectionService(InspectionService):

    def __init__(self):
        super().__init__(
            tag_name='my_service',            # unique OPC UA identifier
            tag_description='What this does',
        )

        # Declare input parameters (locked at START, readable by POL)
        self.add_parameter(
            'ana', 'threshold',
            tag_description='Detection threshold (0.0 - 1.0)',
            v_scl_min=0.0, v_scl_max=1.0,
        )

        # Declare output report values (live-updated during EXECUTE)
        self.add_report_value('str',  'result',     tag_description='Last detection result')
        self.add_report_value('ana',  'confidence', tag_description='Confidence 0-1',
                              v_scl_min=0.0, v_scl_max=1.0)
        self.add_report_value('dint', 'count',      tag_description='Detection count',
                              v_min=0, v_max=1000)
        self.add_report_value('bin',  'alert',      tag_description='Alert flag')

        self._threshold = 0.5

    def on_starting(self):
        # Read parameters once — they are locked until STOP/RESET
        self._threshold = float(self.get_param('threshold') or 0.5)

    def on_result(self, result) -> None:
        # Called every frame from the processor QThread — do NOT block
        if result is None:
            return
        self.set_report('count',      result.count)
        self.set_report('confidence', result.confidence)
        self.set_report('alert',      result.confidence > self._threshold)
        self.set_report('result',     result.label)
```

### Parameter / report value kinds

| Kind | OPC UA type | Python type | Useful kwargs |
|---|---|---|---|
| `'ana'` | Float | float | `v_scl_min`, `v_scl_max`, `v_unit` |
| `'dint'` | Int32 | int | `v_min`, `v_max` |
| `'bin'` | Boolean | bool | `v_state_0`, `v_state_1` |
| `'str'` | String | str | — |

The same kinds work for both `add_parameter()` and `add_report_value()`.

---

## Registering the service in plugin.json

Add two optional fields to your `plugin.json`:

```json
{
    "name":           "my_plugin",
    "label":          "My Task",
    "icon":           "◈",
    "version":        "1.0.0",
    "panel_module":   "panel",
    "panel_class":    "MyPanel",
    "service_module": "service",
    "service_class":  "MyInspectionService"
}
```

VisionForge will instantiate the service at startup, wire `processor.result_ready → service.on_result`, and register it in the shared OPC UA server. An **Inspection** sub-tab is added automatically to your panel.

---

## The Inspection sub-tab

When a service is registered, the platform wraps your panel in a `QTabWidget` and adds an **Inspection** tab:

| Element | Description |
|---|---|
| POL banner | Amber warning shown whenever `SrcExtAct = True` (POL has control) |
| State indicator | Large colored label — IDLE (grey) / EXECUTE (green) / COMPLETED (cyan) / STOPPED/ABORTED (red) |
| Control buttons | START / COMPLETE / STOP / RESET / ABORT — send Operator-mode commands |
| Parameters table | Current `VOut` values (locked at START). Write `VOp` column to set before starting. |
| Report values table | Live-updated every frame during EXECUTE |

The buttons send `CommandOp` after asserting Operator mode. If a POL holds External control, it can reclaim after buttons are used by writing `StateAutOp=True` then `SrcExtOp=True`.

---

## Testing with the dev runner

The dev runner opens an **Inspection** window automatically when your plugin declares a service.

```powershell
python -m VisionForge.app.plugin_sdk.dev_runner plugins\my_plugin `
    --camera 192.168.1.100 `
    --arm    192.168.1.200 `
    --opc-port 48050
```

The window shows the OPC UA endpoint and the full InspectionTab — identical to what the main platform shows. Use the buttons to cycle through states and confirm report values update correctly. Use `--no-inspection` to hide it.

---

## Testing with UaExpert (POL simulation)

### 1. Connect

Open UaExpert → **Server → Add** → endpoint:
```
opc.tcp://localhost:48050/
```

### 2. Navigate the tree

```
Root → Objects → MTP → Services → <tag_name>
```

Two sub-objects: **`StateMachine`** and **`OpSrcMode`**.

### 3. Switch to Automatic + External source

In `OpSrcMode`:
1. Write **`StateAutOp`** = `True` → `StateAutAct` flips to `True`
2. Write **`SrcExtOp`** = `True` → `SrcExtAct` flips to `True`

The POL banner appears in the inspection window within 500 ms.

> `StateAutOp` and `SrcExtOp` are **pulse nodes** — they auto-reset to `False`, but `StateAutAct` and `SrcExtAct` stay `True` until overridden.

### 4. Send commands via CommandExt

In `StateMachine`, write to **`CommandExt`**:

| Command | Value |
|---|---|
| START | `4` |
| STOP | `8` |
| RESET | `2` |
| ABORT | `256` |
| COMPLETE | `1024` |

Write `4` → service transitions STARTING → EXECUTE. Report values update live in UaExpert subscriptions and in the inspection window simultaneously.

### 5. Subscribe to report values

Drag any node from the tree into the **Data Access View** panel. Right-click → **Subscribe** for live updates.

---

## OPC UA server port

Default port: **48050**. Configure in the VisionForge connection dialog or with `--opc-port` in the dev runner.

---

## Built-in services

| Task | tag_name | Parameters | Report values |
|---|---|---|---|
| Seven-Segment Reader | `seven_segment_inspection` | `confidence_threshold` (ana, 0-1) | `detections` (str) — format: `"N\|name:text:conf\|..."`, one entry per named/tracked display |
