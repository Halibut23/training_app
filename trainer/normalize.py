"""raw → derived (DESIGN D-005, §5.1/5.2). Idempotent: rebuilds derived files from scratch."""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from . import metrics
from .classify import classify, work_intervals
from .config import Paths, read_json, read_jsonl, write_jsonl


def _sport_env(type_key: str) -> tuple[str, str]:
    t = (type_key or "").lower()
    env = "indoor" if any(k in t for k in ("indoor", "virtual", "treadmill")) else "outdoor"
    if any(k in t for k in ("cycling", "biking", "ride")):
        return "bike", env
    if "run" in t:
        return "run", env
    if "strength" in t:
        return "strength", "indoor"
    return "other", "unknown"


def _num(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


STEADY_TYPES = {"bike_z2", "bike_long", "bike_recovery"}


def _ftp_at(profile: dict, date: str) -> float:
    """FTP valid at activity date (latest ftp_history entry with date <= activity date)."""
    ftp = profile["bike"]["ftp_w"]
    hist = [h for h in profile["bike"].get("ftp_history", []) if h.get("date") and len(h["date"]) == 10]
    hist.sort(key=lambda h: h["date"])
    valid = [h for h in hist if h["date"] <= date]
    return valid[-1]["ftp_w"] if valid else ftp


def finalize(act: dict, profile: dict) -> dict:
    """Compute derived metrics + session type on a partially filled activity."""
    sport, dur = act["sport"], act.get("duration_s") or 0
    if sport == "bike":
        ftp = _ftp_at(profile, act["date"])
        np_w = act.get("np") or metrics.np_from_laps(act.get("laps") or []) or act.get("avg_power")
        if np_w and dur:
            act["np"] = round(np_w)
            act["tss"], act["if"] = metrics.bike_tss(dur, np_w, ftp)
            act["tss_method"] = "power"
        elif act.get("avg_hr") and dur:
            act["tss"] = metrics.hr_tss(dur, act["avg_hr"], profile["run"]["lthr_bpm_estimate"] * 0.97)
            act["tss_method"] = "hr"
        act["work_intervals"] = work_intervals(act.get("laps") or [], ftp)
    elif sport == "run":
        if act.get("avg_hr") and dur:
            act["tss"] = metrics.hr_tss(dur, act["avg_hr"], profile["run"]["lthr_bpm_estimate"])
            act["tss_method"] = "hr"
        elif dur:
            act["tss"] = round(dur / 3600 * 50, 1)
            act["tss_method"] = "duration"
        if act.get("distance_km") and dur:
            act["pace_min_km"] = round(dur / 60 / act["distance_km"], 2)
    elif sport == "strength":
        act["tss"] = metrics.strength_tss(dur)
        act["tss_method"] = "strength"
    act.setdefault("session_type", classify(act, profile))
    # decoupling only meaningful for steady aerobic rides
    act["decoupling_pct"] = (metrics.decoupling_pct(act.get("laps") or [])
                             if act["session_type"] in STEADY_TYPES else None)
    return act


def from_garmin(raw: dict, profile: dict) -> dict:
    s = raw["summary"]
    sport, env = _sport_env((s.get("activityType") or {}).get("typeKey", ""))
    start = (s.get("startTimeLocal") or "").replace(" ", "T")
    laps = []
    splits = raw.get("splits") or {}
    for i, l in enumerate(splits.get("lapDTOs") or [], 1):
        laps.append({
            "i": l.get("lapIndex", i),
            "duration_s": _num(l.get("duration")),
            "distance_m": _num(l.get("distance")),
            "avg_power": _num(l.get("averagePower")),
            "np": _num(l.get("normalizedPower")),
            "avg_hr": _num(l.get("averageHR")),
            "max_hr": _num(l.get("maxHR")),
            "avg_speed_ms": _num(l.get("averageSpeed")),
        })
    dist = _num(s.get("distance"))
    # B-006: Garmin often reports trainer rides as plain "cycling" → no GPS start = indoor
    if sport in ("bike", "run") and env == "outdoor" and s.get("startLatitude") is None:
        env = "indoor"
    act = {
        "id": f"garmin:{s.get('activityId')}",
        "source": "garmin",
        "date": start[:10],
        "start_local": start,
        "sport": sport,
        "environment": env,
        "name": s.get("activityName"),
        "duration_s": _num(s.get("duration")),
        "distance_km": round(dist / 1000, 2) if dist else None,
        "elevation_m": _num(s.get("elevationGain")),
        "avg_hr": _num(s.get("averageHR")),
        "max_hr": _num(s.get("maxHR")),
        "avg_power": _num(s.get("avgPower") or s.get("averagePower")),
        "max_power": _num(s.get("maxPower")),
        "np": _num(s.get("normPower") or s.get("normalizedPower")),
        "garmin_tss": _num(s.get("trainingStressScore")),
        "avg_cadence": _num(s.get("averageBikingCadenceInRevPerMinute")
                            or s.get("averageRunningCadenceInStepsPerMinute")),
        "laps": laps,
        "rpe": None,
        "notes": None,
    }
    if sport == "run":  # B-005: Garmin running power is not comparable to bike power
        act["run_power"] = act.pop("avg_power")
        act["np"] = act["max_power"] = None
        for l in laps:
            l["avg_power"] = l["np"] = None
    return finalize(act, profile)


def from_fit_json(raw: dict, profile: dict) -> dict:
    """raw/fit/*.json produced by fit_import.parse_fit."""
    act = dict(raw["activity"])
    act["laps"] = raw.get("laps", [])
    if raw.get("power_series"):
        act["np"] = metrics.np_from_series(raw["power_series"])
    act.setdefault("rpe", None)
    act.setdefault("notes", None)
    return finalize(act, profile)


MANUAL_COLUMNS = ["date", "sport", "duration_min", "distance_km", "avg_hr", "avg_power", "np", "rpe", "name", "notes"]


def from_manual_csv(path: Path, profile: dict) -> list[dict]:
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if not row.get("date") or row["date"].startswith("#"):
                continue
            act = {
                "id": f"manual:{row['date']}:{i}",
                "source": "manual",
                "date": row["date"],
                "start_local": row["date"] + "T00:00:00",
                "sport": row.get("sport") or "other",
                "environment": "unknown",
                "name": row.get("name") or None,
                "duration_s": (_num(row.get("duration_min")) or 0) * 60,
                "distance_km": _num(row.get("distance_km")),
                "avg_hr": _num(row.get("avg_hr")),
                "avg_power": _num(row.get("avg_power")),
                "np": _num(row.get("np")),
                "laps": [],
                "rpe": _num(row.get("rpe")),
                "notes": row.get("notes") or None,
            }
            out.append(finalize(act, profile))
    return out


def parse_wellness(raw: dict) -> dict:
    hrv = (raw.get("hrv") or {}).get("hrvSummary") or {}
    rhr = None
    try:
        rhr = raw["rhr"]["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"][0]["value"]
    except (KeyError, IndexError, TypeError):
        pass
    sleep = (raw.get("sleep") or {}).get("dailySleepDTO") or {}
    secs = sleep.get("sleepTimeSeconds")
    score = None
    try:
        score = sleep["sleepScores"]["overall"]["value"]
    except (KeyError, TypeError):
        pass
    return {
        "date": raw["date"],
        "hrv_last_night_ms": hrv.get("lastNightAvg"),
        "hrv_weekly_avg_ms": hrv.get("weeklyAvg"),
        "hrv_status": hrv.get("status"),
        "rhr_bpm": rhr,
        "sleep_h": round(secs / 3600, 2) if secs else None,
        "sleep_score": score,
    }


def _apply_checkins(acts: list[dict], paths: Paths, profile: dict) -> list[dict]:
    """Merge subjective data: RPE/notes/type overrides, and strength sessions not in Garmin (D-012)."""
    by_id = {a["id"]: a for a in acts}
    for f in sorted(paths.checkins.glob("*.json")):
        ci = read_json(f)
        for s in ci.get("sessions", []):
            targets = [by_id[s["activity_id"]]] if s.get("activity_id") in by_id else [
                a for a in acts if a["date"] == s["date"] and (not s.get("sport") or a["sport"] == s["sport"])]
            for a in targets[:1]:
                if s.get("rpe") is not None:
                    a["rpe"] = s["rpe"]
                if s.get("note"):
                    a["notes"] = s["note"]
                if s.get("hr_sensor"):
                    a["hr_sensor"] = s["hr_sensor"]
                if s.get("session_type_override"):
                    a["session_type"] = s["session_type_override"]
                    a["session_type_overridden"] = True
        for k, st in enumerate(ci.get("strength", [])):
            if any(a["date"] == st["date"] and a["sport"] == "strength" for a in acts):
                continue
            acts.append(finalize({
                "id": f"checkin:{st['date']}:strength:{k}", "source": "checkin", "date": st["date"],
                "start_local": st["date"] + "T00:00:00", "sport": "strength", "environment": "indoor",
                "name": "Styrka (rapporterad)", "duration_s": st["duration_min"] * 60, "laps": [],
                "rpe": st.get("rpe"), "notes": st.get("note")}, profile))
    return acts


def _dedupe_fit(acts: list[dict], fit_acts: list[dict]) -> list[dict]:
    """Drop FIT activities that duplicate a Garmin activity (same sport, start within 2 min)."""
    out = []
    for f in fit_acts:
        try:
            ft = dt.datetime.fromisoformat(f["start_local"])
        except (KeyError, ValueError):
            out.append(f)
            continue
        dup = False
        for a in acts:
            try:
                at = dt.datetime.fromisoformat(a["start_local"])
            except (KeyError, ValueError):
                continue
            if a["sport"] == f["sport"] and abs((at - ft).total_seconds()) <= 120:
                dup = True
                break
        if not dup:
            out.append(f)
    return out


def run(paths: Paths) -> dict:
    profile = read_json(paths.profile)
    acts = [from_garmin(read_json(p), profile) for p in sorted(paths.raw_garmin_act.glob("*.json"))]
    fit_acts = [from_fit_json(read_json(p), profile) for p in sorted(paths.raw_fit.glob("*.json"))]
    acts += _dedupe_fit(acts, fit_acts)
    acts += from_manual_csv(paths.manual_csv, profile)
    acts = _apply_checkins(acts, paths, profile)
    acts.sort(key=lambda a: a.get("start_local") or a["date"])
    write_jsonl(paths.activities, acts)
    well = [parse_wellness(read_json(p)) for p in sorted(paths.raw_garmin_well.glob("*.json"))]
    write_jsonl(paths.wellness, well)
    return {"activities": len(acts), "wellness_days": len(well)}


def load(paths: Paths) -> tuple[list[dict], list[dict]]:
    return read_jsonl(paths.activities), read_jsonl(paths.wellness)
