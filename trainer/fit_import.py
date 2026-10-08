"""Inbox import: .fit files → data/raw/fit/<name>.json (+ original moved alongside). DESIGN D-003.

Requires optional package `fitdecode` (D-013). Not tested in dev sandbox (B-001).
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from .config import Paths, write_json

_SPORT = {"cycling": "bike", "running": "run", "training": "strength"}


def _v(frame, name):
    try:
        return frame.get_value(name, fallback=None)
    except Exception:
        return None


def _local(t):
    if isinstance(t, dt.datetime):
        if t.tzinfo is not None:
            t = t.astimezone().replace(tzinfo=None)
        return t.isoformat(timespec="seconds")
    return None


def parse_fit(path: Path) -> dict:
    try:
        import fitdecode  # type: ignore
    except ImportError as e:
        raise RuntimeError("Package 'fitdecode' saknas: pip install fitdecode") from e
    session, laps, power, hr = None, [], [], []
    with fitdecode.FitReader(str(path)) as fit:
        for fr in fit:
            if fr.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            if fr.name == "record":
                power.append(_v(fr, "power"))
                hr.append(_v(fr, "heart_rate"))
            elif fr.name == "lap":
                spd = _v(fr, "enhanced_avg_speed") or _v(fr, "avg_speed")
                laps.append({
                    "i": len(laps) + 1,
                    "duration_s": _v(fr, "total_timer_time"),
                    "distance_m": _v(fr, "total_distance"),
                    "avg_power": _v(fr, "avg_power"),
                    "np": _v(fr, "normalized_power"),
                    "avg_hr": _v(fr, "avg_heart_rate"),
                    "max_hr": _v(fr, "max_heart_rate"),
                    "avg_speed_ms": spd,
                })
            elif fr.name == "session" and session is None:
                session = fr
    if session is None:
        raise ValueError(f"{path.name}: ingen session i FIT-filen")
    sport_raw = str(_v(session, "sport") or "")
    sub = str(_v(session, "sub_sport") or "")
    sport = "strength" if "strength" in sub else _SPORT.get(sport_raw, "other")
    env = "indoor" if any(k in sub for k in ("indoor", "virtual", "treadmill")) else "outdoor"
    start = _local(_v(session, "start_time")) or dt.datetime.now().isoformat(timespec="seconds")
    dist = _v(session, "total_distance")
    has_power = any(p for p in power if p)
    return {
        "source_file": path.name,
        "activity": {
            "id": f"fit:{path.stem}",
            "source": "fit",
            "date": start[:10],
            "start_local": start,
            "sport": sport,
            "environment": env,
            "name": path.stem,
            "duration_s": _v(session, "total_timer_time"),
            "distance_km": round(dist / 1000, 2) if dist else None,
            "elevation_m": _v(session, "total_ascent"),
            "avg_hr": _v(session, "avg_heart_rate"),
            "max_hr": _v(session, "max_heart_rate"),
            "avg_power": _v(session, "avg_power"),
            "max_power": _v(session, "max_power"),
            "garmin_tss": _v(session, "training_stress_score"),
            "avg_cadence": _v(session, "avg_cadence"),
        },
        "laps": laps,
        "power_series": power if has_power else None,
    }


def run(paths: Paths) -> dict:
    paths.ensure()
    ok, failed = [], []
    for f in sorted(paths.inbox.glob("*.fit")) + sorted(paths.inbox.glob("*.FIT")):
        if (paths.raw_fit / f"{f.stem}.json").exists():
            continue  # already imported (inbox file could not be removed earlier)
        try:
            data = parse_fit(f)
            write_json(paths.raw_fit / f"{f.stem}.json", data)
            shutil.copy2(str(f), str(paths.raw_fit / f.name))
            try:
                f.unlink()
            except OSError:
                pass  # e.g. no delete permission in agent sandbox; skipped next time
            ok.append(f.name)
        except Exception as e:
            failed.append(f"{f.name}: {e}")
    return {"imported": ok, "failed": failed,
            "manual_csv": paths.manual_csv.exists()}
