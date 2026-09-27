"""
generate_mtp.py — generate a Recipol-ready MTP (.aml) for the VisionForge PEA.

Auto-discovers every task/plugin service.py (each = one MTP service), builds them
into one OPCUAServerPEA with an MTPGenerator, exports the manifest, then applies the
two edits Recipol needs (CAEX default namespace + service hierarchy named "Services").

Run with the VisionForge app CLOSED (it binds localhost:48050 briefly to export).

Output: VisionForge/artifacts/visionforge.aml  (Recipol-ready)
        VisionForge/artifacts/visionforge_raw.aml  (raw MTPPy output, for reference)
"""
import glob
import importlib.util
import os
import re
import sys
from datetime import datetime

# ── Paths (derived from this file's location) ────────────────────────────────
ARTIFACTS   = os.path.dirname(os.path.abspath(__file__))
VF_DIR      = os.path.dirname(ARTIFACTS)                     # ...\VisionForge
PROJECT_ROOT = os.path.dirname(VF_DIR)                       # ...\Project1_...
MTPPY_ROOT  = os.path.join(PROJECT_ROOT, "VDI_VDE_NAMUR_2658", "MTPPy")
MTPPY_SRC   = os.path.join(MTPPY_ROOT, "src")
TEMPLATE    = os.path.join(MTPPY_ROOT, "manifest_files", "manifest_template.xml")

RAW_AML     = os.path.join(ARTIFACTS, "visionforge_raw.aml")
FINAL_AML   = os.path.join(ARTIFACTS, "visionforge.aml")

ENDPOINT    = "opc.tcp://localhost:48050/"   # where VisionForge actually serves
MODULE_NAME = "VisionForge"
NS_URI      = "urn:visionforge:pea"          # MUST match register_namespace(...) in MTPPy

sys.path.insert(0, PROJECT_ROOT)   # so `import VisionForge...` resolves
sys.path.insert(0, MTPPY_SRC)      # so `import mtppy` resolves

# ── Headless Qt (services subclass QObject) ──────────────────────────────────
from PySide6.QtCore import QCoreApplication
_app = QCoreApplication.instance() or QCoreApplication([])

from mtppy.opcua_server_pea import OPCUAServerPEA
from mtppy.mtp_generator import MTPGenerator
from VisionForge.app.inspection.inspection_service import InspectionService

# ── Runtime fix (MTPPy left untouched) ───────────────────────────────────────
# MTPGenerator.create_instance classifies a data assembly via __bases__[-1],
# which assumes a service inherits DIRECTLY from mtppy Service. VisionForge's
# services go through an extra InspectionService layer, so the naive check fails.
# Resolve the basic type by scanning the MRO for a recognized SUC base instead.
_RECOGNIZED = {"Service", "SUCServiceProcedure", "SUCOperationElement",
               "SUCIndicatorElement", "SUCActiveElement"}
def _create_instance_mro(self, data_assembly, opc_node_id):
    instance_id = self.random_id_generator()
    instance_name = opc_node_id.split("=")[-1]
    basic = next((c.__name__ for c in type(data_assembly).__mro__ if c.__name__ in _RECOGNIZED),
                 type(data_assembly).__bases__[-1].__name__)
    return self.add_data_assembly_to_instance_list(
        instance_name, instance_id, basic, type(data_assembly).__name__)
MTPGenerator.create_instance = _create_instance_mro


def discover_service_files():
    """Every service.py under app/tasks/* and plugins/* (each is one MTP service)."""
    files = []
    files += glob.glob(os.path.join(VF_DIR, "app", "tasks", "*", "service.py"))
    files += glob.glob(os.path.join(VF_DIR, "plugins", "*", "service.py"))
    return sorted(files)


def load_service_instances(files):
    """Load each service.py, find its InspectionService subclass, instantiate it."""
    instances = []
    for i, path in enumerate(files):
        spec = importlib.util.spec_from_file_location(f"_vf_svc_{i}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = next(
            (v for v in vars(mod).values()
             if isinstance(v, type)
             and issubclass(v, InspectionService)
             and v is not InspectionService),
            None,
        )
        if cls is None:
            print(f"    [skip] no InspectionService subclass in {path}")
            continue
        svc = cls()   # VisionForge instantiates services with no args
        instances.append((svc, path))
        print(f"    [ok]   {svc.tag_name:26} <- {os.path.relpath(path, VF_DIR)}")
    return instances


def apply_recipol_fixes(text):
    """Two edits so Recipol's CAEX-3.0 parser accepts the MTPPy CAEX-2.15 output."""
    # 1. default CAEX namespace on the root (+ bump schema version cosmetically)
    text = text.replace("<CAEXFile ", '<CAEXFile xmlns="http://www.dke.de/CAEX" ', 1)
    text = text.replace('SchemaVersion="2.15"', 'SchemaVersion="3.0"', 1)
    # 2. service InstanceHierarchy: MTPPy gives it a random Name==ID; Recipol needs "Services"
    text, n = re.subn(r'<InstanceHierarchy Name="([^"]+)" ID="\1">',
                      r'<InstanceHierarchy Name="Services" ID="\1">', text)
    # 3. Namespace: Recipol resolves it as a URI via get_namespace_index(), so the .aml
    #    must carry the URI (not the numeric index). Must match register_namespace() in MTPPy.
    text = re.sub(
        r'(<Attribute Name="Namespace"[^>]*>(?:\s*<Description>.*?</Description>)?)\s*<Value>[^<]*</Value>',
        rf'\1<Value>{NS_URI}</Value>', text, flags=re.DOTALL)
    # 4. Identifiers: Recipol prepends "ns={resolved};s=" itself, so strip MTPPy's ns=N;s= prefix -> bare
    text = re.sub(r'<Value>ns=\d+;s=([^<]*)</Value>', r'<Value>\1</Value>', text)
    # 5. cosmetic: give the module a readable name
    text = text.replace('Name="mtp_test"', f'Name="{MODULE_NAME}"')
    return text, n


if __name__ == "__main__":
    print(f"[1] discovering services under {VF_DIR} ...")
    files = discover_service_files()
    if not files:
        sys.exit("No service.py found under app/tasks or plugins.")
    services = load_service_instances(files)
    if not services:
        sys.exit("No InspectionService subclasses instantiated.")

    print(f"\n[2] building MTP generator (template: {os.path.exists(TEMPLATE)})")
    writer_info = {
        "WriterName": "tud/plt", "WriterID": "tud/plt", "WriterVendor": "tud",
        "WriterVendorURL": "www.tud.de", "WriterVersion": "1.0.0", "WriterRelease": "",
        "LastWritingDateTime": str(datetime.now()),
        "WriterProjectTitle": "VisionForge", "WriterProjectID": "",
    }
    gen = MTPGenerator(writer_info, RAW_AML, TEMPLATE)
    pea = OPCUAServerPEA(mtp_generator=gen, endpoint=ENDPOINT)
    for svc, _ in services:
        pea.add_service(svc)

    print(f"[3] exporting manifest via run_opcua_server() ...")
    pea.run_opcua_server()          # builds nodes + writes RAW_AML
    try:
        pea.opcua_server.stop()
    except Exception:
        pass
    print(f"    raw  -> {RAW_AML}  exists={os.path.exists(RAW_AML)}")

    print(f"[4] applying Recipol fixes ...")
    with open(RAW_AML, "r", encoding="utf-8") as f:
        text = f.read()
    text, n = apply_recipol_fixes(text)
    with open(FINAL_AML, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"    renamed {n} hierarchy to 'Services'")
    print(f"    final -> {FINAL_AML}")
    print(f"\nDONE. {len(services)} service(s), endpoint {ENDPOINT}")
    sys.stdout.flush()
    os._exit(0)   # server threads are non-daemon; force-exit now that files are written
