"""ISO-week helpers. Weeks are 'YYYY-Www', Monday–Sunday."""
from __future__ import annotations

import datetime as dt
import re

_RX = re.compile(r"^(\d{4})-W(\d{2})$")


def week_of(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_bounds(week: str) -> tuple[dt.date, dt.date]:
    m = _RX.match(week)
    if not m:
        raise ValueError(f"Bad week id {week!r}, expected YYYY-Www")
    start = dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return start, start + dt.timedelta(days=6)


def shift_week(week: str, n: int) -> str:
    start, _ = week_bounds(week)
    return week_of(start + dt.timedelta(weeks=n))


def next_week(today: dt.date | None = None) -> str:
    return shift_week(week_of(today or dt.date.today()), 1)


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])
