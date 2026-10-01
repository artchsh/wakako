"""Google Analytics 4 (optional): properties, reports, and GSC+GA landing-page analysis.

Everything here needs `gsc login --ga`; GSC-only users never import a GA API.
"""

import re
from datetime import date, timedelta
from urllib.parse import unquote, urlsplit

from gsc_cli import client
from gsc_cli.client import execute
from gsc_cli.errors import GscError, UsageError

PAGE_SIZE = 100000
GA_PERMISSION_HINT = (
    "Check the property ID with `gsc ga properties` and that your Google account has at "
    "least Viewer access to that GA4 property."
)
OPERATORS = ("equals", "notEquals", "contains", "notContains", "beginsWith", "endsWith", "regex", "notRegex")
_MATCH = {
    "equals": ("EXACT", False), "notequals": ("EXACT", True),
    "contains": ("CONTAINS", False), "notcontains": ("CONTAINS", True),
    "beginswith": ("BEGINS_WITH", False), "endswith": ("ENDS_WITH", False),
    "regex": ("PARTIAL_REGEXP", False), "notregex": ("PARTIAL_REGEXP", True),
}
ORGANIC_FILTER = {
    "dimension": "sessionDefaultChannelGroup", "operator": "equals", "expression": "Organic Search",
}
LANDING_METRICS = ("sessions", "engagementRate", "averageSessionDuration", "keyEvents")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_:]*$")


# ---- argument parsing -------------------------------------------------------

def normalize_property(value: str) -> str:
    raw = value.strip()
    number = raw[len("properties/"):] if raw.startswith("properties/") else raw
    if not number.isdigit():
        raise UsageError(
            f"Invalid GA4 property '{value}'. Use the numeric ID from `gsc ga properties` "
            "(e.g. 123456789)."
        )
    return f"properties/{number}"


def parse_names(text: str, what: str) -> list[str]:
    names = [n.strip() for n in text.split(",") if n.strip()]
    for name in names:
        if not _NAME.match(name):
            raise UsageError(f"Invalid GA4 {what} name '{name}'.")
    return names


def parse_filter(text: str) -> dict:
    parts = text.strip().split(None, 2)
    usage = (
        'Invalid filter. Use "<dimension> <operator> <value>", e.g. "pagePath contains /blog". '
        f"Operators: {', '.join(OPERATORS)}."
    )
    if len(parts) != 3:
        raise UsageError(usage)
    dimension, operator, expression = parts
    if not _NAME.match(dimension):
        raise UsageError(f"{usage} Bad dimension '{dimension}'.")
    if operator.lower() not in _MATCH:
        raise UsageError(f"{usage} Unknown operator '{operator}'.")
    canonical = next(o for o in OPERATORS if o.lower() == operator.lower())
    return {"dimension": dimension, "operator": canonical, "expression": expression}


def date_range(days: int, start: str | None, end: str | None, today: date | None = None):
    """Explicit range, or the last N days ending yesterday (GA data is near real time)."""
    if start or end:
        return client.date_range(days, start, end)
    if days < 1:
        raise UsageError("--days must be at least 1.")
    end_d = (today or date.today()) - timedelta(days=1)
    return (end_d - timedelta(days=days - 1)).isoformat(), end_d.isoformat()


# ---- request building ---------------------------------------------------------

def _filter_node(f: dict) -> dict:
    match, negate = _MATCH[f["operator"].lower()]
    node = {"filter": {"fieldName": f["dimension"],
                       "stringFilter": {"matchType": match, "value": f["expression"]}}}
    return {"notExpression": node} if negate else node


def dimension_filter(filters: list[dict]) -> dict | None:
    nodes = [_filter_node(f) for f in filters]
    if not nodes:
        return None
    return nodes[0] if len(nodes) == 1 else {"andGroup": {"expressions": nodes}}


def build_order_by(sort: str | None, dims: list[str], metrics: list[str]) -> dict | None:
    """`sort` is `name` or `name:asc|desc`; default is the first metric, descending."""
    if not sort:
        return {"metric": {"metricName": metrics[0]}, "desc": True} if metrics else None
    name, _, direction = sort.partition(":")
    if direction not in ("", "asc", "desc"):
        raise UsageError(f"Sort direction must be asc or desc, got '{direction}'.")
    desc = direction != "asc"
    if name in metrics:
        return {"metric": {"metricName": name}, "desc": desc}
    if name in dims:
        return {"dimension": {"dimensionName": name}, "desc": desc}
    raise UsageError(f"--sort '{name}' must be one of the requested metrics or dimensions.")


def build_report_body(dims, metrics, start, end, filters, order_by, offset, limit) -> dict:
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": d} for d in dims],
        "metrics": [{"name": m} for m in metrics],
        "limit": str(limit),
        "offset": str(offset),
        "keepEmptyRows": False,
    }
    node = dimension_filter(filters)
    if node:
        body["dimensionFilter"] = node
    if order_by:
        body["orderBys"] = [order_by]
    return body


# ---- API calls ------------------------------------------------------------------

def _number(value, metric_type=None):
    try:
        if metric_type == "TYPE_INTEGER":
            return int(float(value))
        number = float(value)
    except (TypeError, ValueError):
        return value
    if metric_type is None and number.is_integer() and "." not in str(value):
        return int(number)
    return round(number, 4)


def run_report(service, property_id, dims, metrics, start, end, filters=(), sort=None, limit=1000):
    """Rows as dicts: one key per dimension (str) and metric (number). limit 0 = all."""
    if not metrics:
        raise UsageError("Give at least one metric, e.g. --metrics sessions,activeUsers.")
    prop = normalize_property(property_id)
    order_by = build_order_by(sort, dims, metrics)
    rows: list[dict] = []
    offset = 0
    while True:
        size = PAGE_SIZE if limit <= 0 else min(PAGE_SIZE, limit - len(rows))
        body = build_report_body(dims, metrics, start, end, list(filters), order_by, offset, size)
        response = execute(
            service.properties().runReport(property=prop, body=body),
            site=prop, login_flag="--ga", permission_hint=GA_PERMISSION_HINT,
        )
        batch = response.get("rows", [])
        types = [h.get("type") for h in response.get("metricHeaders", [])] or [None] * len(metrics)
        for raw in batch:
            row = {d: v.get("value", "") for d, v in zip(dims, raw.get("dimensionValues", []))}
            for name, mtype, v in zip(metrics, types, raw.get("metricValues", [])):
                row[name] = _number(v.get("value"), mtype)
            rows.append(row)
        offset += len(batch)
        total = int(response.get("rowCount", offset))
        if len(batch) < size or offset >= total or (limit > 0 and len(rows) >= limit):
            return rows


def list_properties(admin_service, include_streams: bool = True) -> list[dict]:
    """GA4 properties the user can see: property (numeric id), name, account, websites."""
    rows: list[dict] = []
    token = None
    while True:
        kwargs = {"pageSize": 200}
        if token:
            kwargs["pageToken"] = token
        response = execute(
            admin_service.accountSummaries().list(**kwargs),
            login_flag="--ga", permission_hint=GA_PERMISSION_HINT,
        )
        for account in response.get("accountSummaries", []):
            for prop in account.get("propertySummaries", []):
                rows.append({
                    "property": prop["property"].split("/")[-1],
                    "name": prop.get("displayName", ""),
                    "account": account.get("displayName", ""),
                    "websites": "",
                })
        token = response.get("nextPageToken")
        if not token:
            break
    if include_streams:
        for row in rows:
            try:
                streams = execute(
                    admin_service.properties().dataStreams().list(parent=f"properties/{row['property']}"),
                    login_flag="--ga",
                ).get("dataStreams", [])
            except GscError:
                continue
            uris = {s.get("webStreamData", {}).get("defaultUri", "") for s in streams
                    if s.get("type") == "WEB_DATA_STREAM"}
            row["websites"] = " ".join(sorted(u for u in uris if u))
    return sorted(rows, key=lambda r: (r["account"].lower(), r["name"].lower()))


# ---- GSC + GA combined analysis ---------------------------------------------------

def site_ga_filters(site: str) -> list[dict]:
    """GA filters that scope organic sessions to the same pages the GSC property covers."""
    filters = [ORGANIC_FILTER]
    if site.startswith("sc-domain:"):
        host = site[len("sc-domain:"):]
        filters.append({"dimension": "hostName", "operator": "endsWith", "expression": host})
    else:
        parts = urlsplit(site)
        filters.append({"dimension": "hostName", "operator": "equals", "expression": parts.netloc})
        if parts.path not in ("", "/"):
            filters.append({"dimension": "landingPage", "operator": "beginsWith", "expression": parts.path})
    return filters


def _page_key(host: str, path_and_query: str) -> tuple[str, str]:
    path, _, query = unquote(path_and_query).partition("?")
    path = path.rstrip("/") or "/"
    return host.lower(), (path + ("?" + query if query else "")).lower()


def landing_pages(
    gsc_service, ga_service, site, property_id, start, end, limit=100
) -> list[dict]:
    """Per page: GSC clicks/impressions/ctr/position next to GA organic sessions, engagement
    and key events. Pages seen by only one side are kept (the other side's fields are None)."""
    gsc_rows = client.query_rows(gsc_service, site, ["page"], start, end, [], "web", 0)
    ga_rows = run_report(
        ga_service, property_id, ["hostName", "landingPage"], list(LANDING_METRICS),
        start, end, site_ga_filters(site), sort="sessions", limit=0,
    )

    merged: dict[tuple[str, str], dict] = {}
    for r in gsc_rows:
        parts = urlsplit(r["page"])
        key = _page_key(parts.netloc, parts.path + ("?" + parts.query if parts.query else ""))
        merged[key] = {"page": r["page"], "clicks": r["clicks"], "impressions": r["impressions"],
                       "ctr": r["ctr"], "position": r["position"], "ga": None}
    for r in ga_rows:
        key = _page_key(r["hostName"], r["landingPage"])
        landing = r["landingPage"]
        page = f"https://{r['hostName']}{landing}" if landing.startswith("/") else f"{r['hostName']} {landing}"
        entry = merged.setdefault(key, {
            "page": page,
            "clicks": None, "impressions": None, "ctr": None, "position": None, "ga": None,
        })
        entry["ga"] = r

    rows = []
    for e in merged.values():
        ga = e["ga"]
        sessions = ga["sessions"] if ga else 0
        clicks = e["clicks"]
        rows.append({
            "page": e["page"],
            "clicks": clicks,
            "impressions": e["impressions"],
            "ctr": round(e["ctr"], 4) if e["ctr"] is not None else None,
            "position": round(e["position"], 1) if e["position"] is not None else None,
            "sessions": sessions,
            "sessions_per_click": round(sessions / clicks, 2) if clicks and ga else None,
            "engagement_rate": ga["engagementRate"] if ga else None,
            "avg_session_duration": round(ga["averageSessionDuration"], 1) if ga else None,
            "key_events": ga["keyEvents"] if ga else None,
        })
    rows.sort(key=lambda r: (-(r["clicks"] or 0), -(r["sessions"] or 0)))
    return rows[:limit] if limit > 0 else rows
