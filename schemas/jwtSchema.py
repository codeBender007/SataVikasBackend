from pydantic import BaseModel
from typing import Optional


class jwtSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    employee_id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    status: Optional[str] = "Active"