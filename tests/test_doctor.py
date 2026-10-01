import pytest

from gsc_cli import auth, client, doctor
from gsc_cli.errors import AuthError, PermissionDenied


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "cfg"
    monkeypatch.setenv("GSC_CONFIG_DIR", str(path))
    return path


def by_check(rows):
    return {r["check"]: r for r in rows}


def test_nothing_set_up(cfg):
    rows = by_check(doctor.run_checks())
    assert rows["client_secret"]["status"] == "fail"
    assert rows["token"]["status"] == "fail"
    assert rows["api_access"]["status"] == "skipped"


def test_everything_ok(cfg, monkeypatch):
    cfg.mkdir()
    (cfg / "client_secret.json").write_text("{}")
    (cfg / "token.json").write_text("{}")
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "list_sites", lambda svc: [{}, {}])
    rows = by_check(doctor.run_checks())
    assert {r["status"] for r in rows.values()} == {"ok"}
    assert rows["api_access"]["detail"] == "2 properties visible"


def test_expired_login(cfg, monkeypatch):
    cfg.mkdir()
    (cfg / "token.json").write_text("{}")

    def expired():
        raise AuthError("Not logged in or session expired - run `gsc login`.")

    monkeypatch.setattr(auth, "get_service", expired)
    rows = by_check(doctor.run_checks())
    assert rows["credentials"]["status"] == "fail"
    assert rows["api_access"]["status"] == "skipped"


def test_api_denied(cfg, monkeypatch):
    cfg.mkdir()
    (cfg / "token.json").write_text("{}")
    monkeypatch.setattr(auth, "get_service", lambda: "svc")

    def denied(svc):
        raise PermissionDenied("Permission denied (403): API not enabled")

    monkeypatch.setattr(client, "list_sites", denied)
    rows = by_check(doctor.run_checks())
    assert rows["credentials"]["status"] == "ok"
    assert rows["api_access"]["status"] == "fail"
    assert "API not enabled" in rows["api_access"]["detail"]
