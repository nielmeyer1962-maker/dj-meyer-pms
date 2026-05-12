from datetime import date

import pytest

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod
from app.models.obligation import ObligationStatus, ObligationType
from app.services.obligations.vat201 import generate_vat201


def _make_persisted_client(category: VatCategory, method: VatSubmissionMethod) -> Client:
    """Construct and commit a Client with the given VAT config. Caller must hold app_context."""
    c = Client(
        legal_name=f"Test Cat {category.name}",
        entity_type=EntityType.PTY_LTD,
        has_vat=True,
        vat_category=category,
        vat_submission_method=method,
    )
    db.session.add(c)
    db.session.commit()
    return c


def _assert_vat201_instance(
    instance,
    *,
    client_id: int,
    period_start: date,
    period_end: date,
    due_date: date,
) -> None:
    """All invariants asserted on a single generated ObligationInstance."""
    assert instance.client_id == client_id
    assert instance.obligation_type is ObligationType.VAT201
    assert instance.period_start == period_start
    assert instance.period_end == period_end
    assert instance.submission_due_date == due_date
    assert instance.payment_due_date == due_date
    assert instance.submission_due_date == instance.payment_due_date
    # Default-via-model check — confirms we didn't accidentally pass a status.
    assert instance.status is ObligationStatus.PENDING


# --- §(e) date-pair tests ---


def test_cat_b_efiling_30_apr_2026(app):
    """Cat B + eFiling + period 30 Apr 2026 → Fri 29 May 2026 (Sun 31, Sat 30)."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.B, VatSubmissionMethod.EFILING)
        instances = generate_vat201(client, months_ahead=1, today=date(2026, 4, 1))
        assert len(instances) == 1
        _assert_vat201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 30),
            due_date=date(2026, 5, 29),
        )


def test_cat_b_manual_30_apr_2026(app):
    """Cat B + Manual + period 30 Apr 2026 → Mon 25 May 2026 (no shift)."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.B, VatSubmissionMethod.MANUAL)
        instances = generate_vat201(client, months_ahead=1, today=date(2026, 4, 1))
        assert len(instances) == 1
        _assert_vat201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 30),
            due_date=date(2026, 5, 25),
        )


def test_cat_a_efiling_31_jan_2026(app):
    """Cat A + eFiling + period 31 Jan 2026 → Fri 27 Feb 2026 (Sat 28 Feb)."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.A, VatSubmissionMethod.EFILING)
        instances = generate_vat201(client, months_ahead=1, today=date(2026, 1, 1))
        assert len(instances) == 1
        _assert_vat201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2025, 12, 1),
            period_end=date(2026, 1, 31),
            due_date=date(2026, 2, 27),
        )


def test_cat_c_manual_31_dec_2025(app):
    """Cat C + Manual + period 31 Dec 2025 → Fri 23 Jan 2026 (Sun 25 Jan, Sat 24)."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.C, VatSubmissionMethod.MANUAL)
        instances = generate_vat201(client, months_ahead=1, today=date(2025, 12, 1))
        assert len(instances) == 1
        _assert_vat201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2025, 12, 1),
            period_end=date(2025, 12, 31),
            due_date=date(2026, 1, 23),
        )


def test_cat_a_manual_30_nov_2026_christmas_shift(app):
    """Cat A + Manual + period 30 Nov 2026 → Thu 24 Dec 2026 (Christmas Day Fri 25)."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.A, VatSubmissionMethod.MANUAL)
        instances = generate_vat201(client, months_ahead=1, today=date(2026, 11, 1))
        assert len(instances) == 1
        _assert_vat201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 11, 30),
            due_date=date(2026, 12, 24),
        )


def test_cat_c_efiling_31_dec_2025_year_rollover(app):
    """Cat C + eFiling + period 31 Dec 2025 → Fri 30 Jan 2026 (Sat 31 Jan)."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.C, VatSubmissionMethod.EFILING)
        instances = generate_vat201(client, months_ahead=1, today=date(2025, 12, 1))
        assert len(instances) == 1
        _assert_vat201_instance(
            instances[0],
            client_id=client.id,
            period_start=date(2025, 12, 1),
            period_end=date(2025, 12, 31),
            due_date=date(2026, 1, 30),
        )


# --- Pre-condition gate ---


def test_no_vat_returns_empty(app):
    """has_vat=False → []. Transient client; never committed."""
    with app.app_context():
        c = Client(
            legal_name="Non-VAT Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=False,
        )
        assert generate_vat201(c, today=date(2026, 5, 1)) == []


def test_vat_category_none_returns_empty(app):
    """has_vat=True but vat_category=None — exercises the category-None branch.

    The pairing invariant prevents persisting this exact state, so the client
    is constructed transient and never committed (no listener trigger).
    """
    with app.app_context():
        c = Client(
            legal_name="Pending VAT Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
            vat_submission_method=VatSubmissionMethod.EFILING,
            # vat_category intentionally unset — defaults to None.
        )
        assert c.vat_category is None
        assert generate_vat201(c, today=date(2026, 5, 1)) == []


def test_vat_submission_method_none_returns_empty(app):
    """has_vat=True but vat_submission_method=None — exercises the method-None branch."""
    with app.app_context():
        c = Client(
            legal_name="Pending VAT Corp",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
            vat_category=VatCategory.A,
            # vat_submission_method intentionally unset — defaults to None.
        )
        assert c.vat_submission_method is None
        assert generate_vat201(c, today=date(2026, 5, 1)) == []


# --- Category E ---


def test_category_e_raises_not_implemented(app):
    """Cat E is a valid persisted state (paired with a method) but the generator
    raises until the rule is confirmed for a real Cat E vendor."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.E, VatSubmissionMethod.EFILING)
        with pytest.raises(NotImplementedError, match="Category E pending domain confirmation"):
            generate_vat201(client, today=date(2026, 5, 1))


# --- Window correctness ---


def test_returns_empty_list_when_no_periods_in_window(app):
    """Cat A's odd-end months produce no period-end inside [2026-04-01, 2026-05-01]:
    April isn't a Cat A end-month, and May's last day 31 May is past the window end."""
    with app.app_context():
        client = _make_persisted_client(VatCategory.A, VatSubmissionMethod.EFILING)
        assert generate_vat201(client, months_ahead=1, today=date(2026, 4, 1)) == []
