import json

from typer.testing import CliRunner

from gsc_cli import auth, client
from gsc_cli.cli import app
from gsc_cli.errors import AuthError

runner = CliRunner()
SITE = "sc-domain:x.com"


def no_api(*a, **k):
    raise AssertionError("API/auth should not be reached")


# ---- inspect --sitemap -----------------------------------------------------------

def test_inspect_sitemap_limits_urls_and_passes_flags(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "sitemap_urls", lambda u: ["u1", "u2", "u3"])

    def fake_inspect_many(service, site, urls, only_unindexed, progress, **kw):
        seen.update(site=site, urls=urls, only_unindexed=only_unindexed, progress=progress, **kw)
        return [{"url": "u2", "verdict": "NEUTRAL", "error": ""}]

    monkeypatch.setattr(client, "inspect_many", fake_inspect_many)
    result = runner.invoke(app, ["inspect", "--site", SITE, "--sitemap", "https://x.com/s.xml",
                                 "--limit", "2", "--only-unindexed", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen["urls"] == ["u1", "u2"] and seen["site"] == SITE and seen["only_unindexed"] is True
    assert seen["progress"] is None  # not a tty
    assert seen["workers"] == client.INSPECT_WORKERS and seen["service_factory"] is auth.get_service
    assert json.loads(result.output) == [{"url": "u2", "verdict": "NEUTRAL", "error": ""}]


def test_inspect_sitemap_limit_zero_means_all(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "sitemap_urls", lambda u: ["u1", "u2", "u3"])
    monkeypatch.setattr(client, "inspect_many",
                        lambda s, site, urls, o, p, **kw: seen.setdefault("urls", urls) and [])
    runner.invoke(app, ["inspect", "--site", SITE, "--sitemap", "https://x.com/s.xml", "--limit", "0"])
    assert seen["urls"] == ["u1", "u2", "u3"]


def test_inspect_needs_exactly_one_of_url_or_sitemap(monkeypatch):
    monkeypatch.setattr(auth, "get_service", no_api)
    for args in (["inspect", "--site", SITE],
                 ["inspect", "https://x.com/a", "--site", SITE, "--sitemap", "https://x.com/s.xml"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 2
        assert json.loads(result.output)["error"]["code"] == "usage"


def test_inspect_only_unindexed_requires_sitemap(monkeypatch):
    monkeypatch.setattr(auth, "get_service", no_api)
    result = runner.invoke(app, ["inspect", "https://x.com/a", "--site", SITE, "--only-unindexed"])
    assert result.exit_code == 2


# ---- compare ----------------------------------------------------------------------

def test_compare_passes_arguments(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")

    def fake_compare(service, site, dims, start, end, filters, search_type, limit, sort, min_impressions):
        seen.update(site=site, dims=dims, start=start, end=end, filters=filters,
                    search_type=search_type, limit=limit, sort=sort, min_impressions=min_impressions)
        return [{"query": "a", "clicks": 5, "clicks_prev": 2, "clicks_delta": 3}]

    monkeypatch.setattr(client, "compare_rows", fake_compare)
    result = runner.invoke(app, ["compare", SITE, "--dims", "query,page", "--start", "2026-09-01",
                                 "--end", "2026-09-28", "--filter", "page contains /blog",
                                 "--limit", "10", "--sort", "impressions", "--min-impressions", "50",
                                 "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen == {
        "site": SITE, "dims": ["query", "page"], "start": "2026-09-01", "end": "2026-09-28",
        "filters": [{"dimension": "page", "operator": "contains", "expression": "/blog"}],
        "search_type": "web", "limit": 10, "sort": "impressions", "min_impressions": 50,
    }
    assert json.loads(result.output)[0]["clicks_delta"] == 3


def test_compare_defaults(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "compare_rows",
                        lambda *a, **k: seen.update(args=a, kwargs=k) or [])
    runner.invoke(app, ["compare", SITE])
    assert seen["args"][2] == ["query"] and seen["args"][7] == 50
    assert seen["kwargs"] == {"sort": "clicks", "min_impressions": 0}


def test_compare_invalid_sort_fails_before_api(monkeypatch):
    monkeypatch.setattr(auth, "get_service", no_api)
    result = runner.invoke(app, ["compare", SITE, "--sort", "bogus"])
    assert result.exit_code == 2 and "Unknown sort metric" in result.output


# ---- sitemaps submit / delete ---------------------------------------------------------

def test_sitemaps_submit(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "submit_sitemap",
                        lambda svc, site, url: seen.update(site=site, url=url) or [{"action": "submitted"}])
    result = runner.invoke(app, ["sitemaps", SITE, "--submit", "https://x.com/s.xml", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen == {"site": SITE, "url": "https://x.com/s.xml"}
    assert json.loads(result.output) == [{"action": "submitted"}]


def test_sitemaps_delete_requires_yes(monkeypatch):
    monkeypatch.setattr(auth, "get_service", no_api)
    result = runner.invoke(app, ["sitemaps", SITE, "--delete", "https://x.com/old.xml"])
    assert result.exit_code == 2 and "--yes" in result.output


def test_sitemaps_delete_with_yes(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "delete_sitemap",
                        lambda svc, site, url: seen.update(url=url) or [{"action": "deleted"}])
    result = runner.invoke(app, ["sitemaps", SITE, "--delete", "https://x.com/old.xml", "--yes",
                                 "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen["url"] == "https://x.com/old.xml"


def test_sitemaps_submit_and_delete_conflict(monkeypatch):
    monkeypatch.setattr(auth, "get_service", no_api)
    result = runner.invoke(app, ["sitemaps", SITE, "--submit", "a", "--delete", "b", "--yes"])
    assert result.exit_code == 2


def test_sitemaps_missing_write_scope_exits_3(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")

    def scope_error(*a):
        raise AuthError("Missing permission scope for this action (403).",
                        hint="Run `gsc login --write` (human step).")

    monkeypatch.setattr(client, "submit_sitemap", scope_error)
    result = runner.invoke(app, ["sitemaps", SITE, "--submit", "https://x.com/s.xml"])
    assert result.exit_code == 3
    assert "gsc login --write" in json.loads(result.output)["error"]["hint"]


# ---- request-indexing -------------------------------------------------------------------

def test_request_indexing_is_a_dry_run_without_yes(monkeypatch):
    monkeypatch.setattr(auth, "get_indexing_service", no_api)
    monkeypatch.setattr(client, "request_indexing", no_api)
    result = runner.invoke(app, ["request-indexing", "https://x.com/a", "https://x.com/b",
                                 "--format", "json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [r["url"] for r in rows] == ["https://x.com/a", "https://x.com/b"]
    assert {r["status"] for r in rows} == {"dry-run"}


def test_request_indexing_sends_with_yes(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_indexing_service", lambda: "idx")
    monkeypatch.setattr(client, "request_indexing",
                        lambda svc, urls: seen.update(svc=svc, urls=urls)
                        or [{"url": u, "status": "requested", "detail": ""} for u in urls])
    result = runner.invoke(app, ["request-indexing", "https://x.com/a", "--yes", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen == {"svc": "idx", "urls": ["https://x.com/a"]}
    assert json.loads(result.output)[0]["status"] == "requested"


def test_request_indexing_combines_urls_and_sitemap_deduped_with_limit(monkeypatch):
    monkeypatch.setattr(client, "sitemap_urls", lambda u: ["https://x.com/a", "https://x.com/b", "https://x.com/c"])
    result = runner.invoke(app, ["request-indexing", "https://x.com/a", "--sitemap", "https://x.com/s.xml",
                                 "--limit", "2", "--format", "json"])
    assert [r["url"] for r in json.loads(result.output)] == ["https://x.com/a", "https://x.com/b"]


def test_request_indexing_needs_urls(monkeypatch):
    result = runner.invoke(app, ["request-indexing"])
    assert result.exit_code == 2 and "at least one URL" in result.output


def test_request_indexing_only_unindexed_needs_site():
    result = runner.invoke(app, ["request-indexing", "https://x.com/a", "--only-unindexed"])
    assert result.exit_code == 2 and "--site" in result.output


def test_request_indexing_only_unindexed_submits_just_the_unindexed(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(auth, "get_indexing_service", lambda: "idx")

    def fake_inspect_many(service, site, urls, only_unindexed, **kw):
        seen["inspected"] = urls
        assert only_unindexed is True
        return [{"url": "https://x.com/b", "verdict": "NEUTRAL", "error": ""},
                {"url": "https://x.com/c", "verdict": "", "error": "400 not in property"}]

    monkeypatch.setattr(client, "inspect_many", fake_inspect_many)
    monkeypatch.setattr(client, "request_indexing",
                        lambda svc, urls: seen.update(sent=urls) or
                        [{"url": u, "status": "requested", "detail": ""} for u in urls])
    result = runner.invoke(app, ["request-indexing", "https://x.com/a", "https://x.com/b", "https://x.com/c",
                                 "--site", SITE, "--only-unindexed", "--yes", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen["inspected"] == ["https://x.com/a", "https://x.com/b", "https://x.com/c"]
    assert seen["sent"] == ["https://x.com/b"]  # errored inspections are not submitted


# ---- introspection / doctor ---------------------------------------------------------------

def test_commands_lists_new_commands_and_choices():
    doc = json.loads(runner.invoke(app, ["commands"]).output)
    by_name = {c["name"]: c for c in doc["commands"]}
    assert {"compare", "request-indexing"} <= set(by_name)
    sort = next(p for p in by_name["compare"]["params"] if p["name"] == "sort")
    assert sort["choices"] == ["clicks", "impressions", "ctr", "position"]
    site = next(p for p in by_name["inspect"]["params"] if p["name"] == "site")
    assert site["required"] is True
    login_flags = [f for p in by_name["login"]["params"] for f in p.get("flags", [])]
    assert "--write" in login_flags
