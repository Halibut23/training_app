"""Builds the analysis bundle the agent reads before planning week W (CLAUDE.md D3)."""
from __future__ import annotations

import datetime as dt

from .i18n import lang_of, tr
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
        "language": lang_of(profile),
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
    lang = ctx.get("language", "sv")

    def T(key, **kw):
        return tr(lang, key, **kw)

    L = [f"# {T('ctx_title')} {ctx['plan_week']} ({ctx['plan_dates'][0]} – {ctx['plan_dates'][1]})",
         T("generated", ts=ctx["generated"], week=ctx["review_week"]), ""]
    L += [f"## {T('flags')}"]
    L += [f"- **{f['level'].upper()}** `{f['rule']}` {f['msg']}" for f in ctx["flags"]] or [f"- {T('none')}"]
    L += ["", f"## {T('goals')}"]
    L += [f"- P{g['priority']} {g['title']} — deadline {_fmt(g['deadline'])} ({_fmt(g['days_left'])} {T('days')})" for g in ctx["goals"]]
    p = ctx["profile"]
    L += ["", f"## {T('profile')}", f"- FTP {p['ftp_w']} W · {T('limiter_status')}: {p['injury_status']} · {T('run_now')}: {p['run']['current_structure']}",
          f"- {T('lthr_calibrated')}: {p['run']['lthr_is_calibrated']}"]
    L += ["", f"## {T('weekly_load')}", T("load_head"), "|---|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {r['week']} | {r['hours']} | {r['bike_h']} | {r['run_km']} | {r['strength_n']} | {r['tss']:g} | {r['hard_n']} |" for r in ctx["weekly_load"]]
    if ctx["pmc_last"]:
        m = ctx["pmc_last"]
        L += ["", f"CTL {m['ctl']} · ATL {m['atl']} · TSB {m['tsb']} ({T('pmc_note', d=ctx['pmc_history_days'])})"]
    w = ctx["wellness"]
    L += ["", f"## {T('recovery')}", f"- HRV 3d/14d: {_fmt(w['hrv_avg_3d'])}/{_fmt(w['hrv_avg_14d'])} ms ({T('baseline')} {w['baseline'].get('hrv_ms')})",
          f"- {T('rhr')} 3d/14d: {_fmt(w['rhr_avg_3d'])}/{_fmt(w['rhr_avg_14d'])} ({T('baseline')} {w['baseline'].get('rhr_bpm')})",
          f"- {T('sleep')} 3d/14d: {_fmt(w['sleep_avg_3d_h'])}/{_fmt(w['sleep_avg_14d_h'])} h"]
    L += ["", f"## {T('plan_vs_done')}"]
    if ctx["compliance"]:
        L += [T("compl_head"), "|---|---|---|---|---:|---|"]
        moved = f" ({T('moved')})"
        for c in ctx["compliance"]:
            L.append(f"| {c['date']} | {c.get('planned', '–')} | {c.get('planned_type', '–')} → {c.get('actual_type', '–')} | "
                     f"{_fmt(c.get('planned_min'))} → {_fmt(c.get('actual_min'))} | {_fmt(c.get('actual_tss'))} | {c['status']}{moved if c.get('moved') else ''} |")
    else:
        L.append(f"- {T('no_prev_plan')}")
    L += ["", f"## {T('recent_sessions')}"]
    for s in ctx["sessions"]:
        a = s["session"]
        L.append(f"- **{a.get('date')} {a.get('type')}** “{a.get('name') or ''}” — "
                 + ", ".join(f"{k} {_fmt(a[k], k)}" for k in ("min", "km", "np", "if", "tss", "avg_hr", "pace", "work_w", "work_hr", "work_fade_pct", "decoupling_pct", "rpe") if k in a))
        if s.get("reference"):
            r = s["reference"]
            L.append(f"  - ref {r.get('date') or r.get('id')}: " + ", ".join(f"Δ{k} {v:+g}" for k, v in s["delta"].items())
                     + (f" — {r['summary']}" if r.get("summary") else ""))
    ci = ctx["checkin"]
    L += ["", "## Check-in", "```json", __import__("json").dumps(ci, ensure_ascii=False, indent=1) if ci else T("missing"), "```"]
    return "\n".join(L) + "\n"


def run(paths: Paths, week: str, today: dt.date | None = None) -> tuple[dict, str]:
    ctx = build(paths, week, today)
    md = to_markdown(ctx)
    write_json(paths.context / f"{week}.json", ctx)
    (paths.context / f"{week}.md").write_text(md, encoding="utf-8")
    return ctx, md
