import json

import httplib2
import pytest
from googleapiclient.errors import HttpError

from wakako import client
from wakako.errors import AuthError, QuotaError, UsageError


class FakeRequest:
    def __init__(self, *results):
        self.results = list(results)

    def execute(self):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class Fake:
    def __init__(self, **resources):
        self._resources = resources

    def __getattr__(self, name):
        resource = self._resources[name]
        return lambda: resource


def http_error(status, content):
    return HttpError(httplib2.Response({"status": status}), json.dumps(content).encode())


# ---- previous_range -----------------------------------------------------------

def test_previous_range_is_equal_length_period_before():
    assert client.previous_range("2026-09-01", "2026-09-28") == ("2026-08-04", "2026-08-31")
    assert client.previous_range("2026-09-28", "2026-09-28") == ("2026-09-27", "2026-09-27")


# ---- sitemap_urls -------------------------------------------------------------

URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
<url><loc>https://x.com/a</loc><xhtml:link rel="alternate" hreflang="ru" href="https://x.com/ru/a"/></url>
<url><loc> https://x.com/b </loc></url>
<url><loc>https://x.com/a</loc></url>
</urlset>"""

INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://x.com/s1.xml</loc></sitemap>
<sitemap><loc>https://x.com/s2.xml</loc></sitemap>
</sitemapindex>"""


def test_sitemap_urls_reads_locs_dedupes_and_ignores_alternates():
    urls = client.sitemap_urls("https://x.com/s.xml", fetch=lambda u: URLSET)
    assert urls == ["https://x.com/a", "https://x.com/b"]


def test_sitemap_urls_follows_index():
    docs = {
        "https://x.com/index.xml": INDEX,
        "https://x.com/s1.xml": URLSET,
        "https://x.com/s2.xml": URLSET.replace("/a<", "/c<"),
    }
    urls = client.sitemap_urls("https://x.com/index.xml", fetch=docs.__getitem__)
    assert urls == ["https://x.com/a", "https://x.com/b", "https://x.com/c"]


def test_sitemap_urls_invalid_xml():
    with pytest.raises(UsageError, match="not valid XML"):
        client.sitemap_urls("https://x.com/s.xml", fetch=lambda u: "<html>")


def test_sitemap_urls_rejects_runaway_nesting():
    selfref = INDEX.replace("s1.xml", "index.xml").replace("s2.xml", "index.xml")
    with pytest.raises(UsageError, match="nested"):
        client.sitemap_urls("https://x.com/index.xml", fetch=lambda u: selfref)


# ---- inspect_many -------------------------------------------------------------

def inspection(verdict, coverage="Submitted and indexed"):
    return {"inspectionResult": {"indexStatusResult": {
        "verdict": verdict, "coverageState": coverage, "lastCrawlTime": "2026-09-30T00:00:00Z",
        "googleCanonical": "https://x.com/a", "userCanonical": "https://x.com/a",
    }}}


class ScriptedIndex:
    """inspect(body) returns the next scripted result for that URL."""

    def __init__(self, script):
        self.script = script
        self.seen = []

    def inspect(self, body):
        self.seen.append(body["inspectionUrl"])
        return FakeRequest(self.script[body["inspectionUrl"]])


def service_for(index):
    class UI:
        def index(self):
            return index

    return Fake(urlInspection=UI())


def test_inspect_many_summarises_each_url():
    index = ScriptedIndex({"https://x.com/a": inspection("PASS"),
                           "https://x.com/b": inspection("NEUTRAL", "URL is unknown to Google")})
    rows = client.inspect_many(service_for(index), "sc-domain:x.com",
                               ["https://x.com/a", "https://x.com/b"])
    assert [r["url"] for r in rows] == ["https://x.com/a", "https://x.com/b"]
    assert rows[0]["verdict"] == "PASS" and rows[0]["error"] == ""
    assert rows[1]["coverage"] == "URL is unknown to Google"
    assert set(client.SUMMARY_FIELDS) <= set(rows[0])


def test_inspect_many_only_unindexed_filters_passes():
    index = ScriptedIndex({"https://x.com/a": inspection("PASS"),
                           "https://x.com/b": inspection("NEUTRAL", "Crawled - not indexed")})
    rows = client.inspect_many(service_for(index), "s", ["https://x.com/a", "https://x.com/b"],
                               only_unindexed=True)
    assert [r["url"] for r in rows] == ["https://x.com/b"]


def test_inspect_many_records_error_rows_and_continues():
    index = ScriptedIndex({"https://x.com/a": http_error(400, {"error": {"message": "bad url"}}),
                           "https://x.com/b": inspection("PASS")})
    rows = client.inspect_many(service_for(index), "s", ["https://x.com/a", "https://x.com/b"])
    assert "bad url" in rows[0]["error"] and rows[0]["verdict"] == ""
    assert rows[1]["verdict"] == "PASS"


def test_inspect_many_stops_on_quota():
    index = ScriptedIndex({"https://x.com/a": inspection("PASS"),
                           "https://x.com/b": QuotaError("Quota exceeded (429)."),
                           "https://x.com/c": inspection("PASS")})
    rows = client.inspect_many(service_for(index), "s",
                               ["https://x.com/a", "https://x.com/b", "https://x.com/c"])
    assert [r["url"] for r in rows] == ["https://x.com/a", "https://x.com/b"]
    assert "Quota" in rows[1]["error"]
    assert "https://x.com/c" not in index.seen


def test_inspect_many_reports_progress():
    index = ScriptedIndex({"https://x.com/a": inspection("PASS")})
    calls = []
    client.inspect_many(service_for(index), "s", ["https://x.com/a"],
                        progress=lambda i, n: calls.append((i, n)))
    assert calls == [(1, 1)]


# ---- compare_rows -------------------------------------------------------------

class FakeSearchAnalytics:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.bodies = []

    def query(self, siteUrl, body):
        self.bodies.append(body)
        return FakeRequest(self.pages.pop(0))


def sa(keys, clicks, imps, ctr=0.1, pos=3.0):
    return {"keys": keys, "clicks": clicks, "impressions": imps, "ctr": ctr, "position": pos}


def compare(sa_fake, **kw):
    args = dict(dims=["query"], start="2026-09-01", end="2026-09-28", filters=[],
                search_type="web", limit=0)
    args.update(kw)
    return client.compare_rows(Fake(searchanalytics=sa_fake), "s", **args)


def test_compare_rows_merges_periods_and_sorts_by_abs_click_delta():
    fake = FakeSearchAnalytics(
        {"rows": [sa(["a"], 10, 100, 0.10, 3.0), sa(["b"], 2, 50, 0.04, 8.0)]},
        {"rows": [sa(["a"], 4, 80, 0.05, 4.0), sa(["c"], 8, 90, 0.09, 2.0)]},
    )
    rows = compare(fake)
    assert [r["query"] for r in rows] == ["c", "a", "b"]
    c, a, b = rows
    assert (c["clicks"], c["clicks_prev"], c["clicks_delta"], c["clicks_pct"]) == (0, 8, -8, -100.0)
    assert c["position"] is None and c["position_delta"] is None
    assert (a["clicks_delta"], a["clicks_pct"], a["position_delta"]) == (6, 150.0, -1.0)
    assert b["clicks_prev"] == 0 and b["clicks_pct"] is None and b["position_prev"] is None
    assert fake.bodies[0]["startDate"] == "2026-09-01" and fake.bodies[1]["startDate"] == "2026-08-04"
    assert fake.bodies[1]["endDate"] == "2026-08-31"


def test_compare_rows_min_impressions_and_limit():
    fake = FakeSearchAnalytics(
        {"rows": [sa(["a"], 10, 100), sa(["b"], 9, 5)]}, {"rows": []},
    )
    assert [r["query"] for r in compare(fake, min_impressions=50)] == ["a"]
    fake = FakeSearchAnalytics(
        {"rows": [sa(["a"], 10, 100), sa(["b"], 9, 5)]}, {"rows": []},
    )
    assert len(compare(fake, limit=1)) == 1


def test_compare_rows_sort_by_impressions():
    fake = FakeSearchAnalytics(
        {"rows": [sa(["a"], 10, 100), sa(["b"], 1, 900)]},
        {"rows": [sa(["a"], 0, 90), sa(["b"], 1, 100)]},
    )
    assert [r["query"] for r in compare(fake, sort="impressions")] == ["b", "a"]


def test_compare_rows_no_dimensions_gives_single_totals_row():
    fake = FakeSearchAnalytics({"rows": [sa([], 20, 200)]}, {"rows": [sa([], 10, 100)]})
    rows = compare(fake, dims=[])
    assert len(rows) == 1 and rows[0]["clicks_delta"] == 10 and rows[0]["clicks_pct"] == 100.0


def test_compare_rows_rejects_unknown_sort():
    with pytest.raises(UsageError, match="ctr"):
        compare(FakeSearchAnalytics(), sort="bogus")


# ---- sitemaps / indexing ---------------------------------------------------------

class FakeSitemapsWrite:
    def __init__(self):
        self.calls = []

    def submit(self, siteUrl, feedpath):
        self.calls.append(("submit", siteUrl, feedpath))
        return FakeRequest("")

    def delete(self, siteUrl, feedpath):
        self.calls.append(("delete", siteUrl, feedpath))
        return FakeRequest("")


def test_submit_and_delete_sitemap():
    res = FakeSitemapsWrite()
    service = Fake(sitemaps=res)
    assert client.submit_sitemap(service, "sc-domain:x.com", "https://x.com/s.xml") == [
        {"action": "submitted", "site": "sc-domain:x.com", "sitemap": "https://x.com/s.xml"}]
    assert client.delete_sitemap(service, "sc-domain:x.com", "https://x.com/s.xml")[0]["action"] == "deleted"
    assert res.calls == [("submit", "sc-domain:x.com", "https://x.com/s.xml"),
                         ("delete", "sc-domain:x.com", "https://x.com/s.xml")]


class FakeNotifications:
    def __init__(self, script):
        self.script = script
        self.bodies = []

    def publish(self, body):
        self.bodies.append(body)
        return FakeRequest(self.script[body["url"]])


def test_request_indexing_reports_each_url_and_continues_after_errors():
    ok = {"urlNotificationMetadata": {"latestUpdate": {"notifyTime": "2026-10-01T10:00:00Z"}}}
    notes = FakeNotifications({"https://x.com/a": ok,
                               "https://x.com/b": http_error(400, {"error": {"message": "bad"}}),
                               "https://x.com/c": ok})
    rows = client.request_indexing(Fake(urlNotifications=notes),
                                   ["https://x.com/a", "https://x.com/b", "https://x.com/c"])
    assert [r["status"] for r in rows] == ["requested", "error", "requested"]
    assert rows[0]["detail"] == "2026-10-01T10:00:00Z" and "bad" in rows[1]["detail"]
    assert notes.bodies[0] == {"url": "https://x.com/a", "type": "URL_UPDATED"}


def test_request_indexing_stops_on_quota():
    notes = FakeNotifications({"https://x.com/a": QuotaError("Quota exceeded (429)."),
                               "https://x.com/b": {}})
    rows = client.request_indexing(Fake(urlNotifications=notes), ["https://x.com/a", "https://x.com/b"])
    assert len(rows) == 1 and rows[0]["status"] == "error"
    assert len(notes.bodies) == 1


def test_missing_write_scope_points_to_login_write():
    err = http_error(403, {"error": {"message": "Request had insufficient authentication scopes.",
                                     "errors": [{"reason": "insufficientPermissions"}],
                                     "status": "PERMISSION_DENIED",
                                     "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}})
    with pytest.raises(AuthError) as exc:
        client.execute(FakeRequest(err))
    assert exc.value.exit_code == 3 and "wakako login --write" in exc.value.hint
    with pytest.raises(AuthError) as ga_exc:
        client.execute(FakeRequest(err), login_flag="--ga")
    assert "wakako login --ga" in ga_exc.value.hint


def test_api_not_enabled_gets_an_enable_it_hint_not_a_property_hint():
    from wakako.errors import PermissionDenied

    err = http_error(403, {"error": {
        "message": "Google Analytics Admin API has not been used in project 1 before or it is disabled. "
                   "Enable it by visiting https://console.developers.google.com/apis/api/x",
        "details": [{"reason": "SERVICE_DISABLED"}]}})
    with pytest.raises(PermissionDenied) as exc:
        client.execute(FakeRequest(err), site="properties/1", permission_hint="Check the property ID")
    assert "Enable it by visiting" in str(exc.value)
    assert "Enable that API" in exc.value.hint and "property ID" not in exc.value.hint


def test_plain_403_is_still_permission_denied():
    from wakako.errors import PermissionDenied

    with pytest.raises(PermissionDenied):
        client.execute(FakeRequest(http_error(403, {"error": {"message": "no access"}})), site="s")
