# VDI/VDE/NAMUR 2658 — MTP Standard, OPC UA Node Structure, and MTPPy Framework

---

## Table of Contents

1. [What Problem Does MTP Solve?](#1-what-problem-does-mtp-solve)
2. [The Two Actors: PEA and POL](#2-the-two-actors-pea-and-pol)
3. [Core MTP Concepts](#3-core-mtp-concepts)
   - 3.1 Service
   - 3.2 Procedure
   - 3.3 Data Assemblies
   - 3.4 Operation Mode and Source Mode
4. [The Service State Machine](#4-the-service-state-machine)
   - 4.1 All 16 States
   - 4.2 All 10 Commands
   - 4.3 State Transition Rules
5. [The MTP Manifest File](#5-the-mtp-manifest-file)
6. [Exact OPC UA Node Structure](#6-exact-opc-ua-node-structure)
   - 6.1 Namespace
   - 6.2 Full Node Tree
   - 6.3 State and Command Code Reference
7. [MTPPy Framework Overview](#7-mtppy-framework-overview)
   - 7.1 Installation
   - 7.2 Class Hierarchy
   - 7.3 Step-by-Step Usage
   - 7.4 All Abstract State Methods
8. [Known Bugs in MTPPy](#8-known-bugs-in-mtppy)
9. [Water Heater Implementation Summary](#9-water-heater-implementation-summary)

---

## 1. What Problem Does MTP Solve?

In a traditional process plant, every time you add a new piece of equipment (a reactor, a pump skid, a heater) to the plant control system, an automation engineer must sit down and manually configure it: wire up the OPC UA addresses, build the HMI screens, define the alarms, write the integration logic. This takes weeks and costs a lot of money.

**VDI/VDE/NAMUR 2658** — the Module Type Package (MTP) standard — solves this with a simple idea:

> The equipment vendor ships a standardized description file (the MTP) alongside the physical unit. Any compliant plant control system reads that file and integrates the unit automatically — no manual engineering.

This is called **plug-and-produce**: analogous to plug-and-play for USB devices, but for industrial process equipment.

---

## 2. The Two Actors: PEA and POL

### PEA — Process Equipment Assembly

A self-contained, autonomous modular unit. Examples:
- A water heater skid
- A mixing reactor
- A dosing pump unit
- A filtration module

A PEA has its own local controller (PLC or PC), runs its own OPC UA server, and is fully capable of operating independently. It exposes its capabilities through **Services**.

### POL — Process Orchestration Layer

The plant-level system that coordinates multiple PEAs to execute a production process. It:
- Imports MTP files from each PEA
- Orchestrates services across PEAs according to a production recipe
- Provides plant-wide visualization and alarm management

The POL is the only system that talks to PEAs during production. Operators interact with the POL, not directly with individual PEAs.

```
  Operator
     |
     v
  [ POL ]  ←— imports water_heater_manifest.aml
     |
     |── OPC UA ──> [ Water Heater PEA ]  port 48050
     |── OPC UA ──> [ Mixer PEA ]         port 48051
     |── OPC UA ──> [ Dosing PEA ]        port 48052
```

---

## 3. Core MTP Concepts

### 3.1 Service

A **Service** is a named, stateful capability of a PEA. It is NOT a simple function call — it is a process with a defined lifecycle governed by a 16-state machine.

Examples:
- `heat_service` — heat water to a target temperature
- `mix_service`  — mix contents at a target speed for a duration
- `dose_service` — add a precise volume of reagent

A PEA can have multiple services. Each service runs its own independent state machine.

### 3.2 Procedure

A **Procedure** is one specific way to accomplish a service. A service can have multiple procedures.

Example: a `mix_service` might have:
- `slow_mix` procedure — gentle stirring
- `fast_mix` procedure — high-speed homogenization

Only one procedure can be active per service at any time. Each procedure has:

| Container | Direction | Meaning |
|---|---|---|
| **Procedure Parameters** | POL writes before START | Inputs locked in when service starts |
| **Report Values** | PEA writes during EXECUTE | Live outputs (POL reads continuously) |
| **Process Value Outs** | PEA writes on COMPLETING | Final results (readable after COMPLETED) |
| **Process Value Ins** | POL writes during EXECUTE | Live inputs during execution (not in MTPPy yet) |

### 3.3 Data Assemblies

Every piece of data in MTP is a typed **Data Assembly** — not a plain variable. Each type carries metadata (engineering units, scaling, limits) and has a defined access pattern.

#### Operation Elements (writable inputs)

**AnaServParam** — Analog parameter (float)

Has three input channels with automatic arbitration:
```
VOp  (operator/HMI writes here)
VInt (internal PLC writes here)    -->  VReq (validated) --> VOut (locked at START) --> VFbk (echo)
VExt (external POL writes here)

VMin, VMax       — hard limits (writes outside range are silently rejected)
VSclMin, VSclMax — display scaling for HMI
VUnit            — UNECE engineering unit code (23 = Celsius, 2073 = seconds)
```

The lifecycle of `VOut`:
- Before START: POL writes to `VOp`. Value is validated against `VMin/VMax` and stored in `VReq`.
- At START: `VReq` is copied into `VOut` and locked. The service uses `get_v_out()` during EXECUTE.
- At RESET: `VOut` is released for the next run.

**DIntServParam** — Integer parameter (same structure, integer types)

**BinServParam** — Boolean parameter (True/False with named states VState0/VState1)

**StringServParam** — String parameter

#### Indicator Elements (read-only outputs)

**AnaView** — Analog output (float) with `V`, `VUnit`, `VSclMin`, `VSclMax`

**DIntView** — Integer output

**BinView** — Boolean output

**StringView** — String output

#### Active Elements (process equipment)

Physical devices exposed at the PEA level (not inside a service):

**BinVlv** — Binary valve (open/close)

**AnaVlv** — Analog valve (position 0-100%)

**BinDrv** — Binary drive / motor (on/off)

**AnaDrv** — Analog drive (speed setpoint)

**PIDCtrl** — PID controller

Each active element has its own operation mode and can be controlled by either the service logic internally or the POL externally.

### 3.4 Operation Mode and Source Mode

Every service AND every parameter has two independent mode controls:

**Operation Mode** — who has authority to control this object:

| Mode | Meaning |
|---|---|
| `Off` (Offline) | No commands accepted. Default at startup. |
| `Op` (Operator) | Manual operator control via HMI |
| `Aut` (Automatic) | Automated control from POL recipe |

**Source Mode** — where commands originate:

| Mode | Meaning |
|---|---|
| `Int` (Internal) | Commands from internal automation |
| `Ext` (External) | Commands from external POL |

In practice for learning: set the service to `Op` mode by writing `True` to `StateOpOp`. This is a **trigger node** (momentary pulse) — it resets to `False` after being processed. The actual current mode is reflected in `StateOpAct` (stays `True` while in Operator mode).

---

## 4. The Service State Machine

### 4.1 All 16 States

The state machine is defined in VDI/VDE/NAMUR 2658 Part 4. Every service must implement all 16 states.

States fall into two categories:

**Stable states** — the service waits in a loop until a command arrives:

| State | Code | Description |
|---|---|---|
| `idle` | 16 | Ready, waiting for START |
| `execute` | 64 | Actively doing work |
| `completed` | 131072 | Work finished, results available, waiting for RESET |
| `paused` | 32 | Execution paused, waiting for RESUME or STOP |
| `held` | 2048 | Held by POL (recipe logic), waiting for UNHOLD |
| `stopped` | 4 | Orderly shutdown complete, waiting for RESET |
| `aborted` | 512 | Emergency stop complete, waiting for RESET |

**Transient states** — the service does a short action then calls `state_change()` to advance automatically:

| State | Code | Auto-advances to |
|---|---|---|
| `starting` | 8 | `execute` |
| `completing` | 65536 | `completed` |
| `resetting` | 32768* | `idle` |
| `pausing` | 8192 | `paused` |
| `resuming` | 16384 | `execute` |
| `holding` | 1024 | `held` |
| `unholding` | 4096 | `execute` |
| `stopping` | 128 | `stopped` |
| `aborting` | 256 | `aborted` |

*See [Known Bugs](#8-known-bugs-in-mtppy) — MTPPy has this wrong as `32678`.

### 4.2 All 10 Commands

Commands are written as integers to the `CommandOp` (or `CommandExt`/`CommandInt`) OPC UA node.

| Command | Code | Triggers transition |
|---|---|---|
| `start` | 4 | `idle` -> `starting` |
| `stop` | 8 | `execute`/`paused`/`held` -> `stopping` |
| `reset` | 2 | `completed`/`stopped`/`aborted` -> `resetting` |
| `pause` | 64 | `execute` -> `pausing` |
| `resume` | 128 | `paused` -> `resuming` |
| `hold` | 16 | `execute`/`starting`/`resuming` -> `holding` |
| `unhold` | 32 | `held` -> `unholding` |
| `abort` | 256 | (almost any state) -> `aborting` |
| `complete` | 1024 | `execute` -> `completing` (for non-self-completing procedures) |
| `restart` | 512 | `execute` -> `starting` |

### 4.3 State Transition Diagram

```
                              RESET(2)
                         +---------------+
                         |               |
              START(4)   v   auto        |
   [OFFLINE] -------> [IDLE] -------> [STARTING] ---auto---> [EXECUTE]
                         ^                                       |    |
                         |                        COMPLETE(1024) |    | PAUSE(64)
                         |              +------------------------+    v
                         |              |                       [PAUSING] --auto--> [PAUSED]
                         |              v                                               |
                         |       [COMPLETING] --auto--> [COMPLETED]          RESUME(128)|
                         |                                   |                          v
                         +---RESET(2)------------------------+             [RESUMING] --auto--+
                         |                                                                    |
                         |                                                                    |
                    HOLD(16) from EXECUTE/STARTING/RESUMING/UNHOLDING                         |
                         |                                                                    |
                         v                                                                    |
                    [HOLDING] --auto--> [HELD] --UNHOLD(32)--> [UNHOLDING] --auto------------+
                                          |
                                        STOP(8)
                                          |
                    STOP(8) from any  <---+
                         |
                         v
                    [STOPPING] --auto--> [STOPPED] --RESET(2)--> [RESETTING] --auto--> [IDLE]

                    ABORT(256) from almost any state:
                    [ABORTING] --auto--> [ABORTED] --RESET(2)--> [RESETTING] --auto--> [IDLE]
```

**Self-completing procedures**: If a procedure has `is_self_completing=True`, the service itself calls `state_change()` from within `execute()` when it decides the work is done (e.g., target temperature reached). The POL does not need to send `COMPLETE(1024)`.

**Non-self-completing procedures**: The service loops in `execute()` indefinitely until the POL sends `COMPLETE(1024)` to trigger the transition.

---

## 5. The MTP Manifest File

### What it is

The MTP manifest is an **AutomationML** file (`.aml` extension), which is a standardized XML format defined by IEC 62714. It is the machine-readable description of the entire PEA automation interface.

### What it contains

- **OPC UA server endpoint** — where to connect
- **All services and procedures** — names, IDs, whether self-completing
- **All data assemblies** — parameters, report values, process value outs, with their types, units, limits
- **All active elements** — equipment exposed at PEA level
- **OPC UA node IDs** — exact string node IDs for every item
- **HMI graphics links** — references to operator screen files (SVG)
- **Alarm definitions** — linked alarm/event description files
- **Writer metadata** — vendor name, version, timestamp

### What MTPPy generates

MTPPy generates the core manifest (services, procedures, data assemblies, OPC UA node mappings). It does NOT generate HMI graphics or alarm definition files — those are additional deliverables needed for a full production MTP package.

### The ZIP package

In production, the vendor ships a ZIP file (often renamed `.mtp`) containing:

```
WaterHeaterPEA_v1.0.mtp
├── manifest.aml              <- generated by MTPPy
├── hmi/
│   └── heat_service.svg      <- operator faceplate (NOT generated by MTPPy)
├── alarms/
│   └── alarms.aml            <- alarm definitions (NOT generated by MTPPy)
└── docs/
    └── datasheet.pdf         <- optional
```

---

## 6. Exact OPC UA Node Structure

### 6.1 Namespace

MTPPy uses **namespace index 3** (`ns=3`) for all custom nodes. All node IDs are string-based (`s=...`).

Connection endpoint (this project): `opc.tcp://127.0.0.1:48050/`

### 6.2 Full Node Tree

The complete address space MTPPy builds for the water heater PEA:

```
ns=3
|
+-- services/
|   |
|   +-- heat_service/                              (the Service)
|       |
|       +-- [Service-level attributes]
|       |     OSLevel, WQC, PosTextID, InteractQuestionID, InteractAnswerID
|       |
|       +-- op_src_mode/                           (Operation + Source Mode control)
|       |     StateChannel  (Bool, read)
|       |     StateOffAut   (Bool, read)
|       |     StateOpAut    (Bool, read)
|       |     StateAutAut   (Bool, read)
|       |     StateOffOp    (Bool, WRITE True -> go Offline)
|       |     StateOpOp     (Bool, WRITE True -> go Operator)   <-- trigger, resets to False
|       |     StateAutOp    (Bool, WRITE True -> go Automatic)  <-- trigger, resets to False
|       |     StateOffAct   (Bool, READ -> currently Offline?)
|       |     StateOpAct    (Bool, READ -> currently Operator?) <-- stays True while in Op
|       |     StateAutAct   (Bool, READ -> currently Automatic?)
|       |     SrcChannel    (Bool, read)
|       |     SrcExtAut     (Bool, read)
|       |     SrcIntOp      (Bool, write)
|       |     SrcIntAut     (Bool, read)
|       |     SrcExtOp      (Bool, write)
|       |     SrcIntAct     (Bool, read)
|       |     SrcExtAct     (Bool, read)
|       |
|       +-- state_machine/
|       |     CommandOp     (Int64, WRITE command code from Operator)
|       |     CommandInt    (Int64, WRITE command code from Internal)
|       |     CommandExt    (Int64, WRITE command code from POL/External)
|       |     StateCur      (Int64, READ current state code)
|       |     CommandEn     (Int64, READ bitmask of currently allowed commands)
|       |
|       +-- procedure_control/
|       |     ProcedureOp   (Int64, WRITE procedure ID from Operator)
|       |     ProcedureInt  (Int64, WRITE procedure ID from Internal)
|       |     ProcedureExt  (Int64, WRITE procedure ID from POL)
|       |     ProcedureCur  (Int64, READ currently active procedure ID)
|       |     ProcedureReq  (Int64, READ requested procedure ID)
|       |
|       +-- procedures/
|           |
|           +-- default_heat/                      (the Procedure, id=0)
|               |
|               +-- [Procedure attributes]
|               |     ProcedureId      (Int64, value=0)
|               |     IsSelfCompleting (Bool,  value=True)
|               |     IsDefault        (Bool,  value=True)
|               |     WQC              (Int64)
|               |
|               +-- procedure_parameters/          (inputs — set before START)
|               |   |
|               |   +-- target_temp/               (AnaServParam)
|               |         VOp       (Float, WRITE target temperature from Operator)
|               |         VInt      (Float, WRITE from internal source)
|               |         VExt      (Float, WRITE from POL)
|               |         VReq      (Float, READ validated request value)
|               |         VOut      (Float, READ locked value used during EXECUTE)
|               |         VFbk      (Float, READ feedback/confirmation)
|               |         VMin      (Float, READ = 21.0)
|               |         VMax      (Float, READ = 100.0)
|               |         VSclMin   (Float, READ = 21.0)
|               |         VSclMax   (Float, READ = 100.0)
|               |         VUnit     (Int64, READ = 23 = Celsius)
|               |         Sync      (Bool)
|               |         op_src_mode/             (same structure as service op_src_mode)
|               |
|               +-- report_values/                 (live outputs during EXECUTE)
|               |   |
|               |   +-- current_temp/              (AnaView)
|               |         V         (Float, READ current water temperature)
|               |         VUnit     (Int64, READ = 23 = Celsius)
|               |         VSclMin   (Float, READ = 0.0)
|               |         VSclMax   (Float, READ = 120.0)
|               |
|               +-- process_value_outs/            (final results on COMPLETED)
|                   |
|                   +-- actual_temp/               (AnaView)
|                   |     V         (Float, READ achieved temperature)
|                   |     VUnit     (Int64, READ = 23 = Celsius)
|                   |     VSclMin   (Float, READ = 0.0)
|                   |     VSclMax   (Float, READ = 120.0)
|                   |
|                   +-- time_to_reach/             (AnaView)
|                         V         (Float, READ elapsed seconds)
|                         VUnit     (Int64, READ = 2073 = seconds)
|                         VSclMin   (Float, READ = 0.0)
|                         VSclMax   (Float, READ = 3600.0)
```

### 6.3 State and Command Code Reference

**State codes** — read from `StateCur`:

| State | Code | Type |
|---|---|---|
| `stopped` | 4 | stable |
| `starting` | 8 | transient |
| `idle` | 16 | stable |
| `paused` | 32 | stable |
| `execute` | 64 | stable |
| `stopping` | 128 | transient |
| `aborting` | 256 | transient |
| `aborted` | 512 | stable |
| `holding` | 1024 | transient |
| `held` | 2048 | stable |
| `unholding` | 4096 | transient |
| `pausing` | 8192 | transient |
| `resuming` | 16384 | transient |
| `resetting` | 32768 | transient |
| `completing` | 65536 | transient |
| `completed` | 131072 | stable |

All codes follow the pattern 2^n. Note: MTPPy has a bug where `resetting` is coded as `32678` instead of `32768` — see [Known Bugs](#8-known-bugs-in-mtppy).

**Command codes** — write to `CommandOp`:

| Command | Code |
|---|---|
| `reset` | 2 |
| `start` | 4 |
| `stop` | 8 |
| `hold` | 16 |
| `unhold` | 32 |
| `pause` | 64 |
| `resume` | 128 |
| `abort` | 256 |
| `restart` | 512 |
| `complete` | 1024 |

**UNECE unit codes** used in `VUnit`:

| Code | Unit |
|---|---|
| 23 | Degree Celsius (°C) |
| 2073 | Second (s) |
| 5 | Kelvin (K) |
| 4 | Degree Fahrenheit (°F) |

---

## 7. MTPPy Framework Overview

### 7.1 Installation

```bash
# From the cloned repository
cd path/to/MTPPy
pip install opcua==0.98.13
pip install -e .
```

Note: MTPPy uses the legacy `opcua` library (version 0.98.13), NOT the newer `asyncua`. They are completely different APIs.

### 7.2 Class Hierarchy

```
OPCUAServerPEA              <- top-level PEA container, owns the OPC UA server
|
+-- Service (abstract)      <- subclass this for each service
|   +-- HeatService         <- your concrete implementation
|
+-- Procedure               <- holds parameters and outputs for one procedure
|
+-- Data Assemblies
|   +-- AnaServParam        <- analog writable parameter
|   +-- DIntServParam       <- integer writable parameter
|   +-- BinServParam        <- boolean writable parameter
|   +-- StringServParam     <- string writable parameter
|   +-- AnaView             <- analog read-only indicator
|   +-- DIntView            <- integer read-only indicator
|   +-- BinView             <- boolean read-only indicator
|   +-- StringView          <- string read-only indicator
|
+-- Active Elements
|   +-- BinVlv              <- binary valve
|   +-- AnaVlv              <- analog valve
|   +-- BinDrv              <- binary drive/motor
|   +-- AnaDrv              <- analog drive
|   +-- PIDCtrl             <- PID controller
|
+-- MTPGenerator            <- writes the .aml manifest file
```

### 7.3 Step-by-Step Usage

#### Step 1 — Subclass Service, define procedures in `__init__`

```python
from mtppy.service import Service
from mtppy.procedure import Procedure
from mtppy.operation_elements import AnaServParam
from mtppy.indicator_elements import AnaView
import time

class MyService(Service):
    def __init__(self, tag_name, tag_description):
        super().__init__(tag_name, tag_description)

        # Create a procedure
        proc = Procedure(
            procedure_id    = 0,
            tag_name        = 'my_procedure',
            is_self_completing = True,  # service calls state_change() itself
            is_default         = True,
        )

        # Add a writable input parameter
        proc.add_procedure_parameter(
            AnaServParam('setpoint', v_min=0, v_max=100, v_unit=23)
        )

        # Add a live output (updated during EXECUTE)
        proc.add_report_value(
            AnaView('live_value', v_scl_min=0, v_scl_max=100, v_unit=23)
        )

        # Add a final result (written in COMPLETING)
        proc.add_procedure_value_out(
            AnaView('final_value', v_scl_min=0, v_scl_max=100, v_unit=23)
        )

        self.add_procedure(proc)
```

#### Step 2 — Implement all 16 abstract state methods

Every state method runs in its own background thread managed by `ThreadControl`.

**Stable states** must loop on `self.is_state()` — this lets the framework terminate the thread cleanly on transition:

```python
def idle(self):
    while self.is_state('idle'):
        time.sleep(1)

def execute(self):
    setpoint = self.procedures[0].procedure_parameters['setpoint'].get_v_out()
    while self.is_state('execute'):
        value = do_work()
        self.procedures[0].report_values['live_value'].set_v(value)
        if work_is_done:
            self.state_change()  # triggers EXECUTE -> COMPLETING (self-completing)
            break
        time.sleep(1)

def completed(self):
    while self.is_state('completed'):
        time.sleep(0.5)

# paused, held, stopped, aborted follow the same pattern
```

**Transient states** do their work and call `self.state_change()` to advance automatically:

```python
def starting(self):
    # called once, apply parameters are already locked by MTPPy
    self.state_change()   # -> execute

def completing(self):
    # record final results
    final = get_final_result()
    self.procedures[0].process_value_outs['final_value'].set_v(final)
    self.state_change()   # -> completed

def resetting(self):
    # clear outputs
    self.procedures[0].process_value_outs['final_value'].set_v(0.0)
    self.state_change()   # -> idle

# pausing, resuming, holding, unholding, stopping, aborting follow the same pattern
```

**All 16 methods are required** even if some are just `pass`:

```python
def idle(self):       pass   # WARNING: must loop or it terminates immediately
def starting(self):   self.state_change()
def execute(self):    pass
def completing(self): self.state_change()
def completed(self):  pass
def pausing(self):    self.state_change()
def paused(self):     pass
def resuming(self):   self.state_change()
def holding(self):    self.state_change()
def held(self):       pass
def unholding(self):  self.state_change()
def stopping(self):   self.state_change()
def stopped(self):    pass
def aborting(self):   self.state_change()
def aborted(self):    pass
def resetting(self):  self.state_change()
```

#### Step 3 — Accessing parameters and setting outputs

```python
# Read a procedure parameter (use inside execute())
value = self.procedures[procedure_id].procedure_parameters['tag_name'].get_v_out()

# Set a report value (live, during EXECUTE)
self.procedures[procedure_id].report_values['tag_name'].set_v(new_value)

# Set a process value out (final result, in COMPLETING)
self.procedures[procedure_id].process_value_outs['tag_name'].set_v(result)

# Read a service-level configuration parameter
value = self.configuration_parameters['tag_name'].get_v_out()
```

Note: `procedures` is a dict keyed by `procedure_id` (the integer), not by tag name.

#### Step 4 — Wire everything in main()

```python
from mtppy.opcua_server_pea import OPCUAServerPEA
from mtppy.mtp_generator import MTPGenerator
from datetime import datetime

writer_info = {
    'WriterName': 'MyCompany', 'WriterID': 'mycompany/pea1',
    'WriterVendor': 'MyCompany', 'WriterVendorURL': 'www.mycompany.com',
    'WriterVersion': '1.0.0', 'WriterRelease': '',
    'LastWritingDateTime': str(datetime.now()),
    'WriterProjectTitle': 'My PEA', 'WriterProjectID': 'pea-001',
}

mtp = MTPGenerator(writer_info, 'manifest_files/my_pea.aml', 'manifest_files/manifest_template.xml')
pea = OPCUAServerPEA(mtp, endpoint='opc.tcp://127.0.0.1:48050/')

service = MyService('my_service', 'Description of my service')
pea.add_service(service)

pea.run_opcua_server()   # builds nodes, writes manifest, starts server

while True:
    time.sleep(60)       # keep process alive
```

### 7.4 All Abstract State Methods

Every subclass of `Service` must implement exactly these 16 methods:

```python
idle, starting, execute, completing, completed,
pausing, paused, resuming,
holding, held, unholding,
stopping, stopped,
aborting, aborted,
resetting
```

Forgetting any one will raise `TypeError: Can't instantiate abstract class`.

---

## 8. Known Bugs in MTPPy

The following bugs exist in the MTPPy source code as cloned. Both require fixes before the framework works correctly.

---

### Bug 1 — Typo: `selt` instead of `self` in `state_machine.py`

**File:** `src/mtppy/state_machine.py`, line 114

**Symptom:** Calling `state_change()` from the `execute()` state raises:
```
NameError: name 'selt' is not defined. Did you mean: 'self'?
```
This means any self-completing procedure can never transition from EXECUTE to COMPLETING. The service gets stuck in EXECUTE forever.

**Broken code:**
```python
elif selt.act_state == StateCodes.execute:    # line 114
    self._change_state_to(StateCodes.completing)
```

**Fix:**
```python
elif self.act_state == StateCodes.execute:    # selt -> self
    self._change_state_to(StateCodes.completing)
```

**Status in this project:** Already fixed in the local clone.

---

### Bug 2 — Wrong state code for `resetting` in `state_codes.py`

**File:** `src/mtppy/state_codes.py`, lines 20 and 39

**Symptom:** The `resetting` state is assigned code `32678` instead of the correct `32768`. All other state codes follow the 2^n pattern:

```
stopped=4 (2^2), starting=8 (2^3), idle=16 (2^4), paused=32 (2^5),
execute=64 (2^6), stopping=128 (2^7), aborting=256 (2^8), aborted=512 (2^9),
holding=1024 (2^10), held=2048 (2^11), unholding=4096 (2^12),
pausing=8192 (2^13), resuming=16384 (2^14), resetting=32768 (2^15),  <- CORRECT
completing=65536 (2^16), completed=131072 (2^17)
```

`32678` is not a power of 2 — it is clearly a digit transposition typo (`768` -> `678`).

**Impact:** Any code that checks `StateCur == 32768` for the resetting state will never match. The state machine still transitions through resetting correctly (because it compares against the same wrong constant internally), but external clients reading `StateCur` and checking against the correct value `32768` will see a mismatch.

**Broken code:**
```python
self.resetting = 32678          # line 20
self.int_code[32678] = 'resetting'  # line 39
```

**Fix:**
```python
self.resetting = 32768          # 2^15
self.int_code[32768] = 'resetting'
```

**Status in this project:** NOT yet fixed — the local clone still has `32678`. Fix before using `resetting` state code in external client logic.

---

## 9. Water Heater Implementation Summary

### Files in this project

| File | Purpose |
|---|---|
| `water_tank.py` | Physical simulation — knows nothing about MTP or OPC UA |
| `heat_service.py` | `HeatService` — MTPPy Service subclass, all 16 states |
| `main.py` | Wires everything together, starts the OPC UA server |
| `manifest_files/manifest_template.xml` | AML skeleton (from MTPPy, do not edit) |
| `manifest_files/water_heater_manifest.aml` | Generated MTP manifest (created at runtime) |

### How to run

```bash
cd 6-Using_MTPPy_framework
python main.py
```

Server starts at `opc.tcp://127.0.0.1:48050/` and sits at IDLE.

### How to operate from UA Expert

1. Connect to `opc.tcp://127.0.0.1:48050/`
2. Set service to Operator mode — write `True` to:
   `ns=3;s=services.heat_service.op_src_mode.StateOpOp`
3. Set parameter to Operator mode — write `True` to:
   `ns=3;s=services.heat_service.procedures.default_heat.procedure_parameters.target_temp.op_src_mode.StateOpOp`
4. Write target temperature — write e.g. `50.0` to:
   `ns=3;s=services.heat_service.procedures.default_heat.procedure_parameters.target_temp.VOp`
5. Send START — write `4` to:
   `ns=3;s=services.heat_service.state_machine.CommandOp`
6. Watch temperature rise — read:
   `ns=3;s=services.heat_service.procedures.default_heat.report_values.current_temp.V`
7. After COMPLETED (StateCur = 131072), read results:
   `ns=3;s=services.heat_service.procedures.default_heat.process_value_outs.actual_temp.V`
   `ns=3;s=services.heat_service.procedures.default_heat.process_value_outs.time_to_reach.V`
8. Send RESET — write `2` to:
   `ns=3;s=services.heat_service.state_machine.CommandOp`

### Physics parameters (WaterTank)

| Parameter | Value | Meaning |
|---|---|---|
| `ambient_temp` | 20.0 °C | Room temperature (tank cools toward this) |
| `heater_power` | 2.0 °C/tick | Temperature rise per second when heater on |
| `cooling_rate` | 0.05 /tick | Fraction of (T - ambient) lost per second |
| Max reachable temp | ~60 °C | Equilibrium = ambient + power/rate = 20 + 2/0.05 |

Target temperatures above 60°C are not reachable with current physics — the heater will run indefinitely without completing.
