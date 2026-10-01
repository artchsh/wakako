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


def test_login_ga_adds_analytics_scope(cfg, flow):
    saved_client(cfg)
    auth.login(ga=True)
    assert flow.scopes == [*auth.SCOPES, auth.GA_SCOPE]
    auth.login(write=True, ga=True)
    assert flow.scopes == [*auth.SCOPES_WRITE, auth.GA_SCOPE]


def test_relogin_keeps_capabilities_already_granted(cfg, flow):
    saved_client(cfg)
    (cfg / "token.json").write_text(json.dumps({"scopes": [*auth.SCOPES_WRITE, auth.GA_SCOPE]}))
    auth.login()  # plain login must not silently drop write or GA
    assert set(flow.scopes) == {*auth.SCOPES_WRITE, auth.GA_SCOPE}
    (cfg / "token.json").write_text(json.dumps({"scopes": list(auth.SCOPES)}))
    auth.login()
    assert flow.scopes == auth.SCOPES


def _logged_in_with(cfg, monkeypatch, scopes):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "token.json").write_text(json.dumps({"scopes": scopes}))

    class Creds:
        valid = True

    monkeypatch.setattr(auth, "Credentials",
                        types.SimpleNamespace(from_authorized_user_file=lambda p, s: Creds()))


def test_ga_services_refuse_without_ga_scope(cfg, monkeypatch):
    from gsc_cli.errors import AuthError

    _logged_in_with(cfg, monkeypatch, list(auth.SCOPES))
    for getter in (auth.get_analytics_data_service, auth.get_analytics_admin_service):
        with pytest.raises(AuthError) as exc:
            getter()
        assert "gsc login --ga" in exc.value.hint


def test_ga_services_build_data_and_admin_v1beta(cfg, monkeypatch):
    _logged_in_with(cfg, monkeypatch, [*auth.SCOPES, auth.GA_SCOPE])
    seen = []
    monkeypatch.setattr(auth, "build", lambda name, version, credentials, cache_discovery: seen.append((name, version)) or "svc")
    assert auth.get_analytics_data_service() == "svc"
    assert auth.get_analytics_admin_service() == "svc"
    assert seen == [("analyticsdata", "v1beta"), ("analyticsadmin", "v1beta")]
