import json

from typer.testing import CliRunner

from wakako import auth, client, ga
from wakako.cli import app
from wakako.errors import AuthError

runner = CliRunner()


def no_api(*a, **k):
    raise AssertionError("API/auth should not be reached")


def test_ga_properties(monkeypatch):
    monkeypatch.setattr(auth, "get_analytics_admin_service", lambda: "admin")
    monkeypatch.setattr(ga, "list_properties",
                        lambda svc: [{"property": "1", "name": "P", "account": "A", "websites": "https://x.com"}])
    result = runner.invoke(app, ["ga", "properties", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["property"] == "1"


def test_ga_report_passes_arguments(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_analytics_data_service", lambda: "data")

    def fake_run_report(service, prop, dims, metrics, start, end, filters, sort, limit):
        seen.update(service=service, prop=prop, dims=dims, metrics=metrics, start=start, end=end,
                    filters=filters, sort=sort, limit=limit)
        return [{"landingPage": "/a", "sessions": 5}]

    monkeypatch.setattr(ga, "run_report", fake_run_report)
    result = runner.invoke(app, [
        "ga", "report", "123456789", "--metrics", "sessions,keyEvents", "--dims", "landingPage",
        "--start", "2026-09-01", "--end", "2026-09-28", "--filter", "country equals Kazakhstan",
        "--organic", "--sort", "sessions:asc", "--limit", "7", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen["prop"] == "123456789" and seen["service"] == "data"
    assert seen["dims"] == ["landingPage"] and seen["metrics"] == ["sessions", "keyEvents"]
    assert (seen["start"], seen["end"], seen["sort"], seen["limit"]) == ("2026-09-01", "2026-09-28", "sessions:asc", 7)
    assert seen["filters"] == [ga.ORGANIC_FILTER,
                               {"dimension": "country", "operator": "equals", "expression": "Kazakhstan"}]
    assert json.loads(result.output) == [{"landingPage": "/a", "sessions": 5}]


def test_ga_report_defaults(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_analytics_data_service", lambda: "data")
    monkeypatch.setattr(ga, "run_report", lambda *a: seen.update(args=a) or [])
    runner.invoke(app, ["ga", "report", "123456789"])
    _, prop, dims, metrics, _, _, filters, sort, limit = seen["args"]
    assert (dims, metrics, filters, sort, limit) == ([], ["sessions", "activeUsers"], [], None, 1000)


def test_ga_report_usage_errors_fail_before_any_api_call(monkeypatch):
    monkeypatch.setattr(auth, "get_analytics_data_service", no_api)
    for args, code in ((["ga", "report", "G-ABC123"], "usage"),
                       (["ga", "report", "123456789", "--sort", "bounces"], "usage"),
                       (["ga", "report", "123456789", "--filter", "bogus"], "usage"),
                       (["ga", "report", "123456789", "--metrics", "a;b"], "usage")):
        result = runner.invoke(app, args)
        assert result.exit_code == 2, args
        assert json.loads(result.output)["error"]["code"] == code


def test_ga_not_granted_exits_3_with_login_hint(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "token.json").write_text(json.dumps({"scopes": list(auth.SCOPES)}))
    monkeypatch.setenv("WAKAKO_CONFIG_DIR", str(cfg))

    class Creds:
        valid = True

    monkeypatch.setattr(auth, "Credentials",
                        type("C", (), {"from_authorized_user_file": staticmethod(lambda p, s: Creds())}))
    result = runner.invoke(app, ["ga", "properties"])
    assert result.exit_code == 3
    err = json.loads(result.output)["error"]
    assert err["code"] == "auth" and "wakako login --ga" in err["hint"]


def test_ga_landing_pages(monkeypatch):
    seen = {}
    monkeypatch.setattr(auth, "get_service", lambda: "gsc")
    monkeypatch.setattr(auth, "get_analytics_data_service", lambda: "data")

    def fake_landing(gsc_service, ga_service, site, prop, start, end, limit):
        seen.update(gsc=gsc_service, ga=ga_service, site=site, prop=prop, start=start, end=end, limit=limit)
        return [{"page": "https://x.com/a", "clicks": 1, "sessions": 1}]

    monkeypatch.setattr(ga, "landing_pages", fake_landing)
    result = runner.invoke(app, ["ga", "landing-pages", "sc-domain:x.com", "--property", "123456789",
                                 "--start", "2026-09-01", "--end", "2026-09-28", "--limit", "5",
                                 "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen == {"gsc": "gsc", "ga": "data", "site": "sc-domain:x.com", "prop": "123456789",
                    "start": "2026-09-01", "end": "2026-09-28", "limit": 5}
    assert json.loads(result.output)[0]["page"] == "https://x.com/a"


def test_ga_landing_pages_requires_property(monkeypatch):
    monkeypatch.setattr(auth, "get_service", no_api)
    assert runner.invoke(app, ["ga", "landing-pages", "sc-domain:x.com"]).exit_code != 0
    result = runner.invoke(app, ["ga", "landing-pages", "sc-domain:x.com", "--property", "nope"])
    assert result.exit_code == 2


def test_commands_describes_ga_group_without_gsc_choices():
    doc = json.loads(runner.invoke(app, ["commands"]).output)
    by_name = {c["name"]: c for c in doc["commands"]}
    assert {"ga properties", "ga report", "ga landing-pages"} <= set(by_name)
    ga_dims = next(p for p in by_name["ga report"]["params"] if p["name"] == "dims")
    assert "choices" not in ga_dims  # GA dimensions are not the GSC list
    gsc_dims = next(p for p in by_name["query"]["params"] if p["name"] == "dims")
    assert "choices" in gsc_dims
    prop = next(p for p in by_name["ga landing-pages"]["params"] if p["name"] == "property_id")
    assert prop["required"] is True
    assert "--ga" in [f for p in by_name["login"]["params"] for f in p.get("flags", [])]
