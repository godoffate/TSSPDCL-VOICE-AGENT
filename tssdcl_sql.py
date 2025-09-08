# tssdcl_sql.py
import os
import uuid
import datetime
import pyodbc
import asyncio
from dotenv import load_dotenv

load_dotenv()

# Required env vars:
# SQL_SERVER (e.g. your-server.database.windows.net)
# SQL_DATABASE (e.g. TSSPDCL_SQL_DB)
# SQL_USER
# SQL_PASSWORD
# ODBC_DRIVER (optional; default "ODBC Driver 18 for SQL Server")

SQL_SERVER = os.getenv("SQL_SERVER")
SQL_DATABASE = os.getenv("SQL_DATABASE", "TSSPDCL_SQL_DB")
SQL_USER = os.getenv("SQL_USER")
SQL_PASSWORD = os.getenv("SQL_PASSWORD")
ODBC_DRIVER = os.getenv("ODBC_DRIVER", "ODBC Driver 18 for SQL Server")

if not (SQL_SERVER and SQL_USER and SQL_PASSWORD):
    # Delay hard failure — functions will still raise if used without env set.
    pass

CONN_STR = (
    f"DRIVER={{{ODBC_DRIVER}}};"
    f"SERVER={SQL_SERVER};"
    f"DATABASE={SQL_DATABASE};"
    f"UID={SQL_USER};"
    f"PWD={SQL_PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)

def _get_conn():
    """Return a new pyodbc connection. Caller must close it."""
    return pyodbc.connect(CONN_STR)

# ------------- Blocking DB helpers (run in thread) -------------
def _raise_complaint_blocking(service_no, name, area_description, landmark, problem_details):
    conn = _get_conn()
    cur = conn.cursor()
    complaint_id = str(uuid.uuid4())
    created_time = datetime.datetime.utcnow()
    try:
        # Use OUTPUT to return the auto-increment complaint_no
        q = """
        INSERT INTO dbo.complaints
            (id, service_no, name, area_description, landmark, problem_details, status, created_time)
        OUTPUT INSERTED.complaint_no
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cur.execute(q,
                    complaint_id,
                    service_no,
                    name,
                    area_description,
                    landmark,
                    problem_details,
                    'patrolling',
                    created_time)
        inserted = cur.fetchone()  # should contain the complaint_no
        conn.commit()
        complaint_no = inserted[0] if inserted else None
    finally:
        try:
            cur.close()
        except:
            pass
        conn.close()

    return {
        "message": "Complaint registered successfully",
        "complaint_id": complaint_id,
        "complaint_no": complaint_no,
        "status": "patrolling",
        "created_time": created_time.isoformat() + "Z"
    }

def _lookup_complaint_blocking(complaint_no=None, complaint_id=None):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        if complaint_no is not None:
            q = """
            SELECT complaint_no, id, service_no, name, area_description, landmark,
                   problem_details, status, estimation_time, created_time,
                   resolved_time, resolution_duration
            FROM dbo.complaints
            WHERE complaint_no = ?
            """
            cur.execute(q, complaint_no)
        elif complaint_id:
            # if full-length (36 chars) treat as exact match, else do prefix match via LIKE
            if len(complaint_id) == 36:
                q = """
                SELECT complaint_no, id, service_no, name, area_description, landmark,
                       problem_details, status, estimation_time, created_time,
                       resolved_time, resolution_duration
                FROM dbo.complaints
                WHERE id = ?
                """
                cur.execute(q, complaint_id)
            else:
                q = """
                SELECT complaint_no, id, service_no, name, area_description, landmark,
                       problem_details, status, estimation_time, created_time,
                       resolved_time, resolution_duration
                FROM dbo.complaints
                WHERE id LIKE ?
                ORDER BY created_time DESC
                """
                cur.execute(q, complaint_id + "%")
        else:
            return {"error": "Provide complaint_no or complaint_id"}

        row = cur.fetchone()
        if not row:
            return {"error": "Complaint not found"}

        # Map row -> dict
        keys = ["complaint_no", "complaint_id", "service_no", "name", "area_description", "landmark",
                "problem_details", "status", "estimation_time", "created_time",
                "resolved_time", "resolution_duration"]
        values = list(row)
        data = dict(zip(keys, values))
        # convert datetimes to ISO strings
        for k in ("created_time", "resolved_time"):
            if data.get(k) is not None:
                try:
                    data[k] = data[k].isoformat() + "Z"
                except Exception:
                    data[k] = str(data[k])
        return {"complaint": data}
    finally:
        try:
            cur.close()
        except:
            pass
        conn.close()

def _update_complaint_status_blocking(complaint_id, status, estimation_time=None):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        # Fetch existing created_time
        cur.execute("SELECT created_time FROM dbo.complaints WHERE id = ?", complaint_id)
        row = cur.fetchone()
        if not row:
            return {"error": "Complaint not found"}

        created_time = row[0]
        resolved_time = None
        resolution_duration = None
        if status == "fault rectified":
            resolved_time = datetime.datetime.utcnow()
            try:
                duration = resolved_time - created_time
                resolution_duration = str(duration)
            except Exception:
                resolution_duration = None

        # Update
        q = """
        UPDATE dbo.complaints
        SET status = ?, estimation_time = ?, resolved_time = ?, resolution_duration = ?
        WHERE id = ?
        """
        cur.execute(q, status, estimation_time, resolved_time, resolution_duration, complaint_id)
        conn.commit()
        return {"message": "Complaint status updated", "complaint_id": complaint_id, "status": status}
    finally:
        try:
            cur.close()
        except:
            pass
        conn.close()

# ------------- Async wrappers (safe to call from your async main) -------------
async def raise_complaint(service_no=None, name=None, area_description=None, landmark=None, problem_details=None):
    if not name or not problem_details:
        return {"error": "Missing required fields: name and problem_details"}
    return await asyncio.to_thread(_raise_complaint_blocking, service_no, name, area_description, landmark, problem_details)

async def lookup_complaint(complaint_no: int = None, complaint_id: str = None):
    # Accept either complaint_no (int) or complaint_id (string/prefix)
    if complaint_no is None and not complaint_id:
        return {"error": "Provide complaint_no or complaint_id"}
    return await asyncio.to_thread(_lookup_complaint_blocking, complaint_no, complaint_id)

async def update_complaint_status(complaint_id: str, status: str, estimation_time: str = None):
    if not complaint_id or not status:
        return {"error": "Missing complaint_id or status"}
    return await asyncio.to_thread(_update_complaint_status_blocking, complaint_id, status, estimation_time)

# ------------- Function map used by main.py -------------
FUNCTION_MAP = {
    "raise_complaint": raise_complaint,
    "lookup_complaint": lookup_complaint,
    "update_complaint_status": update_complaint_status
}
