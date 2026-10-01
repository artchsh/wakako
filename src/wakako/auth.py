import json
import os
import shutil
import sys
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from wakako.errors import AuthError, UsageError

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
# Opt-in via `wakako login --write`: manage sitemaps + Indexing API (request indexing).
SCOPES_WRITE = [
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/indexing",
]
# Opt-in via `wakako login --ga`: read Google Analytics 4 (Data + Admin APIs).
GA_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
NOT_LOGGED_IN = "Not logged in or session expired - run `wakako login`."
LOGIN_HINT = "`wakako login` opens a browser and needs a human; an agent cannot complete it."


def config_dir() -> Path:
    """`WAKAKO_CONFIG_DIR` (or the old `GSC_CONFIG_DIR`), else the per-user config folder.
    Installs from before the rename keep using their existing `gsc-wrapper` folder, so a
    saved login survives; nothing is moved or copied automatically."""
    override = os.environ.get("WAKAKO_CONFIG_DIR") or os.environ.get("GSC_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    current, legacy = base / "wakako", base / "gsc-wrapper"
    return legacy if legacy.exists() and not current.exists() else current


def client_secret_file() -> Path:
    return config_dir() / "client_secret.json"


def token_file() -> Path:
    return config_dir() / "token.json"


def requested_scopes(write: bool = False, ga: bool = False) -> list[str]:
    """Scopes to request at login: what was asked for plus anything already granted, so a
    later `wakako login --ga` never silently drops write access (and vice versa)."""
    granted = set(granted_scopes())
    wanted = list(SCOPES_WRITE if (write or set(SCOPES_WRITE) <= granted) else SCOPES)
    if ga or GA_SCOPE in granted:
        wanted.append(GA_SCOPE)
    return list(dict.fromkeys(wanted))


def login(
    client_secret_path: "Path | str | None" = None, write: bool = False, ga: bool = False
) -> Path:
    if client_secret_path is not None:
        src = Path(client_secret_path)
        if not src.is_file():
            raise UsageError(f"Client secret file not found: {src}")
        config_dir().mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, client_secret_file())
    elif not client_secret_file().is_file():
        raise UsageError(
            "No OAuth client secret saved yet. Run "
            "`wakako login --client-secret path/to/client_secret.json` "
            "(see README for how to create one)."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_file()), requested_scopes(write, ga)
        )
    except (ValueError, KeyError):
        raise UsageError(
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
        raise AuthError(NOT_LOGGED_IN, hint=LOGIN_HINT)
    try:
        creds = Credentials.from_authorized_user_file(str(path), None)
    except (ValueError, KeyError):
        raise AuthError(NOT_LOGGED_IN, hint=LOGIN_HINT) from None
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise AuthError(NOT_LOGGED_IN, hint=LOGIN_HINT)
    try:
        creds.refresh(Request())
    except RefreshError:
        raise AuthError(NOT_LOGGED_IN, hint=LOGIN_HINT) from None
    path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_service():
    return build(
        "searchconsole", "v1", credentials=get_credentials(), cache_discovery=False
    )


def get_indexing_service():
    return build("indexing", "v3", credentials=get_credentials(), cache_discovery=False)


def granted_scopes() -> list[str]:
    """Scopes recorded in the saved token ([] if not logged in or unreadable)."""
    try:
        scopes = json.loads(token_file().read_text(encoding="utf-8")).get("scopes") or []
    except (OSError, ValueError):
        return []
    return scopes.split(" ") if isinstance(scopes, str) else list(scopes)


def _ga_credentials():
    creds = get_credentials()
    if GA_SCOPE not in granted_scopes():
        raise AuthError(
            "Google Analytics access has not been granted.",
            hint="Run `wakako login --ga` (human step: browser sign-in). Also enable the "
            "'Google Analytics Data API' and 'Google Analytics Admin API' in your GCP project.",
        )
    return creds


def get_analytics_data_service():
    return build("analyticsdata", "v1beta", credentials=_ga_credentials(), cache_discovery=False)


def get_analytics_admin_service():
    return build("analyticsadmin", "v1beta", credentials=_ga_credentials(), cache_discovery=False)
