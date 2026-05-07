from flask.testing import FlaskClient


def test_index_ok(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
