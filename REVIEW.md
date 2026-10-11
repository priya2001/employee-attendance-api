# REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `health()` | Returned 200 without checking MongoDB, so an unavailable database appeared ready. | Simulate a MongoDB connection failure and call `GET /health`; the starter still returns 200. | Ping MongoDB before reporting readiness; catch `PyMongoError` and return 503 with a generic error detail. |
| 2 | `EmployeeIn` fields | Employee codes, names, emails and departments lacked contract validation. | Submit `emp_code="ABC"`, an empty name/department, an invalid email, or overlong text; these should return 422. | Added the contract's patterns and length limits using Pydantic fields. |
| 3 | `EmployeeIn.joined_on` | Accepted malformed and impossible calendar dates. | Submit `2026-02-30` or `2026-7-01`; both should return 422. | Validate the exact date format and actual calendar date, preserving the stored string type. |
| 4 | `EmployeeIn` shift fields | Accepted invalid shift times and identical start/end times. | Submit `25:00`, `9:30`, or equal start/end times; expect 422. A valid overnight shift must still pass. | Added HH:MM patterns and a model validator rejecting equal shift times; retained default and overnight shifts. |

| 5 | `create_employee()` and app startup | Check-then-insert allowed concurrent requests to create duplicate employee codes; no unique index enforced the requirement. | Send 8 simultaneous creates for the same code: exactly one must return 201, the others 409, with one stored document. | Create a unique `emp_code` index at startup and catch `DuplicateKeyError` on insert instead of relying on a prior lookup. Repeated startup safely reuses the index. |

Also note anything you looked at and decided was **not** a defect, and why.
