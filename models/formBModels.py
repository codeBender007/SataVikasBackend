from datetime import datetime
from database.db import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship


# Table 1: Master Form B / Form 2 Handover Header Log
class Form2HandoverLog(Base):
    __tablename__ = "Form2HandoverLog"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    log_date = Column(String(50), nullable=True)
    shift = Column(String(10), nullable=True)
    machine_no = Column(String(100), nullable=True)
    part_name = Column(String(100), nullable=True)
    operation_no = Column(String(50), nullable=True)
    operator_name = Column(String(100), nullable=True)
    operator_id = Column(String(50), nullable=True)  # Employee ID
    supervisor_name = Column(String(100), nullable=True)
    handover_notes = Column(Text, nullable=True)
    image_path = Column(String(255), nullable=True)
    total_defect = Column(String(50), nullable=True)
    raw_details_json = Column(Text, nullable=True)  # JSON string of full details
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tool_records = relationship(
        "Form2ToolRecord",
        back_populates="handover_log",
        cascade="all, delete-orphan",
    )
    pdi_inspections = relationship(
        "Form2PDIInspectionRecord",
        back_populates="handover_log",
        cascade="all, delete-orphan",
    )


# Table 2: Form B Tool Records / FOP Tool Replacement
class Form2ToolRecord(Base):
    __tablename__ = "Form2ToolRecord"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    form2_handover_id = Column(
        Integer, ForeignKey("Form2HandoverLog.id"), nullable=False
    )
    tool_name = Column(String(150), nullable=True)      # toolDescription
    tool_code = Column(String(50), nullable=True)       # toolNo
    operation_no = Column(String(50), nullable=True)    # operationNo
    machine_no = Column(String(50), nullable=True)      # machineNo
    time = Column(String(50), nullable=True)            # time
    reason_for_fop = Column(String(255), nullable=True) # reasonForFOP
    fop_parts = Column(String(50), nullable=True)       # fopParts
    fop_rejection = Column(String(50), nullable=True)   # fopRejection
    tool_set_by = Column(String(100), nullable=True)    # toolSetBy
    qa_insp = Column(String(100), nullable=True)        # qaInsp
    standard_life = Column(Integer, default=0, nullable=True)
    actual_life = Column(Integer, default=0, nullable=True)
    status = Column(String(50), nullable=True)
    remarks = Column(String(255), nullable=True)
    row_index = Column(Integer, default=0, nullable=True)

    handover_log = relationship(
        "Form2HandoverLog", back_populates="tool_records"
    )


# Table 3: Form B PDI Quality Inspection Checks
class Form2PDIInspectionRecord(Base):
    __tablename__ = "Form2PDIInspectionRecord"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    form2_handover_id = Column(
        Integer, ForeignKey("Form2HandoverLog.id"), nullable=False
    )
    parameter_name = Column(String(150), nullable=True)
    specification = Column(String(150), nullable=True)
    sample_1 = Column(String(50), nullable=True)
    sample_2 = Column(String(50), nullable=True)
    sample_3 = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    remarks = Column(String(255), nullable=True)
    row_index = Column(Integer, default=0, nullable=True)

    handover_log = relationship(
        "Form2HandoverLog", back_populates="pdi_inspections"
    )
