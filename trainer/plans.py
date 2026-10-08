"""Plan skeleton, validation (schema + semantic), Markdown rendering (DESIGN D-007, D-009, D-010)."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .config import Paths, read_json, write_json
from .i18n import ADJ, DAYS, PRIO, STATUS, TYPE, tr
from .weeks import parse_date, week_bounds

def skeleton(week: str, today: dt.date | None = None, lang: str = "sv") -> dict:
    s, e = week_bounds(week)
    today = today or dt.date.today()
    return {
        "week": week, "start_date": s.isoformat(), "end_date": e.isoformat(), "revision": 0,
        "status": "draft", "created": today.isoformat(), "phase": "", "adjustment_type": "hold", "focus": "",
        "targets": {"hours": 0, "bike_hours": 0, "run_km": 0, "strength_sessions": 2, "est_tss": 0},
        "rationale": {"summary": "", "data_basis": [], "comparisons": [], "rules_applied": ["R-GEN-02"],
                      "assumptions": [], "open_questions": []},
        "placement_rules": [
            tr(lang, "pr_48h"),
            tr(lang, "pr_vo2"),
            tr(lang, "pr_strength"),
        ],
        "decision_rules": [],
        "sessions": [
            {"id": f"{week}-{i + 1}", "date": (s + dt.timedelta(days=i)).isoformat(), "sport": "rest",
             "session_type": "rest", "title": tr(lang, "rest_title"), "priority": "optional", "duration_min": 0, "status": "planned"}
            for i in range(7)],
        "revision_history": [{"revision": 0, "date": today.isoformat(), "reason": tr(lang, "first_version")}],
    }


def _schema_errors(plan: dict, schema_path: Path) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []  # semantic checks still run; DESIGN D-013
    schema = read_json(schema_path)
    cls = getattr(jsonschema, "Draft202012Validator", None) or getattr(jsonschema, "Draft7Validator")  # old jsonschema
    v = cls(schema)
    return [f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in v.iter_errors(plan)]


def known_rule_ids(spec_path: Path) -> set[str]:
    if not spec_path.exists():
        return set()
    return set(re.findall(r"\b(R-[A-Z]+-\d{2})\b", spec_path.read_text(encoding="utf-8")))


def validate(plan: dict, paths: Paths, profile: dict | None = None) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    errors = _schema_errors(plan, paths.schemas / "plan.schema.json")
    warnings: list[str] = []
    if errors:
        return errors, warnings
    s, e = week_bounds(plan["week"])
    if plan["start_date"] != s.isoformat() or plan["end_date"] != e.isoformat():
        errors.append(f"start/end_date do not match {plan['week']} ({s}–{e})")
    ids = [x["id"] for x in plan["sessions"]]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate session ids")
    for x in plan["sessions"]:
        if not (s <= parse_date(x["date"]) <= e):
            errors.append(f"{x['id']}: date {x['date']} outside the week")
        if x["sport"] == "run" and "run" not in x["session_type"]:
            errors.append(f"{x['id']}: sport run but type {x['session_type']}")
        if x["sport"] == "bike" and "bike" not in x["session_type"]:
            errors.append(f"{x['id']}: sport bike but type {x['session_type']}")
    if plan["revision_history"][-1]["revision"] != plan["revision"]:
        errors.append("revision does not match the last revision_history entry")
    known = known_rule_ids(paths.root / "docs" / "COACHING_SPEC.md")
    unknown = [r for r in plan["rationale"]["rules_applied"] if known and r not in known]
    if unknown:
        errors.append(f"Unknown rule IDs: {unknown}")
    # soft checks
    hours = sum(x["duration_min"] for x in plan["sessions"]) / 60
    if abs(hours - plan["targets"]["hours"]) > 0.25:
        warnings.append(f"Session total {hours:.2f} h ≠ targets.hours {plan['targets']['hours']}")
    run_km = sum(x.get("distance_km") or 0 for x in plan["sessions"] if x["sport"] == "run")
    if "run_km" in plan["targets"] and abs(run_km - plan["targets"]["run_km"]) > 0.5:
        warnings.append(f"Run km total {run_km} ≠ targets.run_km {plan['targets']['run_km']}")
    n_str = sum(1 for x in plan["sessions"] if x["sport"] == "strength")
    if n_str < 2:
        warnings.append(f"{n_str} strength sessions (R-STR-01: 2)")
    hard = sorted(parse_date(x.get("completed_date") or x["date"]) for x in plan["sessions"]
                  if x["session_type"] in ("bike_threshold", "bike_vo2", "bike_test", "run_quality"))
    for a, b in zip(hard, hard[1:]):
        if (b - a).days <= 1:
            warnings.append(f"Quality sessions {a} and {b} on consecutive days (R-GEN-07)")
    if profile:
        lo, hi = profile["budget"]["normal_range_hours"]
        if hours > hi + 1:
            warnings.append(f"{hours:.1f} h > budget {hi} h (R-BUD-01)")
    return errors, warnings


def _target(t: dict | None, lang: str = "sv") -> str:
    if not t:
        return ""
    parts = []
    if t.get("power_w"):
        lo, hi = t["power_w"]
        parts.append(f"{lo:g}–{hi:g} W" if hi else f"{lo:g}+ W")
    if t.get("pace_min_km"):
        lo, hi = t["pace_min_km"]
        f = lambda p: f"{int(p)}:{round((p % 1) * 60):02d}"
        parts.append(f"{f(lo)}–{f(hi)}/km")
    if t.get("hr_max_bpm"):
        parts.append(f"{tr(lang, 'hr')} ≤{t['hr_max_bpm']:g}")
    if t.get("rpe"):
        parts.append(f"RPE {t['rpe'][0]:g}–{t['rpe'][1]:g}")
    if t.get("cadence_rpm"):
        parts.append(f"{t['cadence_rpm'][0]:g}–{t['cadence_rpm'][1]:g} rpm")
    return ", ".join(parts)


def _step(st: dict, lang: str = "sv") -> str:
    q = []
    if st.get("reps"):
        q.append(f"{st['reps']} ×" if (st.get("duration_min") or st.get("distance_km")) else f"{st['reps']} set")
    if st.get("duration_min"):
        q.append(f"{st['duration_min']:g} min")
    if st.get("distance_km"):
        q.append(f"{st['distance_km']:g} km")
    s = f"{st['label']}: {' '.join(q)}".strip()
    tg = _target(st.get("target"), lang)
    if tg:
        s += f" @ {tg}"
    if st.get("recovery_min"):
        s += f" ({tr(lang, 'rest_between')} {st['recovery_min']:g} min)"
    return s


def render(plan: dict, lang: str = "sv") -> str:
    """Plan → Markdown in the athlete's language (D-018)."""
    t = plan["targets"]
    days = DAYS[lang]
    early = [x for x in plan["sessions"] if x.get("completed_date", plan["start_date"]) < plan["start_date"]]
    L = [f"# {tr(lang, 'plan_title')} {plan['week']} ({plan['start_date']} – {plan['end_date']})",
         f"Revision {plan['revision']} · status {plan['status']} · {tr(lang, 'phase')}: {plan['phase']} · "
         f"{tr(lang, 'adjustment')}: **{ADJ[lang][plan['adjustment_type']]}**", "",
         f"**{tr(lang, 'focus')}:** {plan['focus']}", "",
         f"**{tr(lang, 'week_targets')}:** {t['hours']:g} h"
         + (f" · {tr(lang, 'bike')} {t['bike_hours']:g} h" if t.get("bike_hours") is not None else "")
         + (f" · {tr(lang, 'running')} {t['run_km']:g} km" if t.get("run_km") is not None else "")
         + (f" · {tr(lang, 'strength_n', n=t['strength_sessions'])}" if t.get("strength_sessions") is not None else "")
         + (f" · ~{t['est_tss']:g} TSS" if t.get("est_tss") else "")
         + (f" _({tr(lang, 'done_before', min=format(sum(x['duration_min'] for x in early), 'g'))})_" if early else ""), "",
         tr(lang, "days_note"), "",
         tr(lang, "table_head"), "|---|---|---|---:|---|"]
    for x in sorted(plan["sessions"], key=lambda x: x.get("completed_date") or x["date"]):
        d = parse_date(x.get("completed_date") or x["date"])
        content = "<br>".join(_step(s, lang) for s in x.get("structure", [])) or (x.get("instructions") or "")
        mark = ""
        if x["status"] != "planned":
            mark = f" ({STATUS[lang].get(x['status'], x['status'])}"
            if x.get("completed_date"):
                cd = parse_date(x["completed_date"])
                mark += f" {days[cd.weekday()].lower()} {cd.day}/{cd.month}"
            mark += ")"
        L.append(f"| {days[d.weekday()]} {d.day}/{d.month} | **{x['title']}**{mark}<br>_{TYPE[lang][x['session_type']]}_ | "
                 f"{PRIO[lang][x['priority']]} | {x['duration_min']:g} min | {content} |")
    L += ["", f"## {tr(lang, 'session_details')}"]
    for x in sorted(plan["sessions"], key=lambda x: x["date"]):
        if x["sport"] == "rest":
            continue
        L.append(f"### {x['title']} ({x['date']})")
        for key, label in (("purpose", "purpose"), ("instructions", "instruction"), ("fallback", "plan_b")):
            if x.get(key):
                L.append(f"- **{tr(lang, label)}:** {x[key]}")
        if x.get("est_tss"):
            L.append(f"- {tr(lang, 'est_tss')}: {x['est_tss']:g}")
        L.append("")
    if plan.get("placement_rules"):
        L += [f"## {tr(lang, 'placement_rules')}"] + [f"- {r}" for r in plan["placement_rules"]] + [""]
    if plan.get("decision_rules"):
        L += [f"## {tr(lang, 'decision_rules')}"] + [f"- {r}" for r in plan["decision_rules"]] + [""]
    r = plan["rationale"]
    L += [f"## {tr(lang, 'rationale')}", r["summary"], ""]
    for key in ("data_basis", "comparisons", "assumptions", "open_questions"):
        if r.get(key):
            L += [f"**{tr(lang, key)}**"] + [f"- {v}" for v in r[key]] + [""]
    L += [f"**{tr(lang, 'rules')}:** {', '.join(r['rules_applied'])}", "", f"## {tr(lang, 'revisions')}"]
    L += [f"- r{h['revision']} {h['date']}: {h['reason']}" for h in plan["revision_history"]]
    return "\n".join(L) + "\n"


def checkin_template(week: str, today: dt.date | None = None) -> dict:
    return {"week": week, "created": (today or dt.date.today()).isoformat(), "knee": [], "sessions": [],
            "strength": [], "general": {"fatigue_1_5": None, "sleep_note": "", "stress_note": "", "illness": False},
            "goal_changes": "", "constraints_next_week": "", "notes": ""}


def validate_checkin(ci: dict, paths: Paths) -> list[str]:
    return _schema_errors(ci, paths.schemas / "checkin.schema.json")
