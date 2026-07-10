"""`flask import-clients …` CLI — import the firm's client source lists.

Dry-run is the default: parse, validate, and print a data-quality report without writing.
`--commit` applies the parse as a natural-key upsert in one transaction (rollback on any
unexpected error). Either way the full report is also written to a timestamped file under
`var/import-reports/` as an audit trail.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
from flask import current_app
from flask.cli import AppGroup

from app.extensions import db
from app.models.client import Client
from app.models.staff import Staff
from app.services.clients import importer, writer
from app.services.clients.readers import read_rows

import_clients_cli = AppGroup(
    "import-clients", help="Import clients from source spreadsheets (dry-run by default)."
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


def _existing_by_key(key_field: str) -> dict[str, Client]:
    """Map each existing client's natural key -> the Client row, for update-vs-insert
    classification and the upsert itself."""
    column = getattr(Client, key_field)
    clients = db.session.scalars(db.select(Client).where(column.is_not(None))).all()
    return {getattr(c, key_field): c for c in clients}


def _write_report_file(kind: str, text: str, committed: bool) -> Path:
    """Persist the report under var/import-reports/ (created if absent). May echo client
    names — the directory is gitignored (POPIA)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "commit" if committed else "dryrun"
    configured = current_app.config.get("IMPORT_REPORT_DIR")
    directory = (
        Path(configured)
        if configured
        else Path(current_app.root_path).parent / "var" / "import-reports"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}-{stamp}-{mode}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _run_import(
    kind: str, path: str, sheet: str | None, header_row: int | None, commit: bool
) -> None:
    config = _KIND_CONFIG[kind]
    rows = read_rows(
        path,
        sheet=sheet or config["sheet"],
        header_row=header_row or config["header_row"],
        header_overrides=config["header_overrides"],
    )
    staff = db.session.scalars(db.select(Staff)).all()
    existing_by_key = _existing_by_key(config["key_field"])
    report = importer.parse_file(rows, kind, staff, existing_keys=frozenset(existing_by_key))

    output = report.render(committed=commit)
    if commit:
        result = writer.apply_report(report, existing_by_key, db.session)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        output = f"{output}\n\n{result.render()}"

    report_path = _write_report_file(kind, output, commit)
    click.echo(output)
    click.echo(f"\nReport written to {report_path}")


@import_clients_cli.command(importer.COMPANIES)
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet", default=None, help="Worksheet name (xlsx only).")
@click.option("--header-row", type=int, default=None, help="1-based header row override.")
@click.option("--commit", is_flag=True, default=False, help="Apply changes (default: dry run).")
def companies(path: str, sheet: str | None, header_row: int | None, commit: bool) -> None:
    """Import the CIPC companies list from PATH (default sheet 'CIPC List')."""
    _run_import(importer.COMPANIES, path, sheet, header_row, commit)


@import_clients_cli.command(importer.INDIVIDUALS)
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--sheet", default=None, help="Worksheet name (xlsx only).")
@click.option("--header-row", type=int, default=None, help="1-based header row override.")
@click.option("--commit", is_flag=True, default=False, help="Apply changes (default: dry run).")
def individuals(path: str, sheet: str | None, header_row: int | None, commit: bool) -> None:
    """Import the IT12 individuals list from PATH (default sheet 'FINAL FINAL IT12 LIST')."""
    _run_import(importer.INDIVIDUALS, path, sheet, header_row, commit)
