import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_DIR / ".env")

# retrieve database_url from .env, default to app.db inside backend folder
SQLACHEMY_DATABASE_URL = os.getenv('DATABASE_URL')
if not SQLACHEMY_DATABASE_URL:
    db_path = BACKEND_DIR / "app.db"
    SQLACHEMY_DATABASE_URL = f"sqlite:///{db_path.as_posix()}"
elif SQLACHEMY_DATABASE_URL.startswith("sqlite:///./") or SQLACHEMY_DATABASE_URL.startswith("sqlite:////") or SQLACHEMY_DATABASE_URL == "sqlite:///app.db":
    rel_name = SQLACHEMY_DATABASE_URL.replace("sqlite:///./", "").replace("sqlite:///", "")
    db_path = BACKEND_DIR / rel_name
    SQLACHEMY_DATABASE_URL = f"sqlite:///{db_path.as_posix()}"

# SQLite connection setup
connect_args = {"check_same_thread": False} if SQLACHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLACHEMY_DATABASE_URL, connect_args=connect_args)

sessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# DB session
def get_db():
    db = sessionLocal()
    try:
        yield db
    finally:
        db.close()