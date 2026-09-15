from pydantic import BaseModel
from typing import List, Optional

# 1. Hourly Grid Row Schema
class HourlyEntrySchema(BaseModel):
    part_number: Optional[str] = None
    hour_slot: str
    uph: Optional[int] = 0
    actual_production: Optional[int] = 0
    casting_rejection: Optional[int] = 0
    machining_rejection: Optional[int] = 0
    unprocessed_rejection: Optional[int] = 0

# 2. TPM Loss Row Schema
class TPMLossSchema(BaseModel):
    loss_category: Optional[str] = None
    loss_reason: Optional[str] = None
    hour_slot: str
    duration_minutes: Optional[int] = 0

# 3. Main Form A Payload Schema (Extraction response ke sath exact match)
class FormASaveSchema(BaseModel):
    log_date: Optional[str] = None
    shift: Optional[str] = None
    qa_cell: Optional[str] = None
    operation_number: Optional[str] = None
    machine_no: Optional[str] = None
    employee_number: Optional[str] = None
    supervisor_name: Optional[str] = None
    shift_incharge_name: Optional[str] = None
    pdi_ok_part1: Optional[str] = None
    pdi_ok_part2: Optional[str] = None
    entry_person_name: Optional[str] = None
    abnormality_parts: Optional[str] = None
    other_abnormality: Optional[str] = None
    image_path: Optional[str] = None

    production_grid: List[HourlyEntrySchema] = []
    loss_entries: List[TPMLossSchema] = []
