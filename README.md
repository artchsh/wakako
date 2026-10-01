# gsc-wrapper

Google Search Console from the command line, using your personal Google account
(OAuth — no service accounts). Read-only by default; write actions are opt-in.

## Install (standalone, global `gsc` command)

```bash
uv tool install .            # or: pipx install .
gsc skill install            # optional: teach Claude Code to use it (~/.claude/skills/gsc)
```

After pulling changes, reinstall with `uv tool install --force .`.

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
gsc compare sc-domain:example.com --dims query --limit 20      # this period vs the one before
gsc inspect https://example.com/some-page --site sc-domain:example.com
gsc inspect --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed
gsc sitemaps sc-domain:example.com
gsc logout
```

`gsc compare` compares the latest `--days` (default 28) with the same-length period right
before it and gives each row `clicks`, `clicks_prev`, `clicks_delta`, `clicks_pct` (and the
same for impressions, ctr, position), biggest movers first (`--sort`, `--min-impressions`).

`gsc inspect --sitemap` inspects every URL in a sitemap (sitemap indexes are followed),
4 at a time, and returns one row per URL; `--only-unindexed` keeps just the ones Google
has not indexed. URL Inspection quota is about 2,000 URLs per property per day.

## Google Analytics 4 (optional)

GSC works without any of this. To add Analytics reports and a combined search + analytics
view:

1. In the same GCP project, enable the **Google Analytics Data API** and the
   **Google Analytics Admin API** (APIs & Services > Library).
2. `gsc login --ga` (a human step; combine with `--write` if you want both). Your Google
   account needs at least Viewer access on the GA4 property. Later logins keep whatever you
   already granted; `gsc logout` first if you want to start from scratch.

```bash
gsc ga properties                                   # numeric property IDs + their website URLs
gsc ga report 123456789 --dims date --metrics sessions,activeUsers
gsc ga report 123456789 --organic --dims landingPage --metrics sessions,engagementRate,keyEvents --limit 50
gsc ga landing-pages sc-domain:example.com --property 123456789 --limit 50
```

`gsc ga landing-pages` lines up each page's search clicks, impressions and position from
Search Console with its organic sessions, engagement rate and key events from Analytics.
`gsc doctor` shows whether GA access has been granted (`ga_access`).

## Write actions (optional, opt-in)

Everything above is read-only. To also **submit/delete sitemaps** and **request indexing**,
log in once more with write access (a human step; it replaces the saved token):

```bash
gsc login --write
gsc sitemaps sc-domain:example.com --submit https://example.com/sitemap.xml
gsc sitemaps sc-domain:example.com --delete https://example.com/old-sitemap.xml --yes
gsc request-indexing https://example.com/new-post                   # dry run: lists what would be sent
gsc request-indexing https://example.com/new-post --yes             # actually send
gsc request-indexing --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed --yes
```

**About `request-indexing`:** Google has no public API for the "Request indexing" button in
the Search Console UI. This command uses the Google **Indexing API**, which Google documents
only for job-posting and livestream pages. It accepts other URLs, but Google may ignore
them, so treat it as best-effort (the supported way to announce new URLs is a sitemap).
It also needs:

1. You to be a verified **owner** of the property (full-user access is not enough).
2. The **Web Search Indexing API** enabled in your GCP project (APIs & Services > Library).
3. `gsc login --write`. The default quota is about 200 URLs per day.

Without `--yes`, `request-indexing` and `sitemaps --delete` change nothing.

`--format table|json|csv` and `--output FILE` work on every data command.
Search Analytics data lags by ~3 days, so `--days` counts back from 3 days ago.

Credentials live in `%APPDATA%\gsc-wrapper` (Windows) or `~/.config/gsc-wrapper`
(elsewhere). Override with `GSC_CONFIG_DIR`.

## For AI agents

The tool is built to be driven by an agent:

- Output is **JSON by default when piped** (table in a terminal); `--format table|json|csv`
  overrides. Errors are one JSON object on stderr: `{"error": {"code", "message", "hint"}}`.
- Typed exit codes: `0` ok, `2` usage, `3` not logged in, `4` no permission, `5` quota.
- `gsc doctor` checks setup without prompting; `gsc commands` prints every command, option,
  valid value and exit code as JSON; `gsc skill show` prints the full usage guide
  (`src/gsc_cli/skill/SKILL.md`), which `gsc skill install` copies into Claude Code skills.
- `gsc login` is the only step that needs a human (browser sign-in).

## Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```
