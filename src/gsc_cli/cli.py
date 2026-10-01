import functools
import json
import os
import sys
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Optional

import typer

from gsc_cli import auth, client, doctor, introspect, output
from gsc_cli.errors import AuthError, GscError

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

FormatOpt = Annotated[
    Optional[str],
    typer.Option("--format", help="table, json or csv. Default: table in a terminal, json when piped."),
]
OutputOpt = Annotated[
    Optional[Path], typer.Option("--output", help="Write to this file instead of stdout.")
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
):
    """Log in with your Google account in the browser (human step)."""
    token = auth.login(client_secret)
    typer.echo(f"Logged in. Token saved to {token}")


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


@app.command(epilog="Example: gsc inspect https://example.com/a --site sc-domain:example.com")
@guarded
def inspect(
    url: Annotated[str, typer.Argument(help="Page URL to inspect.")],
    site: Annotated[str, typer.Option("--site", help="The property that contains the URL.")],
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """Show index status for a URL (URL Inspection)."""
    fmt = output.resolve_format(fmt)
    _emit(client.inspect_url(auth.get_service(), site, url), fmt, output_path)


@app.command(epilog="Example: gsc sitemaps sc-domain:example.com")
@guarded
def sitemaps(
    site: Annotated[str, typer.Argument(help="sc-domain:example.com or https://example.com/")],
    fmt: FormatOpt = None,
    output_path: OutputOpt = None,
):
    """List sitemaps with status and error counts."""
    fmt = output.resolve_format(fmt)
    _emit(client.list_sitemaps(auth.get_service(), site), fmt, output_path)


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
