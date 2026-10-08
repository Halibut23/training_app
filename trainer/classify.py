"""Rule-based session-type classifier (DESIGN D-011, §5.6). Known limitation B-002."""
from __future__ import annotations


def work_intervals(laps: list[dict], ftp: float, min_pct: float = 0.88, min_s: int = 20) -> list[dict]:
    out = []
    for l in laps:
        p, d = l.get("avg_power"), l.get("duration_s") or 0
        if p and d >= min_s and p >= min_pct * ftp:
            out.append({"i": l.get("i"), "duration_s": round(d), "avg_power": round(p),
                        "avg_hr": l.get("avg_hr"), "max_hr": l.get("max_hr"),
                        "pct_ftp": round(p / ftp, 3)})
    return out


def classify_bike(act: dict, ftp: float) -> str:
    dur = act.get("duration_s") or 0
    if_ = act.get("if")
    name = (act.get("name") or "").lower()
    if "ramp" in name or "ftp test" in name or "ftp-test" in name:
        return "bike_test"
    if dur >= 150 * 60:  # long rides: intervals inside are terrain/segments, not the session's purpose
        return "bike_long"
    wi = act.get("work_intervals") or []
    vo2 = [w for w in wi if w["pct_ftp"] >= 1.05 and 20 <= w["duration_s"] <= 480]
    thr = [w for w in wi if 0.95 <= w["pct_ftp"] < 1.05 and w["duration_s"] >= 360]
    ss = [w for w in wi if 0.88 <= w["pct_ftp"] < 0.95 and w["duration_s"] >= 480]
    if len(vo2) >= 3:
        return "bike_vo2"
    if thr:
        return "bike_threshold"
    if ss:
        return "bike_sweetspot"
    if if_ is None:
        return "bike_long" if dur >= 150 * 60 else "bike_z2"
    if if_ >= 0.95:
        return "bike_threshold"
    if dur >= 150 * 60:
        return "bike_long"
    if if_ >= 0.85:
        return "bike_sweetspot"
    if if_ >= 0.76:
        return "bike_tempo"
    if if_ < 0.60:
        return "bike_recovery"
    return "bike_z2"


def classify_run(act: dict, quality_pace: float = 4.75, easy_hr_cap: float = 145) -> str:
    dur = act.get("duration_s") or 0
    laps = act.get("laps") or []
    fast = [l for l in laps if l.get("avg_speed_ms") and l.get("duration_s", 0) <= 600
            and (1000 / l["avg_speed_ms"] / 60) <= quality_pace]
    if len(fast) >= 2:
        return "run_quality"
    if dur >= 75 * 60:
        return "run_long"
    if act.get("avg_hr") and act["avg_hr"] > easy_hr_cap + 10:
        return "run_quality"
    return "run_easy"


def classify(act: dict, profile: dict) -> str:
    s = act.get("sport")
    if s == "bike":
        return classify_bike(act, profile["bike"]["ftp_w"])
    if s == "run":
        r = profile.get("run", {})
        return classify_run(act, r.get("quality_pace_threshold_min_km", 4.75), r.get("easy_hr_cap_bpm", 145))
    if s == "strength":
        return "strength"
    return "other"
