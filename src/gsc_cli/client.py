from datetime import date, datetime, timedelta

from gsc_cli.errors import GscError

DATA_LAG_DAYS = 3
ROW_LIMIT = 25000
VALID_DIMS = ("query", "page", "country", "device", "date")
VALID_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
OPERATORS = ("equals", "contains", "notContains", "includingRegex", "excludingRegex")


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise GscError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from None


def date_range(
    days: int, start: str | None, end: str | None, today: date | None = None
) -> tuple[str, str]:
    if start or end:
        if not (start and end):
            raise GscError("Provide both --start and --end, or use --days.")
        start_d, end_d = _parse_date(start), _parse_date(end)
        if start_d > end_d:
            raise GscError("--start must be on or before --end.")
        return start_d.isoformat(), end_d.isoformat()
    if days < 1:
        raise GscError("--days must be at least 1.")
    today = today or date.today()
    end_d = today - timedelta(days=DATA_LAG_DAYS)
    start_d = end_d - timedelta(days=days - 1)
    return start_d.isoformat(), end_d.isoformat()


def parse_dims(text: str) -> list[str]:
    dims = [d.strip() for d in text.split(",") if d.strip()]
    for d in dims:
        if d not in VALID_DIMS:
            raise GscError(
                f"Unknown dimension '{d}'. Valid dimensions: {', '.join(VALID_DIMS)}."
            )
    return dims


def parse_filter(text: str) -> dict:
    parts = text.strip().split(None, 2)
    usage = (
        "Invalid filter. Use \"<dimension> <operator> <expression>\", e.g. "
        f"\"page contains /blog\". Operators: {', '.join(OPERATORS)}."
    )
    if len(parts) != 3:
        raise GscError(usage)
    dimension, operator, expression = parts
    if dimension not in VALID_DIMS:
        raise GscError(f"{usage} Unknown dimension '{dimension}'.")
    ops = {o.lower(): o for o in OPERATORS}
    if operator.lower() not in ops:
        raise GscError(f"{usage} Unknown operator '{operator}'.")
    return {
        "dimension": dimension,
        "operator": ops[operator.lower()],
        "expression": expression,
    }


def validate_search_type(value: str) -> str:
    if value not in VALID_TYPES:
        raise GscError(
            f"Unknown search type '{value}'. Valid types: {', '.join(VALID_TYPES)}."
        )
    return value


def build_query_body(
    dims: list[str],
    start: str,
    end: str,
    filters: list[dict],
    search_type: str,
    start_row: int,
    row_limit: int,
) -> dict:
    body = {
        "startDate": start,
        "endDate": end,
        "dimensions": dims,
        "searchType": search_type,
        "rowLimit": row_limit,
        "startRow": start_row,
    }
    if filters:
        body["dimensionFilterGroups"] = [{"groupType": "and", "filters": filters}]
    return body
