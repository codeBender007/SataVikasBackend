from typing import List, Optional, Any, Dict
from pydantic import BaseModel


class ToolRecordItemSchema(BaseModel):
    tool_name: Optional[str] = None
    tool_code: Optional[str] = None
    standard_life: Optional[int] = None
    actual_life: Optional[int] = None
    status: Optional[str] = None
    remarks: Optional[str] = None
    # Extended Form B FOP fields
    toolDescription: Optional[str] = None
    operationNo: Optional[str] = None
    machineNo: Optional[str] = None
    toolNo: Optional[str] = None
    time: Optional[str] = None
    reasonForFOP: Optional[str] = None
    fopParts: Optional[str] = None
    fopRejection: Optional[str] = None
    toolSetBy: Optional[str] = None
    qaInsp: Optional[str] = None
    quantity: Optional[str] = None
    totFopPart: Optional[str] = None
    handoverCheck: Optional[str] = None
    defect: Optional[str] = None
    materialOrTool: Optional[str] = None


class PDIInspectionItemSchema(BaseModel):
    parameter_name: Optional[str] = None
    specification: Optional[str] = None
    sample_1: Optional[str] = None
    sample_2: Optional[str] = None
    sample_3: Optional[str] = None
    status: Optional[str] = None
    remarks: Optional[str] = None


class FormBSaveSchema(BaseModel):
    log_date: Optional[str] = None
    shift: Optional[str] = None
    machine_no: Optional[str] = None
    part_name: Optional[str] = None
    operation_no: Optional[str] = None
    operator_name: Optional[str] = None
    operator_id: Optional[str] = None
    supervisor_name: Optional[str] = None
    handover_notes: Optional[str] = None
    image_path: Optional[str] = None
    total_defect: Optional[str] = None
    tool_records: Optional[List[ToolRecordItemSchema]] = []
    pdi_inspections: Optional[List[PDIInspectionItemSchema]] = []
    # Full frontend records and details for exact paper-replica fidelity
    records: Optional[List[Dict[str, Any]]] = None
    details: Optional[Dict[str, Any]] = None
