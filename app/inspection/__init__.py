"""
VisionForge MTP Inspection Module.

Exposes VisionForge as a VDI/VDE/NAMUR 2658-compliant PEA via OPC UA.
Each task with a service.py gets an MTP service registered in the shared server.
"""
from VisionForge.app.inspection.inspection_service import InspectionService
from VisionForge.app.inspection.inspection_module  import InspectionModule

__all__ = ["InspectionService", "InspectionModule"]
