import functools
import json
import os
import sys
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Optional

import typer

from gsc_cli import auth, client, doctor, ga, introspect, output
from gsc_cli.errors import AuthError, GscError, UsageError

app = typer.Typer(
    help=(
        "Google Search Console from the command line (personal-account OAuth).\n\n"
        "Agents: output is JSON when piped, errors are JSON on stderr, exit codes are "
        "typed. Run `gsc skill show` for the usage guide and `gsc commands` for a "
        "machine-readable description of every command."
    ),
    no_args_is_help=True,
    add_completion=False,
)
skill_app = typer.Typer(help="The agent usage guide (SKILL.md) bundled with this tool.", no_args_is_help=True)
app.add_typer(skill_app, name="skill")
ga_app = typer.Typer(
    help="Optional Google Analytics 4 commands. Need `gsc login --ga`; GSC works without it.",
    no_args_is_help=True,
)
app.add_typer(ga_app, name="ga")

FormatOpt = Annotated[
    Optional[str],
    typer.Option("--format", help="table, json or csv. Default: table in a terminal, json when piped."),
]
OutputOpt = Annotated[
    Optional[Path], typer.Option("--output", help="Write to this file instead of stdout.")
]
YesOpt = Annotated[
    bool, typer.Option("--yes", help="Confirm an action that changes something at Google.")
]


def _report(e: GscError) -> None:
    if sys.stderr.isatty() and not os.environ.get("GSC_JSON_ERRORS"):
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        if e.hint:
            typer.echo(f"Hint: {e.hint}", err=True)
    else:
        payload = {"error": {"code": e.code, "message": str(e), "hint": e.hint}}
        typer.echo(json.dumps(payload), err=True)


def guarded(fn):
    """Report a GscError (JSON when not at a terminal) and exit with its typed code."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except GscError as e:
            _report(e)
            raise typer.Exit(e.exit_code)

    return wrapper


def _emit(rows: list[dict], fmt: str, output_path: Optional[Path]) -> None:
    width = 200 if output_path else None
    output.emit(output.format_rows(rows, fmt, width=width), output_path)


def _progress(done: int, total: int) -> None:
    typer.echo(f"inspected {done}/{total}", err=True)


@app.command(epilog="Needs a human and a browser. First time: --client-secret PATH.")
@guarded
def login(
    client_secret: Annotated[
        Optional[Path],
        typer.Option(
            "--client-secret",
            help="Path to the OAuth 'Desktop app' client_secret.json (saved for reuse).",
        ),
    ] = None,
    write: Annotated[
        bool,
        typer.Option(
            "--write",
            help="Also grant write access: submit/delete sitemaps and request indexing.",
        ),
    ] = False,
    ga_access: Annotated[
        bool,
        typer.Option("--ga", help="Also grant read access to Google Analytics 4 (`gsc ga ...`)."),
    ] = False,
):
    """Log in with your Google account in the browser (human step)."""
    token = auth.login(client_secret, write=write, ga=ga_access)
    scopes = set(auth.granted_scopes())
    parts = ["read + write" if set(auth.SCOPES_WRITE) <= scopes or write else "read-only"]
    if ga_access or auth.GA_SCOPE in scopes:
        parts.append("Google Analytics")
    typer.echo(f"Logged in ({', '.join(parts)}). Token saved to {token}")


@app.command()
@guarded
def logout():
    """Delete the saved login token."""
    if auth.logout():
        typer.echo("Logged out.")
    else:
        typer.echo("Not logged in.")


@app.command("doctor", epilog="Example: gsc doctor")
@guarded
def doctor_cmd(fmt: FormatOpt = None, output_path: OutputOpt = None):
    """Check setup (client secret, login, API access) without prompting. Exit 3 if not ready."""
    fmt = output.resolve_format(fmt)
    rows = doctor.run_checks()
    _emit(rows, fmt, output_path)
    if any(r["status"] == "fail" for r in rows):
        raise typer.Exit(AuthError.exit_code)


@app.command("commands", epilog="Always prints JSON. Example: gsc commands")
@guarded
def commands_cmd():
    """Describe every command, option, valid value and exit code as JSON."""
    typer.echo(json.dumps(introspect.describe(app), indent=2))


@app.command(epilog="Example: gsc sites --format json")
@guarded
def sites(fmt: FormatOpt = None, output_path: OutputOpt = None):
    """List Search Console properties and your permission level."""
    fmt = output.resolve_format(fmt)
    _emit(client.list_sites(auth.get_service()), fmt, output_path)


@app.command(
    epilog=(
        'Examples: gsc query sc-domain:example.com --dims query,page --days 28 --limit 50 | '
        'gsc query https://example.com/ --dims page --filter "page contains /blog" '
        "--format csv --output blog.csv"
    )
)
@guarded
def query(
    site: Annotated[str, typer.Argument(help="sc-domain:example.com or https://example.com/ (exact string from `gsc sites`)")],
    dims: Annotated[str, typer.Option("--dims", help="Comma-separated: query,page,country,device,date")] = "query",
    days: Annotated[int, typer.Option("--days", help="Days back from the latest available date.")] = 28,
    start: Annotated[Optional[str], typer.Option("--start", help="YYYY-MM-DD (use with --end).")] = None,
    end: Annotated[Optional[str], typer.Option("--end", help="YYYY-MM-DD (use with --start).")] = None,
    filters: Annotated[
        Optional[list[str]],
        typer.Option("--filter", help='Repeatable, e.g. "page contains /blog".'),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows (0 = all).")] = 1000,
    search_type: Annotated[str, typer.Option("--type", help="web, image, video, news, discover, googleNews")] = "web",
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """Run a search analytics query (clicks, impressions, ctr, position)."""
    fmt = output.resolve_format(fmt)
    begin, finish = client.date_range(days, start, end)
    dimensions = client.parse_dims(dims)
    parsed_filters = [client.parse_filter(f) for f in filters or []]
    client.validate_search_type(search_type)
    rows = client.query_rows(
        auth.get_service(), site, dimensions, begin, finish,
        parsed_filters, search_type, limit,
    )
    _emit(rows, fmt, output_path)


@app.command(
    epilog=(
        "Examples: gsc compare sc-domain:example.com --dims query --sort clicks --limit 20 | "
        "gsc compare sc-domain:example.com --dims page --days 7 --min-impressions 100"
    )
)
@guarded
def compare(
    site: Annotated[str, typer.Argument(help="sc-domain:example.com or https://example.com/")],
    dims: Annotated[str, typer.Option("--dims", help="Comma-separated: query,page,country,device,date. Empty = totals.")] = "query",
    days: Annotated[int, typer.Option("--days", help="Length of each period; compares the latest N days with the N before.")] = 28,
    start: Annotated[Optional[str], typer.Option("--start", help="Current period start YYYY-MM-DD (use with --end).")] = None,
    end: Annotated[Optional[str], typer.Option("--end", help="Current period end YYYY-MM-DD (use with --start).")] = None,
    filters: Annotated[
        Optional[list[str]],
        typer.Option("--filter", help='Repeatable, e.g. "page contains /blog".'),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows (0 = all).")] = 50,
    search_type: Annotated[str, typer.Option("--type", help="web, image, video, news, discover, googleNews")] = "web",
    sort: Annotated[str, typer.Option("--sort", help="Rank rows by the biggest absolute change in: clicks, impressions, ctr, position.")] = "clicks",
    min_impressions: Annotated[int, typer.Option("--min-impressions", help="Drop rows with fewer impressions in both periods.")] = 0,
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """Compare this period with the previous one: per-row deltas for clicks, impressions, ctr, position."""
    fmt = output.resolve_format(fmt)
    begin, finish = client.date_range(days, start, end)
    dimensions = client.parse_dims(dims)
    parsed_filters = [client.parse_filter(f) for f in filters or []]
    client.validate_search_type(search_type)
    client.validate_sort(sort)
    rows = client.compare_rows(
        auth.get_service(), site, dimensions, begin, finish, parsed_filters,
        search_type, limit, sort=sort, min_impressions=min_impressions,
    )
    _emit(rows, fmt, output_path)


@app.command(
    epilog=(
        "Examples: gsc inspect https://example.com/a --site sc-domain:example.com | "
        "gsc inspect --sitemap https://example.com/sitemap.xml --site sc-domain:example.com "
        "--only-unindexed"
    )
)
@guarded
def inspect(
    url: Annotated[Optional[str], typer.Argument(help="One page URL to inspect (or use --sitemap).")] = None,
    site: Annotated[str, typer.Option("--site", help="The property that contains the URL(s).")] = ...,
    sitemap: Annotated[Optional[str], typer.Option("--sitemap", help="Inspect every URL in this sitemap (follows sitemap indexes).")] = None,
    limit: Annotated[int, typer.Option("--limit", help="With --sitemap: inspect at most N URLs (0 = all). Quota is ~2000/day.")] = 100,
    only_unindexed: Annotated[bool, typer.Option("--only-unindexed", help="With --sitemap: list only URLs that are not indexed (verdict != PASS) or failed.")] = False,
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """Show index status for a URL, or for every URL in a sitemap (URL Inspection)."""
    fmt = output.resolve_format(fmt)
    if bool(url) == bool(sitemap):
        raise UsageError("Give exactly one of: a URL argument, or --sitemap URL.")
    if only_unindexed and not sitemap:
        raise UsageError("--only-unindexed only applies with --sitemap.")
    service = auth.get_service()
    if url:
        rows = client.inspect_url(service, site, url)
    else:
        urls = client.sitemap_urls(sitemap)
        if limit > 0:
            urls = urls[:limit]
        progress = _progress if sys.stderr.isatty() else None
        rows = client.inspect_many(
            service, site, urls, only_unindexed, progress,
            service_factory=auth.get_service, workers=client.INSPECT_WORKERS,
        )
    _emit(rows, fmt, output_path)


@app.command(
    epilog=(
        "Examples: gsc sitemaps sc-domain:example.com | "
        "gsc sitemaps sc-domain:example.com --submit https://example.com/sitemap.xml | "
        "gsc sitemaps sc-domain:example.com --delete https://example.com/old.xml --yes"
    )
)
@guarded
def sitemaps(
    site: Annotated[str, typer.Argument(help="sc-domain:example.com or https://example.com/")],
    submit: Annotated[Optional[str], typer.Option("--submit", help="Submit or resubmit this sitemap URL (needs `gsc login --write`).")] = None,
    delete: Annotated[Optional[str], typer.Option("--delete", help="Remove this sitemap from Search Console (needs --yes and `gsc login --write`).")] = None,
    yes: YesOpt = False,
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """List sitemaps with status and error counts; optionally submit or delete one."""
    fmt = output.resolve_format(fmt)
    if submit and delete:
        raise UsageError("Use only one of --submit and --delete.")
    if delete and not yes:
        raise UsageError(f"Pass --yes to confirm removing {delete} from {site}.")
    service = auth.get_service()
    if submit:
        rows = client.submit_sitemap(service, site, submit)
    elif delete:
        rows = client.delete_sitemap(service, site, delete)
    else:
        rows = client.list_sitemaps(service, site)
    _emit(rows, fmt, output_path)


@app.command(
    "request-indexing",
    epilog=(
        "Best-effort: Google documents the Indexing API only for job-posting and livestream pages, "
        "so it may ignore other URLs. Needs property OWNER access, the Web Search Indexing API "
        "enabled in your GCP project, and `gsc login --write`. Dry run unless --yes. "
        "Examples: gsc request-indexing https://example.com/new-post --yes | "
        "gsc request-indexing --sitemap https://example.com/sitemap.xml "
        "--site sc-domain:example.com --only-unindexed --yes"
    ),
)
@guarded
def request_indexing_cmd(
    urls: Annotated[Optional[list[str]], typer.Argument(help="Page URLs to submit.")] = None,
    sitemap: Annotated[Optional[str], typer.Option("--sitemap", help="Also submit every URL in this sitemap.")] = None,
    site: Annotated[Optional[str], typer.Option("--site", help="Property; required with --only-unindexed.")] = None,
    only_unindexed: Annotated[bool, typer.Option("--only-unindexed", help="Inspect the URLs first (max --limit) and submit only those not indexed.")] = False,
    limit: Annotated[int, typer.Option("--limit", help="Max URLs to submit (default Indexing API quota is ~200/day).")] = 50,
    yes: YesOpt = False,
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """Ask Google to (re)crawl URLs via the Indexing API. Dry run unless --yes."""
    fmt = output.resolve_format(fmt)
    targets = list(urls or [])
    if sitemap:
        targets += client.sitemap_urls(sitemap)
    targets = list(dict.fromkeys(targets))
    if not targets:
        raise UsageError("Give at least one URL, or --sitemap URL.")
    if only_unindexed:
        if not site:
            raise UsageError("--only-unindexed needs --site.")
        inspected = client.inspect_many(
            auth.get_service(), site, targets[:limit] if limit > 0 else targets,
            only_unindexed=True, service_factory=auth.get_service, workers=client.INSPECT_WORKERS,
        )
        targets = [r["url"] for r in inspected if not r["error"]]
    elif limit > 0:
        targets = targets[:limit]

    if not yes:
        rows = [{"url": u, "status": "dry-run", "detail": "pass --yes to send"} for u in targets]
    else:
        rows = client.request_indexing(auth.get_indexing_service(), targets)
    _emit(rows, fmt, output_path)


@ga_app.command("properties", epilog="Example: gsc ga properties")
@guarded
def ga_properties(fmt: FormatOpt = None, output_path: OutputOpt = None):
    """List the GA4 properties you can access (numeric ID, name, account, website URLs)."""
    fmt = output.resolve_format(fmt)
    _emit(ga.list_properties(auth.get_analytics_admin_service()), fmt, output_path)


@ga_app.command(
    "report",
    epilog=(
        "Examples: gsc ga report 123456789 --metrics sessions,activeUsers --dims date | "
        "gsc ga report 123456789 --organic --dims landingPage --metrics sessions,keyEvents "
        '--filter "country equals Kazakhstan" --sort sessions --limit 50'
    ),
)
@guarded
def ga_report(
    property_id: Annotated[str, typer.Argument(metavar="PROPERTY", help="Numeric GA4 property ID (see `gsc ga properties`).")],
    metrics: Annotated[str, typer.Option("--metrics", help="Comma-separated GA4 metrics, e.g. sessions,activeUsers,engagementRate,keyEvents.")] = "sessions,activeUsers",
    dims: Annotated[str, typer.Option("--dims", help="Comma-separated GA4 dimensions, e.g. date,landingPage,sessionDefaultChannelGroup. Empty = totals.")] = "",
    days: Annotated[int, typer.Option("--days", help="Last N days, ending yesterday.")] = 28,
    start: Annotated[Optional[str], typer.Option("--start", help="YYYY-MM-DD (use with --end).")] = None,
    end: Annotated[Optional[str], typer.Option("--end", help="YYYY-MM-DD (use with --start).")] = None,
    filters: Annotated[
        Optional[list[str]],
        typer.Option("--filter", help='Repeatable, ANDed: "<dimension> <operator> <value>". Operators: equals, notEquals, contains, notContains, beginsWith, endsWith, regex, notRegex.'),
    ] = None,
    organic: Annotated[bool, typer.Option("--organic", help="Only organic-search sessions (sessionDefaultChannelGroup = Organic Search).")] = False,
    sort: Annotated[Optional[str], typer.Option("--sort", help="A requested metric or dimension, optionally :asc or :desc. Default: first metric, descending.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows (0 = all).")] = 1000,
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """Run a GA4 report (Data API runReport)."""
    fmt = output.resolve_format(fmt)
    begin, finish = ga.date_range(days, start, end)
    dimensions = ga.parse_names(dims, "dimension")
    metric_names = ga.parse_names(metrics, "metric")
    parsed = [ga.parse_filter(f) for f in filters or []]
    if organic:
        parsed.insert(0, ga.ORGANIC_FILTER)
    ga.normalize_property(property_id)
    ga.build_order_by(sort, dimensions, metric_names)
    rows = ga.run_report(
        auth.get_analytics_data_service(), property_id, dimensions, metric_names,
        begin, finish, parsed, sort, limit,
    )
    _emit(rows, fmt, output_path)


@ga_app.command(
    "landing-pages",
    epilog=(
        "Joins GSC and GA per page: search clicks/impressions/position next to organic "
        "sessions, engagement and key events. Example: gsc ga landing-pages "
        "sc-domain:example.com --property 123456789 --limit 50"
    ),
)
@guarded
def ga_landing_pages(
    site: Annotated[str, typer.Argument(help="GSC property: sc-domain:example.com or https://example.com/")],
    property_id: Annotated[str, typer.Option("--property", help="Numeric GA4 property ID for the same website (see `gsc ga properties`).")] = ...,
    days: Annotated[int, typer.Option("--days", help="Days back from the latest available GSC date.")] = 28,
    start: Annotated[Optional[str], typer.Option("--start", help="YYYY-MM-DD (use with --end).")] = None,
    end: Annotated[Optional[str], typer.Option("--end", help="YYYY-MM-DD (use with --start).")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows (0 = all), most clicks first.")] = 100,
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """Per-page GSC + GA analysis: how search clicks turn into organic sessions and engagement."""
    fmt = output.resolve_format(fmt)
    begin, finish = client.date_range(days, start, end)
    ga.normalize_property(property_id)
    rows = ga.landing_pages(
        auth.get_service(), auth.get_analytics_data_service(), site, property_id,
        begin, finish, limit,
    )
    _emit(rows, fmt, output_path)


def _skill_text() -> str:
    return files("gsc_cli").joinpath("skill", "SKILL.md").read_text(encoding="utf-8")


@skill_app.command("show")
def skill_show():
    """Print the agent usage guide (SKILL.md)."""
    typer.echo(_skill_text())


@skill_app.command("install")
def skill_install(
    dest: Annotated[
        Optional[Path],
        typer.Option("--dest", help="Skills directory. Default: ~/.claude/skills"),
    ] = None,
):
    """Install SKILL.md as a Claude Code skill (<dest>/gsc/SKILL.md)."""
    base = dest or Path.home() / ".claude" / "skills"
    target = base / "gsc" / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_skill_text(), encoding="utf-8")
    typer.echo(f"Installed skill to {target}")
