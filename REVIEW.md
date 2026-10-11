# REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `health()` | Returned 200 without checking MongoDB, so an unavailable database appeared ready. | Simulate a MongoDB connection failure and call `GET /health`; the starter still returns 200. | Ping MongoDB before reporting readiness; catch `PyMongoError` and return 503 with a generic error detail. |

Also note anything you looked at and decided was **not** a defect, and why.
