# Decisions

1. **Indexes.** Unique employee `emp_code` and attendance `(emp_code, date)` indexes enforce identity. Attendance `(date descending, emp_code)` supports listing and monthly leaderboard scans; `(status, date descending, emp_code)` supports status-filtered pages. `(emp_code, punch_in descending)` finds the latest eligible punch. Employee `(joined_on, department)` and `(department, joined_on)` support period headcounts and department queries. Employee-code indexes also support joins. I rejected a standalone status index: it would not provide the required date ordering.

2. **Punch-in race.** Both requests validate input, load the employee and calculate the attendance date. Each attempts an insert. MongoDB's unique compound index allows one insert. That request returns 201; the other catches DuplicateKeyError and returns 409. A preliminary existence check is unnecessary.

3. **Ties.** MongoDB ranks total lateness before filtering rank <= limit. Tied employees share a rank; later ranks skip positions. All cutoff ties remain, ordered by employee code.

4. **Headcount.** Department summaries start from employees who joined by month-end. Each contributes one headcount even when its attendance lookup is empty.

5. **At 100x data.** Maintain daily employee summaries incrementally, including corrections, to reduce repeated aggregation work. Keep raw logs as the audit source and measure query plans before changing indexes.
