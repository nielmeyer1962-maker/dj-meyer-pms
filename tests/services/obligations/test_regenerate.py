from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.app_setting import APP_SETTING_SEED, AppSetting
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
        r.period_end: r for r in _all_for_client(client_id) if r.status is ObligationStatus.PENDING
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

        expected = {inst.period_end: inst for inst in generate_vat201(c, today=date(2026, 1, 1))}
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


# --- 5) Prune: has_vat off-ramp preserves terminal AND past-due PENDING rows ---


def test_prune_has_vat_off_ramp_preserves_terminal_rows(app):
    """has_vat=False generates nothing, but the past-due PENDING row (period_end <=
    today) is now KEPT, not pruned (decision (c)), alongside SUBMITTED/PAID/EXEMPT.

    The seeded PENDING is at 2025-12-31 with today 2026-01-01, so it has already
    come due — silently deleting it would lose an outstanding return. Pruning of
    still-FUTURE no-longer-generated PENDING rows is covered by the dedicated prune
    tests below."""
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

        # Nothing added/updated, and nothing deleted: the past-due PENDING is protected.
        assert result == RegenerateResult(0, 0, 0)
        kept = db.session.get(ObligationInstance, pending.id)
        assert kept is not None
        assert kept.status is ObligationStatus.PENDING
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

    today=2026-01-01 first (12 PENDING rows Jan–Dec 2026), today=2026-07-15 second
    (Cat A MANUAL). The new window's generated keys are Jul/Sep/Nov 2026 + Jan/Mar/
    May 2027. Of the original twelve 2026 rows: three (Jul/Sep/Nov) are refreshed,
    three 2027 keys are added, and the nine that fall out split by the past-due
    guard — the six first-half-2026 rows (period_end <= today_2) are PROTECTED, only
    the three future ones (Aug/Oct/Dec 2026) are pruned."""
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

        # 3 added (2027 keys), 3 updated (refreshed 2026 keys), 3 deleted (future orphans).
        assert result == RegenerateResult(added=3, updated=3, deleted=3)

        pending = _pending_by_period_end(c.id)
        expected = {inst.period_end: inst for inst in generate_vat201(c, today=today_2)}

        # Every generated key is present with the refreshed (MANUAL) due dates.
        for period_end, inst in expected.items():
            assert period_end in pending
            assert pending[period_end].submission_due_date == inst.submission_due_date
            assert pending[period_end].payment_due_date == inst.payment_due_date

        # Past-due orphans (period_end <= today_2), no longer generated, are KEPT.
        protected = {
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
            date(2026, 4, 30),
            date(2026, 5, 31),
            date(2026, 6, 30),
        }
        assert protected <= set(pending)

        # Future orphans (period_end > today_2), no longer generated, are pruned.
        for gone in (date(2026, 8, 31), date(2026, 10, 31), date(2026, 12, 31)):
            assert gone not in pending

        # The surviving PENDING set is exactly the generated set plus the protected past-due rows.
        assert set(pending) == set(expected) | protected


# --- 8) Refresh path preserves notes (Ticket 3c §C2) ---


def test_refresh_path_preserves_notes_on_pending(app):
    """A PENDING row with notes survives the refresh branch of regenerate.

    The refresh branch only writes submission_due_date / payment_due_date on the
    existing row (see regenerate.py). This test seeds notes on one PENDING row,
    triggers a config change that forces every PENDING row through the refresh
    branch (EFILING → MANUAL shifts every due date), and asserts the notes
    survive untouched. Catches any future refactor that copies whole rows from
    the generator output (which has notes=None) instead of patching due dates."""
    with app.app_context():
        c = _make_client(method=VatSubmissionMethod.EFILING)
        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        target = _pending_by_period_end(c.id)[date(2026, 4, 30)]
        target_id = target.id
        note_text = "Awaiting client signature on VAT201 — chase 2026-05-20."
        target.notes = note_text
        db.session.commit()

        c.vat_submission_method = VatSubmissionMethod.MANUAL
        db.session.commit()

        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        assert result.updated > 0  # confirms the refresh branch did run

        refreshed = db.session.get(ObligationInstance, target_id)
        assert refreshed is not None
        assert refreshed.notes == note_text
        # And the refresh branch did update the due date — proves we went through
        # the patch path, not the no-op path.
        expected = {inst.period_end: inst for inst in generate_vat201(c, today=date(2026, 1, 1))}
        assert refreshed.submission_due_date == expected[date(2026, 4, 30)].submission_due_date


# --- EMP201 coexistence (Ticket 4e) ---


def test_regenerate_emits_vat201_and_emp201_together(app):
    """A client registered for both VAT and PAYE gets both obligation types in one
    regenerate pass, keyed independently so neither crowds the other out."""
    with app.app_context():
        c = Client(
            legal_name="VAT + PAYE Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
            vat_category=VatCategory.C,
            vat_submission_method=VatSubmissionMethod.EFILING,
            has_paye=True,
        )
        db.session.add(c)
        db.session.commit()

        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        rows = _all_for_client(c.id)
        vat = [r for r in rows if r.obligation_type is ObligationType.VAT201]
        emp = [r for r in rows if r.obligation_type is ObligationType.EMP201]
        emp501 = [
            r
            for r in rows
            if r.obligation_type in (ObligationType.EMP501_INTERIM, ObligationType.EMP501_ANNUAL)
        ]
        # 12 monthly VAT201 (Cat C) + 12 monthly EMP201 in the 12-month window, plus the
        # two PAYE-gated EMP501 reconciliations (interim + annual) for the current tax year.
        assert len(vat) == 12
        assert len(emp) == 12
        assert len(emp501) == 2
        assert result == RegenerateResult(added=26, updated=0, deleted=0)


def test_regenerate_skips_emp201_when_not_paye_registered(app):
    """No PAYE registration → only VAT201 rows, no EMP201."""
    with app.app_context():
        c = _make_client()  # has_vat=True, has_paye defaults to False
        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        rows = _all_for_client(c.id)
        assert all(r.obligation_type is ObligationType.VAT201 for r in rows)
        assert not any(r.obligation_type is ObligationType.EMP201 for r in rows)


# --- Past-due prune guard (decision (c)) ---


def test_prune_keeps_past_due_pending_but_prunes_future(app):
    """The prune deletes only FUTURE no-longer-generated PENDING rows. A PENDING row
    that has already come due (period_end <= today) is protected, as is one whose
    period_end is exactly today; terminal rows are always preserved.

    The client is registered for nothing (has_vat/paye/income_tax all False), so the
    generated set is empty and every seeded row is "no longer generated" — isolating
    the guard from the generators."""
    with app.app_context():
        c = _make_client(has_vat=False, legal_name="Prune Guard Corp")
        today = date(2026, 6, 15)
        future_pending = _seed_instance(c.id, date(2026, 9, 30), ObligationStatus.PENDING)
        past_due_pending = _seed_instance(c.id, date(2026, 3, 31), ObligationStatus.PENDING)
        due_today_pending = _seed_instance(c.id, date(2026, 6, 15), ObligationStatus.PENDING)
        future_submitted = _seed_instance(c.id, date(2026, 12, 31), ObligationStatus.SUBMITTED)

        result = regenerate(c, today=today)
        db.session.commit()

        # Only the single future PENDING row is pruned.
        assert result == RegenerateResult(0, 0, 1)
        assert db.session.get(ObligationInstance, future_pending.id) is None
        # Past-due and due-today PENDING rows are protected.
        assert db.session.get(ObligationInstance, past_due_pending.id) is not None
        assert db.session.get(ObligationInstance, due_today_pending.id) is not None
        # Terminal rows are always preserved, future or not.
        assert db.session.get(ObligationInstance, future_submitted.id) is not None


# --- ITR14 end-to-end through regenerate (Ticket 4a) ---


def test_regenerate_emits_and_preserves_itr14_across_years(app):
    """An eligible company gets one ITR14 for its most-recently-completed FY, and on a
    later regenerate (a year on, a new current FY) the prior-year ITR14 — still PENDING
    and now past-due — survives the prune rather than being silently dropped."""
    with app.app_context():
        c = Client(
            legal_name="ITR14 Regen Corp",
            entity_type=EntityType.PTY_LTD,
            has_income_tax=True,
        )
        c.year_end_month = 2
        c.year_end_day = 28
        db.session.add(c)
        db.session.commit()

        # First run: today 2026-06-10 → completed FY ended 28 Feb 2026.
        regenerate(c, today=date(2026, 6, 10))
        db.session.commit()
        itr14_rows = [r for r in _all_for_client(c.id) if r.obligation_type is ObligationType.ITR14]
        assert len(itr14_rows) == 1
        first = itr14_rows[0]
        assert first.period_end == date(2026, 2, 28)
        assert first.period_start == date(2025, 3, 1)
        # due_raw 28 Feb 2027 is a Sunday → forward-rolls to Mon 1 Mar 2027.
        assert first.submission_due_date == date(2027, 3, 1)
        assert first.status is ObligationStatus.PENDING
        first_id = first.id

        # A year later: today 2027-06-10 → new completed FY ended 28 Feb 2027.
        result = regenerate(c, today=date(2027, 6, 10))
        db.session.commit()

        # New ITR14 added; the prior-year one (past-due PENDING) is kept, not pruned.
        assert result == RegenerateResult(added=1, updated=0, deleted=0)
        itr14_rows = sorted(
            (r for r in _all_for_client(c.id) if r.obligation_type is ObligationType.ITR14),
            key=lambda r: r.period_end,
        )
        assert [r.period_end for r in itr14_rows] == [date(2026, 2, 28), date(2027, 2, 28)]
        assert db.session.get(ObligationInstance, first_id) is not None


# --- ITR12 end-to-end through regenerate (Ticket 4b) ---


def _seed_itr12_deadlines() -> None:
    for row in APP_SETTING_SEED:
        db.session.add(AppSetting(**row))
    db.session.commit()


def test_regenerate_emits_and_preserves_it12_across_years(app):
    """An eligible individual gets one ITR12 for the most-recently-closed YoA, and on a
    later regenerate (a year on) the prior-year ITR12 — still PENDING and now past-due —
    survives the prune rather than being silently dropped."""
    with app.app_context():
        _seed_itr12_deadlines()
        c = Client(
            legal_name="Smit, J",
            entity_type=EntityType.INDIVIDUAL,
            has_income_tax=True,
        )
        db.session.add(c)
        db.session.commit()

        # First run: today 2026-06-11 → YoA closed 28 Feb 2026, non-prov due 23 Oct 2026.
        regenerate(c, today=date(2026, 6, 11))
        db.session.commit()
        it12 = [r for r in _all_for_client(c.id) if r.obligation_type is ObligationType.ITR12]
        assert len(it12) == 1
        first = it12[0]
        assert first.period_end == date(2026, 2, 28)
        assert first.submission_due_date == date(2026, 10, 23)
        assert first.status is ObligationStatus.PENDING
        first_id = first.id

        # A year later: today 2027-06-11 → new YoA closed 28 Feb 2027.
        result = regenerate(c, today=date(2027, 6, 11))
        db.session.commit()

        # New ITR12 added; the prior-year one (past-due PENDING) is kept, not pruned.
        assert result == RegenerateResult(added=1, updated=0, deleted=0)
        it12_rows = sorted(
            (r for r in _all_for_client(c.id) if r.obligation_type is ObligationType.ITR12),
            key=lambda r: r.period_end,
        )
        assert [r.period_end for r in it12_rows] == [date(2026, 2, 28), date(2027, 2, 28)]
        assert db.session.get(ObligationInstance, first_id) is not None


def test_regenerate_skips_it12_for_non_individual(app):
    """A company is never given an ITR12, even with income tax — the entity gate keeps
    generate_it12 out before it touches settings."""
    with app.app_context():
        c = Client(
            legal_name="Acme Pty Ltd",
            entity_type=EntityType.PTY_LTD,
            has_income_tax=True,
        )
        db.session.add(c)
        db.session.commit()

        regenerate(c, today=date(2026, 6, 11))
        db.session.commit()

        rows = _all_for_client(c.id)
        assert not any(r.obligation_type is ObligationType.ITR12 for r in rows)


# --- Archived client is inert (H1 chunk 2) ---


def test_regenerate_on_archived_client_prunes_future_pending(app):
    """Once a client is archived, its generators yield nothing, so regenerate adds 0 and
    prunes its still-future PENDING rows by the existing rule — while terminal rows are
    preserved as always."""
    with app.app_context():
        c = _make_client()  # active VAT Cat C client
        regenerate(c, today=date(2026, 1, 1))
        db.session.commit()
        pendings = _pending_by_period_end(c.id)
        assert len(pendings) == 12

        # Mark one row SUBMITTED so we can confirm terminal rows survive the archive.
        keep = pendings[date(2026, 6, 30)]
        keep.status = ObligationStatus.SUBMITTED
        db.session.commit()
        keep_id = keep.id

        c.active = False
        db.session.commit()

        result = regenerate(c, today=date(2026, 1, 1))
        db.session.commit()

        # Nothing generated; the 11 remaining future PENDING rows are pruned.
        assert result.added == 0
        assert result.deleted == 11
        # Terminal row preserved; no PENDING rows remain.
        kept = db.session.get(ObligationInstance, keep_id)
        assert kept is not None and kept.status is ObligationStatus.SUBMITTED
        assert _pending_by_period_end(c.id) == {}
