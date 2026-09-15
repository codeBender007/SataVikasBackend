from pydantic import BaseModel
from typing import Optional


class userSchema(BaseModel):
    employee_id: str
    full_name: Optional[str] = None
    username: str
    email: str
    password: str
    role: Optional[str] = "employee"
    designation: Optional[str] = None
    department: Optional[str] = None
    status: Optional[str] = "Active"


class UserUpdateSchema(BaseModel):
    full_name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    status: Optional[str] = None