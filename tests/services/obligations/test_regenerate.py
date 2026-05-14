from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.obligation import ObligationInstance, ObligationStatus, ObligationType
from app.services.obligations.regenerate import RegenerateResult, regenerate
from app.services.obligations.vat201 import generate_vat201


def _make_client(
    *,
    category: VatCategory | None = VatCategory.C,
    method: VatSubmissionMethod | None = VatSubmissionMethod.EFILING,
    has_vat: bool = True,
    legal_name: str = "Regenerate Test Corp",
) -> Client:
    """Persist a client with the given VAT config. Caller holds app_context."""
    c = Client(
        legal_name=legal_name,
        entity_type=EntityType.PTY_LTD,
        has_vat=has_vat,
        vat_category=category if has_vat else None,
        vat_submission_method=method if has_vat else None,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _seed_instance(
    client_id: int,
    period_end: date,
    status: ObligationStatus,
    *,
    submission_due_date: date | None = None,
) -> ObligationInstance:
    """Insert one VAT201 row with the given period_end / status."""
    due = submission_due_date or period_end
    oi = ObligationInstance(
        client_id=client_id,
        obligation_type=ObligationType.VAT201,
        period_start=date(period_end.year, period_end.month, 1),
        period_end=period_end,
        submission_due_date=due,
        payment_due_date=due,
        status=status,
    )
    db.session.add(oi)
    db.session.commit()
    return oi


def _all_for_client(client_id: int) -> list[ObligationInstance]:
    return list(
        db.session.scalars(
            db.select(ObligationInstance).where(ObligationInstance.client_id == client_id)
        )
    )


def _pending_by_period_end(client_id: int) -> dict[date, ObligationInstance]:
    return {
        r.period_end: r
        for r in _all_for_client(client_id)
        if r.status is ObligationStatus.PENDING
    }


# --- 1) First run on a new client ---


def test_first_run_cat_c_efiling_adds_twelve(app):
    """Cat C + EFILING + today=2026-01-01 → 12 added, 0 updated, 0 deleted."""
    with app.app_context():
        c = _make_client()
        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        assert result == RegenerateResult(added=12, updated=0, deleted=0)
        assert len(_all_for_client(c.id)) == 12


# --- 2) Second run is a no-op and preserves PKs ---


def test_second_run_unchanged_config_is_noop(app):
    """Re-running with the same config returns (0,0,0) and does not churn PKs."""
    with app.app_context():
        c = _make_client()
        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()
        pks_before = {r.period_end: r.id for r in _all_for_client(c.id)}

        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()
        pks_after = {r.period_end: r.id for r in _all_for_client(c.id)}

        assert result == RegenerateResult(0, 0, 0)
        assert pks_before == pks_after


# --- 3) Refresh: EFILING → MANUAL ---


def test_refresh_switches_due_dates_keeps_pks(app):
    """Switching EFILING → MANUAL refreshes all PENDING due dates without churning PKs."""
    with app.app_context():
        c = _make_client(method=VatSubmissionMethod.EFILING)
        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()
        pks_before = {r.period_end: r.id for r in _pending_by_period_end(c.id).values()}

        c.vat_submission_method = VatSubmissionMethod.MANUAL
        db.session.commit()

        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        assert result.updated > 0
        assert result.added == 0
        assert result.deleted == 0

        pending = _pending_by_period_end(c.id)
        assert {pe: r.id for pe, r in pending.items()} == pks_before

        expected = {
            inst.period_end: inst for inst in generate_vat201(c, today=date(2026, 1, 1))
        }
        assert set(pending) == set(expected)
        for period_end, row in pending.items():
            assert row.submission_due_date == expected[period_end].submission_due_date
            assert row.payment_due_date == expected[period_end].payment_due_date


# --- 4) Prune: category change Cat C → Cat A ---


def test_prune_category_change_drops_even_month_pendings(app):
    """Cat C → Cat A drops PENDING rows whose period_end month is even."""
    with app.app_context():
        c = _make_client(category=VatCategory.C)
        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        c.vat_category = VatCategory.A
        db.session.commit()

        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        assert result.deleted > 0
        for row in _pending_by_period_end(c.id).values():
            assert row.period_end.month in {1, 3, 5, 7, 9, 11}


# --- 5) Prune: has_vat off-ramp preserves terminal rows ---


def test_prune_has_vat_off_ramp_preserves_terminal_rows(app):
    """has_vat=False removes the lone PENDING but leaves SUBMITTED/PAID/EXEMPT untouched."""
    with app.app_context():
        c = _make_client(category=VatCategory.C, method=VatSubmissionMethod.EFILING)
        pending = _seed_instance(c.id, date(2025, 12, 31), ObligationStatus.PENDING)
        submitted = _seed_instance(c.id, date(2025, 11, 30), ObligationStatus.SUBMITTED)
        paid = _seed_instance(c.id, date(2025, 10, 31), ObligationStatus.PAID)
        exempt = _seed_instance(c.id, date(2025, 9, 30), ObligationStatus.EXEMPT)
        terminal_snapshot = {
            r.id: (r.status, r.submission_due_date, r.payment_due_date, r.period_end)
            for r in (submitted, paid, exempt)
        }

        c.has_vat = False
        c.vat_category = None
        c.vat_submission_method = None
        db.session.commit()

        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        assert result == RegenerateResult(0, 0, 1)
        assert db.session.get(ObligationInstance, pending.id) is None
        for row_id, snap in terminal_snapshot.items():
            row = db.session.get(ObligationInstance, row_id)
            assert row is not None
            assert (
                row.status,
                row.submission_due_date,
                row.payment_due_date,
                row.period_end,
            ) == snap


# --- 6) Terminal-state immutability ---


def test_submitted_row_due_date_immutable(app):
    """A SUBMITTED row whose submission_due_date is wrong stays wrong after regenerate."""
    with app.app_context():
        c = _make_client(category=VatCategory.C, method=VatSubmissionMethod.EFILING)
        wrong_due = date(1999, 1, 1)
        submitted = _seed_instance(
            c.id,
            period_end=date(2026, 1, 31),
            status=ObligationStatus.SUBMITTED,
            submission_due_date=wrong_due,
        )

        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()
        db.session.refresh(submitted)

        assert submitted.status is ObligationStatus.SUBMITTED
        assert submitted.submission_due_date == wrong_due
        assert submitted.payment_due_date == wrong_due


# --- 7) Mixed: method + category change between two regenerate calls ---


def test_mixed_call_method_and_category_change(app):
    """Cat C EFILING → Cat A MANUAL with the window also moving forward.

    today=2026-01-01 first, today=2026-07-15 second: the new Cat A MANUAL window
    contains three keys that already exist (refresh), three keys that don't (add),
    and leaves nine 2026 PENDING rows orphaned (prune)."""
    with app.app_context():
        c = _make_client(category=VatCategory.C, method=VatSubmissionMethod.EFILING)
        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        c.vat_category = VatCategory.A
        c.vat_submission_method = VatSubmissionMethod.MANUAL
        db.session.commit()

        today_2 = date(2026, 7, 15)
        result = regenerate(c, today=today_2)
        db.session.commit()

        assert result.added > 0
        assert result.updated > 0
        assert result.deleted > 0

        pending = _pending_by_period_end(c.id)
        expected = {inst.period_end: inst for inst in generate_vat201(c, today=today_2)}
        assert set(pending) == set(expected)
        for period_end, row in pending.items():
            assert row.submission_due_date == expected[period_end].submission_due_date
            assert row.payment_due_date == expected[period_end].payment_due_date
