import csv
import io
import json
import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table

from gsc_cli.errors import GscError

FORMATS = ("table", "json", "csv")


def check_format(fmt: str) -> None:
    if fmt not in FORMATS:
        raise GscError(f"Unknown format '{fmt}'. Valid formats: {', '.join(FORMATS)}.")


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def format_rows(
    rows: list[dict],
    fmt: str,
    columns: list[str] | None = None,
    width: int | None = None,
) -> str:
    check_format(fmt)
    if columns is None:
        columns = list(rows[0].keys()) if rows else []

    if fmt == "json":
        return json.dumps(rows, indent=2, default=str) + "\n"

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
        )
        if columns:
            writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    if not rows:
        return "No results.\n"
    table = Table(*columns)
    for row in rows:
        table.add_row(*[_cell(row.get(c)) for c in columns])
    buf = io.StringIO()
    if width is None:
        width = shutil.get_terminal_size((120, 24)).columns
    Console(file=buf, width=width, color_system=None).print(table)
    return buf.getvalue()


def emit(text: str, output_path: "str | Path | None" = None) -> None:
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
    else:
        print(text, end="" if text.endswith("\n") else "\n")
