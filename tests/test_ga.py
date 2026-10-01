import json
from datetime import date

import httplib2
import pytest
from googleapiclient.errors import HttpError

from gsc_cli import ga
from gsc_cli.errors import AuthError, PermissionDenied, UsageError


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Fake:
    def __init__(self, **resources):
        self._resources = resources

    def __getattr__(self, name):
        resource = self._resources[name]
        return lambda: resource


def http_error(status, content):
    return HttpError(httplib2.Response({"status": status}), json.dumps(content).encode())


# ---- parsing ------------------------------------------------------------------

@pytest.mark.parametrize("value", ["123456789", "properties/123456789", " 123456789 "])
def test_normalize_property(value):
    assert ga.normalize_property(value) == "properties/123456789"


@pytest.mark.parametrize("bad", ["", "abc", "properties/x", "G-ABC123"])
def test_normalize_property_rejects_non_numeric(bad):
    with pytest.raises(UsageError, match="gsc ga properties"):
        ga.normalize_property(bad)


def test_parse_names():
    assert ga.parse_names("sessions, activeUsers,customEvent:plan", "metric") == [
        "sessions", "activeUsers", "customEvent:plan"]
    assert ga.parse_names("", "dimension") == []
    with pytest.raises(UsageError, match="metric"):
        ga.parse_names("sessions;drop", "metric")


def test_parse_filter():
    assert ga.parse_filter("pagePath contains /blog/my post") == {
        "dimension": "pagePath", "operator": "contains", "expression": "/blog/my post"}
    assert ga.parse_filter("country NOTEQUALS Kazakhstan")["operator"] == "notEquals"


@pytest.mark.parametrize("bad", ["", "pagePath contains", "pagePath like x", "9bad equals x"])
def test_parse_filter_rejects_invalid(bad):
    with pytest.raises(UsageError, match="filter"):
        ga.parse_filter(bad)


def test_date_range_defaults_to_last_n_days_ending_yesterday():
    assert ga.date_range(28, None, None, today=date(2026, 10, 1)) == ("2026-09-03", "2026-09-30")
    assert ga.date_range(1, None, None, today=date(2026, 10, 1)) == ("2026-09-30", "2026-09-30")
    assert ga.date_range(7, "2026-09-01", "2026-09-07") == ("2026-09-01", "2026-09-07")
    with pytest.raises(UsageError):
        ga.date_range(0, None, None)
    with pytest.raises(UsageError, match="both"):
        ga.date_range(7, "2026-09-01", None)


# ---- request building ---------------------------------------------------------------

def test_filters_single_and_group_and_negation():
    one = ga.dimension_filter([{"dimension": "country", "operator": "equals", "expression": "Kazakhstan"}])
    assert one == {"filter": {"fieldName": "country",
                              "stringFilter": {"matchType": "EXACT", "value": "Kazakhstan"}}}
    both = ga.dimension_filter([
        {"dimension": "country", "operator": "notEquals", "expression": "Kazakhstan"},
        {"dimension": "pagePath", "operator": "beginsWith", "expression": "/blog"},
    ])
    assert both["andGroup"]["expressions"][0] == {"notExpression": {"filter": {
        "fieldName": "country", "stringFilter": {"matchType": "EXACT", "value": "Kazakhstan"}}}}
    assert both["andGroup"]["expressions"][1]["filter"]["stringFilter"]["matchType"] == "BEGINS_WITH"
    assert ga.dimension_filter([]) is None


def test_build_order_by():
    assert ga.build_order_by(None, ["date"], ["sessions", "users"]) == {
        "metric": {"metricName": "sessions"}, "desc": True}
    assert ga.build_order_by("users:asc", ["date"], ["sessions", "users"]) == {
        "metric": {"metricName": "users"}, "desc": False}
    assert ga.build_order_by("date", ["date"], ["sessions"]) == {
        "dimension": {"dimensionName": "date"}, "desc": True}
    with pytest.raises(UsageError, match="requested"):
        ga.build_order_by("bounces", ["date"], ["sessions"])
    with pytest.raises(UsageError, match="asc or desc"):
        ga.build_order_by("sessions:up", [], ["sessions"])


def test_build_report_body():
    body = ga.build_report_body(["pagePath"], ["sessions"], "2026-09-01", "2026-09-28",
                                [ga.ORGANIC_FILTER], {"metric": {"metricName": "sessions"}, "desc": True}, 0, 10)
    assert body["dateRanges"] == [{"startDate": "2026-09-01", "endDate": "2026-09-28"}]
    assert body["dimensions"] == [{"name": "pagePath"}] and body["metrics"] == [{"name": "sessions"}]
    assert body["limit"] == "10" and body["offset"] == "0"
    assert body["dimensionFilter"]["filter"]["fieldName"] == "sessionDefaultChannelGroup"
    assert body["orderBys"][0]["desc"] is True


# ---- run_report ---------------------------------------------------------------------------

class FakeProperties:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []

    def runReport(self, property, body):
        self.calls.append((property, body))
        return FakeRequest(self.pages.pop(0))


def report_page(rows, total=None, types=("TYPE_INTEGER", "TYPE_FLOAT")):
    return {
        "metricHeaders": [{"name": "sessions", "type": types[0]}, {"name": "engagementRate", "type": types[1]}],
        "rows": [{"dimensionValues": [{"value": d}], "metricValues": [{"value": a}, {"value": b}]}
                 for d, a, b in rows],
        "rowCount": total if total is not None else len(rows),
    }


def test_run_report_converts_types_and_builds_request():
    props = FakeProperties(report_page([("/a", "10", "0.5"), ("/b", "3", "1")]))
    rows = ga.run_report(Fake(properties=props), "123", ["pagePath"], ["sessions", "engagementRate"],
                         "2026-09-01", "2026-09-28", [ga.ORGANIC_FILTER])
    assert rows == [{"pagePath": "/a", "sessions": 10, "engagementRate": 0.5},
                    {"pagePath": "/b", "sessions": 3, "engagementRate": 1.0}]
    assert isinstance(rows[1]["engagementRate"], float)
    prop, body = props.calls[0]
    assert prop == "properties/123" and body["limit"] == "1000"


def test_run_report_paginates_and_limits(monkeypatch):
    monkeypatch.setattr(ga, "PAGE_SIZE", 2)
    props = FakeProperties(
        report_page([("/a", "1", "0"), ("/b", "1", "0")], total=3),
        report_page([("/c", "1", "0")], total=3),
    )
    rows = ga.run_report(Fake(properties=props), "123", ["pagePath"], ["sessions", "engagementRate"],
                         "2026-09-01", "2026-09-28", limit=0)
    assert [r["pagePath"] for r in rows] == ["/a", "/b", "/c"]
    assert [c[1]["offset"] for c in props.calls] == ["0", "2"]

    props = FakeProperties(report_page([("/a", "1", "0"), ("/b", "1", "0")], total=5),
                           report_page([("/c", "1", "0")], total=5))
    rows = ga.run_report(Fake(properties=props), "123", ["pagePath"], ["sessions", "engagementRate"],
                         "2026-09-01", "2026-09-28", limit=3)
    assert len(rows) == 3 and [c[1]["limit"] for c in props.calls] == ["2", "1"]


def test_run_report_needs_metrics():
    with pytest.raises(UsageError, match="metric"):
        ga.run_report(Fake(properties=FakeProperties()), "123", [], [], "2026-09-01", "2026-09-28")


def test_run_report_totals_without_dimensions():
    props = FakeProperties({"metricHeaders": [{"name": "sessions", "type": "TYPE_INTEGER"}],
                            "rows": [{"metricValues": [{"value": "42"}]}], "rowCount": 1})
    assert ga.run_report(Fake(properties=props), "123", [], ["sessions"], "2026-09-01", "2026-09-28") == [
        {"sessions": 42}]


def test_run_report_permission_error_has_ga_hint():
    props = FakeProperties(http_error(403, {"error": {"message": "User does not have access"}}))
    with pytest.raises(PermissionDenied) as exc:
        ga.run_report(Fake(properties=props), "123", [], ["sessions"], "2026-09-01", "2026-09-28")
    assert "properties/123" in str(exc.value) and "gsc ga properties" in exc.value.hint


def test_run_report_missing_scope_points_to_login_ga():
    err = http_error(403, {"error": {"message": "insufficient authentication scopes",
                                     "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}})
    with pytest.raises(AuthError) as exc:
        ga.run_report(Fake(properties=FakeProperties(err)), "123", [], ["sessions"], "2026-09-01", "2026-09-28")
    assert "gsc login --ga" in exc.value.hint


# ---- list_properties ----------------------------------------------------------------------------

class FakeAccountSummaries:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.kwargs = []

    def list(self, **kwargs):
        self.kwargs.append(kwargs)
        return FakeRequest(self.pages.pop(0))


class FakeDataStreams:
    def __init__(self, by_parent):
        self.by_parent = by_parent

    def list(self, parent):
        return FakeRequest(self.by_parent[parent])


class FakeAdminProperties:
    def __init__(self, streams):
        self._streams = streams

    def dataStreams(self):
        return self._streams


def test_list_properties_follows_pages_and_adds_websites():
    summaries = FakeAccountSummaries(
        {"accountSummaries": [{"displayName": "Beta", "propertySummaries": [
            {"property": "properties/222", "displayName": "Zed site"}]}], "nextPageToken": "t2"},
        {"accountSummaries": [{"displayName": "Acme", "propertySummaries": [
            {"property": "properties/111", "displayName": "Main site"}]}]},
    )
    streams = FakeDataStreams({
        "properties/111": {"dataStreams": [
            {"type": "WEB_DATA_STREAM", "webStreamData": {"defaultUri": "https://acme.com"}},
            {"type": "ANDROID_APP_DATA_STREAM"}]},
        "properties/222": {"dataStreams": []},
    })
    admin = Fake(accountSummaries=summaries, properties=FakeAdminProperties(streams))
    rows = ga.list_properties(admin)
    assert rows == [
        {"property": "111", "name": "Main site", "account": "Acme", "websites": "https://acme.com"},
        {"property": "222", "name": "Zed site", "account": "Beta", "websites": ""},
    ]
    assert summaries.kwargs == [{"pageSize": 200}, {"pageSize": 200, "pageToken": "t2"}]


def test_list_properties_tolerates_stream_errors_and_can_skip_them():
    summaries = FakeAccountSummaries({"accountSummaries": [{"displayName": "A", "propertySummaries": [
        {"property": "properties/1", "displayName": "P"}]}]})

    class Boom:
        def list(self, parent):
            return FakeRequest(http_error(403, {"error": {"message": "no"}}))

    admin = Fake(accountSummaries=summaries, properties=FakeAdminProperties(Boom()))
    assert ga.list_properties(admin)[0]["websites"] == ""
    summaries2 = FakeAccountSummaries({"accountSummaries": [{"displayName": "A", "propertySummaries": [
        {"property": "properties/1", "displayName": "P"}]}]})
    assert ga.list_properties(Fake(accountSummaries=summaries2), include_streams=False)[0]["property"] == "1"


# ---- landing_pages --------------------------------------------------------------------------------

def test_site_ga_filters():
    domain = ga.site_ga_filters("sc-domain:example.com")
    assert domain[0] == ga.ORGANIC_FILTER
    assert domain[1] == {"dimension": "hostName", "operator": "endsWith", "expression": "example.com"}
    prefix = ga.site_ga_filters("https://example.com/blog/")
    assert prefix[1] == {"dimension": "hostName", "operator": "equals", "expression": "example.com"}
    assert prefix[2] == {"dimension": "landingPage", "operator": "beginsWith", "expression": "/blog/"}
    assert len(ga.site_ga_filters("https://example.com/")) == 2


class FakeSearchAnalytics:
    def __init__(self, rows):
        self.rows = rows
        self.bodies = []

    def query(self, siteUrl, body):
        self.bodies.append(body)
        return FakeRequest({"rows": self.rows})


def gsc_row(url, clicks, imps, ctr=0.1, pos=3.0):
    return {"keys": [url], "clicks": clicks, "impressions": imps, "ctr": ctr, "position": pos}


def ga_page(rows):
    return {
        "metricHeaders": [{"name": n, "type": t} for n, t in (
            ("sessions", "TYPE_INTEGER"), ("engagementRate", "TYPE_FLOAT"),
            ("averageSessionDuration", "TYPE_SECONDS"), ("keyEvents", "TYPE_INTEGER"))],
        "rows": [{"dimensionValues": [{"value": h}, {"value": p}],
                  "metricValues": [{"value": str(v)} for v in m]} for h, p, m in rows],
        "rowCount": len(rows),
    }


def landing(gsc_rows, ga_rows, **kw):
    gsc = Fake(searchanalytics=FakeSearchAnalytics(gsc_rows))
    props = FakeProperties(ga_page(ga_rows))
    rows = ga.landing_pages(gsc, Fake(properties=props), "sc-domain:x.com", "123",
                            "2026-09-01", "2026-09-28", **kw)
    return rows, props


def test_landing_pages_merges_gsc_and_ga_by_host_and_path():
    rows, props = landing(
        [gsc_row("https://x.com/a", 100, 2000, 0.05, 2.34), gsc_row("https://x.com/b/", 10, 500),
         gsc_row("https://meks.x.com/", 50, 900)],
        [("x.com", "/a", (80, 0.7, 65.43, 4)), ("x.com", "/b", (12, 0.5, 30, 0)),
         ("meks.x.com", "/", (40, 0.9, 120, 2))],
    )
    by_page = {r["page"]: r for r in rows}
    a = by_page["https://x.com/a"]
    assert (a["clicks"], a["sessions"], a["sessions_per_click"]) == (100, 80, 0.8)
    assert (a["engagement_rate"], a["avg_session_duration"], a["key_events"]) == (0.7, 65.4, 4)
    assert (a["ctr"], a["position"]) == (0.05, 2.3)
    assert by_page["https://x.com/b/"]["sessions"] == 12  # trailing slash difference still matches
    assert by_page["https://meks.x.com/"]["sessions"] == 40  # subdomain root not merged into x.com/
    assert "https://x.com/" not in by_page
    assert [r["page"] for r in rows][0] == "https://x.com/a"  # most clicks first
    body = props.calls[0][1]
    assert [d["name"] for d in body["dimensions"]] == ["hostName", "landingPage"]
    assert [m["name"] for m in body["metrics"]] == list(ga.LANDING_METRICS)
    assert "andGroup" in body["dimensionFilter"]


def test_landing_pages_keeps_one_sided_pages():
    rows, _ = landing(
        [gsc_row("https://x.com/only-gsc", 7, 300)],
        [("x.com", "/only-ga", (9, 0.6, 20, 1))],
    )
    by_page = {r["page"]: r for r in rows}
    gsc_only = by_page["https://x.com/only-gsc"]
    assert gsc_only["sessions"] == 0 and gsc_only["engagement_rate"] is None
    assert gsc_only["sessions_per_click"] is None
    ga_only = by_page["https://x.com/only-ga"]
    assert ga_only["clicks"] is None and ga_only["sessions"] == 9 and ga_only["position"] is None


def test_landing_pages_non_path_landing_values_stay_readable():
    rows, _ = landing([], [("x.com", "(not set)", (2, 0.0, 0, 0))])
    assert rows[0]["page"] == "x.com (not set)"


def test_landing_pages_decodes_percent_encoding_and_respects_limit():
    rows, _ = landing(
        [gsc_row("https://x.com/%D1%82%D0%B5%D1%81%D1%82", 5, 50), gsc_row("https://x.com/z", 1, 10)],
        [("x.com", "/тест", (4, 0.5, 10, 0))],
        limit=1,
    )
    assert len(rows) == 1 and rows[0]["sessions"] == 4
