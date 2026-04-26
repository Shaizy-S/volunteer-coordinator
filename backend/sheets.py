import gspread
from google.oauth2.service_account import Credentials
import os
import uuid
import json
from datetime import datetime, timezone

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_workbook():
    # Try reading from environment variable first (production/Render)
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    
    if creds_json:
        # Running on Render — credentials stored as env variable
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # Running locally — read from file as before
        creds = Credentials.from_service_account_file(
            "service_account.json", scopes=SCOPES
        )
    
    client = gspread.authorize(creds)
    return client.open_by_key(os.getenv("GOOGLE_SHEETS_ID"))


# ─── NEEDS ───────────────────────────────────────────────────

def get_all_needs():
    ws = get_workbook().worksheet("Needs")
    records = ws.get_all_records()
    # Clean empty rows
    return [r for r in records if r.get("description", "").strip()]


def add_need(need: dict):
    ws = get_workbook().worksheet("Needs")
    ws.append_row([
        need.get("id", str(uuid.uuid4())[:8]),
        need.get("ngo_name", ""),
        need.get("contact", ""),
        need.get("description", ""),
        need.get("category", ""),
        need.get("urgency", ""),
        need.get("people_affected", 0),
        need.get("location", ""),
        need.get("lat", 0),
        need.get("lng", 0),
        need.get("priority_score", 0),
        need.get("status", "pending"),
        need.get("timestamp", datetime.now(timezone.utc).isoformat()),
        need.get("assigned_volunteer", "")
    ])


def update_need(need_id: str, updates: dict):
    wb = get_workbook()
    ws = wb.worksheet("Needs")
    records = ws.get_all_records()
    headers = ws.row_values(1)
    for i, row in enumerate(records, start=2):
        if str(row.get("id")) == str(need_id):
            for field, value in updates.items():
                if field in headers:
                    col = headers.index(field) + 1
                    ws.update_cell(i, col, value)
            return True
    return False


# ─── VOLUNTEERS ──────────────────────────────────────────────

def get_all_volunteers():
    ws = get_workbook().worksheet("Volunteers")
    records = ws.get_all_records()
    return [r for r in records if r.get("name", "").strip()]


def add_volunteer(vol: dict):
    ws = get_workbook().worksheet("Volunteers")
    ws.append_row([
        vol.get("id", str(uuid.uuid4())[:8]),
        vol.get("name", ""),
        vol.get("phone", ""),
        vol.get("skills", ""),
        vol.get("location", ""),
        vol.get("lat", 0),
        vol.get("lng", 0),
        vol.get("availability", "available"),
        vol.get("assigned_count", 0),
        vol.get("max_capacity", 2)
    ])


def update_volunteer(vol_id: str, updates: dict):
    wb = get_workbook()
    ws = wb.worksheet("Volunteers")
    records = ws.get_all_records()
    headers = ws.row_values(1)
    for i, row in enumerate(records, start=2):
        if str(row.get("id")) == str(vol_id):
            for field, value in updates.items():
                if field in headers:
                    col = headers.index(field) + 1
                    ws.update_cell(i, col, value)
            return True
    return False


# ─── ASSIGNMENTS ─────────────────────────────────────────────

def get_all_assignments():
    try:
        ws = get_workbook().worksheet("Assignments")
        return ws.get_all_records()
    except Exception:
        return []


def add_assignment(need_id: str, volunteer_id: str):
    wb = get_workbook()
    ws = wb.worksheet("Assignments")
    ws.append_row([
        str(uuid.uuid4())[:8],
        need_id,
        volunteer_id,
        datetime.now(timezone.utc).isoformat(),
        "",       # completed_at
        "",       # outcome
        ""        # feedback
    ])


def complete_assignment(need_id: str, outcome: str = "successful", feedback: str = ""):
    wb = get_workbook()
    ws = wb.worksheet("Assignments")
    records = ws.get_all_records()
    headers = ws.row_values(1)
    for i, row in enumerate(records, start=2):
        if str(row.get("need_id")) == str(need_id) and not row.get("completed_at"):
            ws.update_cell(i, headers.index("completed_at") + 1,
                           datetime.now(timezone.utc).isoformat())
            ws.update_cell(i, headers.index("outcome") + 1, outcome)
            ws.update_cell(i, headers.index("feedback") + 1, feedback)
            return True
    return False