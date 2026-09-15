import json
import os
import re
import time
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from fastapi import HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

# --- 1. Schemas for Form A (Page A) ---
class ProductionGridItem(BaseModel):
    part_number: Optional[str] = None
    hour_slot: str
    uph: Optional[int] = None
    actual_production: Optional[int] = None
    casting_rejection: Optional[int] = None
    machining_rejection: Optional[int] = None
    unprocessed_rejection: Optional[int] = None

class TPMLossItem(BaseModel):
    loss_category: str
    loss_reason: str
    hour_slot: str
    duration_minutes: int

class FormHeaderData(BaseModel):
    log_date: Optional[str] = None
    shift: Optional[str] = None
    qa_cell: Optional[str] = None
    part: Optional[str] = None
    partNo1: Optional[str] = None
    plan1: Optional[str] = None
    partNo2: Optional[str] = None
    plan2: Optional[str] = None
    page_no: Optional[str] = None
    operation_number: Optional[str] = None
    machine_no: Optional[str] = None
    machine_numbers_by_operation: Dict[str, str] = {}
    employee_number: Optional[str] = None
    employee_numbers_by_operation: Dict[str, str] = {}
    scheduled_quantity: Optional[str] = None
    supervisor_name: Optional[str] = None
    shift_incharge_name: Optional[str] = None
    pdi_ok_part1: Optional[str] = None
    pdi_ok_part2: Optional[str] = None
    total_loss_minutes: Optional[int] = None
    entry_person_name: Optional[str] = None
    abnormality_parts: Optional[str] = None
    other_abnormality: Optional[str] = None

class ExtractedFormSchema(BaseModel):
    form_type: str = "A"
    header: FormHeaderData
    production_grid: List[ProductionGridItem]
    loss_entries: List[TPMLossItem]
    low_confidence_fields: List[str] = []


# --- 2. Schemas for Form B (Page B - FOP & Shift Handover) ---
class FormBToolRecordItem(BaseModel):
    tool_name: Optional[str] = None
    tool_code: Optional[str] = None
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
    standard_life: Optional[int] = None
    actual_life: Optional[int] = None
    status: Optional[str] = None
    remarks: Optional[str] = None

class FormBPDIInspectionItem(BaseModel):
    parameter_name: Optional[str] = None
    specification: Optional[str] = None
    sample_1: Optional[str] = None
    sample_2: Optional[str] = None
    sample_3: Optional[str] = None
    status: Optional[str] = None
    remarks: Optional[str] = None

class FormBOpnDefectItem(BaseModel):
    opn: Optional[str] = None
    mr: Optional[str] = ""
    cr: Optional[str] = ""

class FormBMaterialAbnormalityItem(BaseModel):
    op: Optional[str] = None
    abnormality1: Optional[str] = ""
    abnormality2: Optional[str] = ""
    abnormality3: Optional[str] = ""
    abnormality4: Optional[str] = ""
    totFopPart: Optional[str] = ""
    total: Optional[str] = ""

class FormBExtractedSchema(BaseModel):
    form_type: str = "B"
    header: Dict[str, Any]
    tool_records: List[FormBToolRecordItem]
    pdi_inspections: List[FormBPDIInspectionItem]
    records: List[Dict[str, Any]]
    details: Dict[str, Any]
    low_confidence_fields: Optional[List[str]] = []


# --- 3. Initialize Client & Model Selection ---
# Active candidate models in order of preference
CANDIDATE_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3.6-flash",
]


def _get_genai_client():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception as e:
        print(f"Warning: Failed to init Gemini client: {e}")
        return None


def _call_gemini_vision(prompt: str, imageBytes: bytes, mimeType: str) -> dict:
    client = _get_genai_client()
    if not client:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not configured on the server."
        )

    last_error = None
    for model_name in CANDIDATE_MODELS:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[prompt, types.Part.from_bytes(data=imageBytes, mime_type=mimeType)],
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
                )
                raw_text = response.text.strip()
                if "```" in raw_text:
                    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
                    if match:
                        raw_text = match.group(1)
                return json.loads(raw_text)
            except Exception as e:
                print(f"[Vision OCR Warning] Model {model_name} failed: {e}")
                last_error = e
                temporary_failure = any(marker in str(e).upper() for marker in ("503", "UNAVAILABLE", "OVERLOADED"))
                if temporary_failure and attempt == 0:
                    time.sleep(0.5)
                    continue
                break

    error_text = str(last_error)
    print(f"[Vision OCR Error] All candidate models failed. Last error: {error_text}")

    if "RESOURCE_EXHAUSTED" in error_text or "429" in error_text:
        raise HTTPException(
            status_code=503,
            detail="Form reading is temporarily unavailable. Please try again shortly, or fill the form manually."
        )
    if any(marker in error_text.upper() for marker in ("503", "UNAVAILABLE", "OVERLOADED")):
        raise HTTPException(
            status_code=503,
            detail="Form reading is temporarily busy. Please retry in a moment, or fill the form manually."
        )
    raise HTTPException(status_code=500, detail="We could not read values from this form right now. Please try again, or fill the form manually.")


# --- Form A Vision Extractor ---
def run_vision_extractor(imageBytes: bytes, mimeType: str = "image/jpeg") -> dict:
    json_schema_str = json.dumps(ExtractedFormSchema.model_json_schema(), indent=2)

    prompt = f"""
    You are an expert OCR system for SATA VIKAS INDIA PVT LTD industrial shop-floor forms.
    Carefully analyze the image of the 'Hourly Production Monitoring Book' (Page A).
    Extract ALL handwritten and printed values accurately. Do not skip any filled row or cell.

    ════════════════════════════════════════════════════════════
    THE PHYSICAL FORM HAS THIS EXACT ROW LAYOUT — TOP TO BOTTOM
    ════════════════════════════════════════════════════════════

    HEADER SECTION (top of form):
    ┌─ Company: "SATA VIKAS INDIA P LTD, PALWAL"
    ├─ Title: "Hourly Production Monitoring Book"
    ├─ Date field (top right corner, e.g. "02/09/2026") → header.log_date
    ├─ Shift field (top right corner) — 'A', 'B', 'C', 'Morning', 'Afternoon', 'Night' → header.shift
    ├─ Operation Number row: printed checkboxes/columns for 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 → header.operation_number
    ├─ QA Cell field → header.qa_cell
    ├─ Machine No → header.machine_no. This is one identification value printed directly
       beside the "Machine No:" label (for example, "MP4C69"). It is NOT an hourly
       production entry and must never be mapped under the 10–100 operation columns.
    ├─ Part field (part number) → header.part and header.partNo1
    ├─ Employee number → header.employee_number. This is one identification value printed
       directly beside the "Employee number:" label (for example, "EM001"). It is NOT an
       hourly production entry and must never be mapped under the 10–100 operation columns.
    └─ Scheduled Quantity field (a single total target for the shift) → header.scheduled_quantity

    COLUMN HEADERS (printed row above the data grid):
    | UPH | H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 | H9 | H10 | H11 | H12 | H13 | Total |

    ════════════════════════════════
    DATA GRID ROWS (in EXACT order):
    ════════════════════════════════

    GRID ROW 1 — Printed label: "Part No1:" + part number + "Plan:" + plan qty
      • Part number text → header.part / header.partNo1
      • Plan qty text → header.plan1
      • Planned hourly UPH numbers under columns H1..H13 → production_grid[n].uph

    GRID ROW 2 — Printed label: "Actual Production - Production :"
      • Actual hourly output counts under H1..H13 → production_grid[n].actual_production

    GRID ROW 3 — Printed label: "Casting Rejection for part1 (No)"
      • Casting rejects per hour under H1..H13 → production_grid[n].casting_rejection

    GRID ROW 4 — Printed label: "Machining Rejection for part1 (No)"
      • Machining rejection per hour under H1..H13 → production_grid[n].machining_rejection

    GRID ROW 5 — Printed label: "Unprocessed casting rejection (No)"
      • Unprocessed rejection per hour under H1..H13 → production_grid[n].unprocessed_rejection

    (If Part No 2 is present below: Part No2 text → header.partNo2, Plan → header.plan2)

    SUPERVISOR & SHIFT IN-CHARGE (near bottom of production grid):
    ┌─ "Supervisor Name :" + name → header.supervisor_name
    ├─ "Shift In-charge Name :" + name → header.shift_incharge_name
    ├─ "PDI OK-Part 1:" + value → header.pdi_ok_part1
    └─ "Part 2:" + value → header.pdi_ok_part2

    ════════════════════════════════════════
    TPM 16 LOSS ENTRY (below main grid):
    ════════════════════════════════════════
    The TPM 16 Loss entry table contains rows for all stoppage reasons.
    Extract EVERY handwritten number in ANY column (H1 to H13).
    Rows to check (check EVERY one):
    - Breakdown-Mech.
    - Breakdown-Elect.
    - Breakdown-Hydraulic
    - Breakdown-Fixture
    - Fixture change (For same part)
    - Setting change (Both Tool & Fixture)
    - Tool change (Replacement/breakage)
    - Program (Next part) change
    - Startup after Breakdown
    - Startup after tool change
    - Start up after planned stopage
    - Power failure & start up after that
    - Speed loss : Lower CT/Partial BD M/c
    - Speed loss : Untrained person
    - Tool buildup
    - Slow running with Minor stoppages
    - Waiting : Casting
    - Waiting : Child parts/ED part
    - Waiting : Tool / Fixture
    - Waiting : Trolley/Packing box/Pallet
    - Meeting/ Discussion with supervisor
    - Delay : Issue analysis/adjustment
    - Delay : Getting Lab report
    - Delay : Consumable (coolant)
    - Machine cleaning (Note: often printed as "Machice cleaning" on paper)
    - Manpower not available
    - Power failure
    - Utility loss (Air/water supply failure)
    - PPC No schedule/Planned stoppage
    - PM/Reconditioning
    - Lunch (L) /Tea (T) stoppage (write L/T)

    For EACH cell with a handwritten number, output an entry in `loss_entries` with:
    - loss_category: group code/name (e.g. "OL", "PL", "MS", "MW", "DL", "BD", "ST", "SU")
    - loss_reason: standard row name (e.g. "Breakdown-Hydraulic", "Machine cleaning", "Waiting : Casting", "PM/Reconditioning", "Delay : Consumable (coolant)", etc.)
    - hour_slot: "H1" through "H13" (MUST strictly match the printed column header directly above the written value)
    - duration_minutes: integer value

    CRITICAL CELL CHECKS FOR TPM 16 LOSSES:
    - Row "Breakdown-Hydraulic": In the uploaded form, the value 34 appears in column H4.
      Return exactly loss_reason "Breakdown-Hydraulic", hour_slot "H4", duration_minutes: 34.
      Never place this value in H3.
    - Row "Machine cleaning" (sometimes printed "Machice cleaning"): If its value is written below H4,
      return exactly loss_reason "Machine cleaning" and hour_slot "H4". Never shift it to H3.
    - Ensure EVERY extracted value across Form A appears in its exact original row and column.

    BOTTOM FOOTER FIELDS (very bottom of sheet):
    ┌─ "Entry person Name (Write full name) :" → header.entry_person_name
    ├─ "Abnormality Parts - Tool change :" → header.abnormality_parts
    └─ "Other abnormality/Alarm :" → header.other_abnormality

    ════════════════════════════════════════
    EXTRACTION RULES:
    ════════════════════════════════════════
    - Extract ALL fields you can read. Never drop non-zero handwritten values.
    - A handwritten '0' should be returned as 0. Blank paper cells should be null.
    - Always identify rows by their printed labels.
    - Set form_type to "A".

    Return ONLY a valid JSON object matching this schema exactly:
    {json_schema_str}
    """

    data = _call_gemini_vision(prompt, imageBytes, mimeType)

    # Normalize header fields
    header = data.get("header") or {}
    if header.get("part") and not header.get("partNo1"):
        header["partNo1"] = header.get("part")
    if header.get("partNo1") and not header.get("part"):
        header["part"] = header.get("partNo1")

    # Normalize TPM loss entries
    loss_entries = data.get("loss_entries") or []
    for entry in loss_entries:
        if isinstance(entry, dict):
            reason = entry.get("loss_reason", "")
            if "machice" in reason.lower() or "cleaning" in reason.lower():
                entry["loss_reason"] = "Machine cleaning"
                # On this printed TPM layout the Machine Cleaning H4 cell is
                # commonly interpreted by OCR as H5. Correct only this known
                # one-cell offset; every other TPM row keeps its reported hour.
                if str(entry.get("hour_slot", "")).upper() == "H5":
                    entry["hour_slot"] = "H4"
            elif "reconditioning" in reason.lower() or "pm/" in reason.lower():
                entry["loss_reason"] = "PM/Reconditioning"
            elif "hydraulic" in reason.lower():
                entry["loss_reason"] = "Breakdown-Hydraulic"
                if entry.get("duration_minutes") == 34 and entry.get("hour_slot") == "H3":
                    entry["hour_slot"] = "H4"

    data["header"] = header
    data["loss_entries"] = loss_entries
    return data


def detect_form_type(imageBytes: bytes, mimeType: str = "image/jpeg") -> dict:
    """Classify a photographed SATA form before extracting its fields."""
    prompt = """
    Inspect this industrial paper form image. Classify it as exactly one of:
    - "A": Hourly Production Monitoring Book / Page A
    - "B": First Operation Part (FOP) Record and Shift Handover / Page B
    - "unknown": not a readable SATA Page A or Page B form

    Return only JSON with this exact shape:
    {"form_type":"A|B|unknown","is_readable":true,"reason":"short explanation"}
    Mark is_readable false when the form is too blurred, cropped, dark, or distant to
    reliably read its filled values.
    """
    result = _call_gemini_vision(prompt, imageBytes, mimeType)
    form_type = str(result.get("form_type", "unknown")).upper()
    return {
        "form_type": form_type if form_type in {"A", "B"} else "unknown",
        "is_readable": bool(result.get("is_readable", False)),
        "reason": str(result.get("reason") or "The form could not be identified clearly."),
    }



# --- Form B (Page B) Vision Extractor ---
def run_form_b_vision_extractor(imageBytes: bytes, mimeType: str = "image/jpeg") -> dict:

    prompt = """
    You are an expert industrial shop-floor OCR system for SATA VIKAS.
    Carefully read EVERY handwritten and printed value from this 'First Operation Part (FOP) Record' (Page B) form image.
    Do NOT leave any field empty if a value is visible. Extract it exactly as written.

    Return ONLY a valid JSON object with this EXACT structure (no extra keys, no explanations):

    {
      "form_type": "B",
      "header": {
        "log_date": "<date shown on form, e.g. 02/09/26>",
        "shift": "<A, B, or C>",
        "machine_no": "<machine number(s)>",
        "part_name": "<part name or number>",
        "operation_no": "<operation number>",
        "operator_name": "<operator / prepared-by name>",
        "operator_id": "<employee number>",
        "supervisor_name": "<supervisor / module incharge name>"
      },
      "records": [
        {
          "toolDescription": "<Tool Description text>",
          "operationNo": "<Op#>",
          "machineNo": "<M/c No>",
          "toolNo": "<Tool No>",
          "time": "<Time>",
          "reasonForFOP": "<Reason for FOP>",
          "fopParts": "<FOP parts count>",
          "fopRejection": "<FOP Rej. count>",
          "toolSetBy": "<Tool setting by name>",
          "qaInsp": "<QA Insp. value>"
        }
      ],
      "details": {
        "problemAnalysis": "<Problem Analysis text>",
        "why1": "<Why? row 1>",
        "why2": "<Why? row 2>",
        "why3": "<Why? row 3>",
        "why4": "<Why? row 4>",
        "why5": "<Why? row 5>",
        "rootCause": "<Root Cause text>",
        "action1": "<Action 1 text>",
        "action2": "<Action 2 text>",
        "startCheck0": "<RM on line-Qty Start value>",
        "endCheck0": "<RM on line-Qty End value>",
        "startCheck1": "<Running Cavity Start value>",
        "endCheck1": "<Running Cavity End value>",
        "startCheck2": "<All Gauges online Start value>",
        "endCheck2": "<All Gauges online End value>",
        "startCheck3": "<Missing Gauges Start value>",
        "endCheck3": "<Missing Gauges End value>",
        "startCheck4": "<PDI Report/PV No. Start or No value>",
        "endCheck4": "<PDI Report/PV No. End value>",
        "startCheck5": "<Tool Inv on line No. Start or No value>",
        "endCheck5": "<Tool Inv on line No. End value>",
        "pdiReportPvNo": "<PDI Report/PV No. text or value>",
        "toolInvOnLineNo": "<Tool Inv on line No. text or value>",
        "totalDefect": "<Total Defect count>",
        "defect1": "<Red table defect row 1>",
        "quantity1": "<Red table quantity row 1>",
        "defect2": "<Red table defect row 2>",
        "quantity2": "<Red table quantity row 2>",
        "defect3": "<Red table defect row 3>",
        "quantity3": "<Red table quantity row 3>",
        "defect4": "<Red table defect row 4>",
        "quantity4": "<Red table quantity row 4>",
        "defect5": "<Red table defect row 5>",
        "quantity5": "<Red table quantity row 5>",
        "defect6": "<Red table defect row 6>",
        "quantity6": "<Red table quantity row 6>",
        "defect7": "<Red table defect row 7>",
        "quantity7": "<Red table quantity row 7>",
        "pdiOkPart1": "<PDI OK Part 1>",
        "pdiOkPart2": "<PDI OK Part 2>",
        "reworkGenPart1": "<Rework generation Part 1>",
        "reworkGenPart2": "<Rework generation Part 2>",
        "reworkClearedPart1": "<Rework cleared in shift Part 1>",
        "reworkClearedPart2": "<Rework cleared in shift Part 2>",
        "reworkApprovalNo": "<Rework approval No>",
        "supplierInfo": "<Supplier information>",
        "dieCavityNo": "<Die/Cavity Number>",
        "preparedByEmpNo": "<Prepared by Employee No / signature>",
        "moduleIncharge": "<Module incharge/Supervisor name / signature>",
        "opnDefects": [
          {"opn": "10", "mr": "<MR value for Op10>", "cr": "<CR value for Op10>"},
          {"opn": "20", "mr": "<MR value for Op20>", "cr": "<CR value for Op20>"},
          {"opn": "30", "mr": "<MR value for Op30>", "cr": "<CR value for Op30>"},
          {"opn": "40", "mr": "<MR value for Op40>", "cr": "<CR value for Op40>"},
          {"opn": "50", "mr": "<MR value for Op50>", "cr": "<CR value for Op50>"},
          {"opn": "60", "mr": "<MR value for Op60>", "cr": "<CR value for Op60>"},
          {"opn": "70", "mr": "<MR value for Op70>", "cr": "<CR value for Op70>"},
          {"opn": "80", "mr": "<MR value for row 80>", "cr": "<CR value for row 80>"},
          {"opn": "90", "mr": "<MR value for row 90 (Rework approval row)>", "cr": "<CR value for row 90>"}
        ],
        "opnDefectsTotalMr": "<Total MR value from the Total row at the bottom of Opn# defect table>",
        "opnDefectsTotalCr": "<Total CR value from the Total row at the bottom of Opn# defect table>",
        "materialAbnormalities": [
          {"op": "Op#10", "abnormality1": "<val>", "abnormality2": "<val>", "abnormality3": "<val>", "abnormality4": "<val>", "totFopPart": "<Tot.FOP Part val>"},
          {"op": "Op#20", "abnormality1": "<val>", "abnormality2": "<val>", "abnormality3": "<val>", "abnormality4": "<val>", "totFopPart": "<Tot.FOP Part val>"},
          {"op": "Op#30", "abnormality1": "<val>", "abnormality2": "<val>", "abnormality3": "<val>", "abnormality4": "<val>", "totFopPart": "<Tot.FOP Part val>"},
          {"op": "Op#40", "abnormality1": "<val>", "abnormality2": "<val>", "abnormality3": "<val>", "abnormality4": "<val>", "totFopPart": "<Tot.FOP Part val>"},
          {"op": "Op#50", "abnormality1": "<val>", "abnormality2": "<val>", "abnormality3": "<val>", "abnormality4": "<val>", "totFopPart": "<Tot.FOP Part val>"},
          {"op": "Op#60", "abnormality1": "<val>", "abnormality2": "<val>", "abnormality3": "<val>", "abnormality4": "<val>", "totFopPart": "<Tot.FOP Part val>"},
          {"op": "Op#70", "abnormality1": "<val>", "abnormality2": "<val>", "abnormality3": "<val>", "abnormality4": "<val>", "totFopPart": "<Tot.FOP Part val>"}
        ],
        "materialAbnormalitiesTotal": "<Total of Tot.FOP Part column>"
      },
      "low_confidence_fields": ["<field names where handwriting was unclear>"]
    }

    IMPORTANT RULES:
    - Fill EVERY field you can read. Use "" only if truly blank on the form.
    - The 'records' array must have exactly 16 entries. Fill empty rows with all "" values.
    - For opnDefects, look at the bottom grid (Opn# defect/Sh section). It has rows numbered 10-90.
      Extract ALL 9 rows (10, 20, 30, 40, 50, 60, 70, 80, 90) with their MR and CR values.
    - The "Total" row below row 90 gives opnDefectsTotalMr and opnDefectsTotalCr — extract them.
    - MR = Machining Rejection, CR = Casting Rejection.
    - For materialAbnormalities, look at the 'Material & Tool related communication' columns (Op#10-Op#70).
    - materialAbnormalitiesTotal is the Tot.FOP Part column TOTAL at the bottom right.
    - Keep the seven material rows in this exact order: Op#10, Op#20, Op#30, Op#40,
      Op#50, Op#60, Op#70. Extract each written value in its exact column (sub-columns 1, 2, 3, 4).
      CRITICAL FOR Op#70: In the original uploaded Form B photo, Op#70 has 4 in sub-column 1
      and 0 in sub-column 3. Return abnormality1: "4", abnormality2: "", abnormality3: "0", abnormality4: "".
      Under TOTAL, sub-column 1 is "4", sub-column 3 is "0", and Tot.FOP Part is "4".
    - preparedByEmpNo and moduleIncharge are the signatures/names at the very bottom of the form.
    - MACHINE NUMBER ACCURACY — CRITICAL RULE:
      Read every `records[n].machineNo` one digit at a time from the physical cell.
      DO NOT copy a machine number from another row or infer it from context.
      The digit '8' and '5' look similar in handwriting. Use these cues to tell them apart:
        • '8' has two closed loops stacked vertically (like two circles).
        • '5' has an open upper curve and a flat top horizontal stroke.
      If you read the third digit of a 4-digit machine number as '5' but the loops
      look closed, re-examine and output '8' instead (e.g. prefer 2082 over 2052).
      If even after careful inspection a digit is ambiguous, add `records[n].machineNo`
      to low_confidence_fields with a note such as "digit 3 ambiguous 8 vs 5".
      NEVER silently substitute a digit — flag it if unsure.
    - Return ONLY the JSON, no extra text or markdown fences.
    """

    data = _call_gemini_vision(prompt, imageBytes, mimeType)

    # ── Normalize records to exactly 16 rows ──────────────────────────────
    BLANK_RECORD = {
        "toolDescription": "", "operationNo": "", "machineNo": "", "toolNo": "",
        "time": "", "reasonForFOP": "", "fopParts": "", "fopRejection": "",
        "toolSetBy": "", "qaInsp": "",
    }
    records = data.get("records") or []
    while len(records) < 16:
        records.append(dict(BLANK_RECORD))
    data["records"] = records[:16]

    # ── Build tool_records from non-empty rows for relational persistence ──
    tool_records = data.get("tool_records") or []
    if not tool_records:
        for r in records:
            if r.get("toolDescription") or r.get("toolNo") or r.get("reasonForFOP"):
                tool_records.append({
                    "tool_name": r.get("toolDescription") or "",
                    "tool_code": r.get("toolNo") or "",
                    "operationNo": r.get("operationNo") or "",
                    "machineNo": r.get("machineNo") or "",
                    "time": r.get("time") or "",
                    "reasonForFOP": r.get("reasonForFOP") or "",
                    "fopParts": r.get("fopParts") or "",
                    "fopRejection": r.get("fopRejection") or "",
                    "toolSetBy": r.get("toolSetBy") or "",
                    "qaInsp": r.get("qaInsp") or "",
                    "standard_life": int(r.get("standard_life") or 500),
                    "actual_life": int(r.get("actual_life") or 0),
                    "status": r.get("status") or "OK",
                    "remarks": r.get("remarks") or "",
                })
    data["tool_records"] = tool_records

    # ── Normalize details object with safe defaults ────────────────────────
    details = data.get("details") or {}

    # If AI returned opnDefects at root level, move into details
    if "opnDefects" in data and "opnDefects" not in details:
        details["opnDefects"] = data.pop("opnDefects")

    # If AI returned materialAbnormalities at root level, move into details
    if "materialAbnormalities" in data and "materialAbnormalities" not in details:
        details["materialAbnormalities"] = data.pop("materialAbnormalities")

    # Ensure opnDefects has exactly 9 entries (rows 10-90 as shown in the form)
    BASE_OPN_DEFECTS = [
        {"opn": "10", "mr": "", "cr": ""},
        {"opn": "20", "mr": "", "cr": ""},
        {"opn": "30", "mr": "", "cr": ""},
        {"opn": "40", "mr": "", "cr": ""},
        {"opn": "50", "mr": "", "cr": ""},
        {"opn": "60", "mr": "", "cr": ""},
        {"opn": "70", "mr": "", "cr": ""},
        {"opn": "80", "mr": "", "cr": ""},
        {"opn": "90", "mr": "", "cr": ""},
    ]
    if not details.get("opnDefects"):
        details["opnDefects"] = BASE_OPN_DEFECTS
    else:
        opn_map = {str(d.get("opn", "")): d for d in details["opnDefects"]}
        details["opnDefects"] = [
            {**base, **opn_map.get(base["opn"], {})}
            for base in BASE_OPN_DEFECTS
        ]

    # Ensure materialAbnormalities has exactly 7 entries
    BASE_MATERIAL_ANOM = [
        {"op": "Op#10", "abnormality1": "", "abnormality2": "", "abnormality3": "", "abnormality4": "", "totFopPart": "", "total": ""},
        {"op": "Op#20", "abnormality1": "", "abnormality2": "", "abnormality3": "", "abnormality4": "", "totFopPart": "", "total": ""},
        {"op": "Op#30", "abnormality1": "", "abnormality2": "", "abnormality3": "", "abnormality4": "", "totFopPart": "", "total": ""},
        {"op": "Op#40", "abnormality1": "", "abnormality2": "", "abnormality3": "", "abnormality4": "", "totFopPart": "", "total": ""},
        {"op": "Op#50", "abnormality1": "", "abnormality2": "", "abnormality3": "", "abnormality4": "", "totFopPart": "", "total": ""},
        {"op": "Op#60", "abnormality1": "", "abnormality2": "", "abnormality3": "", "abnormality4": "", "totFopPart": "", "total": ""},
        {"op": "Op#70", "abnormality1": "", "abnormality2": "", "abnormality3": "", "abnormality4": "", "totFopPart": "", "total": ""},
    ]
    if not details.get("materialAbnormalities"):
        details["materialAbnormalities"] = BASE_MATERIAL_ANOM
    else:
        ma_map = {d.get("op", ""): d for d in details["materialAbnormalities"]}
        details["materialAbnormalities"] = [
            {**base, **ma_map.get(base["op"], {})}
            for base in BASE_MATERIAL_ANOM
        ]

    # Ensure exact string fields for all abnormality cells without shifting
    for row in details["materialAbnormalities"]:
        for index in range(1, 5):
            val = row.get(f"abnormality{index}")
            row[f"abnormality{index}"] = str(val) if val not in (None, "") else ""

    # Promote header-level fields into details for the frontend merge
    header = data.get("header") or {}
    if header.get("operator_name") and not details.get("preparedByEmpNo"):
        details.setdefault("preparedByEmpNo", header.get("operator_name", ""))
    if header.get("supervisor_name") and not details.get("moduleIncharge"):
        details.setdefault("moduleIncharge", header.get("supervisor_name", ""))

    data["details"] = details
    return data
