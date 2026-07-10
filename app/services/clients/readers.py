"""Spreadsheet readers for the client import — turn an .xlsx or .csv file into a list of
`SourceRow`s keyed by the file's *exact* header text.

Deliberately dumb: no field mapping, no validation, no Flask. It preserves the original
sheet row number (for the data-quality report), trims surrounding whitespace on every
cell, and never numeric-coerces text (so tax references keep their leading zeros). The
importer (`importer.py`) owns all meaning; this module only reads bytes into dicts.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import openpyxl


@dataclass(frozen=True)
class SourceRow:
    """One data row. `number` is the 1-based row number in the source sheet (so the report
    can point a human at the exact line); `values` is keyed by exact header text."""

    number: int
    values: dict[str, str | None]


def _clean(value: object) -> str | None:
    """Normalise a raw cell to a trimmed string or None. Integral floats become plain ints
    ("2.0" -> "2") so numbers read as text don't grow a ".0"; text is never coerced, so
    leading zeros survive. Empty / whitespace-only cells become None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip() or None


def _build(raw: list[tuple], header_row: int, overrides: dict[int, str] | None) -> list[SourceRow]:
    """Shared logic for both formats. `raw` is every row as a tuple (1-based row N is
    raw[N-1]). `overrides` maps a 1-based column number to a header name — used for the
    individuals file's unlabelled full-name column (col B has no header text)."""
    overrides = overrides or {}
    if len(raw) < header_row:
        return []

    # Map 0-based column index -> header name. Override wins even over a blank cell; an
    # unlabelled column with no override is dropped (e.g. the individuals file's blank col J).
    header_cells = raw[header_row - 1]
    headers: dict[int, str] = {}
    for i, cell in enumerate(header_cells):
        pos = i + 1
        if pos in overrides:
            headers[i] = overrides[pos]
        elif cell is not None and str(cell).strip():
            headers[i] = str(cell).strip()

    rows: list[SourceRow] = []
    for number, row in enumerate(raw[header_row:], start=header_row + 1):
        values: dict[str, str | None] = {}
        has_value = False
        for i, name in headers.items():
            value = _clean(row[i]) if i < len(row) else None
            if value is not None:
                has_value = True
            values[name] = value
        # Skip rows with no data in any mapped column — trailing blank rows are common
        # (the CIPC sheet has ~850 empty rows below the real 447).
        if has_value:
            rows.append(SourceRow(number=number, values=values))
    return rows


def read_rows(
    path: str | Path,
    *,
    sheet: str | None = None,
    header_row: int = 1,
    header_overrides: dict[int, str] | None = None,
) -> list[SourceRow]:
    """Read a source file into `SourceRow`s.

    `sheet` selects a worksheet by name (xlsx only; None = active sheet). `header_row` is
    the 1-based row holding the headers (rows above it, e.g. a title banner, are ignored).
    `header_overrides` names columns by 1-based position where the file has no header text.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in {".xlsx", ".xlsm"}:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            worksheet = workbook[sheet] if sheet else workbook.active
            raw = list(worksheet.iter_rows(values_only=True))
        finally:
            workbook.close()
        return _build(raw, header_row, header_overrides)

    if suffix == ".csv":
        # utf-8-sig strips a BOM if Excel wrote one.
        with path.open(newline="", encoding="utf-8-sig") as handle:
            raw = [tuple(row) for row in csv.reader(handle)]
        return _build(raw, header_row, header_overrides)

    raise ValueError(f"Unsupported source file type {suffix!r}: expected .xlsx, .xlsm, or .csv")
