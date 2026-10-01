import os
import shutil
import sys
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from gsc_cli.errors import GscError

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
NOT_LOGGED_IN = "Not logged in or session expired — run `gsc login`."


def config_dir() -> Path:
    override = os.environ.get("GSC_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "gsc-wrapper"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gsc-wrapper"


def client_secret_file() -> Path:
    return config_dir() / "client_secret.json"


def token_file() -> Path:
    return config_dir() / "token.json"


def login(client_secret_path: "Path | str | None" = None) -> Path:
    if client_secret_path is not None:
        src = Path(client_secret_path)
        if not src.is_file():
            raise GscError(f"Client secret file not found: {src}")
        config_dir().mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, client_secret_file())
    elif not client_secret_file().is_file():
        raise GscError(
            "No OAuth client secret saved yet. Run "
            "`gsc login --client-secret path/to/client_secret.json` "
            "(see README for how to create one)."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_file()), SCOPES
        )
    except (ValueError, KeyError):
        raise GscError(
            f"{client_secret_file()} is not a valid OAuth client file. "
            "Download a 'Desktop app' client secret from Google Cloud Console."
        ) from None
    creds = flow.run_local_server(port=0)
    token_file().write_text(creds.to_json(), encoding="utf-8")
    return token_file()


def logout() -> bool:
    path = token_file()
    if path.is_file():
        path.unlink()
        return True
    return False


def get_credentials():
    path = token_file()
    if not path.is_file():
        raise GscError(NOT_LOGGED_IN)
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, KeyError):
        raise GscError(NOT_LOGGED_IN) from None
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise GscError(NOT_LOGGED_IN)
    try:
        creds.refresh(Request())
    except RefreshError:
        raise GscError(NOT_LOGGED_IN) from None
    path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_service():
    return build(
        "searchconsole", "v1", credentials=get_credentials(), cache_discovery=False
    )
