---
name: gsc
description: Query Google Search Console from the terminal with the `gsc` CLI - search performance (clicks, impressions, CTR, position by query/page/country/device/date), period-over-period comparison, URL indexing status (single or whole sitemap), sitemaps, and best-effort indexing requests. Use when the user asks about organic search traffic, rankings, keywords, indexing, or Search Console data.
---

# gsc - Google Search Console CLI

Access to the user's Search Console through their personal Google login. Reads work by
default; changing things at Google (submit/delete sitemap, request indexing) needs an
extra opt-in login. Run `gsc doctor` first if you are unsure whether it is set up.

## Output contract (built for agents)

- When stdout is not a terminal, output is **JSON by default** (a list of row objects).
  Override with `--format table|json|csv`; write to a file with `--output FILE`.
- Errors are a single JSON object on **stderr**: `{"error": {"code", "message", "hint"}}`.
- Exit codes: `0` ok, `1` other, `2` usage error (fix your arguments), `3` not logged in
  (or missing write scope), `4` no permission for that property, `5` quota exceeded (wait, retry).
- `gsc commands` prints every command, option, valid value and exit code as JSON. Use it
  instead of guessing flags.

## Human-only steps

`gsc login` opens a browser for Google sign-in. **You cannot do it.** On exit code `3`,
or if `gsc doctor` reports a failing `token`/`credentials` check, stop and ask the user
to run `gsc login` (first time only: `gsc login --client-secret path/to/client_secret.json`,
see the README for creating that file).

Write actions need `gsc login --write` (also human). `gsc doctor` shows `write_access`:
if it says "not granted", ask the user before attempting any write command.

## Commands

```bash
gsc doctor                                   # setup/health check, never prompts
gsc sites                                    # properties the user can access -> use these exact strings
gsc query SITE [options]                     # search analytics
gsc compare SITE [options]                   # this period vs the previous one, per-row deltas
gsc inspect URL --site SITE                  # indexing status of one URL
gsc inspect --sitemap SITEMAP_URL --site SITE   # ...of every URL in a sitemap
gsc sitemaps SITE                            # sitemaps + error/warning counts
gsc sitemaps SITE --submit URL               # (write) submit/resubmit a sitemap
gsc sitemaps SITE --delete URL --yes         # (write) remove a sitemap from Search Console
gsc request-indexing URL... [--yes]          # (write, best-effort) ask Google to recrawl
gsc commands                                 # full machine-readable CLI description
gsc logout                                   # delete the saved token (only if the user asks)
gsc skill show                               # print this guide
gsc skill install [--dest DIR]               # copy this guide to <DIR or ~/.claude/skills>/gsc/SKILL.md
```

`SITE` is either `sc-domain:example.com` (domain property) or `https://example.com/`
(URL-prefix property, trailing slash included). **Always take the exact string from
`gsc sites`**; a wrong form returns exit code 4.

### `gsc query` options

| Option | Meaning | Default |
|---|---|---|
| `--dims query,page,country,device,date` | Group-by dimensions, comma-separated (`""` = totals only) | `query` |
| `--days N` | Last N days, counted back from 3 days ago | `28` |
| `--start YYYY-MM-DD --end YYYY-MM-DD` | Explicit range (use both; overrides `--days`) | - |
| `--filter "DIM OP VALUE"` | Repeatable, ANDed. OP: `equals contains notContains includingRegex excludingRegex` | none |
| `--limit N` | Max rows, `0` = all (auto-paginates past 25,000) | `1000` |
| `--type` | `web image video news discover googleNews` | `web` |

Rows contain one key per dimension plus `clicks`, `impressions`, `ctr` (a fraction, 0.05 =
5%), `position` (average rank, lower is better).

### `gsc compare` options

Same `--dims --days --start --end --filter --type` as `query`, plus:

| Option | Meaning | Default |
|---|---|---|
| `--sort clicks\|impressions\|ctr\|position` | Rank rows by biggest absolute change in this metric | `clicks` |
| `--min-impressions N` | Drop rows below N impressions in both periods | `0` |
| `--limit N` | Max rows (`0` = all) | `50` |

The previous period is the same length, immediately before the current one (with
`--days 28`: the latest 28 days vs the 28 days before). Each row has, per metric,
`X`, `X_prev`, `X_delta` and (clicks/impressions only) `X_pct` (percent change, `null`
when the previous value was 0). A row new in this period has `clicks_prev` and
`impressions_prev` = 0 and `ctr_prev`/`position_prev` = `null`; a row that vanished has
current `clicks = 0` and `ctr`/`position` = `null`. `position_delta < 0` means the
ranking improved.

### `gsc inspect` options

| Option | Meaning | Default |
|---|---|---|
| `URL` | One page: returns `{field, value}` rows (verdict, coverage, canonicals, last crawl...) | - |
| `--sitemap URL` | Instead of one URL: inspect every URL in the sitemap (follows sitemap indexes) | - |
| `--limit N` | With `--sitemap`: inspect at most N URLs (`0` = all). If you get exactly N rows there may be more | `100` |
| `--only-unindexed` | With `--sitemap`: keep only URLs whose verdict is not `PASS`, plus ones that failed (`error` set) | off |

Sitemap mode returns one row per URL: `url, verdict, coverage, indexing_state, robots_txt,
page_fetch, last_crawl, google_canonical, user_canonical, error`. `verdict` `PASS` = indexed.
Common `coverage` values: "Submitted and indexed", "URL is unknown to Google" (never
discovered), "Crawled - currently not indexed", "Discovered - currently not indexed",
"Page with redirect", "Duplicate without user-selected canonical".

### Write actions (need `gsc login --write`; exit code 3 otherwise)

- `gsc sitemaps SITE --submit URL` submits or resubmits a sitemap so Google refetches it.
  This is the officially supported way to tell Google about new URLs.
- `gsc sitemaps SITE --delete URL --yes` removes a stale sitemap from Search Console
  (e.g. one that now 404s). Refuses without `--yes`.
- `gsc request-indexing URL... [--sitemap URL --site SITE --only-unindexed] [--limit N] [--yes]`
  asks Google to recrawl URLs via the **Indexing API**. **Best-effort and unofficial for
  normal pages**: Google documents that API only for job-posting and livestream pages, so
  it may accept the request and still not index the page. It needs the user to be a
  property **owner** (not just full user), the "Web Search Indexing API" enabled in their
  GCP project, and the default quota is about 200 URLs/day. Without `--yes` it is a dry run
  that only lists what would be sent: always show the user that list and get a go-ahead
  before re-running with `--yes`. `--only-unindexed` (needs `--site`) first inspects up to
  `--limit` URLs and submits only the ones that are not indexed.

## Recipes

```bash
# Top queries, last 28 days
gsc query sc-domain:example.com --dims query --limit 100

# What changed vs the previous 28 days? (biggest movers first)
gsc compare sc-domain:example.com --dims query --limit 30
gsc compare sc-domain:example.com --dims page --sort impressions --min-impressions 100
gsc compare sc-domain:example.com --dims ""            # one totals row

# Striking-distance keywords: pull everything, then keep position 8-20 with high impressions
gsc query sc-domain:example.com --dims query,page --limit 0 --output rows.json
#   ...then filter rows where 8 <= position <= 20, sort by impressions desc

# Low-CTR pages with real impressions
gsc query sc-domain:example.com --dims page --limit 0   # keep impressions > 500, ctr < 0.02

# One section of the site / one page's queries
gsc query sc-domain:example.com --dims page --filter "page contains /blog/"
gsc query sc-domain:example.com --dims query --filter "page equals https://example.com/pricing"

# Daily trend / device split
gsc query SITE --dims date --days 90 --limit 0
gsc query SITE --dims device

# Is this URL indexed? Which URLs in the sitemap are not?
gsc inspect https://example.com/pricing --site sc-domain:example.com
gsc inspect --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed

# Get unindexed pages recrawled: dry run first, then send after the user agrees
gsc request-indexing --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed
gsc request-indexing --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed --yes

# Clean up a dead sitemap and resubmit the live one
gsc sitemaps SITE --delete https://example.com/old.xml --yes
gsc sitemaps SITE --submit https://example.com/sitemap.xml
```

## Gotchas

- Data lags ~3 days; the default range already accounts for it. Today/yesterday are empty.
- Search Console only keeps ~16 months of data.
- Very low-volume queries are anonymized and omitted, so totals from `--dims query` can be
  lower than totals with no dimension (`--dims ""`).
- `inspect` is quota-limited (about 2,000 URLs per property per day, 600/minute). Each
  inspection takes several seconds at Google; `--sitemap` runs 4 in parallel, so expect
  roughly 1.5-2 seconds per URL (28 URLs ~ 50 s, 500 URLs ~ 15 min). Use `--limit`.
- `inspect --sitemap` fetches the sitemap over plain HTTP from this machine; the sitemap
  must be publicly reachable and uncompressed XML (no `.gz`).
- Prefer `--limit 0 --output file.json` for large pulls and analyse the file, rather than
  printing thousands of rows into the conversation.
- "URL is unknown to Google" on a new site usually means Google has not crawled it yet:
  make sure the sitemap is submitted, the URL is linked from indexed pages, then give it
  days. Requesting indexing may speed this up but is not guaranteed.
