from wakako import auth, client
from wakako.errors import WakakoError


def run_checks() -> list[dict]:
    """Non-interactive health check. Each row: check, status (ok|fail|skipped), detail."""
    rows: list[dict] = []

    def add(check: str, status: str, detail: str) -> None:
        rows.append({"check": check, "status": status, "detail": detail})

    secret, token = auth.client_secret_file(), auth.token_file()
    add(
        "client_secret",
        "ok" if secret.is_file() else "fail",
        str(secret) if secret.is_file()
        else "missing - run `wakako login --client-secret PATH` (human step, see README)",
    )
    if not token.is_file():
        add("token", "fail", "not logged in - a human must run `wakako login`")
        add("api_access", "skipped", "needs a valid login")
        return rows
    add("token", "ok", str(token))
    write_granted = set(auth.SCOPES_WRITE) <= set(auth.granted_scopes())
    add(
        "write_access",
        "ok",
        "granted (sitemap submit/delete, request-indexing)" if write_granted
        else "not granted (optional): read-only. Run `wakako login --write` for write actions",
    )

    ga_granted = auth.GA_SCOPE in auth.granted_scopes()
    add(
        "ga_access",
        "ok",
        "granted (wakako ga ...)" if ga_granted
        else "not granted (optional): GSC works without it. Run `wakako login --ga` for Analytics",
    )

    try:
        service = auth.get_service()
    except WakakoError as e:
        add("credentials", "fail", str(e))
        add("api_access", "skipped", "needs a valid login")
        return rows
    add("credentials", "ok", "valid")

    try:
        count = len(client.list_sites(service))
    except WakakoError as e:
        add("api_access", "fail", str(e))
    else:
        add("api_access", "ok", f"{count} propert{'y' if count == 1 else 'ies'} visible")
    return rows
