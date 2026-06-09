from __future__ import annotations

from app.extensions import db
from app.models.client import Client, EntityType, VatCategory, VatSubmissionMethod


def _base_form(**overrides) -> dict:
    """Minimum-viable POST body for /clients/new — entity_type + legal_name are required."""
    data = {
        "legal_name": "Test Co",
        "entity_type": EntityType.PTY_LTD.name,
        "submit": "Save",
    }
    data.update(overrides)
    return data


def _get_client(app, legal_name: str = "Test Co") -> Client | None:
    with app.app_context():
        return db.session.scalar(db.select(Client).where(Client.legal_name == legal_name))


def _create_vat_client(app, **kwargs) -> int:
    """Create a fully-configured VAT client directly via the ORM. Returns its id."""
    defaults = dict(
        legal_name="Regen Test Co",
        entity_type=EntityType.PTY_LTD,
        has_vat=True,
        vat_category=VatCategory.B,
        vat_submission_method=VatSubmissionMethod.EFILING,
    )
    defaults.update(kwargs)
    with app.app_context():
        c = Client(**defaults)
        db.session.add(c)
        db.session.commit()
        return c.id


# --- create_client: VAT happy paths ---


def test_create_client_with_full_vat_config_persists_enums(app, client):
    resp = client.post(
        "/clients/new",
        data=_base_form(
            has_vat="y",
            vat_category=VatCategory.A.name,
            vat_submission_method=VatSubmissionMethod.EFILING.name,
        ),
    )
    assert resp.status_code == 302
    c = _get_client(app)
    assert c is not None
    assert c.vat_category is VatCategory.A
    assert c.vat_submission_method is VatSubmissionMethod.EFILING


def test_create_client_with_has_vat_true_and_both_vat_fields_blank_succeeds(app, client):
    """The newly-registered-but-details-pending case from 3a §a invariant 2."""
    resp = client.post("/clients/new", data=_base_form(has_vat="y"))
    assert resp.status_code == 302
    c = _get_client(app)
    assert c is not None
    assert c.has_vat is True
    assert c.vat_category is None
    assert c.vat_submission_method is None


# --- create_client: pairing-rule rejections ---


def test_create_client_has_vat_false_with_category_rejects(app, client):
    resp = client.post(
        "/clients/new",
        data=_base_form(vat_category=VatCategory.A.name),
    )
    assert resp.status_code == 200
    assert b"VAT category and submission method must both be empty" in resp.data
    assert _get_client(app) is None


def test_create_client_has_vat_true_category_only_rejects(app, client):
    resp = client.post(
        "/clients/new",
        data=_base_form(has_vat="y", vat_category=VatCategory.A.name),
    )
    assert resp.status_code == 200
    assert b"VAT category and submission method must both be set or both be empty" in resp.data
    assert _get_client(app) is None


def test_create_client_has_vat_true_method_only_rejects(app, client):
    resp = client.post(
        "/clients/new",
        data=_base_form(has_vat="y", vat_submission_method=VatSubmissionMethod.MANUAL.name),
    )
    assert resp.status_code == 200
    assert b"VAT category and submission method must both be set or both be empty" in resp.data
    assert _get_client(app) is None


# --- edit_client: round-trip + GET pre-population ---


def test_edit_client_updates_vat_fields_and_get_prepopulates(app, client):
    """Create a client with one config, GET the edit form (assert pre-population),
    then POST a different config and assert the change persisted."""
    with app.app_context():
        c = Client(
            legal_name="Edit Target Co",
            entity_type=EntityType.PTY_LTD,
            has_vat=True,
            vat_category=VatCategory.A,
            vat_submission_method=VatSubmissionMethod.EFILING,
        )
        db.session.add(c)
        db.session.commit()
        client_id = c.id

    # GET pre-populates from current state
    resp = client.get(f"/clients/{client_id}/edit")
    assert resp.status_code == 200
    assert b'value="A" selected' in resp.data or b'<option selected value="A">' in resp.data
    assert b"EFILING" in resp.data

    # POST flips to a different valid VAT config
    resp = client.post(
        f"/clients/{client_id}/edit",
        data=_base_form(
            legal_name="Edit Target Co",
            has_vat="y",
            vat_category=VatCategory.C.name,
            vat_submission_method=VatSubmissionMethod.MANUAL.name,
        ),
    )
    assert resp.status_code == 302

    with app.app_context():
        c = db.session.get(Client, client_id)
        assert c.vat_category is VatCategory.C
        assert c.vat_submission_method is VatSubmissionMethod.MANUAL


# --- regenerate_obligations: happy path + idempotency ---


def test_regenerate_obligations_creates_instances_and_flashes_count(app, client):
    """Pty Ltd + VAT + Cat B + eFiling → POST regenerate → N>0 VAT201 rows
    created, 302 redirect back to /edit, flash text contains the count."""
    from app.models.obligation import ObligationInstance, ObligationType

    client_id = _create_vat_client(app)

    resp = client.post(f"/clients/{client_id}/regenerate")
    assert resp.status_code == 302
    assert resp.location.endswith(f"/clients/{client_id}/edit")

    with app.app_context():
        rows = db.session.scalars(
            db.select(ObligationInstance).where(ObligationInstance.client_id == client_id)
        ).all()
    n = len(rows)
    assert n > 0
    assert all(r.obligation_type is ObligationType.VAT201 for r in rows)

    # Follow the redirect to consume the flash; the count must appear in the message.
    resp = client.get(f"/clients/{client_id}/edit")
    assert resp.status_code == 200
    assert (
        f"Regenerated obligations for Regen Test Co: added {n}, updated 0, removed 0; "
        f"CIPC added 0, updated 0, removed 0.".encode()
        in resp.data
    )


def test_regenerate_obligations_is_idempotent(app, client):
    """Calling regenerate a second time adds zero rows and does not raise on
    the (client_id, obligation_type, period_end) unique constraint."""
    from app.models.obligation import ObligationInstance

    client_id = _create_vat_client(app, legal_name="Idem Co")

    client.post(f"/clients/{client_id}/regenerate")
    with app.app_context():
        first_count = db.session.scalar(
            db.select(db.func.count(ObligationInstance.id)).where(
                ObligationInstance.client_id == client_id
            )
        )
    assert first_count > 0

    resp = client.post(f"/clients/{client_id}/regenerate")
    assert resp.status_code == 302

    with app.app_context():
        second_count = db.session.scalar(
            db.select(db.func.count(ObligationInstance.id)).where(
                ObligationInstance.client_id == client_id
            )
        )
    assert second_count == first_count

    # Second-call flash specifically says zero new obligations.
    resp = client.get(f"/clients/{client_id}/edit")
    assert (
        b"Regenerated obligations for Idem Co: added 0, updated 0, removed 0; "
        b"CIPC added 0, updated 0, removed 0." in resp.data
    )
