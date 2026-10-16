"""`python -m trainer brief` — the only thing read at session start besides CLAUDE.md (DESIGN D-019).

Prints Markdown in `profile.language`, writes no files (always fresh) and never refuses: on a missing or
example profile it leads with an onboarding banner and builds the sections it can.
"""
from __future__ import annotations

import datetime as dt
import re

from . import analysis, coachlog
from .config import Paths, profile_state, read_json
from .i18n import ADJ, STATUS, lang_of, tr
from .normalize import load
from .weeks import parse_date, week_of

LIMIT = 4000
STALE_DAYS = 3
DASH = "–"


def _g(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict) or d.get(k) is None:
            return default
        d = d[k]
    return d


def _cut(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _rng(r):
    return f"{r[0]}–{r[1] if r[1] is not None else '∞'}" if isinstance(r, list) and len(r) == 2 else DASH


def _plan_for(paths: Paths, week: str) -> dict | None:
    files = sorted(p for p in paths.plans.glob("*.json") if p.stem <= week)
    return read_json(files[-1]) if files else None


def _open_questions(paths: Paths) -> list[str]:
    f = paths.root / "docs" / "DESIGN.md"
    if not f.exists():
        return []
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^## 6\. Open questions\s*$(.*?)(?=^## )", text, re.M | re.S)
    out = []
    for line in (m.group(1) if m else "").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and re.match(r"^[A-Z]+-\d+$", cells[0]) and "~~" not in cells[1]:
            out.append(f"{cells[0]} {_cut(cells[1], 90)}")
    return out


def _sections(paths: Paths, week: str, today: dt.date, log_chars: int, title_chars: int) -> str:
    state = profile_state(paths)
    prof = read_json(paths.profile) if state != "missing" else {}
    lang = lang_of(prof)

    def T(key, **kw):
        return tr(lang, key, **kw)

    acts, well = load(paths)
    L = []
    if state != "ok":
        L += [T("b_banner"), ""]
    L += [f"# {T('b_title')} {week}", ""]

    # 1. state + freshness
    L += [f"## {T('b_h_state')}", f"- {T('b_state', state=state, lg=lang, asof=_g(prof, 'as_of', default=DASH))}"]
    la = max((a["date"] for a in acts), default=None)
    lw = max((w["date"] for w in well), default=None)
    ages = {k: (today - parse_date(v)).days if v else None for k, v in (("a", la), ("w", lw))}
    L.append(f"- {T('b_fresh', act=la or DASH, a=ages['a'] if la else DASH, well=lw or DASH, w=ages['w'] if lw else DASH)}")
    known = [v for v in ages.values() if v is not None]
    if not known or min(known) > STALE_DAYS:
        L.append(f"- {T('b_sync', d=min(known) if known else DASH)}")

    # 2. anchors
    L += ["", f"## {T('b_h_anchors')}"]
    hist = _g(prof, "bike", "ftp_history", default=[])
    ftp = _g(prof, "bike", "ftp_w")
    fdate = next((h.get("date") for h in reversed(hist) if h.get("ftp_w") == ftp), None)
    L.append(f"- {T('b_ftp', ftp=ftp or DASH, date=fdate or DASH)}")
    zones = _g(prof, "bike", "zones_w", default={})
    L.append(f"- {T('b_zones')}: " + (" · ".join(f"{k} {_rng(v)}" for k, v in zones.items()) or DASH))
    run = _g(prof, "run", default={})
    L.append(f"- {T('b_run', cap=run.get('easy_hr_cap_bpm', DASH), pace=_rng(run.get('easy_pace_min_km')), lthr=run.get('lthr_is_calibrated', DASH), maxhr=_g(prof, 'bike', 'max_hr_observed_bpm', default=DASH))}")
    L.append(f"- {T('b_injury', status=_g(prof, 'injury', 'current_status', default=DASH), limiter=_cut(_g(prof, 'injury', 'primary_limiter', default=DASH), 90))}")
    b = _g(prof, "budget", default={})
    rng = b.get("normal_range_hours") or [DASH, DASH]
    L.append(f"- {T('b_budget', lo=rng[0], hi=rng[1], n=b.get('strength_sessions_per_week', DASH))}")

    # 3. goals
    L += ["", f"## {T('b_h_goals')}"]
    goals = sorted((g for g in (read_json(paths.goals)["goals"] if paths.goals.exists() else []) if g.get("status") == "active"),
                   key=lambda g: g.get("priority", 99))
    for g in goals:
        dl = g.get("deadline")
        days = (parse_date(dl) - today).days if dl else DASH
        L.append(f"- P{g.get('priority', '?')} {_cut(g.get('title', ''), 70)} — {dl or DASH} ({days} {T('days')})")
    if not goals:
        L.append(f"- {DASH}")

    # 4. current plan
    L += ["", f"## {T('b_h_plan')}"]
    plan = _plan_for(paths, week)
    if not plan:
        L.append(f"- {T('b_no_plan')}")
    else:
        L.append(T("b_plan_head", week=plan["week"], rev=plan.get("revision", DASH), status=plan.get("status", DASH),
                   adj=ADJ[lang].get(plan.get("adjustment_type"), plan.get("adjustment_type") or DASH),
                   focus=_cut(plan.get("focus", ""), 160)))
        L += ["", T("b_plan_cols"), "|---|---|---|---|---|---:|"]
        for s in plan.get("sessions", []):
            if s.get("sport") == "rest":
                continue
            st = s.get("status") or "planned"
            L.append(f"| {s.get('id', DASH)} | {s.get('date', DASH)[5:]} | {_cut(s.get('title', ''), title_chars)} | "
                     f"{s.get('priority', DASH)} | {STATUS[lang].get(st, st) if st != 'planned' else 'planned'} | {s.get('duration_min', DASH)} |")
        pr = plan.get("placement_rules") or []
        if pr:
            L.append(f"- {T('b_placement')}: " + " · ".join(_cut(r, 70) for r in pr))
        rh = (plan.get("revision_history") or [None])[-1]
        if rh:
            L.append(f"- {T('b_lastrev')}: r{rh.get('revision')} {rh.get('date')} — {_cut(rh.get('reason', ''), 140)}")

    # 5. recovery
    w = analysis.wellness_summary(well, today, prof)
    base = w["baseline"]
    L += ["", f"## {T('b_h_recovery')}",
          f"- HRV {w['hrv_avg_3d'] or DASH} / 14d {w['hrv_avg_14d'] or DASH} ms ({T('baseline')} {base.get('hrv_ms', DASH)})",
          f"- {T('rhr')} {w['rhr_avg_3d'] or DASH} / 14d {w['rhr_avg_14d'] or DASH} ({T('baseline')} {base.get('rhr_bpm', DASH)})",
          f"- {T('sleep')} {w['sleep_avg_3d_h'] or DASH} / 14d {w['sleep_avg_14d_h'] or DASH} h"]

    # 6. check-in
    L += ["", f"## {T('b_h_checkin')}"]
    cf = paths.checkins / f"{week}.json"
    if cf.exists():
        ci = read_json(cf)
        knee = ci.get("knee") or []
        last = (knee[-1].get("status") if knee else None) or DASH
        n_rpe = sum(1 for s in ci.get("sessions", []) if s.get("rpe") is not None)
        L.append(f"- {T('b_checkin_present', week=week, st=last, n=n_rpe)}")
    else:
        L.append(f"- {T('b_checkin_missing', week=week)}")

    # 7. coach log
    L += ["", f"## {T('b_h_log')}"]
    entries = coachlog.read_entries(paths.log)[:3]
    for e in entries:
        body = e["text"].strip()
        body = "###" + body[2:] if body.startswith("## ") else body  # nest under the section heading
        L.append(body if len(body) <= log_chars else body[:log_chars].rstrip() + " " + T("b_log_more"))
        L.append("")
    if not entries:
        L += [f"- {DASH}", ""]

    # 8. open questions + 9. next step
    L += [f"## {T('b_h_oq')}"]
    oq = _open_questions(paths)
    L += [f"- {q}" for q in oq] or [f"- {T('none')}"]
    L += ["", f"## {T('b_h_next')}", T("b_next")]
    return "\n".join(L) + "\n"


def build(paths: Paths, week: str | None = None, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    week = week or week_of(today)
    # Hard limit: shrink log entries first, then session titles, then cut (D-019).
    for log_chars, title_chars in ((600, 40), (400, 40), (250, 40), (120, 40), (120, 25), (60, 15)):
        out = _sections(paths, week, today, log_chars, title_chars)
        if len(out) <= LIMIT:
            return out
    return out[:LIMIT - 1].rstrip() + "…\n"
