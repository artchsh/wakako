import json
import time
from datetime import date, datetime, timedelta

from googleapiclient.errors import HttpError

from gsc_cli.errors import GscError, PermissionDenied, QuotaError, UsageError

DATA_LAG_DAYS = 3
ROW_LIMIT = 25000
VALID_DIMS = ("query", "page", "country", "device", "date")
VALID_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
OPERATORS = ("equals", "contains", "notContains", "includingRegex", "excludingRegex")


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


def execute(request, *, site: str | None = None, sleep=time.sleep):
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
            if status == 403:
                target = f"No access to {site}" if site else "Permission denied"
                raise PermissionDenied(
                    f"{target} (403): {_reason(e).rstrip('.')}.",
                    hint="Check the exact property string with `gsc sites` and that "
                    "you are logged in as the right Google account.",
                ) from e
            raise GscError(f"Google API error {status}: {_reason(e)}") from e


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


def inspect_url(service, site: str, url: str) -> list[dict]:
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
    return [{"field": k, "value": v or ""} for k, v in fields.items()]
