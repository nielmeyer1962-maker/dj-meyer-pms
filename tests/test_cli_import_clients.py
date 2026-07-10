"""End-to-end test of the `flask import-clients` CLI (Chunk 2 --commit path).

Drives the real click command via Flask's test runner against an in-memory DB, so the
click wiring, transaction, and report-file output are all exercised, not just the writer.
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.client import Client, VatSubmissionMethod
from app.models.staff import Staff, StaffRole

pytestmark = pytest.mark.usefixtures("app")

# CO_* headers, verbatim (two spaces in the email header are deliberate).
_COMPANIES_CSV = (
    "Client_field,Reg Number,Staff Member,is_Vat_category\nAcme (Pty) Ltd,2015/123456/07,Niel,B\n"
)


def _seed_staff() -> None:
    db.session.add(Staff(code="NIEL", full_name="Niel Meyer", role=StaffRole.TAX))
    db.session.commit()


def test_dry_run_writes_nothing(app, tmp_path):
    _seed_staff()
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text(_COMPANIES_CSV, encoding="utf-8")
    app.config["IMPORT_REPORT_DIR"] = str(tmp_path / "reports")

    result = app.test_cli_runner().invoke(args=["import-clients", "companies", str(csv_path)])

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert db.session.scalar(db.select(db.func.count()).select_from(Client)) == 0
    assert len(list((tmp_path / "reports").glob("companies-*-dryrun.txt"))) == 1


def test_commit_creates_row_and_report(app, tmp_path):
    _seed_staff()
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text(_COMPANIES_CSV, encoding="utf-8")
    app.config["IMPORT_REPORT_DIR"] = str(tmp_path / "reports")

    result = app.test_cli_runner().invoke(
        args=["import-clients", "companies", str(csv_path), "--commit"]
    )

    assert result.exit_code == 0, result.output
    assert "COMMIT" in result.output
    assert "inserted:                1" in result.output
    c = db.session.scalar(db.select(Client).where(Client.registration_number == "2015/123456/07"))
    assert c is not None
    assert c.vat_submission_method is VatSubmissionMethod.EFILING
    assert len(list((tmp_path / "reports").glob("companies-*-commit.txt"))) == 1
