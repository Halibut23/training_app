"""Plan skeleton, validation (schema + semantic), Markdown rendering (DESIGN D-007, D-009, D-010)."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .config import Paths, read_json, write_json
from .weeks import DAYS_SV, parse_date, week_bounds

TYPE_SV = {
    "bike_recovery": "Cykel återhämtning", "bike_z2": "Cykel Z2", "bike_long": "Cykel långpass",
    "bike_tempo": "Cykel tempo", "bike_sweetspot": "Cykel sweet spot", "bike_threshold": "Cykel tröskel",
    "bike_vo2": "Cykel VO2", "bike_test": "Cykel test", "run_easy": "Löpning lugn", "run_quality": "Löpning kvalitet",
    "run_long": "Löpning lång", "strength": "Styrka", "rest": "Vila", "other": "Övrigt",
}
PRIO_SV = {"key": "Nyckelpass", "supporting": "Stödjande", "optional": "Valfritt"}
STATUS_SV = {"done": "gjort", "modified": "ändrat", "missed": "missat", "replaced": "ersatt"}
ADJ_SV = {"progression": "Progression", "hold": "Bibehåll", "deload": "Avlastning",
          "replacement": "Ersättning", "restructure": "Omstrukturering"}


def skeleton(week: str, today: dt.date | None = None) -> dict:
    s, e = week_bounds(week)
    today = today or dt.date.today()
    return {
        "week": week, "start_date": s.isoformat(), "end_date": e.isoformat(), "revision": 0,
        "status": "draft", "created": today.isoformat(), "phase": "", "adjustment_type": "hold", "focus": "",
        "targets": {"hours": 0, "bike_hours": 0, "run_km": 0, "strength_sessions": 2, "est_tss": 0},
        "rationale": {"summary": "", "data_basis": [], "comparisons": [], "rules_applied": ["R-GEN-02"],
                      "assumptions": [], "open_questions": []},
        "placement_rules": [
            "Minst 48 h mellan nyckelpass med kvalitet (R-GEN-07).",
            "Inte VO2 dagen efter ett pass med TSS > 150.",
            "Tung benstyrka inte dagen före ett nyckelpass eller löppass (R-STR-03).",
        ],
        "decision_rules": [],
        "sessions": [
            {"id": f"{week}-{i + 1}", "date": (s + dt.timedelta(days=i)).isoformat(), "sport": "rest",
             "session_type": "rest", "title": "Vila", "priority": "optional", "duration_min": 0, "status": "planned"}
            for i in range(7)],
        "revision_history": [{"revision": 0, "date": today.isoformat(), "reason": "Första version"}],
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
        errors.append(f"start/end_date matchar inte {plan['week']} ({s}–{e})")
    ids = [x["id"] for x in plan["sessions"]]
    if len(ids) != len(set(ids)):
        errors.append("Dubbla sessions-id")
    for x in plan["sessions"]:
        if not (s <= parse_date(x["date"]) <= e):
            errors.append(f"{x['id']}: datum {x['date']} utanför veckan")
        if x["sport"] == "run" and "run" not in x["session_type"]:
            errors.append(f"{x['id']}: sport run men typ {x['session_type']}")
        if x["sport"] == "bike" and "bike" not in x["session_type"]:
            errors.append(f"{x['id']}: sport bike men typ {x['session_type']}")
    if plan["revision_history"][-1]["revision"] != plan["revision"]:
        errors.append("revision matchar inte sista revision_history-posten")
    known = known_rule_ids(paths.root / "docs" / "COACHING_SPEC.md")
    unknown = [r for r in plan["rationale"]["rules_applied"] if known and r not in known]
    if unknown:
        errors.append(f"Okända regel-ID: {unknown}")
    # soft checks
    hours = sum(x["duration_min"] for x in plan["sessions"]) / 60
    if abs(hours - plan["targets"]["hours"]) > 0.25:
        warnings.append(f"Summa pass {hours:.2f} h ≠ targets.hours {plan['targets']['hours']}")
    run_km = sum(x.get("distance_km") or 0 for x in plan["sessions"] if x["sport"] == "run")
    if "run_km" in plan["targets"] and abs(run_km - plan["targets"]["run_km"]) > 0.5:
        warnings.append(f"Summa löp-km {run_km} ≠ targets.run_km {plan['targets']['run_km']}")
    n_str = sum(1 for x in plan["sessions"] if x["sport"] == "strength")
    if n_str < 2:
        warnings.append(f"{n_str} styrkepass (R-STR-01: 2)")
    hard = sorted(parse_date(x.get("completed_date") or x["date"]) for x in plan["sessions"]
                  if x["session_type"] in ("bike_threshold", "bike_vo2", "bike_test", "run_quality"))
    for a, b in zip(hard, hard[1:]):
        if (b - a).days <= 1:
            warnings.append(f"Kvalitetspass {a} och {b} i följd (R-GEN-07)")
    if profile:
        lo, hi = profile["budget"]["normal_range_hours"]
        if hours > hi + 1:
            warnings.append(f"{hours:.1f} h > budget {hi} h (R-BUD-01)")
    return errors, warnings


def _target(t: dict | None) -> str:
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
        parts.append(f"puls ≤{t['hr_max_bpm']:g}")
    if t.get("rpe"):
        parts.append(f"RPE {t['rpe'][0]:g}–{t['rpe'][1]:g}")
    if t.get("cadence_rpm"):
        parts.append(f"{t['cadence_rpm'][0]:g}–{t['cadence_rpm'][1]:g} rpm")
    return ", ".join(parts)


def _step(st: dict) -> str:
    q = []
    if st.get("reps"):
        q.append(f"{st['reps']} ×" if (st.get("duration_min") or st.get("distance_km")) else f"{st['reps']} set")
    if st.get("duration_min"):
        q.append(f"{st['duration_min']:g} min")
    if st.get("distance_km"):
        q.append(f"{st['distance_km']:g} km")
    s = f"{st['label']}: {' '.join(q)}".strip()
    tg = _target(st.get("target"))
    if tg:
        s += f" @ {tg}"
    if st.get("recovery_min"):
        s += f" (vila {st['recovery_min']:g} min)"
    return s


def render(plan: dict) -> str:
    t = plan["targets"]
    L = [f"# Träningsplan {plan['week']} ({plan['start_date']} – {plan['end_date']})",
         f"Revision {plan['revision']} · status {plan['status']} · fas: {plan['phase']} · justering: **{ADJ_SV[plan['adjustment_type']]}**", "",
         f"**Fokus:** {plan['focus']}", "",
         f"**Mål för veckan:** {t['hours']:g} h"
         + (f" · cykel {t['bike_hours']:g} h" if t.get("bike_hours") is not None else "")
         + (f" · löpning {t['run_km']:g} km" if t.get("run_km") is not None else "")
         + (f" · styrka {t['strength_sessions']} pass" if t.get("strength_sessions") is not None else "")
         + (f" · ~{t['est_tss']:g} TSS" if t.get("est_tss") else "")
         + (f" _(varav {sum(x['duration_min'] for x in plan['sessions'] if x.get('completed_date', plan['start_date']) < plan['start_date']):g} min redan gjort före veckan)_"
            if any(x.get("completed_date", plan["start_date"]) < plan["start_date"] for x in plan["sessions"]) else ""), "",
         "_Dagarna är ett förslag. Passen kan flyttas inom veckan (eller till intilliggande dagar) så länge placeringsreglerna nedan hålls. Det viktiga är syftet och ungefärlig intensitet (R-GEN-11)._", "",
         "| Dag (förslag) | Pass | Prio | Tid | Innehåll |", "|---|---|---|---:|---|"]
    for x in sorted(plan["sessions"], key=lambda x: x.get("completed_date") or x["date"]):
        d = parse_date(x.get("completed_date") or x["date"])
        content = "<br>".join(_step(s) for s in x.get("structure", [])) or (x.get("instructions") or "")
        mark = "" if x["status"] == "planned" else f" ({STATUS_SV.get(x['status'], x['status'])}" + (
            f" {DAYS_SV[parse_date(x['completed_date']).weekday()].lower()} {parse_date(x['completed_date']).day}/{parse_date(x['completed_date']).month}"
            if x.get("completed_date") else "") + ")"
        L.append(f"| {DAYS_SV[d.weekday()]} {d.day}/{d.month} | **{x['title']}**{mark}<br>_{TYPE_SV[x['session_type']]}_ | "
                 f"{PRIO_SV[x['priority']]} | {x['duration_min']:g} min | {content} |")
    L += ["", "## Passdetaljer"]
    for x in sorted(plan["sessions"], key=lambda x: x["date"]):
        if x["sport"] == "rest":
            continue
        L.append(f"### {x['title']} ({x['date']})")
        if x.get("purpose"):
            L.append(f"- **Syfte:** {x['purpose']}")
        if x.get("instructions"):
            L.append(f"- **Instruktion:** {x['instructions']}")
        if x.get("fallback"):
            L.append(f"- **Plan B:** {x['fallback']}")
        if x.get("est_tss"):
            L.append(f"- Uppskattad TSS: {x['est_tss']:g}")
        L.append("")
    if plan.get("placement_rules"):
        L += ["## Placeringsregler (när du flyttar pass)"] + [f"- {r}" for r in plan["placement_rules"]] + [""]
    if plan.get("decision_rules"):
        L += ["## Beslutsregler denna vecka"] + [f"- {r}" for r in plan["decision_rules"]] + [""]
    r = plan["rationale"]
    L += ["## Motivering", r["summary"], ""]
    for key, title in (("data_basis", "Underlag"), ("comparisons", "Jämförelser"), ("assumptions", "Antaganden"),
                       ("open_questions", "Öppna frågor")):
        if r.get(key):
            L += [f"**{title}**"] + [f"- {v}" for v in r[key]] + [""]
    L += [f"**Regler:** {', '.join(r['rules_applied'])}", "", "## Revisioner"]
    L += [f"- r{h['revision']} {h['date']}: {h['reason']}" for h in plan["revision_history"]]
    return "\n".join(L) + "\n"


def checkin_template(week: str, today: dt.date | None = None) -> dict:
    return {"week": week, "created": (today or dt.date.today()).isoformat(), "knee": [], "sessions": [],
            "strength": [], "general": {"fatigue_1_5": None, "sleep_note": "", "stress_note": "", "illness": False},
            "goal_changes": "", "constraints_next_week": "", "notes": ""}


def validate_checkin(ci: dict, paths: Paths) -> list[str]:
    return _schema_errors(ci, paths.schemas / "checkin.schema.json")
