import os
from pathlib import Path
from dotenv import load_dotenv
import jwt
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from database.db import get_db
from models.userModels import User

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_DIR / ".env")

SECRET_KEY = (os.getenv('SECRET_KEY') or 'satavikas_secret_key_for_sarvagya').strip('"').strip("'")
ALGORITHM = (os.getenv('ALGORITHM') or 'HS256').strip('"').strip("'")

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials / Token invalid",
        headers={'WWW-Authenticate': "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get('sub')
        if not username:
            raise credentials_exception
    except Exception as e:
        print(f"🔒 [AUTH] Token validation failed: {e}")
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    # Status check: do not block if Active / active, but block if inactive or suspended
    if user.status and user.status.strip().lower() in ['inactive', 'suspended', 'disabled', 'false']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User account is {user.status}. Please contact an administrator."
        )

    return user


def get_current_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Access denied: Admin rights required'
        )
    return current_user


    