"""Client-import mapping layer: turn reader `SourceRow`s into `ParsedRow`s carrying mapped
Client fields, a natural key, and per-row data-quality issues.

Pure and Flask-free (Staff rows are passed in, never queried here). Header names are matched
by exact literal constant — the CIPC/IT12 headers are messy (double spaces, stray
underscores) and are reproduced verbatim below. The orchestration/report layer (review b)
consumes ParsedRow; this half only maps and derives.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.models.client import EntityType, VatCategory

if TYPE_CHECKING:
    from app.models.staff import Staff
    from app.services.clients.readers import SourceRow

# --- Exact source headers (verbatim — do not tidy the spellings) ---

# Companies: TSEGO_CIPC_LIST_updated.xlsx, sheet "CIPC List", headers row 1.
CO_MONTH = "CIPC Month"
CO_NAME = "Client_field"
CO_REG = "Reg Number"
CO_CONTACT = "Director/Owner"
CO_DUE_DAY = "Due Day"
CO_STAFF = "Staff Member"
CO_EMAIL = "E  mail address"  # two spaces, verbatim
CO_VAT = "is_Vat_category"
CO_PAYE = "is_paye_registered"
CO_PROVISIONAL = "is_ provisiona_l taxpayer"  # spacing/underscores verbatim
CO_YEAR_END = "Year_end_month"
# Not mapped: "ID Number" (director ID — Ticket 7), "Business address",
# "Industry Code" (Ticket 4a), "has_sole proprietor business" (empty for companies).

# Individuals: FINAL FINAL IT12 LIST sheet, headers row 2, col B unlabelled (override).
IN_NAME = "Surname, Initials"
IN_FULLNAME = "full_name"  # header_overrides={2: "full_name"}
IN_ID = "ID Number"
IN_TAXREF = "Income Tax number"
IN_EMAIL = "Email address"
IN_STAFF = "Staff member"
IN_SOURCE = "Source"  # report metadata only; not stored
IN_SOLEPROP = "has-sole-prop-business"
IN_PROVISIONAL = "is-provisional-taxpayer"


@dataclass
class ParsedRow:
    """A mapped source row. `fields` are Client column kwargs; `natural_key` is the
    normalised reg number (companies) or ID (individuals) used for dup-detection and the
    Chunk-2 upsert; `issues` are human-readable data-quality messages for this row."""

    number: int
    entity_type: EntityType | None
    natural_key: str | None
    fields: dict[str, object] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


# --- small derivation helpers ---

_MONTHS = (
    {name.lower(): num for num, name in enumerate(calendar.month_name) if name}
    | {abbr.lower(): num for num, abbr in enumerate(calendar.month_abbr) if abbr}
    | {"sept": 9}
)


def month_number(text: str | None) -> int | None:
    """Month name or 3-letter abbrev -> 1–12, else None."""
    if not text:
        return None
    return _MONTHS.get(text.strip().lower())


def derive_year_end(text: str | None) -> tuple[int | None, int | None, str | None]:
    """Text month -> (month, calendar month-end day, issue). Feb -> 2/28 (non-leap)."""
    if not text:
        return None, None, None  # absent, not an error
    month = month_number(text)
    if month is None:
        return None, None, f"unrecognised year-end month {text.strip()!r}"
    _, last_day = calendar.monthrange(2001, month)  # non-leap so Feb caps at 28
    return month, last_day, None


_TRUE_FLAGS = {"y", "yes", "true", "1"}


def parse_flag(value: str | None) -> bool:
    """Yes/Y/True/1 (any case) -> True; blank/anything else -> False."""
    return bool(value) and value.strip().casefold() in _TRUE_FLAGS


_REG_RE = re.compile(r"^\s*(\d{4})\s*/\s*(\d{1,6})\s*/\s*(\d{1,2})\s*$")
_REG_SUFFIX = {
    "07": EntityType.PTY_LTD,
    "23": EntityType.CC,
    "08": EntityType.NPC,
    "21": EntityType.INC,
    "06": EntityType.NPC,  # Section 21 (old-Act NPC)
}


def normalize_reg_number(raw: str | None) -> tuple[str | None, str | None]:
    """Normalise to YYYY/NNNNNN/NN (pad serial to 6, suffix to 2). Malformed -> raw + issue."""
    if not raw or not raw.strip():
        return None, "missing registration number"
    match = _REG_RE.match(raw)
    if not match:
        return raw.strip(), f"malformed registration number {raw.strip()!r}"
    year, serial, suffix = match.groups()
    return f"{year}/{int(serial):06d}/{suffix.zfill(2)}", None


def derive_entity_type(reg_number: str) -> tuple[EntityType | None, str | None]:
    """Map the reg-number suffix to an entity type. Unknown suffix -> None + issue."""
    suffix = reg_number.rsplit("/", 1)[-1]
    entity_type = _REG_SUFFIX.get(suffix)
    if entity_type is None:
        return None, f"unknown registration suffix /{suffix}"
    return entity_type, None


def classify_id_number(raw: str | None) -> tuple[str | None, str | None]:
    """13-digit SA ID and passports accepted as-is; registration-shaped values flagged."""
    if not raw or not raw.strip():
        return None, "missing ID number"
    cleaned = "".join(raw.split())  # drop all internal whitespace
    if "/" in cleaned or _REG_RE.match(raw):
        return cleaned, f"registration-shaped value in ID column {raw.strip()!r}"
    # 13 digits = SA ID; anything else = passport/other, accepted without a flag.
    return cleaned, None


_VAT_NOT_REGISTERED = {"not registered", "none", "no"}
_VAT_OWN = {"own"}


def derive_vat(value: str | None) -> tuple[bool, VatCategory | None, str | None, str | None]:
    """Map the messy is_Vat_category column -> (has_vat, category, note, issue).

    A-E            -> (True, category, None, None)
    blank / "Not registered" -> (False, None, None, None)   # not our VAT work, silent
    "Own"          -> (False, None, "handles own VAT", None) # client files own VAT
    anything else  -> (False, None, None, issue)             # genuinely unexpected
    """
    if not value or not value.strip():
        return False, None, None, None
    text = value.strip()
    key = text.casefold()
    if key in _VAT_OWN:
        return False, None, "handles own VAT", None
    if key in _VAT_NOT_REGISTERED:
        return False, None, None, None
    try:
        return True, VatCategory[text.upper()], None, None
    except KeyError:
        return False, None, None, f"unrecognised VAT value {text!r}"


def _parse_day(value: str | None) -> tuple[int | None, str | None]:
    if not value or not value.strip():
        return None, None
    try:
        day = int(float(value))
    except ValueError:
        return None, f"non-numeric day {value.strip()!r}"
    if not 1 <= day <= 31:
        return None, f"day out of range {value.strip()!r}"
    return day, None


# --- staff-name index ---


def build_staff_index(staff: Iterable[Staff]) -> dict[str, int | None]:
    """Case-insensitive, trimmed alias -> staff.id. Each staff contributes full_name,
    first-name token, and code. An alias claimed by two different staff maps to None
    (ambiguous) so lookup leaves the client unallocated rather than mis-assigning."""
    index: dict[str, int | None] = {}

    def add(alias: str | None, staff_id: int) -> None:
        if not alias or not alias.strip():
            return
        key = alias.strip().casefold()
        if key in index and index[key] != staff_id:
            index[key] = None  # ambiguous
        else:
            index.setdefault(key, staff_id)

    for member in staff:
        add(member.full_name, member.id)
        if member.full_name:
            add(member.full_name.split()[0], member.id)  # first-name token
        add(member.code, member.id)
    return index


def lookup_staff(name: str | None, index: dict[str, int | None]) -> tuple[int | None, str | None]:
    """Resolve a source staff name to a staff.id. Blank/unknown/ambiguous -> None + issue."""
    if not name or not name.strip():
        return None, "no staff member specified (unallocated)"
    key = name.strip().casefold()
    if key not in index:
        return None, f"unknown staff member {name.strip()!r} (left unallocated)"
    staff_id = index[key]
    if staff_id is None:
        return None, f"ambiguous staff member {name.strip()!r} (left unallocated)"
    return staff_id, None


# --- per-file mappers ---


def map_company_row(
    row_number: int, values: dict[str, str | None], staff_index: dict[str, int | None]
) -> ParsedRow:
    """Map one CIPC company row. Assumes a real row (non-blank company name); the
    orchestration layer skips template/junk rows before calling this."""
    issues: list[str] = []
    fields: dict[str, object] = {"legal_name": values.get(CO_NAME), "has_income_tax": True}

    reg, reg_issue = normalize_reg_number(values.get(CO_REG))
    fields["registration_number"] = reg
    if reg_issue:
        issues.append(reg_issue)
    entity_type: EntityType | None = None
    if reg and not reg_issue:
        entity_type, et_issue = derive_entity_type(reg)
        if et_issue:
            issues.append(et_issue)

    month = month_number(values.get(CO_MONTH))
    day, day_issue = _parse_day(values.get(CO_DUE_DAY))
    if day_issue:
        issues.append(day_issue)
    # month/day must travel together (model invariant); flag a lone half.
    if (month is None) != (day is None):
        issues.append("CIPC anniversary month and day must both be present")
        month = day = None
    fields["cipc_anniversary_month"] = month
    fields["cipc_anniversary_day"] = day

    ye_month, ye_day, ye_issue = derive_year_end(values.get(CO_YEAR_END))
    if ye_issue:
        issues.append(ye_issue)
    fields["year_end_month"] = ye_month
    fields["year_end_day"] = ye_day

    has_vat, vat_category, vat_note, vat_issue = derive_vat(values.get(CO_VAT))
    fields["has_vat"] = has_vat
    fields["vat_category"] = vat_category
    if vat_note:
        issues.append(vat_note)
    if vat_issue:
        issues.append(vat_issue)
    # NB: vat_submission_method deliberately unset here — the source has no such column and
    # the model pairs category+method. Resolved as a Chunk-2 (--commit) decision, not here.

    fields["has_paye"] = parse_flag(values.get(CO_PAYE))
    fields["has_provisional_tax"] = parse_flag(values.get(CO_PROVISIONAL))
    fields["contact_person"] = values.get(CO_CONTACT)
    fields["email"] = values.get(CO_EMAIL)

    staff_id, staff_issue = lookup_staff(values.get(CO_STAFF), staff_index)
    fields["allocated_staff_id"] = staff_id
    if staff_issue:
        issues.append(staff_issue)

    return ParsedRow(
        number=row_number,
        entity_type=entity_type,
        natural_key=reg,
        fields=fields,
        issues=issues,
    )


def map_individual_row(
    row_number: int, values: dict[str, str | None], staff_index: dict[str, int | None]
) -> ParsedRow:
    """Map one IT12 individual row. Assumes a real row (non-blank Surname, Initials)."""
    issues: list[str] = []
    fields: dict[str, object] = {
        "legal_name": values.get(IN_NAME),
        "known_as": values.get(IN_FULLNAME),
    }

    id_number, id_issue = classify_id_number(values.get(IN_ID))
    fields["id_number"] = id_number
    if id_issue:
        issues.append(id_issue)

    tax_ref = values.get(IN_TAXREF)
    fields["tax_ref"] = tax_ref
    fields["has_income_tax"] = bool(tax_ref)  # spec: income-tax registered where a ref exists

    fields["email"] = values.get(IN_EMAIL)

    sole_prop_business = values.get(IN_SOLEPROP)
    if sole_prop_business:
        entity_type = EntityType.SOLE_PROP
        fields["trading_name"] = sole_prop_business
    else:
        entity_type = EntityType.INDIVIDUAL

    fields["has_provisional_tax"] = parse_flag(values.get(IN_PROVISIONAL))

    staff_id, staff_issue = lookup_staff(values.get(IN_STAFF), staff_index)
    fields["allocated_staff_id"] = staff_id
    if staff_issue:
        issues.append(staff_issue)

    return ParsedRow(
        number=row_number,
        entity_type=entity_type,
        natural_key=id_number,
        fields=fields,
        issues=issues,
    )


# --- orchestration + report ---

COMPANIES = "companies"
INDIVIDUALS = "individuals"

_NAME_HEADER = {COMPANIES: CO_NAME, INDIVIDUALS: IN_NAME}
_MAPPER = {COMPANIES: map_company_row, INDIVIDUALS: map_individual_row}


@dataclass
class ImportReport:
    """Outcome of a dry-run parse. `to_insert`/`to_update` are the rows that would load
    (classified against `existing_keys`); `duplicates` are (row, name, key) tuples skipped
    because their natural key already appeared earlier in the same file."""

    kind: str
    source_rows: int  # non-empty rows read from the sheet
    real_rows: int  # rows with a name (after junk-skip)
    to_insert: list[ParsedRow] = field(default_factory=list)
    to_update: list[ParsedRow] = field(default_factory=list)
    duplicates: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def flagged(self) -> list[ParsedRow]:
        return [row for row in (self.to_insert + self.to_update) if row.issues]

    def render(self) -> str:
        lines = [
            f"Client import - {self.kind} (DRY RUN - no changes written)",
            f"  source rows (non-empty): {self.source_rows}",
            f"  real rows (named):       {self.real_rows}",
            f"  would insert:            {len(self.to_insert)}",
            f"  would update:            {len(self.to_update)}",
            f"  skipped duplicates:      {len(self.duplicates)}",
            f"  flagged (data-quality):  {len(self.flagged)}",
        ]
        if self.flagged:
            lines.append("\nData-quality issues:")
            for row in sorted(self.flagged, key=lambda r: r.number):
                name = row.fields.get("legal_name") or "(no name)"
                lines.append(f"  row {row.number}  {name}")
                lines.extend(f"      - {issue}" for issue in row.issues)
        if self.duplicates:
            lines.append("\nSkipped duplicates (natural key already seen in this file):")
            for number, name, key in self.duplicates:
                lines.append(f"  row {number}  {name or '(no name)'}  [{key}]")
        return "\n".join(lines)


def parse_file(
    rows: Iterable[SourceRow],
    kind: str,
    staff: Iterable[Staff],
    existing_keys: frozenset[str] = frozenset(),
) -> ImportReport:
    """Map every real row, detect intra-file duplicate natural keys, classify insert vs
    update against `existing_keys`, and compose each row's data_quality_note. No DB writes —
    the caller decides whether to commit (Chunk 2)."""
    if kind not in _MAPPER:
        raise ValueError(f"unknown import kind {kind!r}: expected 'companies' or 'individuals'")
    name_header = _NAME_HEADER[kind]
    mapper = _MAPPER[kind]
    staff_index = build_staff_index(staff)

    rows = list(rows)
    # Junk-row filter: a row without a name is a template/blank line, not a client
    # (the CIPC sheet carries ~850 of these below the real 447).
    real = [row for row in rows if row.values.get(name_header)]
    parsed = [mapper(row.number, row.values, staff_index) for row in real]

    # Intra-file duplicates: the first row with a key loads; later rows sharing it are
    # skipped (never silently merged) and the first row is flagged so the pair surfaces.
    seen: dict[str, ParsedRow] = {}
    loaded: list[ParsedRow] = []
    duplicates: list[tuple[int, str, str]] = []
    for row in parsed:
        key = row.natural_key
        if key and key in seen:
            duplicates.append((row.number, row.fields.get("legal_name") or "", key))
            seen[key].issues.append(f"shares natural key {key} with row {row.number} (skipped)")
            continue
        if key:
            seen[key] = row
        loaded.append(row)

    report = ImportReport(
        kind=kind, source_rows=len(rows), real_rows=len(real), duplicates=duplicates
    )
    for row in loaded:
        if row.issues:
            row.fields["data_quality_note"] = "; ".join(row.issues)
        if row.natural_key and row.natural_key in existing_keys:
            report.to_update.append(row)
        else:
            report.to_insert.append(row)
    return report
