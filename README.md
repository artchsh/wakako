# gsc-wrapper

Google Search Console from the command line, using your personal Google account
(OAuth — no service accounts). Read-only.

## Install

```bash
pipx install .        # or: pip install -e ".[dev]" inside a venv
```

## One-time Google setup (about 5 minutes)

1. Create a project at https://console.cloud.google.com/ (free).
2. APIs & Services > Library: enable **Google Search Console API**.
3. APIs & Services > OAuth consent screen: user type **External**, fill in the app name and
   your email, add yourself as a test user.
4. **Publish the app** (consent screen > "Publish app" / In production). In "Testing" mode
   Google expires refresh tokens after 7 days. For personal use no verification is needed;
   you will just click through an "unverified app" warning at login.
5. APIs & Services > Credentials > Create credentials > **OAuth client ID** > type
   **Desktop app**. Download the JSON.

## Use

```bash
gsc login --client-secret path/to/client_secret.json   # opens your browser once
gsc sites
gsc query sc-domain:example.com --dims query,page --days 28 --limit 50
gsc query https://example.com/ --dims page --filter "page contains /blog" --format csv --output blog.csv
gsc inspect https://example.com/some-page --site sc-domain:example.com
gsc sitemaps sc-domain:example.com
gsc logout
```

`--format table|json|csv` and `--output FILE` work on every data command.
Search Analytics data lags by ~3 days, so `--days` counts back from 3 days ago.

Credentials live in `%APPDATA%\gsc-wrapper` (Windows) or `~/.config/gsc-wrapper`
(elsewhere). Override with `GSC_CONFIG_DIR`.

## Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```
