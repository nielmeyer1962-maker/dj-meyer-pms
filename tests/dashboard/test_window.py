from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.cipc import CIPCAnnualInstance, CIPCAnnualStatus
from app.models.client import Client, EntityType
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType

# Frozen "today" for every window assertion in this module.
TODAY = date(2026, 5, 13)


@pytest.fixture(autouse=True)
def _freeze_today():
    with patch("app.dashboard.routes.today_sast", return_value=TODAY):
        yield


@pytest.fixture
def window_world(app):
    """One client with obligations placed at window boundaries (all VAT201, all PENDING
    unless noted), each on a unique due date so it can be matched by its date string:
      - past_open    due TODAY-1   → overdue
      - due_today    due TODAY     → NOT overdue (strict <), but inside every forward window
      - in_60        due TODAY+60  → inside d60 (inclusive boundary)
      - beyond_60    due TODAY+61  → outside d60, inside m12
      - past_filed   due TODAY-3, SUBMITTED → neither overdue nor forward → only in 'all'
    Plus one CIPC AR due TODAY+2 so counts span both sources.
    """
    c = Client(legal_name="Window Co", entity_type=EntityType.PTY_LTD)
    db.session.add(c)
    db.session.commit()

    def _ob(due, period_end, status=ObligationStatus.PENDING):
        db.session.add(
            ObligationInstance(
                client_id=c.id,
                obligation_type=ObligationType.VAT201,
                period_start=date(period_end.year, period_end.month, 1),
                period_end=period_end,
                submission_due_date=due,
                payment_due_date=due,
                status=status,
            )
        )

    _ob(TODAY - timedelta(days=1), date(2026, 1, 31))  # past_open  → 2026-05-12
    _ob(TODAY, date(2026, 2, 28))  # due_today → 2026-05-13
    _ob(TODAY + timedelta(days=60), date(2026, 3, 31))  # in_60 → 2026-07-12
    _ob(TODAY + timedelta(days=61), date(2026, 4, 30))  # beyond_60 → 2026-07-13
    _ob(TODAY - timedelta(days=3), date(2025, 12, 31), ObligationStatus.SUBMITTED)  # past_filed
    db.session.add(
        CIPCAnnualInstance(
            client_id=c.id,
            anniversary_date=date(2025, 5, 1),
            due_date=TODAY + timedelta(days=2),  # 2026-05-15
            status=CIPCAnnualStatus.GENERATED,
        )
    )
    db.session.commit()


def test_due_today_is_inside_d60_but_not_overdue(client, window_world):
    body = client.get("/dashboard/?window=d60").data.decode()
    assert "2026-05-13" in body  # due today is inside the window…
    # …but it is NOT flagged overdue (strict less-than). Only the past_open row is.
    overdue_body = client.get("/dashboard/?window=overdue").data.decode()
    assert "2026-05-13" not in overdue_body
    assert "2026-05-12" in overdue_body  # past_open is overdue


def test_d60_inclusive_boundary_and_exclusion(client, window_world):
    body = client.get("/dashboard/?window=d60").data.decode()
    assert "2026-07-12" in body  # TODAY+60 is inside (inclusive)
    assert "2026-07-13" not in body  # TODAY+61 is outside d60
    assert "2025-12-31" not in body  # past_filed: not overdue, not forward → excluded


def test_m12_includes_beyond_60(client, window_world):
    body = client.get("/dashboard/?window=m12").data.decode()
    assert "2026-07-13" in body  # TODAY+61 now inside the 12-month window


def test_all_window_includes_past_filed(client, window_world):
    body = client.get("/dashboard/?window=all").data.decode()
    assert "2025-12-31" in body  # only 'all' surfaces the past-but-filed row


def test_default_window_is_d60(client, window_world):
    """No window arg behaves exactly like window=d60."""
    default_body = client.get("/dashboard/").data.decode()
    d60_body = client.get("/dashboard/?window=d60").data.decode()
    for marker in ("2026-07-13", "2025-12-31"):
        assert (marker in default_body) == (marker in d60_body)
    assert "2026-07-12" in default_body  # inside default


def test_window_composes_with_type_filter(client, window_world):
    """type=CIPC_AR + d60 returns only the CIPC row (TODAY+2), no obligations."""
    body = client.get("/dashboard/?type=CIPC_AR&window=d60").data.decode()
    assert "2026-05-15" in body  # CIPC AR due TODAY+2
    assert "2026-05-12" not in body  # obligation rows excluded by the Type filter


def test_counts_match_rendered_rows(client, window_world):
    """The 'Showing N' count equals the SQL count and the overdue count is independent of
    the window. Under d60: past_open, due_today, in_60 (obligations) + CIPC = 4 rows;
    overdue (any window) = 1 (past_open only)."""
    body = client.get("/dashboard/?window=d60").data.decode()
    assert "Showing <strong>4</strong>" in body
    assert "1 overdue" in body
    # 'all' widens the total (adds beyond_60 + past_filed = 6) but overdue stays 1.
    all_body = client.get("/dashboard/?window=all").data.decode()
    assert "Showing <strong>6</strong>" in all_body
    assert "1 overdue" in all_body
