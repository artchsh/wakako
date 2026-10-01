# GSC CLI — Design (v1)

Date: 2026-10-01

## Goal

A Python command-line wrapper around Google Search Console, authenticated as the user's
personal Google account via OAuth 2.0 (no service accounts). v1 is GSC-only and read-only.
Google Analytics (GA4) is a planned follow-up that will reuse the same auth module.

## Non-goals (v1)

- GA4 / Analytics Data API (next phase).
- Write actions (submit sitemaps, request indexing).
- Multiple accounts / profiles.
- A GUI or web server.

## Architecture

Python 3.10+, `typer` (CLI), `rich` (tables), Google client libraries
(`google-auth-oauthlib`, `google-api-python-client`). Installable via `pipx install .`;
the command is `gsc`.

Modules (`src/gsc_cli/`):

| Module | Responsibility | Depends on |
|---|---|---|
| `auth.py` | OAuth flow, token storage, refresh. Only module touching credentials. | google-auth-oauthlib |
| `client.py` | Thin wrapper over the Search Console API: pagination, date handling, filter building. | `auth.py` |
| `output.py` | Render rows as table / JSON / CSV, to stdout or file. | rich |
| `cli.py` | Typer commands. Parses args, calls `client`, hands results to `output`. No API logic. | all above |

OAuth scope: `https://www.googleapis.com/auth/webmasters.readonly`. Wider scopes can be
added later by re-running login.

## Auth and storage

- One-time setup by the user: create a GCP project, enable the Search Console API, create an
  OAuth client of type "Desktop app", download `client_secret.json`. Set the consent screen
  to "In production" so refresh tokens do not expire after 7 days (unverified-app warning
  is acceptable for personal use).
- `gsc login --client-secret PATH` copies the client file into the config dir, runs the
  local-server redirect flow in the browser, and saves the refresh token.
- `gsc logout` deletes the saved token.
- Config dir: `%APPDATA%\gsc-wrapper` on Windows, `~/.config/gsc-wrapper` elsewhere.
  Holds `client_secret.json` and `token.json`. Never inside the repo.
- Access tokens refresh automatically. If refresh fails (revoked/expired), print
  "Not logged in or session expired — run `gsc login`" and exit non-zero; no stack trace.

## Commands

Global options: `--format table|json|csv` (default `table`), `--output FILE`.

- `gsc login`, `gsc logout` — as above.
- `gsc sites` — list properties with permission level.
- `gsc query SITE` — search analytics query.
  - `--dims query,page,country,device,date` (comma-separated)
  - `--days N` (default 28) or `--start DATE --end DATE`
  - `--filter "page contains /blog"` (repeatable; operators: equals, contains,
    notContains, includingRegex, excludingRegex)
  - `--limit N` (default 1000; 0 = all)
  - `--type web|image|video|news|discover|googleNews`
  - Pages automatically past the API's 25,000-row cap using `startRow`.
  - Default end date is today minus 3 days (GSC data lag); `--days` counts back from it.
- `gsc inspect URL --site SITE` — URL Inspection: index status, canonical, last crawl,
  mobile usability, rich results summary.
- `gsc sitemaps SITE` — list sitemaps with status, last downloaded, errors/warnings.

`SITE` accepts either `sc-domain:example.com` or a URL-prefix property
(`https://example.com/`).

## Errors

- 403: "No access to <site>. Check the property URL (`gsc sites`) and that you are logged in
  as the right account."
- 429 / quota: message with retry hint; exponential backoff (3 tries) before failing.
- Not logged in / missing client file: actionable message pointing to `gsc login`.
- Invalid filter or dimension: usage error listing valid values.

## Testing

`pytest`, Google API client mocked. Covered:
- Query body construction (dimensions, filters, date defaults incl. 3-day lag).
- Pagination across multiple pages and `--limit` truncation.
- Filter parsing and validation.
- Output formatting (table/JSON/CSV).
- Auth: token load, refresh, and expired/revoked handling (credentials mocked).

The interactive browser login is verified manually once, not in automated tests.

## Future work

- GA4 commands (`ga properties`, `ga report`) reusing `auth.py` with added
  `analytics.readonly` scope.
- Optional write actions behind explicit scopes.
