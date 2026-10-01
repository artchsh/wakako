from datetime import date

import pytest

from gsc_cli import client
from gsc_cli.errors import GscError

TODAY = date(2026, 10, 1)


def test_date_range_default_uses_three_day_lag():
    assert client.date_range(28, None, None, today=TODAY) == ("2026-09-01", "2026-09-28")


def test_date_range_one_day_is_just_end_date():
    assert client.date_range(1, None, None, today=TODAY) == ("2026-09-28", "2026-09-28")


def test_date_range_explicit_start_end():
    assert client.date_range(28, "2026-08-01", "2026-08-31", today=TODAY) == (
        "2026-08-01",
        "2026-08-31",
    )


def test_date_range_requires_both_start_and_end():
    with pytest.raises(GscError, match="both"):
        client.date_range(28, "2026-08-01", None, today=TODAY)


def test_date_range_rejects_bad_dates_and_order():
    with pytest.raises(GscError, match="YYYY-MM-DD"):
        client.date_range(28, "08/01/2026", "2026-08-31", today=TODAY)
    with pytest.raises(GscError, match="before"):
        client.date_range(28, "2026-09-01", "2026-08-01", today=TODAY)


def test_date_range_rejects_non_positive_days():
    with pytest.raises(GscError, match="--days"):
        client.date_range(0, None, None, today=TODAY)


def test_parse_dims():
    assert client.parse_dims("query, page") == ["query", "page"]
    assert client.parse_dims("") == []


def test_parse_dims_rejects_unknown():
    with pytest.raises(GscError, match="bogus"):
        client.parse_dims("query,bogus")


def test_parse_filter_keeps_spaces_in_expression():
    assert client.parse_filter("page contains /blog/my post") == {
        "dimension": "page",
        "operator": "contains",
        "expression": "/blog/my post",
    }


def test_parse_filter_operator_is_case_insensitive():
    assert client.parse_filter("query includingregex ^foo")["operator"] == "includingRegex"


@pytest.mark.parametrize(
    "bad", ["page contains", "nope contains x", "page like x", ""]
)
def test_parse_filter_rejects_invalid(bad):
    with pytest.raises(GscError, match="filter"):
        client.parse_filter(bad)


def test_validate_search_type():
    assert client.validate_search_type("image") == "image"
    with pytest.raises(GscError, match="web"):
        client.validate_search_type("tv")


def test_build_query_body_without_filters():
    body = client.build_query_body(
        ["query"], "2026-09-01", "2026-09-28", [], "web", 0, 100
    )
    assert body == {
        "startDate": "2026-09-01",
        "endDate": "2026-09-28",
        "dimensions": ["query"],
        "searchType": "web",
        "rowLimit": 100,
        "startRow": 0,
    }


def test_build_query_body_with_filters():
    f = {"dimension": "page", "operator": "contains", "expression": "/blog"}
    body = client.build_query_body(
        ["page"], "2026-09-01", "2026-09-28", [f], "web", 25000, 100
    )
    assert body["dimensionFilterGroups"] == [{"groupType": "and", "filters": [f]}]
    assert body["startRow"] == 25000
