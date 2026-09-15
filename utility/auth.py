import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import jwt

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_DIR / ".env")

SECRET_KEY = (os.getenv('SECRET_KEY') or 'satavikas_secret_key_for_sarvagya').strip('"').strip("'")
ALGORITHM = (os.getenv('ALGORITHM') or 'HS256').strip('"').strip("'")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv('ACCESS_TOKEN_EXPIRE_HOURS', 24))


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({'exp': expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt