# gsc-wrapper

Google Search Console from the command line, using your personal Google account
(OAuth — no service accounts). Read-only.

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
gsc inspect https://example.com/some-page --site sc-domain:example.com
gsc sitemaps sc-domain:example.com
gsc logout
```

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
