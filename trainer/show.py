"""Read-only views of normalised data for the agent (DESIGN D-024).

`trainer activity` prints one or more activities with laps and work intervals; `trainer wellness` prints
daily morning values. Both read `data/derived/` through `normalize.load`, so the agent never has to open
`data/derived/*.jsonl` or `data/raw/**` itself (CLAUDE.md C1). They print only and write no files.
"""
from __future__ import annotations

import datetime as dt

from .analysis import compact
from .i18n import lang_of, tr
from .weeks import parse_date

DASH = "–"


def _f(v, nd=0):
    if v is None:
        return DASH
    if isinstance(v, float):
        return f"{v:.{nd}f}" if nd else f"{round(v)}"
    return str(v)


def _pace(speed_ms):
    if not speed_ms:
        return DASH
    p = 1000 / speed_ms / 60
    m, s = int(p), round((p % 1) * 60)
    if s == 60:
        m, s = m + 1, 0
    return f"{m}:{s:02d}"


def select_activities(acts: list[dict], date: str | None = None, aid: str | None = None,
                      session_type: str | None = None) -> list[dict]:
    """By id, else by date (default: the latest date with an activity); optional session-type filter."""
    if aid:
        key = aid if ":" in aid else None
        return [a for a in acts if a["id"] == aid or (key is None and a["id"].split(":", 1)[-1] == aid)]
    pool = [a for a in acts if not session_type or a.get("session_type") == session_type]
    if not pool:
        return []
    day = date or max(a["date"] for a in pool)
    return [a for a in pool if a["date"] == day]


def rep_summary(a: dict) -> dict | None:
    """Per-rep drift for interval sessions: first vs last work interval (power and HR)."""
    wi = a.get("work_intervals") or []
    if len(wi) < 2:
        return None
    f, l = wi[0], wi[-1]
    out = {"n": len(wi), "power_first_w": f["avg_power"], "power_last_w": l["avg_power"],
           "fade_pct": round((l["avg_power"] - f["avg_power"]) / f["avg_power"] * 100, 1)}
    if f.get("avg_hr") and l.get("avg_hr"):
        out.update(hr_first=f["avg_hr"], hr_last=l["avg_hr"], hr_drift_bpm=round(l["avg_hr"] - f["avg_hr"]))
    return out


def activity_markdown(a: dict, lang: str, ftp: float | None = None) -> str:
    T = lambda k, **kw: tr(lang, k, **kw)  # noqa: E731
    c = compact(a)
    is_run = a.get("sport") == "run"
    name = f" “{a['name']}”" if a.get("name") else ""
    L = [f"## {a['date']} {a.get('session_type') or a.get('sport')}{name} ({a['id']})"]
    facts = [f"{c.get('min', DASH)} min"]
    for k, lab in (("km", "km"), ("np", "NP"), ("avg_w", T("sh_avg_w")), ("if", "IF"), ("tss", "TSS"),
                   ("avg_hr", T("sh_avg_hr")), ("max_hr", T("sh_max_hr"))):
        if c.get(k) is not None and not (k == "km" and a.get("environment") == "indoor" and not is_run):
            facts.append(f"{lab} {_f(c[k], 2) if k == 'if' else _f(c[k], 1) if k in ('km', 'tss') else _f(c[k])}")
    if is_run and a.get("pace_min_km"):
        facts.append(f"{T('sh_pace')} {_pace(1000 / (a['pace_min_km'] * 60))}/km")
    if a.get("decoupling_pct") is not None:
        facts.append(f"decoupling {a['decoupling_pct']} %")
    facts.append(f"{T('sh_sensor')} {a.get('hr_sensor') or T('sh_unknown')}")
    if a.get("rpe") is not None:
        facts.append(f"RPE {a['rpe']}")
    L.append("- " + " · ".join(facts))
    laps = a.get("laps") or []
    if laps:
        L += ["", f"### {T('sh_laps')}"]
        if is_run:
            L += [T("sh_laps_run_cols"), "|---:|---:|---:|---:|---:|---:|"]
            for l in laps:
                L.append(f"| {l.get('i')} | {_f((l.get('duration_s') or 0) / 60, 1)} | {_f((l.get('distance_m') or 0) / 1000, 2)} | "
                         f"{_pace(l.get('avg_speed_ms'))} | {_f(l.get('avg_hr'))} | {_f(l.get('max_hr'))} |")
        else:
            L += [T("sh_laps_bike_cols"), "|---:|---:|---:|---:|---:|---:|"]
            for l in laps:
                L.append(f"| {l.get('i')} | {_f((l.get('duration_s') or 0) / 60, 1)} | {_f(l.get('avg_power'))} | "
                         f"{_f(l.get('np'))} | {_f(l.get('avg_hr'))} | {_f(l.get('max_hr'))} |")
    wi = a.get("work_intervals") or []
    if wi:
        L += ["", f"### {T('sh_work')}", T("sh_work_cols"), "|---:|---:|---:|---:|---:|---:|"]
        for n, w in enumerate(wi, 1):
            L.append(f"| {n} ({T('sh_lap')} {w.get('i')}) | {_f(w['duration_s'] / 60, 1)} | {w['avg_power']} | "
                     f"{round(w['pct_ftp'] * 100)} | {_f(w.get('avg_hr'))} | {_f(w.get('max_hr'))} |")
        rs = rep_summary(a)
        if rs:
            s = T("sh_reps", n=rs["n"], p1=rs["power_first_w"], p2=rs["power_last_w"], fade=f"{rs['fade_pct']:+g}")
            if "hr_drift_bpm" in rs:
                s += " · " + T("sh_drift", h1=_f(rs["hr_first"]), h2=_f(rs["hr_last"]), d=f"{rs['hr_drift_bpm']:+d}")
            L.append(f"- {s}")
    if a.get("notes"):
        L += ["", f"- {T('sh_notes')}: {a['notes']}"]
    return "\n".join(L) + "\n"


def daily_wellness(well: list[dict], end: dt.date, days: int) -> list[dict]:
    start = end - dt.timedelta(days=days - 1)
    return [w for w in sorted(well, key=lambda w: w["date"]) if start <= parse_date(w["date"]) <= end]


def flag_marks(row: dict, base: dict) -> dict:
    """'↓' HRV below baseline low, '↑' resting HR above baseline high (display only, R-REC-01)."""
    hrv_b, rhr_b = base.get("hrv_ms") or [None, None], base.get("rhr_bpm") or [None, None]
    hrv, rhr = row.get("hrv_last_night_ms"), row.get("rhr_bpm")
    return {"hrv": " ↓" if hrv is not None and hrv_b[0] is not None and hrv < hrv_b[0] else "",
            "rhr": " ↑" if rhr is not None and rhr_b[1] is not None and rhr > rhr_b[1] else ""}


def wellness_markdown(rows: list[dict], profile: dict) -> str:
    lang = lang_of(profile)
    T = lambda k, **kw: tr(lang, k, **kw)  # noqa: E731
    base = profile.get("recovery_baseline", {})
    L = [f"## {T('sh_well_title')}", f"- {T('baseline')}: HRV {base.get('hrv_ms', DASH)} ms · {T('rhr')} {base.get('rhr_bpm', DASH)} bpm · {T('sh_marks')}",
         "", T("sh_well_cols"), "|---|---:|---:|---|---:|---:|---:|"]
    for r in rows:
        m = flag_marks(r, base)
        L.append(f"| {r['date']} | {_f(r.get('hrv_last_night_ms'))}{m['hrv']} | {_f(r.get('hrv_weekly_avg_ms'))} | "
                 f"{r.get('hrv_status') or DASH} | {_f(r.get('rhr_bpm'))}{m['rhr']} | {_f(r.get('sleep_h'), 1)} | {_f(r.get('sleep_score'))} |")
    if not rows:
        L.append(f"| {DASH} | | | | | | |")
    return "\n".join(L) + "\n"


def wellness_inline(rows: list[dict], profile: dict) -> str:
    """Compact one-liner for `brief`: 'MM-DD HRV 84↓ · vp 41↑ · 7.1 h; …'."""
    lang = lang_of(profile)
    base = profile.get("recovery_baseline", {})
    parts = []
    for r in rows:
        m = flag_marks(r, base)
        parts.append(f"{r['date'][5:]} HRV {_f(r.get('hrv_last_night_ms'))}{m['hrv'].strip()} · "
                     f"{tr(lang, 'sh_rhr_short')} {_f(r.get('rhr_bpm'))}{m['rhr'].strip()} · {_f(r.get('sleep_h'), 1)} h")
    return "; ".join(parts) or DASH
