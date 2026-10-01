import json

import pytest

from gsc_cli import output
from gsc_cli.errors import GscError

ROWS = [
    {"query": "shoes", "clicks": 3, "ctr": 0.034567, "position": 12.0},
    {"query": "boots", "clicks": 1, "ctr": 0.0, "position": 4.5},
]


def test_json_roundtrips():
    text = output.format_rows(ROWS, "json")
    assert json.loads(text) == ROWS


def test_csv_has_header_and_rows():
    text = output.format_rows([{"query": "x", "clicks": 3}], "csv")
    assert text == "query,clicks\nx,3\n"


def test_csv_respects_columns_order():
    text = output.format_rows([{"a": 1, "b": 2}], "csv", columns=["b", "a"])
    assert text == "b,a\n2,1\n"


def test_table_contains_headers_and_trimmed_floats():
    text = output.format_rows(ROWS, "table", width=120)
    assert "query" in text and "clicks" in text
    assert "shoes" in text
    assert "0.0346" in text  # rounded to 4 places
    assert "12" in text and "12.0" not in text  # trailing zeros trimmed


def test_table_empty_says_no_results():
    assert output.format_rows([], "table").strip() == "No results."


def test_json_empty_is_empty_list():
    assert json.loads(output.format_rows([], "json")) == []


def test_invalid_format_raises():
    with pytest.raises(GscError, match="table, json, csv"):
        output.format_rows(ROWS, "xml")
    with pytest.raises(GscError):
        output.check_format("xml")


def test_emit_writes_file(tmp_path):
    target = tmp_path / "out.csv"
    output.emit("a,b\n", target)
    assert target.read_text(encoding="utf-8") == "a,b\n"


def test_emit_prints_to_stdout(capsys):
    output.emit("hello")
    assert capsys.readouterr().out == "hello\n"
