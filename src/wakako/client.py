import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests
from googleapiclient.errors import HttpError

from wakako.errors import AuthError, WakakoError, PermissionDenied, QuotaError, UsageError

DATA_LAG_DAYS = 3
ROW_LIMIT = 25000
VALID_DIMS = ("query", "page", "country", "device", "date")
VALID_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
OPERATORS = ("equals", "contains", "notContains", "includingRegex", "excludingRegex")
INSPECT_WORKERS = 4
SORT_METRICS = ("clicks", "impressions", "ctr", "position")
SUMMARY_FIELDS = (
    "verdict", "coverage", "indexing_state", "robots_txt",
    "page_fetch", "last_crawl", "google_canonical", "user_canonical",
)


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise UsageError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from None


def date_range(
    days: int, start: str | None, end: str | None, today: date | None = None
) -> tuple[str, str]:
    if start or end:
        if not (start and end):
            raise UsageError("Provide both --start and --end, or use --days.")
        start_d, end_d = _parse_date(start), _parse_date(end)
        if start_d > end_d:
            raise UsageError("--start must be on or before --end.")
        return start_d.isoformat(), end_d.isoformat()
    if days < 1:
        raise UsageError("--days must be at least 1.")
    today = today or date.today()
    end_d = today - timedelta(days=DATA_LAG_DAYS)
    start_d = end_d - timedelta(days=days - 1)
    return start_d.isoformat(), end_d.isoformat()


def parse_dims(text: str) -> list[str]:
    dims = [d.strip() for d in text.split(",") if d.strip()]
    for d in dims:
        if d not in VALID_DIMS:
            raise UsageError(
                f"Unknown dimension '{d}'. Valid dimensions: {', '.join(VALID_DIMS)}."
            )
    return dims


def parse_filter(text: str) -> dict:
    parts = text.strip().split(None, 2)
    usage = (
        "Invalid filter. Use \"<dimension> <operator> <expression>\", e.g. "
        f"\"page contains /blog\". Operators: {', '.join(OPERATORS)}."
    )
    if len(parts) != 3:
        raise UsageError(usage)
    dimension, operator, expression = parts
    if dimension not in VALID_DIMS:
        raise UsageError(f"{usage} Unknown dimension '{dimension}'.")
    ops = {o.lower(): o for o in OPERATORS}
    if operator.lower() not in ops:
        raise UsageError(f"{usage} Unknown operator '{operator}'.")
    return {
        "dimension": dimension,
        "operator": ops[operator.lower()],
        "expression": expression,
    }


def validate_search_type(value: str) -> str:
    if value not in VALID_TYPES:
        raise UsageError(
            f"Unknown search type '{value}'. Valid types: {', '.join(VALID_TYPES)}."
        )
    return value


def validate_sort(value: str) -> str:
    if value not in SORT_METRICS:
        raise UsageError(f"Unknown sort metric '{value}'. Valid: {', '.join(SORT_METRICS)}.")
    return value


def build_query_body(
    dims: list[str],
    start: str,
    end: str,
    filters: list[dict],
    search_type: str,
    start_row: int,
    row_limit: int,
) -> dict:
    body = {
        "startDate": start,
        "endDate": end,
        "dimensions": dims,
        "searchType": search_type,
        "rowLimit": row_limit,
        "startRow": start_row,
    }
    if filters:
        body["dimensionFilterGroups"] = [{"groupType": "and", "filters": filters}]
    return body


def _reason(error: HttpError) -> str:
    try:
        return json.loads(error.content)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return str(error.reason or "unknown error")


def _needs_write_scope(error: HttpError) -> bool:
    text = (error.content or b"").decode("utf-8", "replace").lower()
    return "scope_insufficient" in text or ("insufficient" in text and "scope" in text)


def _api_disabled(error: HttpError) -> bool:
    text = (error.content or b"").decode("utf-8", "replace")
    return "SERVICE_DISABLED" in text or "has not been used in project" in text


def execute(
    request, *, site: str | None = None, sleep=time.sleep,
    login_flag: str = "--write", permission_hint: str | None = None,
):
    delay = 1
    for attempt in range(3):
        try:
            return request.execute()
        except HttpError as e:
            status = e.resp.status
            if status == 429:
                if attempt < 2:
                    sleep(delay)
                    delay *= 2
                    continue
                raise QuotaError(
                    "Quota exceeded (429).", hint="Wait a bit and retry."
                ) from e
            if status == 403 and _needs_write_scope(e):
                raise AuthError(
                    "Missing permission scope for this action (403).",
                    hint=f"Run `wakako login {login_flag}` (human step: browser sign-in) to grant access.",
                ) from e
            if status == 403 and _api_disabled(e):
                raise PermissionDenied(
                    f"{_reason(e)}",
                    hint="Enable that API in your Google Cloud project (the link is in the "
                    "message), wait a minute or two for it to propagate, then retry.",
                ) from e
            if status == 403:
                target = f"No access to {site}" if site else "Permission denied"
                raise PermissionDenied(
                    f"{target} (403): {_reason(e).rstrip('.')}.",
                    hint=permission_hint or "Check the exact property string with `wakako sites` "
                    "and that you are logged in as the right Google account.",
                ) from e
            raise WakakoError(f"Google API error {status}: {_reason(e)}") from e


def query_rows(
    service, site, dims, start, end, filters, search_type, limit
) -> list[dict]:
    rows: list[dict] = []
    start_row = 0
    while True:
        page_size = ROW_LIMIT if limit <= 0 else min(ROW_LIMIT, limit - len(rows))
        body = build_query_body(
            dims, start, end, filters, search_type, start_row, page_size
        )
        response = execute(
            service.searchanalytics().query(siteUrl=site, body=body), site=site
        )
        batch = response.get("rows", [])
        for raw in batch:
            row = dict(zip(dims, raw.get("keys", [])))
            for metric in ("clicks", "impressions", "ctr", "position"):
                row[metric] = raw.get(metric)
            rows.append(row)
        start_row += len(batch)
        if len(batch) < page_size or (limit > 0 and len(rows) >= limit):
            return rows


def list_sites(service) -> list[dict]:
    response = execute(service.sites().list())
    return [
        {"site": s["siteUrl"], "permission": s.get("permissionLevel", "")}
        for s in response.get("siteEntry", [])
    ]


def list_sitemaps(service, site: str) -> list[dict]:
    response = execute(service.sitemaps().list(siteUrl=site), site=site)
    return [
        {
            "path": s.get("path", ""),
            "type": s.get("type", ""),
            "last_downloaded": s.get("lastDownloaded", ""),
            "pending": s.get("isPending", False),
            "errors": s.get("errors", "0"),
            "warnings": s.get("warnings", "0"),
        }
        for s in response.get("sitemap", [])
    ]


def _inspect_fields(service, site: str, url: str) -> dict:
    body = {"inspectionUrl": url, "siteUrl": site}
    response = execute(service.urlInspection().index().inspect(body=body), site=site)
    result = response.get("inspectionResult", {})
    index = result.get("indexStatusResult", {})
    fields = {
        "verdict": index.get("verdict"),
        "coverage": index.get("coverageState"),
        "indexing_state": index.get("indexingState"),
        "robots_txt": index.get("robotsTxtState"),
        "page_fetch": index.get("pageFetchState"),
        "last_crawl": index.get("lastCrawlTime"),
        "crawled_as": index.get("crawledAs"),
        "google_canonical": index.get("googleCanonical"),
        "user_canonical": index.get("userCanonical"),
        "mobile_usability": result.get("mobileUsabilityResult", {}).get("verdict"),
        "rich_results": result.get("richResultsResult", {}).get("verdict"),
    }
    return fields


def inspect_url(service, site: str, url: str) -> list[dict]:
    fields = _inspect_fields(service, site, url)
    return [{"field": k, "value": v or ""} for k, v in fields.items()]


# ---- bulk inspection --------------------------------------------------------

def _http_get(url: str) -> str:
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": "wakako"})
        response.raise_for_status()
    except requests.RequestException as e:
        raise UsageError(f"Could not fetch {url}: {e}") from None
    return response.text


def sitemap_urls(sitemap_url: str, fetch=_http_get, _depth: int = 0) -> list[str]:
    """All page URLs in a sitemap; follows sitemap indexes (2 levels). Order kept, deduped."""
    try:
        root = ET.fromstring(fetch(sitemap_url))
    except ET.ParseError:
        raise UsageError(f"{sitemap_url} is not valid XML.") from None
    locs = [
        e.text.strip()
        for e in root.iter()
        if e.tag.rsplit("}", 1)[-1] == "loc" and e.text and e.text.strip()
    ]
    if root.tag.rsplit("}", 1)[-1] == "sitemapindex":
        if _depth >= 2:
            raise UsageError(f"{sitemap_url}: sitemap indexes nested too deeply.")
        urls = [u for child in locs for u in sitemap_urls(child, fetch, _depth + 1)]
    else:
        urls = locs
    return list(dict.fromkeys(urls))


def inspect_many(
    service, site: str, urls: list[str], only_unindexed: bool = False, progress=None,
    service_factory=None, workers: int = 1,
) -> list[dict]:
    """Inspect each URL, in input order. Per-URL failures become rows with `error` set; a
    quota error ends the run. With workers > 1 and a `service_factory`, URLs are inspected
    in parallel, one API service per thread (the Google client is not thread-safe)."""
    blank = {k: "" for k in SUMMARY_FIELDS}
    parallel = workers > 1 and service_factory is not None
    stop = threading.Event()
    local = threading.local()

    def thread_service():
        if not parallel:
            return service
        if not hasattr(local, "service"):
            local.service = service_factory()
        return local.service

    def one(url):
        """-> (row, hit_quota), or None if skipped after a quota error elsewhere."""
        if stop.is_set():
            return None
        try:
            fields = _inspect_fields(thread_service(), site, url)
            return {"url": url, **{k: fields[k] or "" for k in SUMMARY_FIELDS}, "error": ""}, False
        except QuotaError as e:
            stop.set()
            return {"url": url, **blank, "error": str(e)}, True
        except WakakoError as e:
            return {"url": url, **blank, "error": str(e)}, False

    rows: list[dict] = []
    pool = ThreadPoolExecutor(max_workers=workers) if parallel else None
    try:
        results = pool.map(one, urls) if pool else map(one, urls)
        for done, result in enumerate(results, 1):
            if result is None:
                break
            row, hit_quota = result
            rows.append(row)
            if hit_quota:
                break
            if progress:
                progress(done, len(urls))
    finally:
        if pool:
            stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
    if only_unindexed:
        rows = [r for r in rows if r["verdict"] != "PASS"]
    return rows


# ---- period comparison ------------------------------------------------------

def previous_range(start: str, end: str) -> tuple[str, str]:
    """The period of equal length immediately before [start, end]."""
    start_d, end_d = _parse_date(start), _parse_date(end)
    length = (end_d - start_d).days + 1
    prev_end = start_d - timedelta(days=1)
    return (prev_end - timedelta(days=length - 1)).isoformat(), prev_end.isoformat()


def _pct(current, previous):
    return round((current - previous) / previous * 100, 1) if previous else None


def compare_rows(
    service, site, dims, start, end, filters, search_type, limit,
    sort: str = "clicks", min_impressions: int = 0,
) -> list[dict]:
    validate_sort(sort)
    prev_start, prev_end = previous_range(start, end)
    current = query_rows(service, site, dims, start, end, filters, search_type, 0)
    previous = query_rows(service, site, dims, prev_start, prev_end, filters, search_type, 0)

    def key(row):
        return tuple(row[d] for d in dims)

    cur_by, prev_by = {key(r): r for r in current}, {key(r): r for r in previous}
    rows = []
    for k in [*cur_by, *[k for k in prev_by if k not in cur_by]]:
        c, p = cur_by.get(k), prev_by.get(k)
        row = dict(zip(dims, k))
        for m in ("clicks", "impressions"):
            cv, pv = (c[m] if c else 0), (p[m] if p else 0)
            row.update({m: cv, f"{m}_prev": pv, f"{m}_delta": cv - pv, f"{m}_pct": _pct(cv, pv)})
        for m, digits in (("ctr", 4), ("position", 1)):
            cv = round(c[m], digits) if c and c[m] is not None else None
            pv = round(p[m], digits) if p and p[m] is not None else None
            delta = None if cv is None or pv is None else round(cv - pv, digits)
            row.update({m: cv, f"{m}_prev": pv, f"{m}_delta": delta})
        rows.append(row)

    rows = [r for r in rows if max(r["impressions"], r["impressions_prev"]) >= min_impressions]
    rows.sort(key=lambda r: (-abs(r[f"{sort}_delta"] or 0), -r["impressions"]))
    return rows[:limit] if limit > 0 else rows


# ---- write actions (need `wakako login --write`) --------------------------------

def submit_sitemap(service, site: str, sitemap_url: str) -> list[dict]:
    execute(service.sitemaps().submit(siteUrl=site, feedpath=sitemap_url), site=site)
    return [{"action": "submitted", "site": site, "sitemap": sitemap_url}]


def delete_sitemap(service, site: str, sitemap_url: str) -> list[dict]:
    execute(service.sitemaps().delete(siteUrl=site, feedpath=sitemap_url), site=site)
    return [{"action": "deleted", "site": site, "sitemap": sitemap_url}]


def request_indexing(indexing_service, urls: list[str]) -> list[dict]:
    """Indexing API URL_UPDATED notifications. Best-effort for non-job/livestream pages."""
    rows: list[dict] = []
    for url in urls:
        try:
            response = execute(
                indexing_service.urlNotifications().publish(
                    body={"url": url, "type": "URL_UPDATED"}
                )
            )
        except (QuotaError, AuthError) as e:
            rows.append({"url": url, "status": "error", "detail": str(e)})
            break
        except WakakoError as e:
            rows.append({"url": url, "status": "error", "detail": str(e)})
            continue
        notified = (response or {}).get("urlNotificationMetadata", {}).get("latestUpdate", {})
        rows.append({"url": url, "status": "requested", "detail": notified.get("notifyTime", "")})
    return rows
