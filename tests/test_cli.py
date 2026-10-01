import json

from typer.testing import CliRunner

from gsc_cli import auth, client
from gsc_cli.cli import app
from gsc_cli.errors import GscError

runner = CliRunner()

QUERY_ROWS = [{"query": "a", "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 3.0}]


def test_sites_json(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(
        client, "list_sites", lambda svc: [{"site": "sc-domain:x.com", "permission": "siteOwner"}]
    )
    result = runner.invoke(app, ["sites", "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"site": "sc-domain:x.com", "permission": "siteOwner"}]


def test_query_passes_parsed_arguments(monkeypatch):
    captured = {}
    monkeypatch.setattr(auth, "get_service", lambda: "svc")

    def fake_query_rows(service, site, dims, start, end, filters, search_type, limit):
        captured.update(site=site, dims=dims, start=start, end=end,
                        filters=filters, search_type=search_type, limit=limit)
        return QUERY_ROWS

    monkeypatch.setattr(client, "query_rows", fake_query_rows)
    result = runner.invoke(app, [
        "query", "sc-domain:x.com", "--dims", "query,page",
        "--start", "2026-09-01", "--end", "2026-09-07",
        "--filter", "page contains /blog", "--limit", "5",
        "--type", "image", "--format", "json",
    ])
    assert result.exit_code == 0, result.output
    assert captured == {
        "site": "sc-domain:x.com", "dims": ["query", "page"],
        "start": "2026-09-01", "end": "2026-09-07",
        "filters": [{"dimension": "page", "operator": "contains", "expression": "/blog"}],
        "search_type": "image", "limit": 5,
    }
    assert json.loads(result.output) == QUERY_ROWS


def test_query_writes_output_file(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "query_rows", lambda *a, **k: QUERY_ROWS)
    target = tmp_path / "out.csv"
    result = runner.invoke(app, [
        "query", "sc-domain:x.com", "--format", "csv", "--output", str(target),
    ])
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8").startswith("query,clicks,impressions,ctr,position")


def test_query_invalid_filter_exits_1_with_message(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    result = runner.invoke(app, ["query", "sc-domain:x.com", "--filter", "bogus"])
    assert result.exit_code == 1
    assert "Invalid filter" in result.output


def test_query_invalid_format_fails_before_calling_api(monkeypatch):
    def boom():
        raise AssertionError("API should not be reached")

    monkeypatch.setattr(auth, "get_service", boom)
    result = runner.invoke(app, ["query", "sc-domain:x.com", "--format", "xml"])
    assert result.exit_code == 1
    assert "Unknown format" in result.output


def test_not_logged_in_exits_1_pointing_to_login(tmp_path, monkeypatch):
    monkeypatch.setenv("GSC_CONFIG_DIR", str(tmp_path / "empty"))
    result = runner.invoke(app, ["sites"])
    assert result.exit_code == 1
    assert "gsc login" in result.output


def test_api_error_is_shown_without_traceback(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")

    def denied(svc):
        raise GscError("No access to sc-domain:x.com (403)")

    monkeypatch.setattr(client, "list_sites", denied)
    result = runner.invoke(app, ["sites"])
    assert result.exit_code == 1
    assert "No access" in result.output
    assert "Traceback" not in result.output


def test_sitemaps(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(
        client, "list_sitemaps",
        lambda svc, site: [{"path": f"{site}sitemap.xml", "errors": "0"}],
    )
    result = runner.invoke(app, ["sitemaps", "https://x.com/", "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"path": "https://x.com/sitemap.xml", "errors": "0"}]


def test_inspect_requires_site_and_passes_args(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    seen = {}

    def fake_inspect(svc, site, url):
        seen.update(site=site, url=url)
        return [{"field": "verdict", "value": "PASS"}]

    monkeypatch.setattr(client, "inspect_url", fake_inspect)
    assert runner.invoke(app, ["inspect", "https://x.com/a"]).exit_code != 0
    result = runner.invoke(
        app, ["inspect", "https://x.com/a", "--site", "sc-domain:x.com", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    assert seen == {"site": "sc-domain:x.com", "url": "https://x.com/a"}


def test_login_passes_client_secret_path(monkeypatch, tmp_path):
    seen = {}

    def fake_login(path):
        seen["path"] = path
        return tmp_path / "token.json"

    monkeypatch.setattr(auth, "login", fake_login)
    secret = tmp_path / "cs.json"
    result = runner.invoke(app, ["login", "--client-secret", str(secret)])
    assert result.exit_code == 0, result.output
    assert str(seen["path"]) == str(secret)
    assert "Logged in" in result.output


def test_logout(monkeypatch):
    monkeypatch.setattr(auth, "logout", lambda: True)
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0
    assert "Logged out" in result.output
