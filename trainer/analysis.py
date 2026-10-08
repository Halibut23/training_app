"""Deterministic analysis for the agent: weekly load, references, compliance, rule flags."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import metrics
from .weeks import parse_date, week_bounds, week_of

HARD_TYPES = {"bike_threshold", "bike_vo2", "bike_test", "bike_sweetspot", "run_quality"}
KEY_TYPES = HARD_TYPES | {"bike_long", "run_long"}


def is_hard(a: dict) -> bool:
    return a.get("session_type") in HARD_TYPES or (a.get("tss") or 0) > 120


# ---------- weekly load ----------
def weekly_summary(acts: list[dict], weeks: list[str]) -> list[dict]:
    rows = []
    for w in weeks:
        s, e = week_bounds(w)
        wa = [a for a in acts if s <= parse_date(a["date"]) <= e]
        h = defaultdict(float)
        for a in wa:
            h[a["sport"]] += (a.get("duration_s") or 0) / 3600
        runs = [a for a in wa if a["sport"] == "run"]
        rows.append({
            "week": w,
            "sessions": len(wa),
            "hours": round(sum(h.values()), 2),
            "bike_h": round(h["bike"], 2),
            "run_h": round(h["run"], 2),
            "strength_h": round(h["strength"], 2),
            "strength_n": sum(1 for a in wa if a["sport"] == "strength"),
            "run_km": round(sum(a.get("distance_km") or 0 for a in runs), 1),
            "run_n": len(runs),
            "longest_run_km": round(max([a.get("distance_km") or 0 for a in runs], default=0), 1),
            "tss": round(sum(a.get("tss") or 0 for a in wa), 0),
            "bike_tss": round(sum(a.get("tss") or 0 for a in wa if a["sport"] == "bike"), 0),
            "hard_n": sum(1 for a in wa if is_hard(a)),
        })
    return rows


def load_chart(acts: list[dict], end: dt.date, days: int = 120) -> list[dict]:
    daily = defaultdict(float)
    for a in acts:
        daily[parse_date(a["date"])] += a.get("tss") or 0
    start = min(daily) if daily else end - dt.timedelta(days=days)
    start = max(start, end - dt.timedelta(days=days))
    return metrics.pmc(daily, start, end)


# ---------- references (R-GEN-10) ----------
def _wi_stats(a: dict):
    wi = a.get("work_intervals") or []
    if not wi:
        return a.get("work_interval_avg_power"), a.get("work_interval_avg_hr"), None
    d = sum(w["duration_s"] for w in wi)
    p = sum(w["avg_power"] * w["duration_s"] for w in wi) / d
    hrs = [w for w in wi if w.get("avg_hr")]
    hr = sum(w["avg_hr"] * w["duration_s"] for w in hrs) / sum(w["duration_s"] for w in hrs) if hrs else None
    fade = None
    if len(wi) >= 2:
        fade = round((wi[-1]["avg_power"] - wi[0]["avg_power"]) / wi[0]["avg_power"] * 100, 1)
    return round(p), (round(hr) if hr else None), fade


def compact(a: dict) -> dict:
    p, hr, fade = _wi_stats(a)
    eff = None
    if a.get("avg_power") and a.get("avg_hr"):
        eff = round(a["avg_power"] / a["avg_hr"], 2)
    return {k: v for k, v in {
        "id": a.get("id"), "date": a.get("date"), "type": a.get("session_type"), "name": a.get("name"),
        "min": round((a.get("duration_s") or 0) / 60) or None, "km": a.get("distance_km"),
        "avg_w": a.get("avg_power"), "np": a.get("np"), "if": a.get("if"), "tss": a.get("tss"),
        "avg_hr": a.get("avg_hr"), "max_hr": a.get("max_hr"), "pace": a.get("pace_min_km"),
        "w_per_bpm": eff, "work_w": p, "work_hr": hr, "work_fade_pct": fade,
        "n_work": len(a.get("work_intervals") or []) or None,
        "decoupling_pct": a.get("decoupling_pct"), "rpe": a.get("rpe"), "notes": a.get("notes"),
        "summary": a.get("summary"),
    }.items() if v is not None}


def find_reference(a: dict, history: list[dict], profile: dict) -> dict | None:
    t = a.get("session_type")
    prev = [h for h in history if h.get("session_type") == t and h["date"] < a["date"] and h["id"] != a["id"]]
    if prev:
        return prev[-1]
    refs = [r for r in profile.get("reference_sessions", []) if r.get("session_type") == t
            and r.get("activity_id") != a["id"] and (r.get("date") or "") < a["date"]]
    return refs[-1] if refs else None


def compare(a: dict, ref: dict) -> dict:
    ca, cr = compact(a), compact(ref)
    deltas = {}
    for k in ("np", "if", "tss", "avg_hr", "avg_w", "work_w", "work_hr", "w_per_bpm", "pace", "km", "min", "decoupling_pct"):
        if ca.get(k) is not None and cr.get(k) is not None:
            deltas[k] = round(ca[k] - cr[k], 3)
    return {"session": ca, "reference": cr, "delta": deltas}


# ---------- compliance (R-GEN-03) ----------
def compliance(plan: dict | None, acts: list[dict], lookback_days: int = 7) -> list[dict]:
    """Planned vs done, order-independent (R-GEN-11).

    A planned session is matched by purpose, not by date: first an explicit `actual_activity_ids`,
    then any unused activity in [week start − lookback, week end] with the same session_type,
    then the same sport (nearest date). Moved sessions are reported as moved, never as missed.
    """
    if not plan:
        return []
    s, e = parse_date(plan["start_date"]), parse_date(plan["end_date"])
    pool = [a for a in acts if s - dt.timedelta(days=lookback_days) <= parse_date(a["date"]) <= e]
    by_id = {a["id"]: a for a in acts}
    used, out = set(), []
    real = [ps for ps in plan["sessions"] if ps["sport"] != "rest"]
    # key sessions first so they claim their best match
    order = {"key": 0, "supporting": 1, "optional": 2}
    for ps in sorted(real, key=lambda x: order.get(x["priority"], 3)):
        pd = parse_date(ps["date"])
        match = None
        for aid in ps.get("actual_activity_ids", []):
            if aid in by_id and aid not in used:
                match = by_id[aid]
                break
        if match is None:
            for same_type in (True, False):
                cands = [a for a in pool if a["id"] not in used and a["sport"] == ps["sport"]
                         and (not same_type or a.get("session_type") == ps["session_type"])
                         and (same_type or s <= parse_date(a["date"]) <= e)]
                cands.sort(key=lambda a: abs((parse_date(a["date"]) - pd).days))
                if cands:
                    match = cands[0]
                    break
        row = {"planned_id": ps["id"], "date": ps["date"], "planned": ps["title"],
               "planned_type": ps["session_type"], "planned_min": ps["duration_min"],
               "planned_tss": ps.get("est_tss")}
        if not match:
            row["status"] = "missed_or_not_synced"
        else:
            used.add(match["id"])
            amin = round((match.get("duration_s") or 0) / 60)
            row.update({"actual_id": match["id"], "actual_date": match["date"], "actual_type": match.get("session_type"),
                        "actual_min": amin, "actual_tss": match.get("tss")})
            off = ps["duration_min"] and abs(amin - ps["duration_min"]) / ps["duration_min"] > 0.25
            row["status"] = "modified" if (match.get("session_type") != ps["session_type"] or off) else "done"
            if match["date"] != ps["date"]:
                row["moved"] = True
        out.append(row)
    out.sort(key=lambda r: r["date"])
    planned_ids = {r.get("actual_id") for r in out}
    for a in pool:
        if s <= parse_date(a["date"]) <= e and a["id"] not in planned_ids:
            out.append({"date": a["date"], "status": "unplanned", "actual_id": a["id"],
                        "actual_type": a.get("session_type"), "actual_min": round((a.get("duration_s") or 0) / 60),
                        "actual_tss": a.get("tss")})
    return out


# ---------- wellness ----------
def wellness_summary(well: list[dict], end: dt.date, profile: dict, days: int = 14) -> dict:
    rows = [w for w in well if end - dt.timedelta(days=days) < parse_date(w["date"]) <= end]
    base = profile.get("recovery_baseline", {})

    def avg(key, rs):
        v = [r[key] for r in rs if r.get(key) is not None]
        return round(sum(v) / len(v), 1) if v else None

    last3 = rows[-3:]
    return {
        "days": len(rows),
        "baseline": base,
        "hrv_avg_14d": avg("hrv_last_night_ms", rows), "hrv_avg_3d": avg("hrv_last_night_ms", last3),
        "rhr_avg_14d": avg("rhr_bpm", rows), "rhr_avg_3d": avg("rhr_bpm", last3),
        "sleep_avg_14d_h": avg("sleep_h", rows), "sleep_avg_3d_h": avg("sleep_h", last3),
        "daily": rows,
    }


# ---------- rule flags ----------
def flags(acts: list[dict], weekly: list[dict], checkin: dict | None, wsum: dict,
          pmc_rows: list[dict], profile: dict, review_week: str) -> list[dict]:
    out = []
    s, e = week_bounds(review_week)
    recent = sorted([a for a in acts if s - dt.timedelta(days=7) <= parse_date(a["date"]) <= e],
                    key=lambda a: a["date"])
    # stacked hard days
    hard_days = sorted({parse_date(a["date"]) for a in recent if is_hard(a) and a["sport"] in ("bike", "run")})
    for d1, d2 in zip(hard_days, hard_days[1:]):
        if (d2 - d1).days == 1:
            out.append({"rule": "R-GEN-07", "level": "warn", "msg": f"Hårda pass dag efter dag: {d1} och {d2}."})
    for a in recent:
        if (a.get("tss") or 0) > 300:
            out.append({"rule": "R-BIKE-04", "level": "info", "msg": f"Pass med TSS {a['tss']} den {a['date']} — kräver lätta dagar runt."})
    # weekly budget + run progression
    wk = {r["week"]: r for r in weekly}
    cur = wk.get(review_week)
    prev = weekly[-2] if len(weekly) >= 2 else None
    if cur:
        lo, hi = profile["budget"]["normal_range_hours"]
        if cur["hours"] > hi + 1:
            out.append({"rule": "R-BUD-01", "level": "warn", "msg": f"{cur['hours']} h över budget ({lo}–{hi} h)."})
        if cur["strength_n"] < profile["budget"]["strength_sessions_per_week"]:
            out.append({"rule": "R-STR-01", "level": "info", "msg": f"{cur['strength_n']} styrkepass registrerade (mål 2). Bekräfta i check-in."})
        if prev and cur["run_km"] - prev["run_km"] > 2:
            out.append({"rule": "R-RUN-07", "level": "warn", "msg": f"Löpvolym +{round(cur['run_km'] - prev['run_km'], 1)} km mot föregående vecka."})
    # primary limiter (check-in field `knee`, historical name)
    runs = [a for a in recent if a["sport"] == "run" and s <= parse_date(a["date"]) <= e]
    knee = (checkin or {}).get("knee", [])
    worst = None
    order = {"green": 0, "yellow": 1, "red": 2}
    for k in knee:
        for st in (k.get("status"), k.get("next_morning")):
            if st and (worst is None or order[st] > order[worst]):
                worst = st
    if runs and not knee:
        out.append({"rule": "R-RUN-01", "level": "warn", "msg": "Löppass utan symptomrapport — anta GUL tills atleten svarat (CLAUDE.md F1)."})
    if worst == "yellow":
        out.append({"rule": "R-RUN-03", "level": "warn", "msg": "Primär begränsning GUL denna vecka → håll/minska, ingen ny löpprogression."})
    if worst == "red":
        out.append({"rule": "R-RUN-04", "level": "stop", "msg": "Primär begränsning RÖD → backa löpbelastningen, ersätt med cykel/vila."})
    if any(a.get("session_type") == "run_quality" for a in runs) and worst != "green":
        out.append({"rule": "R-RUN-06", "level": "warn", "msg": "Löpkvalitet genomförd utan bekräftad grön status för primär begränsning."})
    # recovery
    b = profile.get("recovery_baseline", {})
    neg = []
    if wsum.get("hrv_avg_3d") and b.get("hrv_ms") and wsum["hrv_avg_3d"] < b["hrv_ms"][0]:
        neg.append(f"HRV 3d {wsum['hrv_avg_3d']} ms < baslinje {b['hrv_ms'][0]}")
    if wsum.get("rhr_avg_3d") and b.get("rhr_bpm") and wsum["rhr_avg_3d"] >= b["rhr_bpm"][1] + 4:
        neg.append(f"Vilopuls 3d {wsum['rhr_avg_3d']} ≥ baslinje+4")
    if wsum.get("sleep_avg_3d_h") and wsum["sleep_avg_3d_h"] < 6.5:
        neg.append(f"Sömn 3d {wsum['sleep_avg_3d_h']} h")
    fat = ((checkin or {}).get("general") or {}).get("fatigue_1_5")
    if fat and fat >= 4:
        neg.append(f"Subjektiv trötthet {fat}/5")
    if (checkin or {}).get("general", {}).get("illness"):
        neg.append("Sjukdom rapporterad")
    if len(neg) >= 2:
        out.append({"rule": "R-REC-03", "level": "warn", "msg": "Flera negativa återhämtningssignaler: " + "; ".join(neg)})
    elif neg:
        out.append({"rule": "R-REC-01", "level": "info", "msg": "Enstaka signal (ensam ej beslutsgrund): " + neg[0]})
    if len(pmc_rows) >= 42 and pmc_rows[-1]["tsb"] < -25:  # C-M4: needs history
        out.append({"rule": "R-REC-02", "level": "info", "msg": f"TSB {pmc_rows[-1]['tsb']} — hög ackumulerad belastning."})
    if not acts:
        out.append({"rule": "R-GEN-02", "level": "warn", "msg": "Ingen träningsdata — kör sync eller lägg filer i data/inbox/."})
    return out
