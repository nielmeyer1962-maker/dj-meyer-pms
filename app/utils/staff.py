from __future__ import annotations

from app.extensions import db
from app.models.staff import Staff

# Shared filter helpers used by both the obligations dashboard and the tasks
# blueprint: the canonical "active staff" query (ordered by code) and the
# sentinel value standing in for the Unassigned filter option. Keeping them in
# one place means both blueprints agree on what "active staff" means and on the
# magic string that distinguishes "unassigned" from "no filter".
UNASSIGNED_SENTINEL = "__unassigned__"


def get_active_staff() -> list[Staff]:
    return db.session.scalars(
        db.select(Staff).where(Staff.active.is_(True)).order_by(Staff.code)
    ).all()
