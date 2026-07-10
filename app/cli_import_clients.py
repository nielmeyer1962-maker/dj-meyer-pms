"""`flask import-clients …` CLI — dry-run import of the firm's client source lists.

Chunk 1: parse, validate, and print a data-quality report. No database writes (the
--commit path lands in Chunk 2). Reads existing natural keys so the report can show
would-insert vs would-update on re-runs.
"""

from __future__ import annotations

import click
from flask.cli import AppGroup

from app.extensions import db
from app.models.client import Client
from app.models.staff import Staff
from app.services.clients import importer
from app.services.clients.readers import read_rows

import_clients_cli = AppGroup(
    "import-clients", help="Dry-run import of clients from source spreadsheets."
)

# Per-kind source layout + the Client column holding that kind's natural key.
_KIND_CONFIG = {
    importer.COMPANIES: {
        "sheet": "CIPC List",
        "header_row": 1,
        "header_overrides": None,
        "key_field": "registration_number",
    },
    importer.INDIVIDUALS: {
        "sheet": "FINAL FINAL IT12 LIST",
        "header_row": 2,
        "header_overrides": {2: "full_name"},  # col B has no header
        "key_field": "id_number",
    },
}


def _existing_keys(key_field: str) -> frozenset[str]:
    """Natural keys already in the clients table (for would-insert vs would-update)."""
    column = getattr(Client, key_field)
    return frozenset(db.session.scalars(db.select(column).where(column.is_not(None))).all())


def _dry_run(kind: str, path: str, sheet: str | None, header_row: int | None) -> None:
    config = _KIND_CONFIG[kind]
    rows = read_rows(
        path,
        sheet=sheet or config["sheet"],
        header_row=header_row or config["header_row"],
        header_overrides=config["header_overrides"],
    )
    staff = db.session.scalars(db.select(Staff)).all()
    existing = _existing_keys(config["key_field"])
    report = importer.parse_file(rows, kind, staff, existing_keys=existing)
    click.echo(report.render())


@import_clients_cli.command(importer.COMPANIES)
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet", default=None, help="Worksheet name (xlsx only).")
@click.option("--header-row", type=int, default=None, help="1-based header row override.")
def companies(path: str, sheet: str | None, header_row: int | None) -> None:
    """Dry-run import of the CIPC companies list from PATH (default sheet 'CIPC List')."""
    _dry_run(importer.COMPANIES, path, sheet, header_row)


@import_clients_cli.command(importer.INDIVIDUALS)
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet", default=None, help="Worksheet name (xlsx only).")
@click.option("--header-row", type=int, default=None, help="1-based header row override.")
def individuals(path: str, sheet: str | None, header_row: int | None) -> None:
    """Dry-run import of the IT12 individuals list from PATH (default sheet
    'FINAL FINAL IT12 LIST')."""
    _dry_run(importer.INDIVIDUALS, path, sheet, header_row)
