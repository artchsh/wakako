import functools
from pathlib import Path
from typing import Annotated, Optional

import typer

from gsc_cli import auth, client, output
from gsc_cli.errors import GscError

app = typer.Typer(
    help="Google Search Console from the command line (personal-account OAuth).",
    no_args_is_help=True,
    add_completion=False,
)

FormatOpt = Annotated[
    str, typer.Option("--format", help="Output format: table, json or csv.")
]
OutputOpt = Annotated[
    Optional[Path], typer.Option("--output", help="Write to this file instead of stdout.")
]


def guarded(fn):
    """Turn GscError into a one-line message and exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except GscError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

    return wrapper


def _emit(rows: list[dict], fmt: str, output_path: Optional[Path]) -> None:
    width = 200 if output_path else None
    output.emit(output.format_rows(rows, fmt, width=width), output_path)


@app.command()
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
    """Log in with your Google account in the browser."""
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


@app.command()
@guarded
def sites(fmt: FormatOpt = "table", output_path: OutputOpt = None):
    """List Search Console properties and your permission level."""
    output.check_format(fmt)
    _emit(client.list_sites(auth.get_service()), fmt, output_path)


@app.command()
@guarded
def query(
    site: Annotated[str, typer.Argument(help="sc-domain:example.com or https://example.com/")],
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
    fmt: FormatOpt = "table",
    output_path: OutputOpt = None,
):
    """Run a search analytics query."""
    output.check_format(fmt)
    begin, finish = client.date_range(days, start, end)
    dimensions = client.parse_dims(dims)
    parsed_filters = [client.parse_filter(f) for f in filters or []]
    client.validate_search_type(search_type)
    rows = client.query_rows(
        auth.get_service(), site, dimensions, begin, finish,
        parsed_filters, search_type, limit,
    )
    _emit(rows, fmt, output_path)


@app.command()
@guarded
def inspect(
    url: Annotated[str, typer.Argument(help="Page URL to inspect.")],
    site: Annotated[str, typer.Option("--site", help="The property that contains the URL.")],
    fmt: FormatOpt = "table",
    output_path: OutputOpt = None,
):
    """Show index status for a URL (URL Inspection)."""
    output.check_format(fmt)
    _emit(client.inspect_url(auth.get_service(), site, url), fmt, output_path)


@app.command()
@guarded
def sitemaps(
    site: Annotated[str, typer.Argument(help="sc-domain:example.com or https://example.com/")],
    fmt: FormatOpt = "table",
    output_path: OutputOpt = None,
):
    """List sitemaps with status and error counts."""
    output.check_format(fmt)
    _emit(client.list_sitemaps(auth.get_service(), site), fmt, output_path)
