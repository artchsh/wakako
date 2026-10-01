import json

import httplib2
import pytest
from googleapiclient.errors import HttpError

from gsc_cli import client
from gsc_cli.errors import GscError, PermissionDenied, QuotaError, UsageError


def http_error(status, message="boom"):
    content = json.dumps({"error": {"message": message}}).encode()
    return HttpError(httplib2.Response({"status": status}), content)


class FakeRequest:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def execute(self):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


# ---- execute() error mapping -------------------------------------------------

def test_execute_returns_payload():
    assert client.execute(FakeRequest({"ok": 1})) == {"ok": 1}


def test_execute_403_names_the_site():
    with pytest.raises(GscError, match="No access to sc-domain:x.com"):
        client.execute(FakeRequest(http_error(403)), site="sc-domain:x.com")


def test_execute_retries_429_then_succeeds():
    sleeps = []
    req = FakeRequest(http_error(429), {"ok": 1})
    assert client.execute(req, sleep=sleeps.append) == {"ok": 1}
    assert sleeps == [1]


def test_execute_gives_up_after_three_429s():
    sleeps = []
    req = FakeRequest(http_error(429), http_error(429), http_error(429))
    with pytest.raises(GscError, match="Quota"):
        client.execute(req, sleep=sleeps.append)
    assert req.calls == 3
    assert sleeps == [1, 2]


def test_execute_other_errors_include_status_and_reason():
    with pytest.raises(GscError, match=r"500.*kaput"):
        client.execute(FakeRequest(http_error(500, "kaput")))


# ---- fakes for service resources --------------------------------------------

class Fake:
    """Attribute-chain fake: fake.searchanalytics().query(...) -> FakeRequest."""

    def __init__(self, **resources):
        self._resources = resources

    def __getattr__(self, name):
        resource = self._resources[name]
        return lambda: resource


class FakeSearchAnalytics:
    def __init__(self, pages):
        self.pages = list(pages)
        self.bodies = []

    def query(self, siteUrl, body):
        self.bodies.append(body)
        return FakeRequest(self.pages.pop(0))


def sa_row(keys, clicks=1):
    return {"keys": keys, "clicks": clicks, "impressions": 10, "ctr": 0.1, "position": 2.0}


# ---- query_rows --------------------------------------------------------------

def test_query_rows_flattens_keys_by_dimension():
    sa = FakeSearchAnalytics([{"rows": [sa_row(["shoes", "/a"])]}])
    rows = client.query_rows(
        Fake(searchanalytics=sa), "sc-domain:x.com", ["query", "page"],
        "2026-09-01", "2026-09-28", [], "web", 1000,
    )
    assert rows == [
        {"query": "shoes", "page": "/a", "clicks": 1, "impressions": 10,
         "ctr": 0.1, "position": 2.0}
    ]
    assert sa.bodies[0]["rowLimit"] == 1000 and sa.bodies[0]["startRow"] == 0


def test_query_rows_no_rows_returns_empty():
    sa = FakeSearchAnalytics([{}])
    assert client.query_rows(
        Fake(searchanalytics=sa), "s", ["query"], "2026-09-01", "2026-09-28", [], "web", 10
    ) == []


def test_query_rows_paginates_until_short_page(monkeypatch):
    monkeypatch.setattr(client, "ROW_LIMIT", 2)
    sa = FakeSearchAnalytics([
        {"rows": [sa_row(["a"]), sa_row(["b"])]},
        {"rows": [sa_row(["c"])]},
    ])
    rows = client.query_rows(
        Fake(searchanalytics=sa), "s", ["query"], "2026-09-01", "2026-09-28", [], "web", 0
    )
    assert [r["query"] for r in rows] == ["a", "b", "c"]
    assert [b["startRow"] for b in sa.bodies] == [0, 2]


def test_query_rows_limit_truncates_and_sizes_last_page(monkeypatch):
    monkeypatch.setattr(client, "ROW_LIMIT", 2)
    sa = FakeSearchAnalytics([
        {"rows": [sa_row(["a"]), sa_row(["b"])]},
        {"rows": [sa_row(["c"])]},
    ])
    rows = client.query_rows(
        Fake(searchanalytics=sa), "s", ["query"], "2026-09-01", "2026-09-28", [], "web", 3
    )
    assert len(rows) == 3
    assert [b["rowLimit"] for b in sa.bodies] == [2, 1]


# ---- sites / sitemaps / inspect ---------------------------------------------

class FakeSites:
    def list(self):
        return FakeRequest({"siteEntry": [
            {"siteUrl": "sc-domain:x.com", "permissionLevel": "siteOwner"}
        ]})


def test_list_sites():
    assert client.list_sites(Fake(sites=FakeSites())) == [
        {"site": "sc-domain:x.com", "permission": "siteOwner"}
    ]


class FakeSitemaps:
    def list(self, siteUrl):
        return FakeRequest({"sitemap": [{
            "path": "https://x.com/sitemap.xml", "type": "sitemap",
            "lastDownloaded": "2026-09-30T10:00:00Z", "isPending": False,
            "errors": "0", "warnings": "2",
        }]})


def test_list_sitemaps():
    rows = client.list_sitemaps(Fake(sitemaps=FakeSitemaps()), "sc-domain:x.com")
    assert rows == [{
        "path": "https://x.com/sitemap.xml", "type": "sitemap",
        "last_downloaded": "2026-09-30T10:00:00Z", "pending": False,
        "errors": "0", "warnings": "2",
    }]


class FakeIndex:
    def __init__(self):
        self.body = None

    def inspect(self, body):
        self.body = body
        return FakeRequest({"inspectionResult": {
            "indexStatusResult": {
                "verdict": "PASS", "coverageState": "Submitted and indexed",
                "indexingState": "INDEXING_ALLOWED", "robotsTxtState": "ALLOWED",
                "pageFetchState": "SUCCESSFUL", "lastCrawlTime": "2026-09-29T01:00:00Z",
                "crawledAs": "MOBILE", "googleCanonical": "https://x.com/a",
                "userCanonical": "https://x.com/a",
            },
            "mobileUsabilityResult": {"verdict": "PASS"},
            "richResultsResult": {"verdict": "NEUTRAL"},
        }})


class FakeUrlInspection:
    def __init__(self, index):
        self._index = index

    def index(self):
        return self._index


def test_inspect_url_flattens_result_and_sends_body():
    index = FakeIndex()
    service = Fake(urlInspection=FakeUrlInspection(index))
    rows = client.inspect_url(service, "sc-domain:x.com", "https://x.com/a")
    assert index.body == {"inspectionUrl": "https://x.com/a", "siteUrl": "sc-domain:x.com"}
    as_dict = {r["field"]: r["value"] for r in rows}
    assert as_dict["verdict"] == "PASS"
    assert as_dict["coverage"] == "Submitted and indexed"
    assert as_dict["google_canonical"] == "https://x.com/a"
    assert as_dict["mobile_usability"] == "PASS"
    assert as_dict["rich_results"] == "NEUTRAL"


def test_inspect_url_tolerates_missing_sections():
    class Empty:
        def inspect(self, body):
            return FakeRequest({"inspectionResult": {}})

    rows = client.inspect_url(
        Fake(urlInspection=FakeUrlInspection(Empty())), "s", "https://x.com/a"
    )
    assert {r["field"]: r["value"] for r in rows}["verdict"] == ""


def test_error_types_and_exit_codes():
    with pytest.raises(PermissionDenied) as denied:
        client.execute(FakeRequest(http_error(403)), site="s")
    assert denied.value.exit_code == 4 and denied.value.hint

    with pytest.raises(QuotaError) as quota:
        client.execute(
            FakeRequest(http_error(429), http_error(429), http_error(429)), sleep=lambda s: None
        )
    assert quota.value.exit_code == 5

    with pytest.raises(UsageError) as usage:
        client.parse_filter("bogus")
    assert usage.value.exit_code == 2 and usage.value.code == "usage"
