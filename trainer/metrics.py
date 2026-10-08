"""Load metrics (DESIGN §4.3, C-M1…C-M5)."""
from __future__ import annotations

import datetime as dt
import math

STRENGTH_TSS_PER_MIN = 0.6  # C-M3


def np_from_series(power: list[float], hz: float = 1.0) -> float | None:
    """Normalized Power from a (≈1 Hz) power series: 30 s rolling mean → ^4 → mean → ^(1/4)."""
    p = [x if x is not None else 0.0 for x in power]
    win = max(1, int(round(30 * hz)))
    if len(p) < win:
        return None
    s = sum(p[:win])
    rolled = [s / win]
    for i in range(win, len(p)):
        s += p[i] - p[i - win]
        rolled.append(s / win)
    return (sum(r ** 4 for r in rolled) / len(rolled)) ** 0.25


def np_from_laps(laps: list[dict]) -> float | None:
    """C-M5 approximation: 4th-power duration-weighted mean of lap powers."""
    tot = sum(l["duration_s"] for l in laps if l.get("avg_power") and l.get("duration_s"))
    if not tot:
        return None
    return (sum(l["duration_s"] * l["avg_power"] ** 4 for l in laps
                if l.get("avg_power") and l.get("duration_s")) / tot) ** 0.25


def bike_tss(duration_s: float, np_w: float, ftp: float) -> tuple[float, float]:
    if_ = np_w / ftp
    return round(duration_s / 3600 * if_ ** 2 * 100, 1), round(if_, 3)


def hr_tss(duration_s: float, avg_hr: float, lthr: float) -> float:
    return round(duration_s / 3600 * (avg_hr / lthr) ** 2 * 100, 1)


def strength_tss(duration_s: float) -> float:
    return round(duration_s / 60 * STRENGTH_TSS_PER_MIN, 1)


def decoupling_pct(laps: list[dict]) -> float | None:
    """Pa:Hr decoupling: (eff_first_half − eff_second_half)/eff_first_half, eff = power/HR.

    Uses laps (needs ≥4 with power+HR); returns % (positive = HR drifted up).
    """
    ls = [l for l in laps if l.get("avg_power") and l.get("avg_hr") and l.get("duration_s")]
    if len(ls) < 4:
        return None
    total = sum(l["duration_s"] for l in ls)
    acc, first, second = 0.0, [], []
    for l in ls:
        (first if acc + l["duration_s"] / 2 <= total / 2 else second).append(l)
        acc += l["duration_s"]
    if not first or not second:
        return None

    def eff(group):
        d = sum(l["duration_s"] for l in group)
        return sum(l["avg_power"] * l["duration_s"] for l in group) / d / (
            sum(l["avg_hr"] * l["duration_s"] for l in group) / d)

    e1, e2 = eff(first), eff(second)
    return round((e1 - e2) / e1 * 100, 1)


def pmc(daily_load: dict[dt.date, float], start: dt.date, end: dt.date,
        ctl_days: int = 42, atl_days: int = 7) -> list[dict]:
    """Performance-management chart: CTL/ATL/TSB per day (C-M4)."""
    ctl = atl = 0.0
    kc, ka = 1 - math.exp(-1 / ctl_days), 1 - math.exp(-1 / atl_days)
    out = []
    d = start
    while d <= end:
        load = daily_load.get(d, 0.0)
        tsb = ctl - atl  # form going into the day
        ctl += (load - ctl) * kc
        atl += (load - atl) * ka
        out.append({"date": d.isoformat(), "load": round(load, 1), "ctl": round(ctl, 1),
                    "atl": round(atl, 1), "tsb": round(tsb, 1)})
        d += dt.timedelta(days=1)
    return out
