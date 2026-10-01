import json

from typer.testing import CliRunner

from gsc_cli import auth, client, doctor
from gsc_cli.cli import app
from gsc_cli.errors import PermissionDenied, QuotaError

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


def test_query_invalid_filter_exits_2_with_json_error(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    result = runner.invoke(app, ["query", "sc-domain:x.com", "--filter", "bogus"])
    assert result.exit_code == 2
    err = json.loads(result.output)["error"]
    assert err["code"] == "usage"
    assert "Invalid filter" in err["message"]


def test_query_invalid_format_fails_before_calling_api(monkeypatch):
    def boom():
        raise AssertionError("API should not be reached")

    monkeypatch.setattr(auth, "get_service", boom)
    result = runner.invoke(app, ["query", "sc-domain:x.com", "--format", "xml"])
    assert result.exit_code == 2
    assert "Unknown format" in result.output


def test_not_logged_in_exits_3_pointing_to_login(tmp_path, monkeypatch):
    monkeypatch.setenv("GSC_CONFIG_DIR", str(tmp_path / "empty"))
    result = runner.invoke(app, ["sites"])
    assert result.exit_code == 3
    err = json.loads(result.output)["error"]
    assert err["code"] == "auth"
    assert "gsc login" in err["message"]
    assert "human" in err["hint"]


def test_api_error_is_shown_without_traceback(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")

    def denied(svc):
        raise PermissionDenied("No access to sc-domain:x.com (403)", hint="check gsc sites")

    monkeypatch.setattr(client, "list_sites", denied)
    result = runner.invoke(app, ["sites"])
    assert result.exit_code == 4
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
    monkeypatch.setenv("GSC_CONFIG_DIR", str(tmp_path / "cfg"))  # hermetic: no real token

    def fake_login(path, write=False, ga=False):
        seen.update(path=path, write=write, ga=ga)
        return tmp_path / "token.json"

    monkeypatch.setattr(auth, "login", fake_login)
    secret = tmp_path / "cs.json"
    result = runner.invoke(app, ["login", "--client-secret", str(secret)])
    assert result.exit_code == 0, result.output
    assert str(seen["path"]) == str(secret)
    assert "Logged in (read-only)" in result.output
    assert seen["write"] is False
    result = runner.invoke(app, ["login", "--client-secret", str(secret), "--write"])
    assert seen["write"] is True and "read + write" in result.output
    result = runner.invoke(app, ["login", "--ga"])
    assert seen["ga"] is True and "Google Analytics" in result.output


def test_logout(monkeypatch):
    monkeypatch.setattr(auth, "logout", lambda: True)
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0
    assert "Logged out" in result.output


# ---- agent-facing behaviour ---------------------------------------------------

def test_default_format_is_json_when_not_a_tty(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")
    monkeypatch.setattr(client, "list_sites", lambda svc: [{"site": "s", "permission": "p"}])
    result = runner.invoke(app, ["sites"])  # no --format
    assert json.loads(result.output) == [{"site": "s", "permission": "p"}]


def test_quota_error_exit_5_and_hint(monkeypatch):
    monkeypatch.setattr(auth, "get_service", lambda: "svc")

    def limited(svc):
        raise QuotaError("Quota exceeded (429).", hint="Wait a bit and retry.")

    monkeypatch.setattr(client, "list_sites", limited)
    result = runner.invoke(app, ["sites"])
    assert result.exit_code == 5
    assert json.loads(result.output)["error"] == {
        "code": "quota", "message": "Quota exceeded (429).", "hint": "Wait a bit and retry.",
    }


def test_commands_describes_cli_as_json():
    result = runner.invoke(app, ["commands"])
    assert result.exit_code == 0
    doc = json.loads(result.output)
    names = {c["name"] for c in doc["commands"]}
    assert {"login", "logout", "sites", "query", "inspect", "sitemaps", "doctor",
            "commands", "skill show", "skill install"} <= names
    query = next(c for c in doc["commands"] if c["name"] == "query")
    dims = next(p for p in query["params"] if p["name"] == "dims")
    assert dims["choices"] == ["query", "page", "country", "device", "date"]
    assert dims["default"] == "query"
    assert next(p for p in query["params"] if p["name"] == "site")["required"] is True
    assert "includingRegex" in doc["filter_operators"]
    assert doc["exit_codes"]["3"].startswith("not logged in")


def test_doctor_all_ok(monkeypatch):
    monkeypatch.setattr(
        doctor, "run_checks", lambda: [{"check": "token", "status": "ok", "detail": "x"}]
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert json.loads(result.output)[0]["status"] == "ok"


def test_doctor_failure_exits_3(monkeypatch):
    monkeypatch.setattr(
        doctor, "run_checks", lambda: [{"check": "token", "status": "fail", "detail": "x"}]
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 3


def test_skill_show_prints_guide():
    result = runner.invoke(app, ["skill", "show"])
    assert result.exit_code == 0
    assert result.output.startswith("---\nname: gsc")


def test_skill_install_writes_file(tmp_path):
    result = runner.invoke(app, ["skill", "install", "--dest", str(tmp_path)])
    assert result.exit_code == 0, result.output
    installed = (tmp_path / "gsc" / "SKILL.md").read_text(encoding="utf-8")
    assert installed.startswith("---\nname: gsc")


def test_skill_mentions_every_command_and_flag():
    guide = runner.invoke(app, ["skill", "show"]).output
    doc = json.loads(runner.invoke(app, ["commands"]).output)
    for command in doc["commands"]:
        assert f"gsc {command['name']}" in guide, command["name"]
    for command in doc["commands"]:
        for param in command["params"]:
            for flag in param.get("flags", []):
                if flag not in ("--format", "--output"):
                    assert flag in guide, (command["name"], flag)
