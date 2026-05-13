"""Persist newly-generated obligation instances for a client, skipping any
that would collide with the existing (client_id, obligation_type, period_end)
unique key.

This is the quick-win prelude to the full Ticket 3c regenerate-with-preservation
service. It does NOT recompute due dates on existing PENDING rows; it only
appends rows for periods that don't yet exist for this client.

Caller owns the commit — generate_and_persist only stages new rows on the
session.
"""

from __future__ import annotations

from app.extensions import db
from app.models.client import Client
from app.models.obligation import ObligationInstance
from app.services.obligations.vat201 import generate_vat201


def generate_and_persist(client: Client) -> int:
    """Generate VAT201 instances for the client and stage the new ones.

    Skips any generated instance whose (obligation_type, period_end) already
    exists for this client — prevents violating the
    uq_obligation_instances_client_type_period unique constraint when re-run.

    Returns the count of new instances added to the session.
    """
    existing_keys: set[tuple] = {
        (row.obligation_type, row.period_end)
        for row in db.session.execute(
            db.select(
                ObligationInstance.obligation_type,
                ObligationInstance.period_end,
            ).where(ObligationInstance.client_id == client.id)
        )
    }

    generated = generate_vat201(client)
    new_instances = [
        inst
        for inst in generated
        if (inst.obligation_type, inst.period_end) not in existing_keys
    ]
    db.session.add_all(new_instances)
    return len(new_instances)
