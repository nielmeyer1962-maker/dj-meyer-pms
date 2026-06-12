"""H2 stage 2: friendly 404/500 pages that never leak a stack trace."""

from __future__ import annotations


def test_404_renders_friendly_page(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.data.decode()
    assert "Page not found" in body
    assert "Back to the dashboard" in body


def test_500_renders_friendly_page_without_traceback(app):
    """An unhandled exception is caught by the 500 handler, which renders a static page —
    the exception message and any traceback must NOT appear in the response."""

    @app.route("/boom")
    def boom():
        raise RuntimeError("kaboom-secret-internal-detail")

    # With TESTING=True Flask re-raises by default; turn that off so the 500 handler runs,
    # exactly as it would in production.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    resp = app.test_client().get("/boom")
    assert resp.status_code == 500
    body = resp.data.decode()
    assert "Something went wrong" in body
    assert "kaboom-secret-internal-detail" not in body
    assert "Traceback" not in body
