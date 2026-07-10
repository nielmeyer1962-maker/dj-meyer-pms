"""Client-import write layer (Chunk 2): apply a parsed `ImportReport` to the database as a
natural-key upsert.

Kept apart from `importer.py` (which stays pure and Flask-free): this half is the only
place that touches SQLAlchemy `Client` rows and a session. It never deletes, only ever
overwrites the fields the import explicitly maps (manual edits to unmapped columns survive
re-runs), and treats data-quality issues as flags, not errors — a flagged row still loads.

The caller owns the transaction: `apply_report` stages inserts/updates on the session and
returns an `ApplyResult`; the CLI wraps the whole file in one commit (rollback on error).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.models.client import Client, VatSubmissionMethod

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.clients.importer import ImportReport, ParsedRow

# The source lists carry no VAT submission-method column, but the model pairs
# vat_category + vat_submission_method (and forbids either when has_vat is False). Imported
# VAT clients default to eFiling — the SA norm — on insert and where no method has been set;
# a method a human later chooses is preserved on re-import.
DEFAULT_VAT_METHOD = VatSubmissionMethod.EFILING

# Set as a group by _apply_vat_fields, so they are excluded from the generic field copy.
_VAT_FIELDS = frozenset({"has_vat", "vat_category", "vat_submission_method"})


@dataclass
class ApplyResult:
    """What a `--commit` run actually did. `skipped` holds rows that could not be written
    (a new client with no resolvable entity type) as (row number, name, reason) — reported,
    never silently dropped."""

    inserted: int = 0
    updated: int = 0
    skipped: list[tuple[int, str, str]] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            "  inserted:                " + str(self.inserted),
            "  updated:                 " + str(self.updated),
            "  skipped (unwritable):    " + str(len(self.skipped)),
        ]
        if self.skipped:
            lines.append("\nSkipped rows (could not be written):")
            for number, name, reason in self.skipped:
                lines.append(f"  row {number}  {name or '(no name)'}  - {reason}")
        return "\n".join(lines)


def _apply_vat_fields(client: Client, fields: dict[str, object]) -> None:
    """Set has_vat / vat_category / vat_submission_method together so the model's VAT
    pairing invariants hold. Individuals carry no VAT info (no has_vat key) — leave the
    client's VAT columns untouched. A manually chosen submission method is preserved."""
    if "has_vat" not in fields:
        return
    has_vat = bool(fields["has_vat"])
    client.has_vat = has_vat
    if has_vat:
        client.vat_category = fields.get("vat_category")  # type: ignore[assignment]
        if client.vat_submission_method is None:
            client.vat_submission_method = DEFAULT_VAT_METHOD
    else:
        client.vat_category = None
        client.vat_submission_method = None


def _apply_fields(client: Client, row: ParsedRow) -> None:
    """Copy the row's mapped fields onto `client`. entity_type lives on the row (not in
    `fields`) and is only overwritten when resolved — a malformed reg number leaves an
    existing client's type intact. VAT columns are handled as a paired group."""
    if row.entity_type is not None:
        client.entity_type = row.entity_type
    for attr, value in row.fields.items():
        if attr not in _VAT_FIELDS:
            setattr(client, attr, value)
    _apply_vat_fields(client, row.fields)


def apply_report(
    report: ImportReport, existing_by_key: dict[str, Client], session: Session
) -> ApplyResult:
    """Stage the report's inserts and updates on `session` and return the counts.

    Inserts a new `Client` per to-insert row (skipping any whose entity type could not be
    derived — the DB requires one); updates the mapped fields on each existing row matched
    by natural key. Does not commit — the caller does, wrapping the whole file in one
    transaction so an unexpected error rolls the lot back."""
    result = ApplyResult()

    for row in report.to_insert:
        name = str(row.fields.get("legal_name") or "")
        if row.entity_type is None:
            result.skipped.append(
                (row.number, name, "no entity type (unresolved registration number)")
            )
            continue
        client = Client(entity_type=row.entity_type)
        _apply_fields(client, row)
        session.add(client)
        result.inserted += 1

    for row in report.to_update:
        client = existing_by_key.get(row.natural_key) if row.natural_key else None
        if client is None:
            name = str(row.fields.get("legal_name") or "")
            result.skipped.append((row.number, name, "existing row not found for update"))
            continue
        _apply_fields(client, row)
        result.updated += 1

    return result
