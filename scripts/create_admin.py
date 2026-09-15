import sys
import os

# Add backend root to path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from database.db import engine, Base, sessionLocal
from models.userModels import User
from datetime import datetime, timezone
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_initial_admin():
    Base.metadata.create_all(bind=engine)
    db = sessionLocal()

    try:
        admin_username = "admin"
        admin_email = "admin@example.com"
        admin_emp_id = "EMP001"
        plain_password = "admin123"

        # Check and remove existing admin users
        existing_users = db.query(User).filter(
            (User.username == admin_username) | (User.email == admin_email) | (User.employee_id == admin_emp_id)
        ).all()

        if existing_users:
            for old_user in existing_users:
                db.delete(old_user)
            db.commit()
            print("[INFO] Existing admin user records removed.")

        # Hash password
        hashed_password = pwd_context.hash(plain_password)

        new_admin = User(
            employee_id=admin_emp_id,
            full_name="System Administrator",
            username=admin_username,
            email=admin_email,
            password=hashed_password,
            role="admin",
            designation="Super Admin",
            department="IT",
            status="Active",
            created_at=datetime.now(timezone.utc)
        )

        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)

        print("========================================")
        print("[SUCCESS] New Admin User Successfully Created!")
        print(f"Username:    {admin_username}")
        print(f"Password:    {plain_password}")
        print(f"Employee ID: {admin_emp_id}")
        print(f"Role:        {new_admin.role}")
        print(f"Status:      {new_admin.status}")
        print("========================================")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error resetting admin user: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    create_initial_admin()