"""Bulk-import the firm's canonical client book from a CSV rowset.

Upsert keyed on ``registration_number``: a row whose reg number is unseen is
inserted; a matching client is updated field-by-field; a row that changes
nothing is counted UNCHANGED. Per-row validation errors never abort the file —
each row is flushed inside its own SAVEPOINT (``begin_nested``), so a bad row
rolls back only itself while the rest of the run proceeds. Errors are collected
against their ``source_row`` for the exit report.

This module is pure of Flask and does NOT commit — the caller (the ``flask
clients import`` command) owns the transaction, committing on success or rolling
back for ``--dry-run``. That mirrors the regenerate services' "caller owns the
commit" contract.

The CSV contract (exact headers) is documented in the ticket. Columns
``owner_id_number`` / ``owner_id_type`` have no model field yet and are ignored;
``source_row`` is read only for error reporting, never stored.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.staff import Staff

_TRUE_TOKENS = frozenset({"yes", "y", "true", "t", "1"})
_FALSE_TOKENS = frozenset({"no", "n", "false", "f", "0"})

# EntityType is matched by its display value ("Pty Ltd", "CC", ...), case-insensitively.
_ENTITY_BY_VALUE = {member.value.lower(): member for member in EntityType}

# The Client attributes populated from the CSV. Update detection compares exactly these.
_CONTRACT_FIELDS = (
    "legal_name",
    "entity_type",
    "registration_number",
    "known_as",
    "trading_name",
    "has_income_tax",
    "has_provisional_tax",
    "has_vat",
    "vat_category",
    "vat_submission_method",
    "has_paye",
    "has_dividends_tax",
    "year_end_month",
    "year_end_day",
    "cipc_anniversary_month",
    "cipc_anniversary_day",
    "allocated_staff_id",
    "contact_person",
    "email",
    "cc_email",
    "street1",
    "postcode",
    "active",
)


@dataclass
class RowError:
    """A single skipped row, tagged with its CSV ``source_row`` for the report."""

    source_row: str
    message: str


@dataclass
class ImportReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[RowError] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Scalar field parsers. Each raises ValueError with a human message on bad data.
# --------------------------------------------------------------------------- #
def _text(row: Mapping[str, str], key: str) -> str | None:
    """Trimmed cell, or None when blank."""
    raw = (row.get(key) or "").strip()
    return raw or None


def _bool(row: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = (row.get(key) or "").strip().lower()
    if raw == "":
        return default
    if raw in _TRUE_TOKENS:
        return True
    if raw in _FALSE_TOKENS:
        return False
    raise ValueError(f"{key}: expected Yes/No, got {raw!r}")


def _int(row: Mapping[str, str], key: str) -> int | None:
    raw = (row.get(key) or "").strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{key}: expected an integer, got {raw!r}") from None


def _entity_type(row: Mapping[str, str]) -> EntityType:
    raw = (row.get("entity_type") or "").strip()
    if raw == "":
        raise ValueError("entity_type is required")
    member = _ENTITY_BY_VALUE.get(raw.lower())
    if member is None:
        valid = ", ".join(m.value for m in EntityType)
        raise ValueError(f"entity_type {raw!r} is not one of: {valid}")
    return member


def _vat_category(row: Mapping[str, str]) -> VatCategory | None:
    raw = (row.get("vat_category") or "").strip()
    if raw == "":
        return None
    try:
        return VatCategory[raw.upper()]
    except KeyError:
        valid = ", ".join(m.name for m in VatCategory)
        raise ValueError(f"vat_category {raw!r} is not one of: {valid}") from None


def _vat_method(row: Mapping[str, str]) -> VatSubmissionMethod | None:
    raw = (row.get("vat_submission_method") or "").strip()
    if raw == "":
        return None
    try:
        return VatSubmissionMethod[raw.upper()]
    except KeyError:
        valid = ", ".join(m.name for m in VatSubmissionMethod)
        raise ValueError(f"vat_submission_method {raw!r} is not one of: {valid}") from None


def _resolve_staff(row: Mapping[str, str], staff: list[Staff]) -> Staff | None:
    """Resolve ``allocated_staff`` against active staff by code or full-name prefix,
    case-insensitively. Blank -> None (unallocated). A non-blank name that matches
    nothing, or is ambiguous, is a per-row error."""
    name = (row.get("allocated_staff") or "").strip()
    if name == "":
        return None
    low = name.lower()
    for member in staff:
        if member.code.lower() == low:
            return member
    matches = [m for m in staff if m.full_name.lower().startswith(low)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        codes = ", ".join(m.code for m in matches)
        raise ValueError(f"allocated_staff {name!r} is ambiguous (matches {codes})")
    raise ValueError(f"allocated_staff {name!r} did not match any active staff")


def _build_values(row: Mapping[str, str], staff: list[Staff]) -> dict[str, object]:
    """Map one CSV row to a dict of Client attribute values. Raises ValueError on
    bad data. The reg number (upsert key) is required and non-blank."""
    reg = _text(row, "registration_number")
    if reg is None:
        raise ValueError("registration_number is required (used as the upsert key)")

    has_vat = _bool(row, "has_vat", default=False)
    # has_vat=No forces both VAT fields to None regardless of the CSV cells.
    vat_category = _vat_category(row) if has_vat else None
    vat_method = _vat_method(row) if has_vat else None

    resolved_staff = _resolve_staff(row, staff)

    return {
        "legal_name": _text(row, "legal_name"),
        "entity_type": _entity_type(row),
        "registration_number": reg,
        "known_as": _text(row, "known_as"),
        "trading_name": _text(row, "trading_name"),
        "has_income_tax": _bool(row, "has_income_tax", default=False),
        "has_provisional_tax": _bool(row, "has_provisional_tax", default=False),
        "has_vat": has_vat,
        "vat_category": vat_category,
        "vat_submission_method": vat_method,
        "has_paye": _bool(row, "has_paye", default=False),
        "has_dividends_tax": _bool(row, "has_dividends_tax", default=False),
        "year_end_month": _int(row, "year_end_month"),
        "year_end_day": _int(row, "year_end_day"),
        "cipc_anniversary_month": _int(row, "cipc_anniversary_month"),
        "cipc_anniversary_day": _int(row, "cipc_anniversary_day"),
        "allocated_staff_id": resolved_staff.id if resolved_staff else None,
        "contact_person": _text(row, "contact_person"),
        "email": _text(row, "email"),
        "cc_email": _text(row, "cc_email"),
        "street1": _text(row, "street1"),
        "postcode": _text(row, "postcode"),
        "active": _bool(row, "active", default=True),
    }


def import_rows(rows: Iterable[Mapping[str, str]]) -> ImportReport:
    """Upsert every CSV row into the clients table. Does NOT commit.

    Keyed on registration_number: insert / update-changed-fields / unchanged.
    Each write is flushed inside a SAVEPOINT so a failing row is rolled back
    on its own and reported (with its source_row) without aborting the run.
    """
    report = ImportReport()

    staff = list(db.session.scalars(db.select(Staff).where(Staff.active.is_(True))))
    existing_by_reg: dict[str, Client] = {
        client.registration_number: client
        for client in db.session.scalars(db.select(Client))
        if client.registration_number
    }

    for row in rows:
        source_row = (row.get("source_row") or "").strip()
        try:
            values = _build_values(row, staff)
        except ValueError as exc:
            report.errors.append(RowError(source_row, str(exc)))
            continue

        reg = values["registration_number"]
        existing = existing_by_reg.get(reg)

        if existing is None:
            try:
                with db.session.begin_nested():
                    client = Client(**values)
                    db.session.add(client)
                    db.session.flush()
            except (ValueError, SQLAlchemyError) as exc:
                report.errors.append(RowError(source_row, str(exc)))
                continue
            existing_by_reg[reg] = client
            report.added += 1
            continue

        changed = {
            key: values[key] for key in _CONTRACT_FIELDS if getattr(existing, key) != values[key]
        }
        if not changed:
            report.unchanged += 1
            continue

        # Snapshot so we can restore in-memory state if the flush is rejected — a
        # SAVEPOINT rollback reverts the DB but not the Python object's attributes.
        originals = {key: getattr(existing, key) for key in changed}
        try:
            with db.session.begin_nested():
                for key, value in changed.items():
                    setattr(existing, key, value)
                db.session.flush()
        except (ValueError, SQLAlchemyError) as exc:
            for key, value in originals.items():
                setattr(existing, key, value)
            report.errors.append(RowError(source_row, str(exc)))
            continue
        report.updated += 1

    return report
