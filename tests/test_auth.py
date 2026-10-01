import types

import pytest
from google.auth.exceptions import RefreshError

from wakako import auth
from wakako.errors import WakakoError


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "cfg"
    monkeypatch.setenv("WAKAKO_CONFIG_DIR", str(path))
    return path


# ---- config_dir -------------------------------------------------------------

def test_config_dir_env_override(cfg):
    assert auth.config_dir() == cfg
    assert auth.token_file() == cfg / "token.json"
    assert auth.client_secret_file() == cfg / "client_secret.json"


def test_config_dir_windows(tmp_path, monkeypatch):
    monkeypatch.delenv("WAKAKO_CONFIG_DIR", raising=False)
    monkeypatch.setattr(auth.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert auth.config_dir() == tmp_path / "wakako"


def test_config_dir_posix_uses_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("WAKAKO_CONFIG_DIR", raising=False)
    monkeypatch.setattr(auth.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert auth.config_dir() == tmp_path / "wakako"


# ---- login ------------------------------------------------------------------

class FakeCreds:
    def to_json(self):
        return '{"refresh_token": "r"}'


class FakeFlow:
    last = None
    fail_on_load = False

    @classmethod
    def from_client_secrets_file(cls, path, scopes):
        if cls.fail_on_load:
            raise ValueError("bad client file")
        cls.last = (path, scopes)
        return cls()

    def run_local_server(self, port=0):
        return FakeCreds()


@pytest.fixture(autouse=True)
def fake_flow(monkeypatch):
    FakeFlow.fail_on_load = False
    monkeypatch.setattr(auth, "InstalledAppFlow", FakeFlow)


def test_login_copies_client_secret_and_saves_token(cfg, tmp_path):
    src = tmp_path / "cs.json"
    src.write_text('{"installed": {}}')
    token = auth.login(src)
    assert token == cfg / "token.json"
    assert (cfg / "client_secret.json").read_text() == '{"installed": {}}'
    assert token.read_text() == '{"refresh_token": "r"}'
    assert FakeFlow.last[1] == auth.SCOPES


def test_login_reuses_saved_client_secret(cfg):
    cfg.mkdir(parents=True)
    (cfg / "client_secret.json").write_text('{"installed": {}}')
    assert auth.login(None) == cfg / "token.json"


def test_login_without_any_client_secret_errors(cfg):
    with pytest.raises(WakakoError, match="client secret"):
        auth.login(None)


def test_login_missing_file_errors(cfg, tmp_path):
    with pytest.raises(WakakoError, match="not found"):
        auth.login(tmp_path / "nope.json")


def test_login_invalid_client_file_errors(cfg, tmp_path):
    src = tmp_path / "cs.json"
    src.write_text("not json")
    FakeFlow.fail_on_load = True
    with pytest.raises(WakakoError, match="valid"):
        auth.login(src)


# ---- get_credentials --------------------------------------------------------

class StoredCreds:
    def __init__(self, valid, refresh_token="r", fail=False):
        self.valid = valid
        self.refresh_token = refresh_token
        self.fail = fail

    def refresh(self, request):
        if self.fail:
            raise RefreshError("revoked")
        self.valid = True

    def to_json(self):
        return '{"refreshed": true}'


def patch_stored(monkeypatch, creds=None, error=None):
    def loader(path, scopes):
        if error:
            raise error
        return creds

    monkeypatch.setattr(
        auth, "Credentials", types.SimpleNamespace(from_authorized_user_file=loader)
    )


def write_token(cfg):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "token.json").write_text("{}")


def test_get_credentials_not_logged_in(cfg):
    with pytest.raises(WakakoError, match="wakako login"):
        auth.get_credentials()


def test_get_credentials_returns_valid_creds(cfg, monkeypatch):
    write_token(cfg)
    creds = StoredCreds(valid=True)
    patch_stored(monkeypatch, creds)
    assert auth.get_credentials() is creds


def test_get_credentials_refreshes_and_saves(cfg, monkeypatch):
    write_token(cfg)
    creds = StoredCreds(valid=False)
    patch_stored(monkeypatch, creds)
    assert auth.get_credentials() is creds
    assert creds.valid
    assert (cfg / "token.json").read_text() == '{"refreshed": true}'


def test_get_credentials_refresh_failure_asks_to_login(cfg, monkeypatch):
    write_token(cfg)
    patch_stored(monkeypatch, StoredCreds(valid=False, fail=True))
    with pytest.raises(WakakoError, match="wakako login"):
        auth.get_credentials()


def test_get_credentials_without_refresh_token_asks_to_login(cfg, monkeypatch):
    write_token(cfg)
    patch_stored(monkeypatch, StoredCreds(valid=False, refresh_token=None))
    with pytest.raises(WakakoError, match="wakako login"):
        auth.get_credentials()


def test_get_credentials_corrupt_token_asks_to_login(cfg, monkeypatch):
    write_token(cfg)
    patch_stored(monkeypatch, error=ValueError("corrupt"))
    with pytest.raises(WakakoError, match="wakako login"):
        auth.get_credentials()


# ---- logout / get_service ---------------------------------------------------

def test_logout_removes_token(cfg):
    write_token(cfg)
    assert auth.logout() is True
    assert not (cfg / "token.json").exists()
    assert auth.logout() is False


def test_get_service_builds_searchconsole_v1(cfg, monkeypatch):
    write_token(cfg)
    creds = StoredCreds(valid=True)
    patch_stored(monkeypatch, creds)
    seen = {}

    def fake_build(name, version, credentials, cache_discovery):
        seen.update(name=name, version=version, credentials=credentials,
                    cache_discovery=cache_discovery)
        return "service"

    monkeypatch.setattr(auth, "build", fake_build)
    assert auth.get_service() == "service"
    assert seen == {"name": "searchconsole", "version": "v1",
                    "credentials": creds, "cache_discovery": False}


def test_legacy_env_var_still_works(tmp_path, monkeypatch):
    monkeypatch.delenv("WAKAKO_CONFIG_DIR", raising=False)
    monkeypatch.setenv("GSC_CONFIG_DIR", str(tmp_path / "old-env"))
    assert auth.config_dir() == tmp_path / "old-env"
    monkeypatch.setenv("WAKAKO_CONFIG_DIR", str(tmp_path / "new-env"))
    assert auth.config_dir() == tmp_path / "new-env"  # new variable wins


def test_existing_gsc_wrapper_folder_is_kept_so_logins_survive(tmp_path, monkeypatch):
    monkeypatch.delenv("WAKAKO_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GSC_CONFIG_DIR", raising=False)
    monkeypatch.setattr(auth.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert auth.config_dir() == tmp_path / "wakako"  # fresh install
    (tmp_path / "gsc-wrapper").mkdir()
    assert auth.config_dir() == tmp_path / "gsc-wrapper"  # pre-rename install keeps working
    (tmp_path / "wakako").mkdir()
    assert auth.config_dir() == tmp_path / "wakako"  # once the new folder exists it wins
