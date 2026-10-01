---
name: wakako
description: Query Google Search Console from the terminal with the `wakako` CLI - search performance (clicks, impressions, CTR, position by query/page/country/device/date), period-over-period comparison, URL indexing status (single or whole sitemap), sitemaps, best-effort indexing requests, and optional Google Analytics 4 reports plus a combined search+analytics page analysis. Use when the user asks about organic search traffic, rankings, keywords, indexing, Search Console data, or website analytics / GA4.
---

# wakako - Google Search Console + Analytics CLI

Access to the user's Search Console through their personal Google login. Reads work by
default; changing things at Google (submit/delete sitemap, request indexing) needs an
extra opt-in login. Run `wakako doctor` first if you are unsure whether it is set up.

## Output contract (built for agents)

- When stdout is not a terminal, output is **JSON by default** (a list of row objects).
  Override with `--format table|json|csv`; write to a file with `--output FILE`.
- Errors are a single JSON object on **stderr**: `{"error": {"code", "message", "hint"}}`.
- Exit codes: `0` ok, `1` other, `2` usage error (fix your arguments), `3` not logged in
  (or missing write scope), `4` no permission for that property, `5` quota exceeded (wait, retry).
- `wakako commands` prints every command, option, valid value and exit code as JSON. Use it
  instead of guessing flags.

## Human-only steps

`wakako login` opens a browser for Google sign-in. **You cannot do it.** On exit code `3`,
or if `wakako doctor` reports a failing `token`/`credentials` check, stop and ask the user
to run `wakako login` (first time only: `wakako login --client-secret path/to/client_secret.json`,
see the README for creating that file).

Write actions need `wakako login --write` and Google Analytics needs `wakako login --ga` (both
human; they can be combined, and a later login keeps what was already granted).
`wakako doctor` shows `write_access` and `ga_access`: if one says "not granted", ask the
user before attempting those commands. Both are optional; everything else works without them.

## Commands

```bash
wakako doctor                                   # setup/health check, never prompts
wakako sites                                    # properties the user can access -> use these exact strings
wakako query SITE [options]                     # search analytics
wakako compare SITE [options]                   # this period vs the previous one, per-row deltas
wakako inspect URL --site SITE                  # indexing status of one URL
wakako inspect --sitemap SITEMAP_URL --site SITE   # ...of every URL in a sitemap
wakako sitemaps SITE                            # sitemaps + error/warning counts
wakako sitemaps SITE --submit URL               # (write) submit/resubmit a sitemap
wakako sitemaps SITE --delete URL --yes         # (write) remove a sitemap from Search Console
wakako request-indexing URL... [--yes]          # (write, best-effort) ask Google to recrawl
wakako ga properties                           # (GA) GA4 properties: numeric ID, name, account, website URLs
wakako ga report PROPERTY [options]             # (GA) any GA4 report
wakako ga landing-pages SITE --property ID      # (GA) per page: GSC clicks next to GA organic sessions
wakako commands                                 # full machine-readable CLI description
wakako logout                                   # delete the saved token (only if the user asks)
wakako skill show                               # print this guide
wakako skill install [--dest DIR]               # copy this guide to <DIR or ~/.claude/skills>/wakako/SKILL.md
```

`SITE` is either `sc-domain:example.com` (domain property) or `https://example.com/`
(URL-prefix property, trailing slash included). **Always take the exact string from
`wakako sites`**; a wrong form returns exit code 4.

### `wakako query` options

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

### `wakako compare` options

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

### `wakako inspect` options

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

### Write actions (need `wakako login --write`; exit code 3 otherwise)

- `wakako sitemaps SITE --submit URL` submits or resubmits a sitemap so Google refetches it.
  This is the officially supported way to tell Google about new URLs.
- `wakako sitemaps SITE --delete URL --yes` removes a stale sitemap from Search Console
  (e.g. one that now 404s). Refuses without `--yes`.
- `wakako request-indexing URL... [--sitemap URL --site SITE --only-unindexed] [--limit N] [--yes]`
  asks Google to recrawl URLs via the **Indexing API**. **Best-effort and unofficial for
  normal pages**: Google documents that API only for job-posting and livestream pages, so
  it may accept the request and still not index the page. It needs the user to be a
  property **owner** (not just full user), the "Web Search Indexing API" enabled in their
  GCP project, and the default quota is about 200 URLs/day. Without `--yes` it is a dry run
  that only lists what would be sent: always show the user that list and get a go-ahead
  before re-running with `--yes`. `--only-unindexed` (needs `--site`) first inspects up to
  `--limit` URLs and submits only the ones that are not indexed.

## Google Analytics 4 (optional)

Not needed for any GSC command. Needs `wakako login --ga` (human) and the GA4 account having
at least Viewer access. GA4 only (Universal Analytics is gone). Properties are identified
by a **numeric ID**: get it from `wakako ga properties`, whose `websites` column (the web
stream URLs) shows which property belongs to which site. If `wakako ga ...` exits 3, the user
has not granted GA access: ask them to run `wakako login --ga`.

### `wakako ga report PROPERTY` options

| Option | Meaning | Default |
|---|---|---|
| `--metrics a,b` | GA4 API metric names (`sessions`, `activeUsers`, `engagementRate`, `averageSessionDuration`, `keyEvents`, `screenPageViews`, `bounceRate`...) | `sessions,activeUsers` |
| `--dims a,b` | GA4 API dimension names (`date`, `landingPage`, `pagePath`, `sessionDefaultChannelGroup`, `sessionSource`, `country`, `deviceCategory`...). Empty = totals | none |
| `--days N` / `--start` `--end` | Last N days ending **yesterday**, or an explicit range | `28` |
| `--filter "DIM OP VALUE"` | Repeatable, ANDed. OP: `equals notEquals contains notContains beginsWith endsWith regex notRegex` | none |
| `--organic` | Only organic-search sessions | off |
| `--sort NAME[:asc\|:desc]` | A requested metric or dimension | first metric, desc |
| `--limit N` | Max rows (`0` = all) | `1000` |

Rows have one key per dimension (string) and per metric (number). Names are validated by
Google: a wrong dimension/metric name returns exit code 1 with the API's message.

### `wakako ga landing-pages SITE --property ID`

The combined analysis. Joins GSC (page level) with GA organic sessions per landing page, for
the same dates (GSC's 3-day lag applies; `--days/--start/--end/--limit` as in `query`).
Columns: `page, clicks, impressions, ctr, position` (from GSC) and `sessions,
sessions_per_click, engagement_rate, avg_session_duration (seconds), key_events` (from GA,
organic search only). Scoped to the property's hostname (and path, for URL-prefix
properties). Pages seen by only one side are kept: GSC-only pages have `sessions: 0`; GA-only
pages (e.g. Bing/other-engine organic traffic) have `clicks: null`.
How to read it: `sessions_per_click` far below 1 means clicks that never became a measured
session (consent banner blocking GA, slow load, bots); above 1 means other search engines
or tracking quirks; compare pages at similar positions on `engagement_rate` and
`key_events` to find content that ranks but does not convert.

## Recipes

```bash
# Top queries, last 28 days
wakako query sc-domain:example.com --dims query --limit 100

# What changed vs the previous 28 days? (biggest movers first)
wakako compare sc-domain:example.com --dims query --limit 30
wakako compare sc-domain:example.com --dims page --sort impressions --min-impressions 100
wakako compare sc-domain:example.com --dims ""            # one totals row

# Striking-distance keywords: pull everything, then keep position 8-20 with high impressions
wakako query sc-domain:example.com --dims query,page --limit 0 --output rows.json
#   ...then filter rows where 8 <= position <= 20, sort by impressions desc

# Low-CTR pages with real impressions
wakako query sc-domain:example.com --dims page --limit 0   # keep impressions > 500, ctr < 0.02

# One section of the site / one page's queries
wakako query sc-domain:example.com --dims page --filter "page contains /blog/"
wakako query sc-domain:example.com --dims query --filter "page equals https://example.com/pricing"

# Daily trend / device split
wakako query SITE --dims date --days 90 --limit 0
wakako query SITE --dims device

# (GA) Which property is this site? Then traffic, organic traffic, and the combined view
wakako ga properties
wakako ga report 123456789 --dims date --metrics sessions,activeUsers --days 30
wakako ga report 123456789 --organic --dims landingPage --metrics sessions,engagementRate,keyEvents --limit 50
wakako ga report 123456789 --dims sessionDefaultChannelGroup --metrics sessions     # traffic by channel
wakako ga landing-pages sc-domain:example.com --property 123456789 --limit 50

# Is this URL indexed? Which URLs in the sitemap are not?
wakako inspect https://example.com/pricing --site sc-domain:example.com
wakako inspect --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed

# Get unindexed pages recrawled: dry run first, then send after the user agrees
wakako request-indexing --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed
wakako request-indexing --sitemap https://example.com/sitemap.xml --site sc-domain:example.com --only-unindexed --yes

# Clean up a dead sitemap and resubmit the live one
wakako sitemaps SITE --delete https://example.com/old.xml --yes
wakako sitemaps SITE --submit https://example.com/sitemap.xml
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
