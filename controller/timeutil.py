"""Simulated-time helpers. Minute 0 == D0 00:00 == 2027-01-04T00:00 IST."""
from __future__ import annotations

import datetime as dt

MIN_PER_DAY = 1440
_D0 = dt.date(2027, 1, 4).toordinal()


def ts_to_minute(ts: str) -> int:
    """'2027-01-05T10:15:00+05:30' -> 2055. String slicing: this runs once per event."""
    d = dt.date(int(ts[0:4]), int(ts[5:7]), int(ts[8:10])).toordinal() - _D0
    return d * MIN_PER_DAY + int(ts[11:13]) * 60 + int(ts[14:16])


class FastTs:
    """Caches the date part so the hot ingest loop does ~3 int() calls per event."""

    def __init__(self):
        self._date, self._base = None, 0

    def __call__(self, ts: str) -> int:
        d = ts[0:10]
        if d != self._date:
            self._date = d
            self._base = (dt.date(int(d[0:4]), int(d[5:7]), int(d[8:10])).toordinal() - _D0) * MIN_PER_DAY
        return self._base + int(ts[11:13]) * 60 + int(ts[14:16])


def day_of(minute: int) -> int:
    return minute // MIN_PER_DAY


def hour_of(minute: int) -> int:
    return (minute % MIN_PER_DAY) // 60


def minute_to_label(minute: int) -> str:
    d, m = divmod(minute, MIN_PER_DAY)
    return f"D{d} {m // 60:02d}:{m % 60:02d}"


def label_to_minute(label: str) -> int:
    day, hm = label.strip().split()
    h, m = hm.split(":")
    return int(day.lstrip("Dd")) * MIN_PER_DAY + int(h) * 60 + int(m)


def next_working(t: int, hours: list[int]) -> int:
    """Same rule the simulated approver uses to schedule its decision."""
    lo, hi = hours
    day, mod = divmod(t, MIN_PER_DAY)
    if mod < lo * 60:
        return day * MIN_PER_DAY + lo * 60
    if mod >= hi * 60:
        return (day + 1) * MIN_PER_DAY + lo * 60
    return t
