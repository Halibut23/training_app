"""Plan session → Garmin Connect workout JSON (DESIGN D-022 / §5.7, COACHING_SPEC R-WO-01…05).

Pure stdlib: no network and no garminconnect import, so it is testable offline and used for --dry-run.
Upload/scheduling lives in garmin_client.push.
"""
from __future__ import annotations

import hashlib
import json
import re

from .i18n import tr

DEFAULT_PREFS = {
    "bike_erg_power_span_w": 10,       # ERG: trainer holds the mean of the span (R-WO-03)
    "bike_power_span_min_w": 20,       # free riding
    "run_pace_span_min_s_per_km": 30,  # watch pace alarm is sensitive
    "run_hr_span_bpm": 10,             # HR target = [cap - span, cap]
    "name_prefix": "",
}

SPORT = {
    "bike": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
    "run": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
}
_STEP = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4, "rest": 5, "other": 7}
_COND = {"lap": (1, "lap.button"), "time": (2, "time"), "distance": (3, "distance"), "iterations": (7, "iterations")}
_TGT = {"none": (1, "no.target"), "power": (2, "power.zone"), "cadence": (3, "cadence"),
        "hr": (4, "heart.rate.zone"), "pace": (6, "pace.zone")}
_KEY2TGT = {v[1]: k for k, v in _TGT.items()}
NAME_MAX, DESC_MAX, NOTE_MAX = 80, 512, 200
SUBSTEP_RE = re.compile(r"\d+\s*[×x]\s*\d+")
EASY_RUN = ("run_easy", "run_long")


def prefs_of(profile: dict | None) -> dict:
    """`profile.garmin_workouts` merged over the defaults (R-WO-03)."""
    own = (profile or {}).get("garmin_workouts") or {}
    return {k: own.get(k, v) for k, v in DEFAULT_PREFS.items()}


def pushable(session: dict) -> bool:
    return (session.get("sport") in SPORT and session.get("status") == "planned"
            and bool(session.get("structure")) and session.get("garmin_push", True) is not False)


def _half_up(x: float) -> int:
    return int(x + 0.5)


def _mmss(sec: float) -> str:
    m, s = divmod(_half_up(sec), 60)
    return f"{m}:{s:02d}"


def _num(x: float) -> str:
    return f"{x:g}"


class _Ctx:
    def __init__(self, session: dict, prefs: dict, lang: str):
        self.s, self.p, self.lang = session, prefs, lang
        self.sport = session["sport"]
        self.erg = bool(session.get("erg")) and self.sport == "bike"
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.order = 0
        self.repeats = 0

    def next_order(self) -> int:
        self.order += 1
        return self.order

    def err(self, msg: str):
        self.errors.append(f"{self.s['id']}: {msg}")

    def warn(self, msg: str):
        self.warnings.append(f"{self.s['id']}: {msg}")


# ── targets ─────────────────────────────────────────────────────────────────

def _widen(lo: float, hi: float | None, min_span: float) -> tuple[float, float]:
    if hi is None:
        return lo, lo + min_span
    lo, hi = sorted((lo, hi))
    c, span = (lo + hi) / 2, max(hi - lo, min_span)
    return c - span / 2, c + span / 2


def _power(ctx: _Ctx, rng) -> tuple[float, float, str]:
    lo, hi = rng
    if ctx.erg:
        sp = _half_up(lo if hi is None else (lo + hi) / 2)
        half = ctx.p["bike_erg_power_span_w"] / 2
        return sp - half, sp + half, f"ERG {sp} W"
    a, b = _widen(lo, hi, ctx.p["bike_power_span_min_w"])
    note = "" if (hi is not None and (a, b) == tuple(sorted((lo, hi)))) else \
        f"plan {_num(lo)}{'–' + _num(hi) if hi is not None else '+'} W"
    return round(a), round(b), note


def _pace(ctx: _Ctx, rng) -> tuple[float, float, str]:
    fast, slow = sorted(x * 60 for x in rng)  # s/km
    c = (fast + slow) / 2
    span = max(slow - fast, ctx.p["run_pace_span_min_s_per_km"])
    f2, s2 = c - span / 2, c + span / 2
    note = "" if (f2, s2) == (fast, slow) else f"plan {_mmss(fast)}–{_mmss(slow)}/km"
    return round(1000 / s2, 4), round(1000 / f2, 4), note  # m/s: slower pace is the lower limit


def _hr(ctx: _Ctx, cap: float) -> tuple[float, float]:
    return cap - ctx.p["run_hr_span_bpm"], cap


def _pick(ctx: _Ctx, t: dict, override: str | None) -> tuple[str, str | None]:
    """Primary and secondary target kind (R-WO-04)."""
    has = {"power": bool(t.get("power_w")), "pace": bool(t.get("pace_min_km")),
           "hr": t.get("hr_max_bpm") is not None, "cadence": bool(t.get("cadence_rpm"))}
    if ctx.sport == "bike":
        primary = override or next((k for k in ("power", "hr", "cadence") if has[k]), "none")
        secondary = "cadence" if primary != "cadence" and has["cadence"] else None
    else:
        if override:
            primary = override
        elif has["pace"] and has["hr"]:
            primary = "hr" if ctx.s["session_type"] in EASY_RUN else "pace"
        else:
            primary = next((k for k in ("pace", "hr") if has[k]), "none")
        other = {"pace": "hr", "hr": "pace"}.get(primary)
        secondary = other if other and has[other] else None
    if primary != "none" and not has.get(primary):
        ctx.err(f"garmin_target '{primary}' but the step has no {primary} target")
        primary = "none"
    return primary, secondary


def _target_values(ctx: _Ctx, kind: str, t: dict) -> tuple[float | None, float | None, str]:
    if kind == "power":
        return _power(ctx, t["power_w"])
    if kind == "pace":
        return _pace(ctx, t["pace_min_km"])
    if kind == "hr":
        a, b = _hr(ctx, t["hr_max_bpm"])
        return a, b, ""
    if kind == "cadence":
        a, b = t["cadence_rpm"]
        return a, b, ""
    return None, None, ""


# ── steps ───────────────────────────────────────────────────────────────────

def _exec_step(ctx: _Ctx, st: dict, kind: str, child_id: int | None) -> dict | None:
    label = st.get("label", "")
    if st.get("lap_button"):
        cond, value = "lap", None
    elif st.get("duration_min"):
        cond, value = "time", float(round(st["duration_min"] * 60))
    elif st.get("distance_km"):
        cond, value = "distance", float(round(st["distance_km"] * 1000))
    else:
        ctx.err(f"step '{label}' has no duration_min, distance_km or lap_button (R-WO-01)")
        return None
    t = st.get("target") or {}
    primary, secondary = _pick(ctx, t, st.get("garmin_target"))
    if primary == "none" and st.get("garmin_target") != "none":
        ctx.warn(f"step '{label}' has no target — add one or set garmin_target 'none' (R-WO-01)")
    if ctx.erg and primary != "power" and st.get("garmin_target") != "none":
        ctx.warn(f"step '{label}' in an ERG session has no power target — the trainer will not hold a setpoint")
    v1, v2, note1 = _target_values(ctx, primary, t)
    s1, s2, note2 = _target_values(ctx, secondary, t) if secondary else (None, None, "")
    cues = [label, note1, note2]
    if t.get("rpe"):
        lo, hi = t["rpe"]
        cues.append(f"RPE {_num(lo)}" + (f"–{_num(hi)}" if hi not in (None, lo) else ""))
    if ctx.sport == "bike" and t.get("hr_max_bpm") is not None and primary != "hr":
        cues.append(f"{tr(ctx.lang, 'hr')} ≤ {_num(t['hr_max_bpm'])}")
    if st.get("notes"):
        cues.append(st["notes"])
    cid, ckey = _COND[cond]
    tid, tkey = _TGT[primary]
    node = {
        "type": "ExecutableStepDTO", "stepOrder": ctx.next_order(),
        "stepType": {"stepTypeId": _STEP[kind], "stepTypeKey": kind, "displayOrder": _STEP[kind]},
        "childStepId": child_id,
        "description": " · ".join(c for c in cues if c)[:NOTE_MAX],
        "endCondition": {"conditionTypeId": cid, "conditionTypeKey": ckey, "displayOrder": cid, "displayable": True},
        "endConditionValue": value,
        "targetType": {"workoutTargetTypeId": tid, "workoutTargetTypeKey": tkey, "displayOrder": tid},
        "targetValueOne": v1, "targetValueTwo": v2,
    }
    if secondary:
        sid_, skey = _TGT[secondary]
        node.update({"secondaryTargetType": {"workoutTargetTypeId": sid_, "workoutTargetTypeKey": skey,
                                             "displayOrder": sid_},
                     "secondaryTargetValueOne": s1, "secondaryTargetValueTwo": s2})
    return {k: v for k, v in node.items() if v is not None}


def _recovery_of(st: dict, lang: str) -> dict | None:
    if not st.get("recovery_min"):
        return None
    rec = {"label": tr(lang, "rest_between").capitalize(), "duration_min": st["recovery_min"], "kind": "recovery"}
    if st.get("recovery_target"):
        rec["target"] = st["recovery_target"]
    return rec


def _group(ctx: _Ctx, reps: int, build) -> dict:
    ctx.repeats += 1
    cid = ctx.repeats
    order = ctx.next_order()
    return {"type": "RepeatGroupDTO", "stepOrder": order,
            "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
            "childStepId": cid, "numberOfIterations": reps, "smartRepeat": False,
            "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7,
                             "displayable": False},
            "endConditionValue": float(reps), "workoutSteps": build(cid)}


def _nodes(ctx: _Ctx, steps: list[dict], top: bool, child_id: int | None, inherit: str) -> list[dict]:
    out: list[dict] = []
    n = len(steps)
    for i, st in enumerate(steps):
        reps = st.get("reps") or 1
        kind = st.get("kind")
        if not kind:
            if top and n >= 2 and i == 0:
                kind = "warmup"
            elif top and n >= 2 and i == n - 1:
                kind = "cooldown"
            else:
                kind = inherit
        label = st.get("label", "")
        if not st.get("steps") and reps <= 1 and SUBSTEP_RE.search(label):
            ctx.warn(f"label '{label}' describes sub-steps that are not programmed — split it into steps (R-WO-01)")
        if st.get("steps"):
            if reps > 1:
                out.append(_group(ctx, reps, lambda cid, s=st: _nodes(ctx, s["steps"], False, cid, "interval")))
            else:
                out += _nodes(ctx, st["steps"], False, child_id, kind)
            continue
        work_kind = st.get("kind") or ("interval" if reps > 1 else kind)
        rec = _recovery_of(st, ctx.lang)
        if reps > 1:
            def build(cid, s=st, wk=work_kind, r=rec):
                nodes = [_exec_step(ctx, s, wk, cid)]
                if r:
                    nodes.append(_exec_step(ctx, r, "recovery", cid))
                return [x for x in nodes if x]
            out.append(_group(ctx, reps, build))
        else:
            for s, k in ((st, work_kind), (rec, "recovery")):
                if s:
                    node = _exec_step(ctx, s, k, child_id)
                    if node:
                        out.append(node)
    return out


# ── sessions / plans ────────────────────────────────────────────────────────

def compile_session(session: dict, week: str, profile: dict | None = None, lang: str = "sv"
                    ) -> tuple[dict | None, list[str], list[str]]:
    """Returns (payload or None, errors, warnings)."""
    prefs = prefs_of(profile)
    ctx = _Ctx(session, prefs, lang)
    if ctx.sport not in SPORT:
        ctx.err(f"sport '{ctx.sport}' is not pushed to Garmin (bike/run only, D-022)")
        return None, ctx.errors, ctx.warnings
    if ctx.sport == "bike" and "erg" not in session:
        ctx.err("bike session must state erg: true|false (R-WO-02)")
    steps = _nodes(ctx, session.get("structure") or [], True, None, "interval")
    if not steps:
        ctx.err("no programmable steps")
    desc = []
    if ctx.sport == "bike":
        desc.append(tr(lang, "erg_on" if ctx.erg else "erg_off"))
    if session.get("purpose"):
        desc.append(session["purpose"])
    if session.get("fallback"):
        desc.append(f"{tr(lang, 'plan_b')}: {session['fallback']}")
    name = f"{prefs['name_prefix']}{week.split('-')[-1]} {session['title']}"[:NAME_MAX]
    payload = {
        "workoutName": name,
        "description": " | ".join(desc)[:DESC_MAX],
        "sportType": SPORT[ctx.sport],
        "estimatedDurationInSecs": int(round((session.get("duration_min") or 0) * 60)),
        "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT[ctx.sport], "workoutSteps": steps}],
    }
    return (None if ctx.errors else payload), ctx.errors, ctx.warnings


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def compile_plan(plan: dict, profile: dict | None = None, lang: str = "sv"
                 ) -> tuple[dict[str, dict], list[str], list[str]]:
    """All pushable sessions → {session_id: {payload, date, hash, title}}, errors, warnings."""
    out, errors, warnings = {}, [], []
    for s in plan.get("sessions", []):
        if not pushable(s):
            continue
        payload, e, w = compile_session(s, plan["week"], profile, lang)
        errors += e
        warnings += w
        if payload:
            out[s["id"]] = {"payload": payload, "date": s["date"], "hash": payload_hash(payload),
                            "title": s["title"], "sport": s["sport"]}
    return out, errors, warnings


# ── human-readable view (dry run) ───────────────────────────────────────────

def _fmt_target(key: str | None, a, b) -> str:
    kind = _KEY2TGT.get(key or "", "none")
    if kind == "none" or a is None:
        return "—"
    if kind == "power":
        return f"{_num(a)}–{_num(b)} W"
    if kind == "pace":
        return f"{_mmss(1000 / b)}–{_mmss(1000 / a)}/km"
    if kind == "hr":
        return f"{_num(a)}–{_num(b)} bpm"
    return f"{_num(a)}–{_num(b)} rpm"


def describe(payload: dict) -> list[str]:
    lines = []

    def walk(nodes, depth):
        for n in nodes:
            pad = "  " * depth
            if n["type"] == "RepeatGroupDTO":
                lines.append(f"{pad}{n['numberOfIterations']} ×")
                walk(n["workoutSteps"], depth + 1)
                continue
            ck, v = n["endCondition"]["conditionTypeKey"], n.get("endConditionValue")
            end = _mmss(v) if ck == "time" else f"{v / 1000:g} km" if ck == "distance" else "lap"
            tgt = _fmt_target(n["targetType"]["workoutTargetTypeKey"], n.get("targetValueOne"), n.get("targetValueTwo"))
            if n.get("secondaryTargetType"):
                tgt += " + " + _fmt_target(n["secondaryTargetType"]["workoutTargetTypeKey"],
                                           n.get("secondaryTargetValueOne"), n.get("secondaryTargetValueTwo"))
            lines.append(f"{pad}{n['stepType']['stepTypeKey']:<9} {end:>7}  {tgt:<26} {n.get('description', '')}")

    walk(payload["workoutSegments"][0]["workoutSteps"], 1)
    return lines
