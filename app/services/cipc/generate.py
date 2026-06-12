"""CIPC Annual Return generator (Ticket 4g).

Returns list[CIPCAnnualInstance] without committing, mirroring the VAT201/EMP201
generators. A SEPARATE model from ObligationInstance, so it runs as a parallel
generation path (see regenerate_cipc).

Gating and timing:
  - Only entity types that file a CIPC AR (Pty Ltd, INC, NPC, CC) and that have an
    incorporation anniversary captured (cipc_anniversary_month + _day) generate an
    instance.
  - Surfacing: the AR appears to Tsego 45 days before the anniversary (~75 days before
    the deadline). We emit the CURRENT cycle — the most recent anniversary occurrence
    whose surface date (anniversary − 45 days) is on or before today. Because each
    anniversary's active window [anniversary − 45 days, next anniversary − 45 days)
    abuts the next with no gap, exactly one occurrence is current at any time, so an
    annual obligation yields exactly one instance (consistent with the current + 12
    month horizon used by VAT201/EMP201).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.services.cipc.due_dates import cipc_ar_due_date
from app.utils.dates import today_sast

# Entity types that file a CIPC Annual Return.
CIPC_FILING_TYPES = frozenset({EntityType.PTY_LTD, EntityType.INC, EntityType.NPC, EntityType.CC})

# Lead time before the anniversary at which the AR surfaces to Tsego.
_SURFACE_LEAD_DAYS = 45


def generate_cipc_annual(
    client: Client,
    today: date | None = None,
    assignee_id: int | None = None,
) -> list[CIPCAnnualInstance]:
    """Generate the current-cycle CIPC AR instance for a client.

    Returns the instance(s) WITHOUT adding them to a session — the caller
    (regenerate_cipc) decides whether to add/commit or diff against existing rows to
    avoid the (client_id, anniversary_date) unique-constraint violation.

    Returns [] when the client does not file a CIPC AR (wrong entity type) or has no
    incorporation anniversary captured. assignee_id is stamped onto the instance
    (centralised to Tsego); the caller resolves it.

    The today parameter exists solely for test determinism. In production, leave it as
    None and the function uses date.today().
    """
    if client.entity_type not in CIPC_FILING_TYPES:
        return []
    if client.cipc_anniversary_month is None or client.cipc_anniversary_day is None:
        return []

    if today is None:
        today = today_sast()

    month = client.cipc_anniversary_month
    day = client.cipc_anniversary_day
    # Look one year either side of today so the current cycle is found near either
    # year boundary. cipc_anniversary_day is validated to <= 28 for Feb, so every
    # candidate date is valid (no 29 Feb).
    candidates = [date(year, month, day) for year in (today.year - 1, today.year, today.year + 1)]
    surfaced = [a for a in candidates if a - timedelta(days=_SURFACE_LEAD_DAYS) <= today]
    if not surfaced:
        return []
    anniversary = max(surfaced)

    due = cipc_ar_due_date(client.entity_type, anniversary)
    return [
        CIPCAnnualInstance(
            client_id=client.id,
            anniversary_date=anniversary,
            due_date=due,
            assignee_id=assignee_id,
            # Set explicitly so callers see GENERATED on un-committed instances;
            # mapped_column(default=...) only applies at INSERT flush time.
            status=CIPCAnnualStatus.GENERATED,
        )
    ]
