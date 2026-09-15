import sys
import os

# Add backend directory to sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from fastapi.testclient import TestClient
from main import app
from database.db import sessionLocal, SQLACHEMY_DATABASE_URL
from models.userModels import User
from passlib.context import CryptContext
from utility.auth import create_access_token
import jwt
from utility.dependancies import SECRET_KEY, ALGORITHM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

print("=" * 60)
print("RUNNING END-TO-END AUTH & API ROUTING VERIFICATION")
print("=" * 60)

# 1. Test Database Path & User query
print(f"[TEST 1] Checking Database URL: {SQLACHEMY_DATABASE_URL}")
db = sessionLocal()
try:
    admin = db.query(User).filter(User.username == "admin").first()
    assert admin is not None, "Admin user not found in database!"
    print(f"  -> Found Admin: {admin.username}, Emp ID: {admin.employee_id}, Role: {admin.role}, Status: {admin.status}")
    
    # Check password hash verification
    is_valid = pwd_context.verify("admin123", admin.password)
    assert is_valid is True, "Password verification failed for admin123!"
    print("  -> Password 'admin123' successfully verified against stored bcrypt hash.")
finally:
    db.close()

# 2. Test JWT Token round-trip
print("[TEST 2] Testing JWT Token generation and decoding...")
test_payload = {"sub": "admin", "employee_id": "EMP001", "role": "admin"}
token = create_access_token(test_payload)
print(f"  -> Generated Token: {token[:30]}...")

decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
assert decoded.get("sub") == "admin", "Decoded token 'sub' does not match!"
assert decoded.get("employee_id") == "EMP001", "Decoded token 'employee_id' does not match!"
print(f"  -> Successfully decoded and verified JWT payload: {decoded}")

# 3. Test API Endpoints via TestClient
print("[TEST 3] Testing FastAPI Endpoints via TestClient...")
client = TestClient(app)

# 3.1 Health Check
res = client.get("/")
assert res.status_code == 200, f"Health check failed: {res.status_code}"
print(f"  -> GET / [Status {res.status_code}]: {res.json()}")

# 3.2 Login with valid credentials
res = client.post("/api/login", json={"username": "admin", "password": "admin123"})
assert res.status_code == 200, f"Valid login failed: {res.status_code} - {res.text}"
login_data = res.json()
assert "access_token" in login_data, "access_token missing from login response"
assert login_data["role"] == "admin", "role mismatch in login response"
assert login_data["username"] == "admin", "username mismatch in login response"
token = login_data["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"  -> POST /api/login (valid) [Status {res.status_code}]: Token received, User: {login_data['username']}, Role: {login_data['role']}")

# 3.3 Login with alias /login
res = client.post("/login", json={"username": "admin", "password": "admin123"})
assert res.status_code == 200, f"Alias /login failed: {res.status_code}"
print(f"  -> POST /login (alias) [Status {res.status_code}]: OK")

# 3.4 Login with invalid password
res = client.post("/api/login", json={"username": "admin", "password": "wrongpassword"})
assert res.status_code == 401, f"Expected 401 for wrong password, got {res.status_code}"
print(f"  -> POST /api/login (wrong password) [Status {res.status_code}]: {res.json()['detail']}")

# 3.5 Login with non-existent user
res = client.post("/api/login", json={"username": "nonexistent_user", "password": "anypassword"})
assert res.status_code == 401, f"Expected 401 for unknown user, got {res.status_code}"
print(f"  -> POST /api/login (unknown user) [Status {res.status_code}]: {res.json()['detail']}")

# 3.6 List Users with Auth Token
res = client.get("/api/users", headers=headers)
assert res.status_code == 200, f"GET /api/users failed: {res.status_code}"
users_list = res.json()
assert len(users_list) >= 1, "Expected at least 1 user"
print(f"  -> GET /api/users [Status {res.status_code}]: Returned {len(users_list)} users.")

# 3.7 Create User
test_user_payload = {
    "employee_id": "EMP_TEST_99",
    "full_name": "Test Engineer",
    "username": "test_engineer",
    "email": "test.engineer@satavikas.com",
    "password": "Password123",
    "role": "employee",
    "designation": "CNC Operator",
    "department": "Machining",
    "status": "Active"
}
res = client.post("/api/createuser", json=test_user_payload, headers=headers)
assert res.status_code in [200, 400], f"POST /api/createuser failed: {res.status_code} - {res.text}"
print(f"  -> POST /api/createuser [Status {res.status_code}]: {res.json().get('Message', res.json())}")

# 3.8 Get Single User
res = client.get("/api/users/EMP_TEST_99", headers=headers)
assert res.status_code == 200, f"GET /api/users/EMP_TEST_99 failed: {res.status_code}"
print(f"  -> GET /api/users/EMP_TEST_99 [Status {res.status_code}]: Found {res.json()['fullName']}")

# 3.9 Update User
update_payload = {
    "designation": "Senior CNC Specialist",
    "department": "Advanced Machining"
}
res = client.put("/api/users/EMP_TEST_99", json=update_payload, headers=headers)
assert res.status_code == 200, f"PUT /api/users/EMP_TEST_99 failed: {res.status_code}"
print(f"  -> PUT /api/users/EMP_TEST_99 [Status {res.status_code}]: {res.json()['Message']}")

# 3.10 Delete Test User
res = client.delete("/api/users/EMP_TEST_99", headers=headers)
assert res.status_code == 200, f"DELETE /api/users/EMP_TEST_99 failed: {res.status_code}"
print(f"  -> DELETE /api/users/EMP_TEST_99 [Status {res.status_code}]: {res.json()['message']}")

# 3.11 Attempt to Delete Admin User (Must Be Prevented)
res = client.delete("/api/users/admin", headers=headers)
assert res.status_code == 400, f"Expected 400 when deleting admin, got {res.status_code}"
print(f"  -> DELETE /api/users/admin (Protected) [Status {res.status_code}]: {res.json()['detail']}")

# 3.12 Form A & Form B list endpoints with token
res = client.get("/api/form-a/list", headers=headers)
assert res.status_code == 200, f"GET /api/form-a/list failed: {res.status_code}"
print(f"  -> GET /api/form-a/list [Status {res.status_code}]: total_count = {res.json().get('total_count')}")

res = client.get("/api/form-b/list", headers=headers)
assert res.status_code == 200, f"GET /api/form-b/list failed: {res.status_code}"
print(f"  -> GET /api/form-b/list [Status {res.status_code}]: total_count = {res.json().get('total_count')}")

print("=" * 60)
print("ALL TESTS PASSED SUCCESSFULLY! AUTH & ROUTING FULLY VERIFIED.")
print("=" * 60)
