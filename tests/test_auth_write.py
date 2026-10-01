import json
import types

import pytest

from gsc_cli import auth


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "cfg"
    monkeypatch.setenv("GSC_CONFIG_DIR", str(path))
    return path


class FakeCreds:
    def to_json(self):
        return "{}"


class RecordingFlow:
    scopes = None

    @classmethod
    def from_client_secrets_file(cls, path, scopes):
        cls.scopes = scopes
        return cls()

    def run_local_server(self, port=0):
        return FakeCreds()


@pytest.fixture
def flow(monkeypatch):
    RecordingFlow.scopes = None
    monkeypatch.setattr(auth, "InstalledAppFlow", RecordingFlow)
    return RecordingFlow


def saved_client(cfg):
    cfg.mkdir(parents=True)
    (cfg / "client_secret.json").write_text("{}")


def test_default_login_is_read_only(cfg, flow):
    saved_client(cfg)
    auth.login()
    assert flow.scopes == auth.SCOPES == ["https://www.googleapis.com/auth/webmasters.readonly"]


def test_write_login_requests_webmasters_and_indexing(cfg, flow):
    saved_client(cfg)
    auth.login(write=True)
    assert flow.scopes == [
        "https://www.googleapis.com/auth/webmasters",
        "https://www.googleapis.com/auth/indexing",
    ]


def test_credentials_load_with_stored_scopes_so_refresh_never_narrows(cfg, monkeypatch):
    cfg.mkdir()
    (cfg / "token.json").write_text("{}")
    seen = {}

    class Creds:
        valid = True

    def loader(path, scopes):
        seen["scopes"] = scopes
        return Creds()

    monkeypatch.setattr(auth, "Credentials", types.SimpleNamespace(from_authorized_user_file=loader))
    auth.get_credentials()
    assert seen["scopes"] is None


def test_granted_scopes_reads_token(cfg):
    assert auth.granted_scopes() == []
    cfg.mkdir()
    (cfg / "token.json").write_text(json.dumps({"scopes": ["a", "b"]}))
    assert auth.granted_scopes() == ["a", "b"]
    (cfg / "token.json").write_text(json.dumps({"scopes": "a b"}))
    assert auth.granted_scopes() == ["a", "b"]
    (cfg / "token.json").write_text("not json")
    assert auth.granted_scopes() == []


def test_get_indexing_service_builds_v3(cfg, monkeypatch):
    cfg.mkdir()
    (cfg / "token.json").write_text("{}")

    class Creds:
        valid = True

    monkeypatch.setattr(auth, "Credentials",
                        types.SimpleNamespace(from_authorized_user_file=lambda p, s: Creds()))
    seen = {}

    def fake_build(name, version, credentials, cache_discovery):
        seen.update(name=name, version=version)
        return "svc"

    monkeypatch.setattr(auth, "build", fake_build)
    assert auth.get_indexing_service() == "svc"
    assert seen == {"name": "indexing", "version": "v3"}
