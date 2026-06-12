from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType

TODAY = date(2026, 5, 13)


@pytest.fixture(autouse=True)
def _freeze_today():
    with patch("app.dashboard.routes.today_sast", return_value=TODAY):
        yield


@pytest.fixture
def search_world(app):
    """Three clients with distinct names + one overdue obligation each (so all fall in the
    default d60 window), plus a CIPC AR for the known_as client. Rows are identified by
    unique due-date markers.
      - Alpha Trading (Pty) Ltd, known_as None       → 2026-05-01
      - Beta Holdings Ltd,        known_as "Bravo"   → 2026-05-02  (+ CIPC 2026-05-03)
      - Gamma Mining CC,          known_as None       → 2026-05-04
    """
    alpha = Client(legal_name="Alpha Trading (Pty) Ltd", entity_type=EntityType.PTY_LTD)
    beta = Client(legal_name="Beta Holdings Ltd", known_as="Bravo", entity_type=EntityType.PTY_LTD)
    gamma = Client(legal_name="Gamma Mining CC", entity_type=EntityType.CC)
    db.session.add_all([alpha, beta, gamma])
    db.session.commit()

    def _ob(client_id, due):
        db.session.add(
            ObligationInstance(
                client_id=client_id,
                obligation_type=ObligationType.VAT201,
                period_start=due,
                period_end=due,
                submission_due_date=due,
                payment_due_date=due,
                status=ObligationStatus.PENDING,  # past + pending → overdue → in d60
            )
        )

    _ob(alpha.id, date(2026, 5, 1))
    _ob(beta.id, date(2026, 5, 2))
    _ob(gamma.id, date(2026, 5, 4))
    db.session.add(
        CIPCAnnualInstance(
            client_id=beta.id,
            anniversary_date=date(2025, 5, 3),
            due_date=date(2026, 5, 3),
            status=CIPCAnnualStatus.GENERATED,
        )
    )
    db.session.commit()
    return {"alpha_id": alpha.id, "beta_id": beta.id, "gamma_id": gamma.id}


def test_search_matches_legal_name(client, search_world):
    body = client.get("/dashboard/?client_q=Alpha").data.decode()
    assert "2026-05-01" in body  # Alpha's row
    assert "2026-05-02" not in body
    assert "2026-05-04" not in body


def test_search_matches_known_as(client, search_world):
    """Beta's known_as is 'Bravo' — searching the known_as matches even though it isn't in
    the legal name."""
    body = client.get("/dashboard/?client_q=Bravo").data.decode()
    assert "2026-05-02" in body  # Beta's obligation
    assert "2026-05-03" in body  # Beta's CIPC row also matches (search applies to both)
    assert "2026-05-01" not in body
    assert "2026-05-04" not in body


def test_search_is_case_insensitive(client, search_world):
    body = client.get("/dashboard/?client_q=gAmMa").data.decode()
    assert "2026-05-04" in body
    assert "2026-05-01" not in body


def test_search_substring_partial_match(client, search_world):
    body = client.get("/dashboard/?client_q=Holdings").data.decode()
    assert "2026-05-02" in body  # Beta Holdings
    assert "2026-05-01" not in body


def test_empty_search_shows_all(client, search_world):
    body = client.get("/dashboard/?client_q=").data.decode()
    for marker in ("2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"):
        assert marker in body


def test_search_composes_with_type_filter(client, search_world):
    """client_q=Bravo + type=CIPC_AR returns only Beta's CIPC row, not its obligation."""
    body = client.get("/dashboard/?client_q=Bravo&type=CIPC_AR").data.decode()
    assert "2026-05-03" in body  # Beta CIPC
    assert "2026-05-02" not in body  # Beta obligation excluded by type


def test_search_composes_with_status_filter(client, search_world):
    body = client.get("/dashboard/?client_q=Beta&status=PENDING").data.decode()
    assert "2026-05-02" in body  # Beta's PENDING obligation
    assert "2026-05-01" not in body  # Alpha excluded by search


def test_search_composes_with_window(client, search_world):
    """A far-future Alpha obligation is excluded under d60 but the search still matches it
    under window=all."""
    db.session.add(
        ObligationInstance(
            client_id=search_world["alpha_id"],
            obligation_type=ObligationType.VAT201,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 1),
            submission_due_date=date(2030, 1, 1),
            payment_due_date=date(2030, 1, 1),
            status=ObligationStatus.PENDING,
        )
    )
    db.session.commit()
    d60 = client.get("/dashboard/?client_q=Alpha&window=d60").data.decode()
    assert "2030-01-01" not in d60  # beyond the default window
    all_body = client.get("/dashboard/?client_q=Alpha&window=all").data.decode()
    assert "2030-01-01" in all_body


def test_explicit_client_id_takes_precedence_over_search(client, search_world):
    """A client id deep-link wins over the search box (deep-links keep working)."""
    body = client.get(f"/dashboard/?client={search_world['alpha_id']}&client_q=Beta").data.decode()
    assert "2026-05-01" in body  # Alpha (by id), NOT Beta (search ignored)
    assert "2026-05-02" not in body


def test_search_repaints_in_input(client, search_world):
    body = client.get("/dashboard/?client_q=Beta").data.decode()
    assert 'value="Beta"' in body  # the typed term repaints in the search input


@pytest.fixture
def bulk_search_world(app):
    """One searchable client with 60 overdue obligations → two pages under the default
    window, so the pager appears and we can assert the search term rides its links."""
    c = Client(legal_name="Pagebulk Trading Ltd", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()
    base = date(2026, 1, 1)  # all past TODAY → overdue → inside d60
    for i in range(60):
        due = base + timedelta(days=i)
        db.session.add(
            ObligationInstance(
                client_id=c.id,
                obligation_type=ObligationType.VAT201,
                period_start=due,
                period_end=due,
                submission_due_date=due,
                payment_due_date=due,
                status=ObligationStatus.PENDING,
            )
        )
    db.session.commit()


def test_search_survives_paging(client, bulk_search_world):
    body = client.get("/dashboard/?client_q=Pagebulk").data.decode()
    assert "Page 1 of 2" in body
    assert "client_q=Pagebulk" in body  # the Next link carries the search term…
    assert "page=2" in body  # …and advances the page
