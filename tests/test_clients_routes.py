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
