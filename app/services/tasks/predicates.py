from __future__ import annotations

from datetime import date

from sqlalchemy import ColumnElement, and_

from app.models.task import Task, TaskStatus

# OVERDUE for a task is never stored — it is a read-time predicate mirroring the
# obligations rule (app/services/obligations/predicates.py): OPEN AND
# due_date < today_in_Africa_Johannesburg. Strict less-than — a task due today is
# "due today", not yet overdue. Like the obligations module, the task list will
# evaluate this in two contexts (Python per-row badge AND a SQL WHERE clause for
# the future filter UI), so we expose two co-located functions instead of a
# hybrid_property whose .expression() half would need a class-method shim that
# obscures the call site. `today` is always a required parameter so callers pass
# today_sast() explicitly — no implicit module-level clock state.


def is_overdue(task: Task, today: date) -> bool:
    return task.status is TaskStatus.OPEN and task.due_date < today


def overdue_filter(today: date) -> ColumnElement[bool]:
    return and_(Task.status == TaskStatus.OPEN, Task.due_date < today)
