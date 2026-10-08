"""Builds the analysis bundle the agent reads before planning week W (CLAUDE.md D3)."""
from __future__ import annotations

import datetime as dt

from . import analysis
from .config import Paths, read_json, write_json
from .normalize import load
from .weeks import parse_date, shift_week, week_bounds


def _maybe(path):
    return read_json(path) if path.exists() else None


def latest_plan(paths: Paths, before_or_eq: str) -> dict | None:
    files = sorted(p for p in paths.plans.glob("*.json") if p.stem <= before_or_eq)
    return read_json(files[-1]) if files else None


def build(paths: Paths, week: str, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    profile, goals = read_json(paths.profile), read_json(paths.goals)
    acts, well = load(paths)
    review = shift_week(week, -1)
    rs, re_ = week_bounds(review)
    plan_prev = _maybe(paths.plans / f"{review}.json")
    checkin = _maybe(paths.checkins / f"{review}.json")
    weeks = [shift_week(review, -i) for i in range(7, -1, -1)]
    weekly = analysis.weekly_summary(acts, weeks)
    end = min(re_, today)
    pmc_rows = analysis.load_chart(acts, end)
    wsum = analysis.wellness_summary(well, end, profile)
    window_start = rs - dt.timedelta(days=7)
    recent = [a for a in acts if window_start <= parse_date(a["date"]) <= re_]
    sessions = []
    for a in recent:
        ref = analysis.find_reference(a, acts, profile)
        sessions.append(analysis.compare(a, ref) if ref else {"session": analysis.compact(a), "reference": None})
    goal_rows = []
    for g in goals["goals"]:
        if g.get("status") != "active":
            continue
        days = (parse_date(g["deadline"]) - today).days if g.get("deadline") else None
        goal_rows.append({"id": g["id"], "priority": g["priority"], "title": g["title"],
                          "deadline": g.get("deadline"), "days_left": days, "metric": g.get("metric")})
    goal_rows.sort(key=lambda g: g["priority"])
    ctx = {
        "generated": today.isoformat(),
        "plan_week": week,
        "plan_dates": [d.isoformat() for d in week_bounds(week)],
        "review_week": review,
        "profile": {
            "ftp_w": profile["bike"]["ftp_w"],
            "zones_w": profile["bike"]["zones_w"],
            "run": {k: profile["run"][k] for k in ("current_km_per_week", "current_structure",
                                                  "easy_pace_min_km", "easy_hr_cap_bpm", "lthr_is_calibrated")},
            "injury_status": profile["injury"]["current_status"],
            "budget": profile["budget"],
        },
        "goals": goal_rows,
        "previous_plan": plan_prev and {
            "week": plan_prev["week"], "revision": plan_prev["revision"],
            "adjustment_type": plan_prev["adjustment_type"], "focus": plan_prev["focus"],
            "targets": plan_prev["targets"]},
        "compliance": analysis.compliance(plan_prev, acts),
        "checkin": checkin,
        "weekly_load": weekly,
        "pmc_last": pmc_rows[-1] if pmc_rows else None,
        "pmc_history_days": len(pmc_rows),
        "wellness": {k: v for k, v in wsum.items() if k != "daily"},
        "sessions": sessions,
        "flags": analysis.flags(acts, weekly, checkin, wsum, pmc_rows, profile, review),
    }
    return ctx


def pace_str(p):
    return f"{int(p)}:{round((p % 1) * 60):02d}" if p else "–"


def _fmt(v, key=None):
    if key == "pace" and v is not None:
        return pace_str(v) + "/km"
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def to_markdown(ctx: dict) -> str:
    L = [f"# Kontext för planering {ctx['plan_week']} ({ctx['plan_dates'][0]} – {ctx['plan_dates'][1]})",
         f"Genererad {ctx['generated']} · granskningsvecka {ctx['review_week']}", ""]
    L += ["## Flaggor (regelbaserade)"]
    L += [f"- **{f['level'].upper()}** `{f['rule']}` {f['msg']}" for f in ctx["flags"]] or ["- Inga"]
    L += ["", "## Mål"]
    L += [f"- P{g['priority']} {g['title']} — deadline {_fmt(g['deadline'])} ({_fmt(g['days_left'])} dagar)" for g in ctx["goals"]]
    p = ctx["profile"]
    L += ["", "## Profil", f"- FTP {p['ftp_w']} W · begränsningsstatus: {p['injury_status']} · löpning nu: {p['run']['current_structure']}",
          f"- LTHR kalibrerad: {p['run']['lthr_is_calibrated']}"]
    L += ["", "## Veckobelastning (8 v)", "| Vecka | h | Cykel h | Löp km | Styrka n | TSS | Hårda |", "|---|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {r['week']} | {r['hours']} | {r['bike_h']} | {r['run_km']} | {r['strength_n']} | {r['tss']:g} | {r['hard_n']} |" for r in ctx["weekly_load"]]
    if ctx["pmc_last"]:
        m = ctx["pmc_last"]
        L += ["", f"CTL {m['ctl']} · ATL {m['atl']} · TSB {m['tsb']} (historik {ctx['pmc_history_days']} d; <42 d = osäkert)"]
    w = ctx["wellness"]
    L += ["", "## Återhämtning", f"- HRV 3d/14d: {_fmt(w['hrv_avg_3d'])}/{_fmt(w['hrv_avg_14d'])} ms (baslinje {w['baseline'].get('hrv_ms')})",
          f"- Vilopuls 3d/14d: {_fmt(w['rhr_avg_3d'])}/{_fmt(w['rhr_avg_14d'])} (baslinje {w['baseline'].get('rhr_bpm')})",
          f"- Sömn 3d/14d: {_fmt(w['sleep_avg_3d_h'])}/{_fmt(w['sleep_avg_14d_h'])} h"]
    L += ["", "## Plan vs utfört (föregående vecka)"]
    if ctx["compliance"]:
        L += ["| Datum | Planerat | Typ plan → utfört | min plan → utfört | TSS | Status |", "|---|---|---|---|---:|---|"]
        for c in ctx["compliance"]:
            L.append(f"| {c['date']} | {c.get('planned', '–')} | {c.get('planned_type', '–')} → {c.get('actual_type', '–')} | "
                     f"{_fmt(c.get('planned_min'))} → {_fmt(c.get('actual_min'))} | {_fmt(c.get('actual_tss'))} | {c['status']}{' (flyttat)' if c.get('moved') else ''} |")
    else:
        L.append("- Ingen tidigare plan.")
    L += ["", "## Pass senaste 2 veckorna med referensjämförelse"]
    for s in ctx["sessions"]:
        a = s["session"]
        L.append(f"- **{a.get('date')} {a.get('type')}** “{a.get('name') or ''}” — "
                 + ", ".join(f"{k} {_fmt(a[k], k)}" for k in ("min", "km", "np", "if", "tss", "avg_hr", "pace", "work_w", "work_hr", "work_fade_pct", "decoupling_pct", "rpe") if k in a))
        if s.get("reference"):
            r = s["reference"]
            L.append(f"  - ref {r.get('date') or r.get('id')}: " + ", ".join(f"Δ{k} {v:+g}" for k, v in s["delta"].items())
                     + (f" — {r['summary']}" if r.get("summary") else ""))
    ci = ctx["checkin"]
    L += ["", "## Check-in", "```json", __import__("json").dumps(ci, ensure_ascii=False, indent=1) if ci else "saknas", "```"]
    return "\n".join(L) + "\n"


def run(paths: Paths, week: str, today: dt.date | None = None) -> tuple[dict, str]:
    ctx = build(paths, week, today)
    md = to_markdown(ctx)
    write_json(paths.context / f"{week}.json", ctx)
    (paths.context / f"{week}.md").write_text(md, encoding="utf-8")
    return ctx, md
