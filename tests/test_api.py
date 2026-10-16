import pytest
from fastapi.testclient import TestClient
from pymobiledevice3.exceptions import NoDeviceConnectedError

from locationspoofer.server import TOKEN_COOKIE, create_app

LOCAL = "http://127.0.0.1:8765"


@pytest.fixture
def client(controller):
    with TestClient(create_app(controller), base_url=LOCAL) as test_client:
        yield test_client


def test_ui_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "LocationSpoofer" in response.text
    assert client.get("/vendor/leaflet/leaflet.js").status_code == 200


def test_teleport_and_reset(client, pool):
    response = client.post("/api/location", json={"latitude": 52.52, "longitude": 13.405})
    assert response.status_code == 200
    assert response.json()["location"] == {"latitude": 52.52, "longitude": 13.405}

    response = client.delete("/api/location")
    assert response.status_code == 200
    assert response.json()["location"] is None
    assert pool.last.calls[-1] == ("clear",)


@pytest.mark.parametrize(
    "body",
    [
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": -181},
        {"latitude": "abc", "longitude": 0},
        {"latitude": 1},
    ],
)
def test_invalid_coordinates_are_rejected(client, pool, body):
    assert client.post("/api/location", json=body).status_code == 422
    assert pool.created == []


def test_device_error_returns_message(client, pool):
    pool.open_error = NoDeviceConnectedError()

    response = client.post("/api/connect")

    assert response.status_code == 502
    assert "Kein iPhone" in response.json()["detail"]


def test_cross_site_requests_are_rejected(client, pool):
    response = client.post(
        "/api/location", json={"latitude": 1, "longitude": 2}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403

    response = client.post(
        "/api/location", json={"latitude": 1, "longitude": 2}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert pool.created == []


def test_same_origin_request_is_accepted(client):
    response = client.post(
        "/api/location",
        json={"latitude": 1, "longitude": 2},
        headers={"Origin": LOCAL, "Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 200


def test_non_json_body_is_rejected(client, pool):
    # Ein Formular einer fremden Seite kann nur "einfache" Content-Types senden.
    response = client.post(
        "/api/location", content='{"latitude": 1, "longitude": 2}', headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 422
    assert pool.created == []


def test_foreign_host_header_is_rejected(client):
    # DNS-Rebinding: Fremde Domain zeigt auf 127.0.0.1
    assert client.get("/api/status", headers={"Host": "evil.example:8765"}).status_code == 400


def test_lan_mode_requires_token(controller):
    with TestClient(create_app(controller, token="s3cret"), base_url="http://192.168.1.20:8765") as client:
        assert client.get("/api/status").status_code == 401
        assert client.get("/login", params={"token": "wrong"}, follow_redirects=False).status_code == 401

        response = client.get("/login", params={"token": "s3cret"}, follow_redirects=False)
        assert response.status_code == 303
        assert TOKEN_COOKIE in response.cookies

        assert client.get("/api/status").status_code == 200


def test_shutdown_restores_real_location(controller, pool):
    with TestClient(create_app(controller), base_url=LOCAL) as client:
        client.post("/api/location", json={"latitude": 1, "longitude": 2})
    assert pool.last.calls[-2:] == [("clear",), ("close",)]
