"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # MongoDB enforces uniqueness even when multiple requests arrive together.
    db.employees.create_index("emp_code", unique=True)
    db.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True)
    db.attendance_logs.create_index([("date", -1), ("emp_code", 1)])
    db.attendance_logs.create_index([("status", 1), ("date", -1), ("emp_code", 1)])
    db.attendance_logs.create_index([("emp_code", 1), ("punch_in", -1)])
    yield


app = FastAPI(
    title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def to_epoch_millis(value: datetime) -> int:
    # PyMongo's default naive datetimes represent UTC, not the host's local time.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    elapsed = value.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (elapsed.days * 86400 + elapsed.seconds) * 1000 + elapsed.microseconds // 1000


def serialize_employee(doc: dict) -> dict:
    result = {key: value for key, value in doc.items() if key != "_id"}
    result["created_at"] = to_epoch_millis(doc["created_at"])
    return result


def serialize_attendance(doc: dict) -> dict:
    def instant(value):
        return to_epoch_millis(value) if value is not None else None

    history = []
    for entry in doc.get("history", []):
        changes = {}
        for field, change in entry["changes"].items():
            changes[field] = {
                direction: instant(value) if field in ("punch_in", "punch_out") else value
                for direction, value in change.items()
            }
        history.append({
            "at": instant(entry["at"]),
            "by": entry["by"],
            "reason": entry["reason"],
            "changes": changes,
        })

    # Build an API-only copy; stored BSON dates and audit entries stay unchanged.
    return {
        "emp_code": doc["emp_code"],
        "date": doc["date"],
        "status": doc["status"],
        "punch_in": instant(doc.get("punch_in")),
        "punch_out": instant(doc.get("punch_out")),
        "work_hours": doc.get("work_hours"),
        "late_minutes": doc.get("late_minutes", 0),
        "overtime_minutes": doc.get("overtime_minutes", 0),
        "half_day": doc.get("half_day", False),
        "history": history,
    }


def normalize_instant(value: datetime) -> datetime:
    # Naive BSON dates returned by PyMongo are UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def attendance_date(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    local = normalize_instant(punch_in).astimezone(IST)
    day = local.date()
    end_hour, end_minute = map(int, shift_end.split(":"))
    before_shift_end = (local.hour, local.minute, local.second) < (end_hour, end_minute, 0)
    if shift_end <= shift_start and before_shift_end:
        day -= timedelta(days=1)
    return day.isoformat()


def compute_late_minutes(punch_in: datetime, shift_start: str, date_str: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    seconds = int((normalize_instant(punch_in) - start).total_seconds())
    # Compare seconds before flooring, so 10:01 late reports 10 minutes.
    return seconds // 60 if seconds > 10 * 60 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = int((normalize_instant(punch_out) - normalize_instant(punch_in)).total_seconds())
    return float((Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(punch_out: datetime, shift_start: str, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    if shift_end <= shift_start:
        end += timedelta(days=1)
    minutes = int((normalize_instant(punch_out) - end).total_seconds()) // 60
    return minutes if minutes >= 30 else 0


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field(default="18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value: str) -> str:
        # Check the calendar date, while keeping MongoDB's required string type.
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def validate_shift(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must differ")
        return self


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: int = Field(
        default_factory=lambda: to_epoch_millis(datetime.now(timezone.utc)),
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )


class PunchInIn(PunchOutIn):
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
    except PyMongoError:
        raise HTTPException(status_code=503, detail="MongoDB unavailable") from None
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists") from None
    return serialize_employee(doc)


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q = {}
    if department is not None:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )
    return {"items": [serialize_employee(doc) for doc in items], "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")
    ts = datetime.fromtimestamp(body.punched_at // 1000, tz=timezone.utc)
    d = attendance_date(ts, emp["shift_start"], emp["shift_end"])
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"], d),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date") from None
    return serialize_attendance(doc)


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "employee not found")
    ts = datetime.fromtimestamp(body.punched_at // 1000, tz=timezone.utc)
    # Select the latest eligible punch, including closed records; do not skip
    # a closed recent shift to accidentally close an older open one.
    record = db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "punch_in": {"$type": "date", "$lte": ts}},
        sort=[("punch_in", -1)],
    )
    if record is None:
        raise HTTPException(404, "no punch-in found")
    if record.get("punch_out") is not None:
        raise HTTPException(409, "already punched out")
    elapsed = (ts - normalize_instant(record["punch_in"])).total_seconds()
    if elapsed <= 0 or elapsed > 24 * 60 * 60:
        raise RequestValidationError([{
            "type": "value_error",
            "loc": ("body", "punched_at"),
            "msg": "punch-out must be after punch-in and within 24 hours",
            "input": body.punched_at,
        }])
    hours = compute_work_hours(record["punch_in"], ts)
    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": record["_id"],
            "punch_out": None,
            "punch_in": record["punch_in"],
            "status": record["status"],
            "history": record.get("history"),
        },
        {"$set": {
            "punch_out": ts,
            "work_hours": hours,
            "overtime_minutes": compute_overtime(ts, emp["shift_start"], emp["shift_end"], record["date"]),
            "half_day": hours < 4.50,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "attendance record changed; retry the request")
    return serialize_attendance(updated)


def validate_calendar_date(value: str) -> str:
    date.fromisoformat(value)
    return value


CalendarDate = Annotated[
    str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$"), AfterValidator(validate_calendar_date)
]
AttendanceStatus = Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]
ATTENDANCE_SORT = [("date", -1), ("emp_code", 1)]


def attendance_list_query(emp_code, date_from, date_to, status):
    if date_from is not None and date_to is not None and date_from > date_to:
        raise RequestValidationError([{
            "type": "value_error",
            "loc": ("query", "date_to"),
            "msg": "date_to must be on or after date_from",
            "input": date_to,
        }])
    query = {}
    if emp_code is not None:
        query["emp_code"] = emp_code
    if date_from is not None or date_to is not None:
        query["date"] = {}
        if date_from is not None:
            query["date"]["$gte"] = date_from
        if date_to is not None:
            query["date"]["$lte"] = date_to
    if status is not None:
        query["status"] = status
    # Equality on employee or status leaves an indexed date order for pagination.
    index = "emp_code_1_date_1" if emp_code is not None else (
        "status_1_date_-1_emp_code_1" if status is not None else "date_-1_emp_code_1"
    )
    return query, index


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[CalendarDate] = None,
    date_to: Optional[CalendarDate] = None,
    status: Optional[AttendanceStatus] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query, index = attendance_list_query(emp_code, date_from, date_to, status)
    total = db.attendance_logs.count_documents(query, hint=index)
    page_docs = (
        db.attendance_logs.find(query, {"_id": 0})
        .sort(ATTENDANCE_SORT)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .hint(index)
    )
    return {
        "items": [serialize_attendance(doc) for doc in page_docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
