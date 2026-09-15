from datetime import datetime
from database.db import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship


# Table 1: Master Production Header
class ProductionLog(Base):
    __tablename__ = "ProductionLog"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    logDate = Column(String(50), nullable=True)
    shift = Column(String(10), nullable=True)
    opearationNumber = Column(String(50), nullable=True)
    machineNo = Column(String(50), nullable=True)
    qaCell = Column(String(50), nullable=True)
    employeeNumber = Column(String(50), nullable=True)
    supervisorName = Column(String(100), nullable=True)
    shiftInchargeName = Column(String(100), nullable=True)
    pdiOkPart = Column(String(50), nullable=True)
    pdiOkPart2 = Column(String(50), nullable=True)
    entryPersonName = Column(String(50), nullable=True)
    abnormalityParts = Column(Text, nullable=True)
    otherAbnormality = Column(Text, nullable=True)
    imagePath = Column(String(255), nullable=True)
    createdAt = Column(DateTime, default=datetime.utcnow)

    # Relationships (Target class ke variable 'production_log' ko point karenge)
    hourlyEntries = relationship(
        "HourlyProductionEntry",
        back_populates="production_log",
        cascade="all, delete-orphan",
    )
    tpmEntries = relationship(
        "TPMLossEntry",
        back_populates="production_log",
        cascade="all, delete-orphan",
    )


# Table 2: Hourly Production & Rejection Data
class HourlyProductionEntry(Base):
    __tablename__ = "HourlyProductionEntry"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    production_log_id = Column(
        Integer, ForeignKey("ProductionLog.id"), nullable=False
    )
    part_number = Column(String(50), nullable=True)
    hour_slot = Column(String(10), nullable=False)  # H1, H2, H3 ... H13
    uph = Column(Integer, default=0)
    actual_production = Column(Integer, default=0)
    casting_rejection = Column(Integer, default=0)
    machining_rejection = Column(Integer, default=0)
    unprocessed_rejection = Column(Integer, default=0)

    # ProductionLog ke attribute 'hourlyEntries' ko point karega
    production_log = relationship(
        "ProductionLog", back_populates="hourlyEntries"
    )


# Table 3: TPM 16 Loss Entries
class TPMLossEntry(Base):
    __tablename__ = "TPMLossEntry"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    production_log_id = Column(
        Integer, ForeignKey("ProductionLog.id"), nullable=False
    )
    loss_category = Column(String(50), nullable=True)  # BD, ST, SU, MS, ML etc.
    loss_reason = Column(String(150), nullable=True)
    hour_slot = Column(String(10), nullable=False)  # H1, H2 ... H13
    duration_minutes = Column(Integer, default=0)

    # ProductionLog ke attribute 'tpmEntries' ko point karega
    production_log = relationship("ProductionLog", back_populates="tpmEntries")

