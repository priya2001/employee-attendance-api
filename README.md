# Employee Attendance & Analytics API

FastAPI + MongoDB implementation of the HROne assignment. All application code is in `app/main.py`; `openapi.yaml` is the supplied contract. All 12 API operations are implemented.

## Run

Requires Python 3.11+ and a running MongoDB 6.0+ server (local or Atlas).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MONGO_URI='mongodb://localhost:27017'
export MONGO_DB='attendance_db'
uvicorn app.main:app --port 8000
```

For Atlas, set `MONGO_URI` to your connection string. A local, untracked `.env` with `MONGO_URI` and `MONGO_DB` is also supported; real environment variables take priority. Never commit credentials.

Open http://localhost:8000/docs for Swagger UI. `/health` pings MongoDB and returns 200 when available, otherwise 503. Indexes are created automatically at startup; startup does not seed or delete records. Duplicate business keys already present in a database must be resolved before unique indexes can be created.

## Optional sample data

The original kit includes 6 employees and 9 attendance examples. To load them into a dedicated sample database:

```bash
python sample_seed.py
```

This script deletes existing documents in that database's `employees` and `attendance_logs` collections before inserting the samples. Do not run it against data you want to preserve or the grader's database.

## Contract and verification

Employees use `emp_code`; attendance uses `(emp_code, date)`. API instants are integer epoch milliseconds; MongoDB stores BSON datetimes. Calendar dates and shift times follow IST. Analytics use stored derived values and MongoDB aggregations.

`REVIEW.md` records starter fixes and verification results. `DECISIONS.md` explains indexes, concurrency, ties, headcount and scaling. Clean-install checks and isolated 100,000-record tests passed on Python 3.14.4 with MongoDB 7.0.26 and 8.2.7. The grader's hidden tests are not available. No known functionality is omitted.

Submit the public repository link using the instructions and deadline in the assignment email. Do not commit `.env`, secrets, virtual environments, a Dockerfile or generated database dumps.
