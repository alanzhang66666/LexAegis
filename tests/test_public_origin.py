"""LEX_PUBLIC_ORIGIN: opt-in extra address; unset keeps loopback-only checks."""
import pytest
from fastapi.testclient import TestClient

from lexaegis.api import create_app, public_origin

PASSWORD = "unit-test-password"


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEX_RUN_PROFILE", "production")
    monkeypatch.setenv("LEX_GATEWAY_SECRET", "unit-test-secret-32-characters-long")
    monkeypatch.setenv("LEX_GATEWAY_URL", "http://testserver")
    monkeypatch.setenv("LEX_OCR_ENABLED", "0")
    monkeypatch.delenv("LEX_EDGE_MODEL", raising=False)
    clients = []

    def build(value=None):
        if value is None:
            monkeypatch.delenv("LEX_PUBLIC_ORIGIN", raising=False)
        else:
            monkeypatch.setenv("LEX_PUBLIC_ORIGIN", value)
        client = TestClient(create_app(tmp_path / f"app{len(clients)}", password=PASSWORD))
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def login(client, host, origin):
    return client.post("/api/v1/login", json={"password": PASSWORD},
                       headers={"host": host, "origin": origin})


def test_unset_keeps_loopback_only(make_client):
    client = make_client()
    assert client.get("/api/v1/health", headers={"host": "115.29.16.14"}).status_code == 400
    assert login(client, "127.0.0.1:38765", "http://115.29.16.14").status_code == 403
    assert login(client, "testserver", "http://testserver").status_code == 200


def test_ip_on_port_80_is_accepted_when_configured(make_client):
    client = make_client("http://115.29.16.14")
    assert client.get("/api/v1/health", headers={"host": "115.29.16.14"}).status_code == 200
    assert login(client, "115.29.16.14", "http://115.29.16.14").status_code == 200


def test_only_the_configured_address_is_added(make_client):
    client = make_client("http://115.29.16.14")
    assert client.get("/api/v1/health", headers={"host": "203.0.113.9"}).status_code == 400
    assert login(client, "115.29.16.14", "http://evil.example").status_code == 403
    assert login(client, "115.29.16.14", "http://115.29.16.14:8080").status_code == 403
    assert login(client, "115.29.16.14", "https://115.29.16.14").status_code == 403


def test_non_default_port_must_match(make_client):
    client = make_client("http://115.29.16.14:38765")
    assert login(client, "115.29.16.14:38765", "http://115.29.16.14:38765").status_code == 200
    assert login(client, "115.29.16.14", "http://115.29.16.14").status_code == 403


@pytest.mark.parametrize("value, expected", [
    ("http://115.29.16.14", {"host": "115.29.16.14", "origin": "http://115.29.16.14"}),
    ("http://115.29.16.14:80/", {"host": "115.29.16.14", "origin": "http://115.29.16.14"}),
    ("https://Lex.Example.com:443", {"host": "lex.example.com", "origin": "https://lex.example.com"}),
    ("http://115.29.16.14:38765", {"host": "115.29.16.14", "origin": "http://115.29.16.14:38765"}),
])
def test_origin_is_normalised(monkeypatch, value, expected):
    monkeypatch.setenv("LEX_PUBLIC_ORIGIN", value)
    assert public_origin() == expected


@pytest.mark.parametrize("value", [
    "115.29.16.14", "ftp://115.29.16.14", "http://115.29.16.14/app", "http://u:p@115.29.16.14",
    "http://115.29.16.14?x=1", "http://115.29.16.14:99999",
])
def test_invalid_values_refuse_startup(monkeypatch, tmp_path, value):
    monkeypatch.setenv("LEX_PUBLIC_ORIGIN", value)
    with pytest.raises(ValueError):
        public_origin()


def test_unset_or_blank_returns_none(monkeypatch):
    monkeypatch.delenv("LEX_PUBLIC_ORIGIN", raising=False)
    assert public_origin() is None
    monkeypatch.setenv("LEX_PUBLIC_ORIGIN", "  ")
    assert public_origin() is None
