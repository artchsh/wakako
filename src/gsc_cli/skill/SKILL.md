---
name: gsc
description: Query Google Search Console from the terminal with the `gsc` CLI - search performance (clicks, impressions, CTR, position by query/page/country/device/date), URL indexing status, sitemaps and the list of verified properties. Use when the user asks about organic search traffic, rankings, keywords, indexing, or Search Console data.
---

# gsc - Google Search Console CLI

Read-only access to the user's Search Console through their personal Google login.
Run `gsc doctor` first if you are unsure whether it is set up.

## Output contract (built for agents)

- When stdout is not a terminal, output is **JSON by default** (a list of row objects).
  Override with `--format table|json|csv`; write to a file with `--output FILE`.
- Errors are a single JSON object on **stderr**: `{"error": {"code", "message", "hint"}}`.
- Exit codes: `0` ok, `1` other, `2` usage error (fix your arguments), `3` not logged in,
  `4` no permission for that property, `5` quota exceeded (wait, retry).
- `gsc commands` prints every command, option, valid value and exit code as JSON. Use it
  instead of guessing flags.

## Human-only step

`gsc login` opens a browser for Google sign-in. **You cannot do it.** On exit code `3`,
or if `gsc doctor` reports a failing `token`/`credentials` check, stop and ask the user
to run `gsc login` (first time only: `gsc login --client-secret path/to/client_secret.json`,
see the README for creating that file).

## Commands

```bash
gsc doctor                                   # setup/health check, never prompts
gsc sites                                    # properties the user can access -> use these exact strings
gsc query SITE [options]                     # search analytics
gsc inspect URL --site SITE                  # indexing status of one URL
gsc sitemaps SITE                            # sitemaps + error/warning counts
gsc commands                                 # full machine-readable CLI description
gsc logout                                   # delete the saved token (only if the user asks)
gsc skill show                               # print this guide
gsc skill install                            # copy this guide to ~/.claude/skills/gsc/SKILL.md
```

`SITE` is either `sc-domain:example.com` (domain property) or `https://example.com/`
(URL-prefix property, trailing slash included). **Always take the exact string from
`gsc sites`**; a wrong form returns exit code 4.

### `gsc query` options

| Option | Meaning | Default |
|---|---|---|
| `--dims query,page,country,device,date` | Group-by dimensions, comma-separated | `query` |
| `--days N` | Last N days, counted back from 3 days ago | `28` |
| `--start YYYY-MM-DD --end YYYY-MM-DD` | Explicit range (use both; overrides `--days`) | - |
| `--filter "DIM OP VALUE"` | Repeatable, ANDed. OP: `equals contains notContains includingRegex excludingRegex` | none |
| `--limit N` | Max rows, `0` = all (auto-paginates past 25,000) | `1000` |
| `--type` | `web image video news discover googleNews` | `web` |

Rows contain one key per dimension plus `clicks`, `impressions`, `ctr` (a fraction, 0.05 =
5%), `position` (average rank, lower is better).

## Recipes

```bash
# Top queries, last 28 days
gsc query sc-domain:example.com --dims query --limit 100

# Striking-distance keywords: pull everything, then keep position 8-20 with high impressions
gsc query sc-domain:example.com --dims query,page --limit 0 --output rows.json
#   ...then filter rows where 8 <= position <= 20, sort by impressions desc

# Low-CTR pages with real impressions
gsc query sc-domain:example.com --dims page --limit 0   # keep impressions > 500, ctr < 0.02

# One section of the site
gsc query sc-domain:example.com --dims page --filter "page contains /blog/"

# One page's queries
gsc query sc-domain:example.com --dims query --filter "page equals https://example.com/pricing"

# Period comparison: run twice with different ranges and diff
gsc query SITE --dims query --start 2026-09-01 --end 2026-09-14 --limit 0
gsc query SITE --dims query --start 2026-09-15 --end 2026-09-28 --limit 0

# Daily trend
gsc query SITE --dims date --days 90 --limit 0

# Mobile vs desktop
gsc query SITE --dims device

# Is this URL indexed? (look at verdict, coverage, google_canonical)
gsc inspect https://example.com/pricing --site sc-domain:example.com
```

## Gotchas

- Data lags ~3 days; the default range already accounts for it. Today/yesterday are empty.
- Search Console only keeps ~16 months of data.
- Very low-volume queries are anonymized and omitted, so totals from `--dims query` can be
  lower than totals with no dimension (`--dims ""`).
- `inspect` is quota-limited (about 2,000 URLs per property per day); do not loop over
  thousands of URLs.
- Prefer `--limit 0 --output file.json` for large pulls and analyse the file, rather than
  printing thousands of rows into the conversation.
- The CLI is read-only: it cannot submit sitemaps or request indexing.
