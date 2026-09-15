import json
import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Query, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Optional, List
from sqlalchemy.orm import Session
from models.userModels import User
from models.productionModels import ProductionLog, HourlyProductionEntry, TPMLossEntry
from models.formBModels import Form2HandoverLog, Form2ToolRecord, Form2PDIInspectionRecord
from database.db import engine, Base, get_db
from pydantic import BaseModel
from schemas.loginSceham import LoginSchema
from schemas.formASchema import FormASaveSchema
from schemas.formBSchema import FormBSaveSchema
from schemas.jwtSchema import jwtSchema
from schemas.userSchema import userSchema, UserUpdateSchema
from utility.auth import create_access_token
from utility.dependancies import get_current_admin, get_current_user
from passlib.context import CryptContext
from services.visionExtractor import run_vision_extractor, run_form_b_vision_extractor

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')

# Automatically create all tables (Form A, Form B, Users) on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="SATA VIKAS Shop-Floor Digitization API")

# Add CORS Middleware to allow requests from frontend dev servers & web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keep the original paper form with the record so it can be reviewed later.
UPLOAD_DIRECTORY = os.path.join(os.path.dirname(__file__), "uploads", "forms")
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "uploads")), name="uploads")


def _save_form_photo(image_bytes: bytes, content_type: str) -> str:
    extension = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png"}.get(content_type, ".jpg")
    filename = f"{uuid.uuid4().hex}{extension}"
    with open(os.path.join(UPLOAD_DIRECTORY, filename), "wb") as photo:
        photo.write(image_bytes)
    return f"/uploads/forms/{filename}"


def _image_mime_type(file: UploadFile) -> str:
    """Browsers normally send image/jpeg; some camera/file clients use octet-stream."""
    if file.content_type in {"image/jpeg", "image/jpg", "image/png"}:
        return "image/jpeg" if file.content_type == "image/jpg" else file.content_type
    filename = (file.filename or "").lower()
    return "image/png" if filename.endswith(".png") else "image/jpeg"


def _read_and_validate_form(image_bytes: bytes, content_type: str, expected_form_type: str) -> tuple[dict, str, dict]:
    extracted = run_vision_extractor(image_bytes, content_type) if expected_form_type == "A" else run_form_b_vision_extractor(image_bytes, content_type)
    detected_type = str(extracted.get("form_type") or "unknown").upper()
    detection = {"form_type": detected_type if detected_type in {"A", "B"} else "unknown", "is_readable": True, "reason": ""}
    if detection["form_type"] in {"A", "B"} and detection["form_type"] != expected_form_type:
        expected_name = f"Page {expected_form_type}"
        detected_name = f"Page {detection['form_type']}"
        raise HTTPException(status_code=422, detail=f"This upload appears to be {detected_name}, not {expected_name}. Please upload the matching form.")

    image_path = _save_form_photo(image_bytes, content_type)
    return extracted, image_path, detection


# Base health route
@app.get('/')
def root():
    return {"message": "Welcome to SATA VIKAS Shop-Floor Digitization Backend!", "status": "online"}


# ─── 1. AUTHENTICATION ────────────────────────────────────────
@app.post('/api/login', response_model=jwtSchema)
@app.post('/login', response_model=jwtSchema)
def login(request: LoginSchema, db: Session = Depends(get_db)):
    raw_user = request.username.strip() if request.username else ""
    print(f"[AUTH] Login attempt received for username/email: '{raw_user}'")

    if not raw_user or not request.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Username and password are required'
        )

    # Search by exact username, case-insensitive username, or email
    user = db.query(User).filter(
        (User.username == raw_user) |
        (User.username.ilike(raw_user)) |
        (User.email.ilike(raw_user))
    ).first()

    if not user:
        print(f"[AUTH] FAILED: User '{raw_user}' does not exist in database.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid Credentials: User not found'
        )

    # Check active status: Active accounts allowed, inactive/suspended accounts blocked
    if user.status and user.status.strip().lower() in ['inactive', 'suspended', 'disabled', 'false']:
        print(f"[AUTH] BLOCKED: User '{user.username}' is {user.status}.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f'Account is {user.status}. Please contact an administrator.'
        )

    # Password verification with bcrypt & automatic self-healing upgrade for legacy entries
    is_valid_password = False
    try:
        is_valid_password = pwd_context.verify(request.password, user.password)
    except Exception as verify_err:
        print(f"[AUTH] Password verify exception (evaluating plaintext fallback): {verify_err}")
        if user.password == request.password:
            is_valid_password = True
            # Upgrade plaintext to bcrypt
            user.password = pwd_context.hash(request.password)
            db.commit()

    if not is_valid_password:
        if user.password == request.password:
            is_valid_password = True
            user.password = pwd_context.hash(request.password)
            db.commit()

    if not is_valid_password:
        print(f"[AUTH] FAILED: Incorrect password for user '{user.username}'.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid Credentials: Password incorrect'
        )

    token_payload = {
        'sub': user.username,
        'employee_id': user.employee_id,
        'role': user.role
    }

    jwt_token = create_access_token(data=token_payload)
    print(f"[AUTH] SUCCESS: User '{user.username}' ({user.role}) authenticated successfully.")

    return {
        'access_token': jwt_token,
        'token_type': 'bearer',
        'role': user.role,
        'employee_id': user.employee_id,
        'username': user.username,
        'full_name': user.full_name or user.username,
        'email': user.email,
        'department': user.department or 'Production',
        'designation': user.designation,
        'status': user.status or 'Active'
    }


# ─── 2. USER MANAGEMENT ──────────────────────────────────────
@app.post('/api/createuser')
@app.post('/createuser')
@app.post('/api/users')
def createUser(request: userSchema, db: Session = Depends(get_db), admin_user: User = Depends(get_current_admin)):
    exist_user = db.query(User).filter(
        (User.employee_id == request.employee_id) |
        (User.email == request.email) |
        (User.username == request.username)
    ).first()

    if exist_user:
        if exist_user.employee_id == request.employee_id:
            msg = "Employee ID Already Exists."
        elif exist_user.email == request.email:
            msg = "Email Already Exists."
        else:
            msg = "Username Already Exists."

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    hashedPassword = pwd_context.hash(request.password)

    newUser = User(
        employee_id=request.employee_id,
        full_name=request.full_name or request.username,
        username=request.username,
        email=request.email,
        password=hashedPassword,
        role=request.role or "employee",
        designation=request.designation,
        department=request.department or "Production",
        status=request.status or "Active"
    )

    db.add(newUser)
    db.commit()
    db.refresh(newUser)

    return {
        "Message": "User Created Successfully.",
        "employee_id": newUser.employee_id,
        "username": newUser.username,
        "full_name": newUser.full_name,
        "role": newUser.role,
        "status": newUser.status
    }


@app.get('/api/users')
@app.get('/users')
def list_users(db: Session = Depends(get_db), admin_user: User = Depends(get_current_admin)):
    users = db.query(User).all()
    return [
        {
            "id": u.employee_id,
            "employeeId": u.employee_id,
            "username": u.username,
            "fullName": u.full_name or u.username,
            "email": u.email,
            "role": u.role,
            "designation": u.designation,
            "department": u.department,
            "status": u.status,
            "createdDate": u.created_at.strftime("%Y-%m-%d") if getattr(u, 'created_at', None) else None
        }
        for u in users
    ]


@app.get('/api/users/{user_id}')
@app.get('/users/{user_id}')
def get_user_by_id(user_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = db.query(User).filter(
        (User.employee_id == user_id) | (User.username == user_id)
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    if current_user.role != "admin" and current_user.employee_id != user.employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return {
        "id": user.employee_id,
        "employeeId": user.employee_id,
        "username": user.username,
        "fullName": user.full_name or user.username,
        "email": user.email,
        "role": user.role,
        "designation": user.designation,
        "department": user.department,
        "status": user.status,
        "createdDate": user.created_at.strftime("%Y-%m-%d") if getattr(user, 'created_at', None) else None
    }


@app.put('/api/users/{user_id}')
@app.put('/users/{user_id}')
def update_user(
    user_id: str,
    request: UserUpdateSchema,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin)
):
    user = db.query(User).filter(
        (User.employee_id == user_id) | (User.username == user_id)
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if request.full_name is not None:
        user.full_name = request.full_name
    if request.email is not None:
        user.email = request.email
    if request.role is not None:
        user.role = request.role
    if request.designation is not None:
        user.designation = request.designation
    if request.department is not None:
        user.department = request.department
    if request.status is not None:
        user.status = request.status
    if request.password:
        user.password = pwd_context.hash(request.password)

    db.commit()
    db.refresh(user)

    return {
        "Message": "User Updated Successfully",
        "employee_id": user.employee_id,
        "username": user.username,
        "fullName": user.full_name,
        "role": user.role,
        "status": user.status
    }


@app.delete('/api/users/{user_id}')
@app.delete('/users/{user_id}')
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin)
):
    user = db.query(User).filter(
        (User.employee_id == user_id) | (User.username == user_id)
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.username == "admin" or user.employee_id == "EMP001":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Default administrator account cannot be deleted.")

    db.delete(user)
    db.commit()
    return {"status": "success", "message": f"User '{user_id}' deleted successfully"}



# ─── 3. FORM A (PAGE A) - HOURLY MONITORING ─────────────────
@app.post("/api/form-a/extract-image")
@app.post('/api/production/extractimage')
async def extractFormData(file: UploadFile = File(...), currentUser: User = Depends(get_current_user)):
    if file.content_type not in ['image/jpeg', 'image/png', 'image/jpg', 'application/octet-stream']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Only upload JPG/PNG images.'
        )

    imageBytes = await file.read()
    mime_type = _image_mime_type(file)
    try:
        extracted_json, image_path, detection = _read_and_validate_form(imageBytes, mime_type, "A")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Form A Extraction Error: {str(e)}"
        )

    return {
        "status": "success",
        "message": "Form extracted successfully.",
        "data": extracted_json,
        "image_path": image_path,
        "detected_form_type": detection["form_type"],
    }


@app.post("/api/form-a/save")
@app.post("/api/form-a-save")
def saveFormA(
    request: FormASaveSchema,
    db: Session = Depends(get_db),
    currentUser: User = Depends(get_current_user)
):
    try:
        parentLog = ProductionLog(
            logDate=request.log_date,
            shift=request.shift,
            opearationNumber=request.operation_number,
            machineNo=request.machine_no,
            qaCell=request.qa_cell,
            employeeNumber=request.employee_number or currentUser.employee_id,
            supervisorName=request.supervisor_name,
            shiftInchargeName=request.shift_incharge_name,
            pdiOkPart=request.pdi_ok_part1,
            pdiOkPart2=request.pdi_ok_part2,
            entryPersonName=request.entry_person_name or currentUser.full_name,
            abnormalityParts=request.abnormality_parts,
            otherAbnormality=request.other_abnormality,
            imagePath=request.image_path
        )

        db.add(parentLog)
        db.flush()


        hourlyRecords = []
        for entry in request.production_grid:
            hourlyItem = HourlyProductionEntry(
                production_log_id=parentLog.id,
                part_number=entry.part_number,
                hour_slot=entry.hour_slot,
                uph=entry.uph or 0,
                actual_production=entry.actual_production or 0,
                casting_rejection=entry.casting_rejection or 0,
                machining_rejection=entry.machining_rejection or 0,
                unprocessed_rejection=entry.unprocessed_rejection or 0
            )
            hourlyRecords.append(hourlyItem)

        if hourlyRecords:
            db.add_all(hourlyRecords)

        tpm_records = []
        for tpm in request.loss_entries:
            tpm_item = TPMLossEntry(
                production_log_id=parentLog.id,
                loss_category=tpm.loss_category,
                loss_reason=tpm.loss_reason,
                hour_slot=tpm.hour_slot,
                duration_minutes=tpm.duration_minutes or 0
            )
            tpm_records.append(tpm_item)

        if tpm_records:
            db.add_all(tpm_records)

        db.commit()
        db.refresh(parentLog)

        return {
            "status": "success",
            "message": "Form A data saved successfully",
            "log_id": parentLog.id
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save Form A: {str(e)}"
        )


@app.get("/api/form-a/list")
def get_form_a_list(
    log_date: Optional[str] = Query(None),
    shift: Optional[str] = Query(None),
    machine_no: Optional[str] = Query(None),
    operator_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        query = db.query(ProductionLog)

        if current_user.role != "admin":
            query = query.filter(ProductionLog.employeeNumber == current_user.employee_id)
        elif operator_id:
            query = query.filter(ProductionLog.employeeNumber == operator_id)

        if log_date:
            query = query.filter(ProductionLog.logDate == log_date)
        if shift:
            query = query.filter(ProductionLog.shift == shift)
        if machine_no:
            query = query.filter(ProductionLog.machineNo.ilike(f"%{machine_no}%"))

        total_records = query.count()
        logs = query.order_by(ProductionLog.id.desc()).offset(offset).limit(limit).all()

        result_list = []
        for item in logs:
            result_list.append({
                "id": item.id,
                "logDate": item.logDate,
                "shift": item.shift,
                "machineNo": item.machineNo,
                "qaCell": item.qaCell,
                "opearationNumber": item.opearationNumber,
                "employeeNumber": item.employeeNumber,
                "supervisorName": item.supervisorName,
                "shiftInchargeName": item.shiftInchargeName,
                "entryPersonName": item.entryPersonName,
                "pdiOkPart": item.pdiOkPart,
                "createdAt": item.createdAt.isoformat() if item.createdAt else None
            })

        return {
            "status": "success",
            "total_count": total_records,
            "count": len(result_list),
            "data": result_list
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch Form A list: {str(e)}"
        )


@app.get("/api/form-a/{id}")
def get_form_a_by_id(id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ProductionLog).filter(ProductionLog.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Form A record not found")

    hourly = [
        {
            "part_number": h.part_number,
            "hour_slot": h.hour_slot,
            "uph": h.uph,
            "actual_production": h.actual_production,
            "casting_rejection": h.casting_rejection,
            "machining_rejection": h.machining_rejection,
            "unprocessed_rejection": h.unprocessed_rejection
        }
        for h in item.hourlyEntries
    ]

    losses = [
        {
            "loss_category": l.loss_category,
            "loss_reason": l.loss_reason,
            "hour_slot": l.hour_slot,
            "duration_minutes": l.duration_minutes
        }
        for l in item.tpmEntries
    ]

    return {
        "id": item.id,
        "logDate": item.logDate,
        "shift": item.shift,
        "machineNo": item.machineNo,
        "qaCell": item.qaCell,
        "opearationNumber": item.opearationNumber,
        "employeeNumber": item.employeeNumber,
        "supervisorName": item.supervisorName,
        "shiftInchargeName": item.shiftInchargeName,
        "pdiOkPart": item.pdiOkPart,
        "pdiOkPart2": item.pdiOkPart2,
        "entryPersonName": item.entryPersonName,
        "abnormalityParts": item.abnormalityParts,
        "otherAbnormality": item.otherAbnormality,
        "imagePath": item.imagePath,
        "production_grid": hourly,
        "loss_entries": losses,
        "createdAt": item.createdAt.isoformat() if item.createdAt else None
    }


@app.put("/api/form-a/{id}")
def update_form_a_by_id(
    id: int,
    request: FormASaveSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist edits from the Page A form viewer without creating a second log."""
    item = db.query(ProductionLog).filter(ProductionLog.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Form A record not found")
    if current_user.role != "admin" and item.employeeNumber != current_user.employee_id:
        raise HTTPException(status_code=403, detail="You can only edit your own Form A records")

    try:
        item.logDate = request.log_date
        item.shift = request.shift
        item.opearationNumber = request.operation_number
        item.machineNo = request.machine_no
        item.qaCell = request.qa_cell
        item.employeeNumber = request.employee_number or item.employeeNumber
        item.supervisorName = request.supervisor_name
        item.shiftInchargeName = request.shift_incharge_name
        item.pdiOkPart = request.pdi_ok_part1
        item.pdiOkPart2 = request.pdi_ok_part2
        item.entryPersonName = request.entry_person_name or item.entryPersonName
        item.abnormalityParts = request.abnormality_parts
        item.otherAbnormality = request.other_abnormality
        # Retain the original photo if the edit payload does not include it.
        item.imagePath = request.image_path or item.imagePath

        db.query(HourlyProductionEntry).filter(HourlyProductionEntry.production_log_id == id).delete()
        db.query(TPMLossEntry).filter(TPMLossEntry.production_log_id == id).delete()

        db.add_all([
            HourlyProductionEntry(
                production_log_id=id,
                part_number=entry.part_number,
                hour_slot=entry.hour_slot,
                uph=entry.uph or 0,
                actual_production=entry.actual_production or 0,
                casting_rejection=entry.casting_rejection or 0,
                machining_rejection=entry.machining_rejection or 0,
                unprocessed_rejection=entry.unprocessed_rejection or 0,
            )
            for entry in request.production_grid
        ])
        db.add_all([
            TPMLossEntry(
                production_log_id=id,
                loss_category=loss.loss_category,
                loss_reason=loss.loss_reason,
                hour_slot=loss.hour_slot,
                duration_minutes=loss.duration_minutes or 0,
            )
            for loss in request.loss_entries
        ])
        db.commit()
        db.refresh(item)
        return get_form_a_by_id(id, db, current_user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update Form A: {str(e)}")


# ─── 4. FORM B (PAGE B) - FOP & SHIFT HANDOVER (PDF SPEC) ─────

# Endpoint 1: Extract Form B Data from Image (AI Vision OCR)
@app.post("/api/form-b/extract-image")
async def extractFormBData(
    file: UploadFile = File(...),
    currentUser: User = Depends(get_current_user)
):
    if file.content_type not in ['image/jpeg', 'image/png', 'image/jpg', 'application/octet-stream']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Only upload JPG/PNG images.'
        )

    imageBytes = await file.read()
    mime_type = _image_mime_type(file)
    try:
        extracted_data, image_path, detection = _read_and_validate_form(imageBytes, mime_type, "B")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Form B Extraction Error: {str(e)}"
        )

    return {
        "status": "success",
        "message": "Form B extracted successfully via Vision AI.",
        "data": extracted_data,
        "image_path": image_path,
        "detected_form_type": detection["form_type"],
    }


# Endpoint 2: Save Form B (Relational Data Persistence)
@app.post("/api/form-b/save", status_code=status.HTTP_201_CREATED)
def saveFormB(
    request: FormBSaveSchema,
    db: Session = Depends(get_db),
    currentUser: User = Depends(get_current_user)
):
    try:
        # Determine operator name and employee id
        op_name = request.operator_name or currentUser.full_name or currentUser.username
        op_id = request.operator_id or currentUser.employee_id

        # Determine machine number if passed in records
        m_no = request.machine_no
        if not m_no and request.records:
            for r in request.records:
                if r.get("machineNo"):
                    m_no = r.get("machineNo")
                    break

        # Preserve the exact editable Page B grid and details in addition to the
        # reporting rows. Relational tool rows omit several paper-form columns.
        details_str = json.dumps({
            "details": request.details or {},
            "records": request.records or [],
        })

        # Step 1: Create Parent Form2HandoverLog
        handover_log = Form2HandoverLog(
            log_date=request.log_date or datetime.utcnow().strftime("%d/%m/%y"),
            shift=request.shift or "A",
            machine_no=m_no or "—",
            part_name=request.part_name or "K-10",
            operation_no=request.operation_no or "60",
            operator_name=op_name,
            operator_id=op_id,
            supervisor_name=request.supervisor_name,
            handover_notes=request.handover_notes,
            image_path=request.image_path,
            total_defect=request.total_defect or (request.details.get("totalDefect") if request.details else None),
            raw_details_json=details_str
        )

        db.add(handover_log)
        db.flush()

        # Step 2: Add Tool Records (from request.tool_records or request.records)
        tool_entities = []
        if request.tool_records:
            for idx, tr in enumerate(request.tool_records):
                t_ent = Form2ToolRecord(
                    form2_handover_id=handover_log.id,
                    tool_name=tr.tool_name or tr.toolDescription or "",
                    tool_code=tr.tool_code or tr.toolNo or "",
                    operation_no=tr.operationNo or "",
                    machine_no=tr.machineNo or "",
                    time=tr.time or "",
                    reason_for_fop=tr.reasonForFOP or tr.remarks or "",
                    fop_parts=tr.fopParts or "",
                    fop_rejection=tr.fopRejection or "",
                    tool_set_by=tr.toolSetBy or "",
                    qa_insp=tr.qaInsp or "",
                    standard_life=tr.standard_life or 0,
                    actual_life=tr.actual_life or 0,
                    status=tr.status or "OK",
                    remarks=tr.remarks or "",
                    row_index=idx
                )
                tool_entities.append(t_ent)
        elif request.records:
            for idx, r in enumerate(request.records):
                if any(r.values()):
                    t_ent = Form2ToolRecord(
                        form2_handover_id=handover_log.id,
                        tool_name=r.get("toolDescription", ""),
                        tool_code=r.get("toolNo", ""),
                        operation_no=r.get("operationNo", ""),
                        machine_no=r.get("machineNo", ""),
                        time=r.get("time", ""),
                        reason_for_fop=r.get("reasonForFOP", ""),
                        fop_parts=r.get("fopParts", ""),
                        fop_rejection=r.get("fopRejection", ""),
                        tool_set_by=r.get("toolSetBy", ""),
                        qa_insp=r.get("qaInsp", ""),
                        standard_life=int(r.get("standard_life") or 0) if r.get("standard_life") else 0,
                        actual_life=int(r.get("actual_life") or 0) if r.get("actual_life") else 0,
                        status=r.get("status", "OK"),
                        remarks=r.get("remarks", ""),
                        row_index=idx
                    )
                    tool_entities.append(t_ent)

        if tool_entities:
            db.add_all(tool_entities)

        # Step 3: Add PDI Inspection Records
        pdi_entities = []
        if request.pdi_inspections:
            for idx, pdi in enumerate(request.pdi_inspections):
                p_ent = Form2PDIInspectionRecord(
                    form2_handover_id=handover_log.id,
                    parameter_name=pdi.parameter_name or "",
                    specification=pdi.specification or "",
                    sample_1=pdi.sample_1 or "",
                    sample_2=pdi.sample_2 or "",
                    sample_3=pdi.sample_3 or "",
                    status=pdi.status or "OK",
                    remarks=pdi.remarks or "",
                    row_index=idx
                )
                pdi_entities.append(p_ent)

        if pdi_entities:
            db.add_all(pdi_entities)

        # Step 4: Commit transaction
        db.commit()
        db.refresh(handover_log)

        return {
            "status": "success",
            "message": "Form B data saved successfully",
            "log_id": handover_log.id
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save Form B: {str(e)}"
        )


# Endpoint 3: Get Filtered Form B List
@app.get("/api/form-b/list")
def get_form_b_list(
    log_date: Optional[str] = Query(None, description="Filter by date string e.g. 13/06/26"),
    shift: Optional[str] = Query(None, description="Production shift: A, B, or C"),
    machine_no: Optional[str] = Query(None, description="Machine number search"),
    operator_id: Optional[str] = Query(None, description="Filter by operator employee ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        query = db.query(Form2HandoverLog)

        if current_user.role != "admin":
            query = query.filter(Form2HandoverLog.operator_id == current_user.employee_id)
        elif operator_id:
            query = query.filter(Form2HandoverLog.operator_id == operator_id)

        if log_date:
            query = query.filter(Form2HandoverLog.log_date == log_date)
        if shift:
            query = query.filter(Form2HandoverLog.shift == shift)
        if machine_no:
            query = query.filter(Form2HandoverLog.machine_no.ilike(f"%{machine_no}%"))

        total_records = query.count()
        logs = query.order_by(Form2HandoverLog.id.desc()).offset(offset).limit(limit).all()

        result_list = []
        for item in logs:
            result_list.append({
                "id": item.id,
                "log_date": item.log_date,
                "logDate": item.log_date,
                "date": item.log_date,
                "shift": item.shift,
                "machine_no": item.machine_no,
                "machineNo": item.machine_no,
                "part_name": item.part_name,
                "partNo1": item.part_name or "Tool & Handover",
                "operation_no": item.operation_no,
                "operationNumber": item.operation_no,
                "operator_name": item.operator_name,
                "uploadedBy": item.operator_name,
                "operator_id": item.operator_id,
                "employeeId": item.operator_id,
                "supervisor_name": item.supervisor_name,
                "supervisorName": item.supervisor_name,
                "handover_notes": item.handover_notes,
                "total_defect": item.total_defect,
                "totalProduction": 0,
                "totalLossMin": 0,
                "qaCell": "FOP Record",
                "formType": "tool-handover",
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "createdAt": item.created_at.isoformat() if item.created_at else None,
            })

        return {
            "status": "success",
            "total_count": total_records,
            "count": len(result_list),
            "data": result_list
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch Form B list: {str(e)}"
        )


# Endpoint 4: Get Single Form B Full Details by ID
@app.get("/api/form-b/{id}")
def get_form_b_by_id(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    item = db.query(Form2HandoverLog).filter(Form2HandoverLog.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Form B record not found")

    # Reconstruct tool records
    tool_records = [
        {
            "id": t.id,
            "tool_name": t.tool_name,
            "tool_code": t.tool_code,
            "toolDescription": t.tool_name,
            "operationNo": t.operation_no,
            "machineNo": t.machine_no,
            "toolNo": t.tool_code,
            "time": t.time,
            "reasonForFOP": t.reason_for_fop,
            "fopParts": t.fop_parts,
            "fopRejection": t.fop_rejection,
            "toolSetBy": t.tool_set_by,
            "qaInsp": t.qa_insp,
            "standard_life": t.standard_life,
            "actual_life": t.actual_life,
            "status": t.status,
            "remarks": t.remarks,
            "row_index": t.row_index
        }
        for t in item.tool_records
    ]

    # Reconstruct 16-row grid for frontend ToolHandoverSheet
    records_16 = []
    for i in range(16):
        matching = next((t for t in tool_records if t.get("row_index") == i), None)
        if matching:
            records_16.append(matching)
        elif i < len(tool_records):
            records_16.append(tool_records[i])
        else:
            records_16.append({
                "toolDescription": "",
                "operationNo": "",
                "machineNo": "",
                "toolNo": "",
                "time": "",
                "reasonForFOP": "",
                "fopParts": "",
                "fopRejection": "",
                "toolSetBy": "",
                "qaInsp": "",
                "quantity": "",
                "totFopPart": "",
                "handoverCheck": "",
                "defect": "",
                "materialOrTool": "",
                "remarks": ""
            })

    # Reconstruct PDI inspections
    pdi_inspections = [
        {
            "id": p.id,
            "parameter_name": p.parameter_name,
            "specification": p.specification,
            "sample_1": p.sample_1,
            "sample_2": p.sample_2,
            "sample_3": p.sample_3,
            "status": p.status,
            "remarks": p.remarks,
            "row_index": p.row_index
        }
        for p in item.pdi_inspections
    ]

    # Parse details
    parsed_details = {}
    saved_records = None
    if item.raw_details_json:
        try:
            snapshot = json.loads(item.raw_details_json)
            if isinstance(snapshot, dict) and "details" in snapshot:
                parsed_details = snapshot.get("details") or {}
                saved_records = snapshot.get("records")
            else:
                # Backward compatibility for Page B records saved before snapshots.
                parsed_details = snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            parsed_details = {}

    return {
        "id": item.id,
        "log_date": item.log_date,
        "date": item.log_date,
        "shift": item.shift,
        "machine_no": item.machine_no,
        "machineNo": item.machine_no,
        "part_name": item.part_name,
        "partNo1": item.part_name or "Tool & Handover",
        "operation_no": item.operation_no,
        "operationNumber": item.operation_no,
        "operator_name": item.operator_name,
        "uploadedBy": item.operator_name,
        "operator_id": item.operator_id,
        "employeeId": item.operator_id,
        "supervisor_name": item.supervisor_name,
        "supervisorName": item.supervisor_name,
        "handover_notes": item.handover_notes,
        "total_defect": item.total_defect,
        "image_path": item.image_path,
        "formType": "tool-handover",
        "qaCell": "FOP Record",
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "createdAt": item.created_at.isoformat() if item.created_at else None,
        "tool_records": tool_records,
        "pdi_inspections": pdi_inspections,
        "records": saved_records if isinstance(saved_records, list) else records_16,
        "details": parsed_details
    }


# Endpoint 5: Update Form B record
@app.put("/api/form-b/{id}")
def update_form_b_by_id(
    id: int,
    request: FormBSaveSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    item = db.query(Form2HandoverLog).filter(Form2HandoverLog.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Form B record not found")

    if request.log_date:
        item.log_date = request.log_date
    if request.shift:
        item.shift = request.shift
    if request.machine_no:
        item.machine_no = request.machine_no
    if request.part_name:
        item.part_name = request.part_name
    if request.operation_no:
        item.operation_no = request.operation_no
    if request.supervisor_name:
        item.supervisor_name = request.supervisor_name
    if request.handover_notes:
        item.handover_notes = request.handover_notes
    if request.details:
        item.raw_details_json = json.dumps(request.details)
        if request.details.get("totalDefect"):
            item.total_defect = str(request.details.get("totalDefect"))

    # Update tool records if passed
    if request.records:
        db.query(Form2ToolRecord).filter(Form2ToolRecord.form2_handover_id == id).delete()
        for idx, r in enumerate(request.records):
            if any(r.values()):
                t_ent = Form2ToolRecord(
                    form2_handover_id=item.id,
                    tool_name=r.get("toolDescription", ""),
                    tool_code=r.get("toolNo", ""),
                    operation_no=r.get("operationNo", ""),
                    machine_no=r.get("machineNo", ""),
                    time=r.get("time", ""),
                    reason_for_fop=r.get("reasonForFOP", ""),
                    fop_parts=r.get("fopParts", ""),
                    fop_rejection=r.get("fopRejection", ""),
                    tool_set_by=r.get("toolSetBy", ""),
                    qa_insp=r.get("qaInsp", ""),
                    standard_life=int(r.get("standard_life") or 0) if r.get("standard_life") else 0,
                    actual_life=int(r.get("actual_life") or 0) if r.get("actual_life") else 0,
                    status=r.get("status", "OK"),
                    remarks=r.get("remarks", ""),
                    row_index=idx
                )
                db.add(t_ent)

    db.commit()
    db.refresh(item)
    return get_form_b_by_id(id, db, current_user)
