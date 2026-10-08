"""Synthetic Garmin-shaped raw data for tests (mirrors garminconnect response field names)."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from trainer.config import Paths, write_json

ROOT = Path(__file__).resolve().parent.parent


def _lap(i, dur_s, power=None, hr=None, speed=None, dist=0):
    return {"lapIndex": i, "duration": dur_s, "distance": dist, "averagePower": power,
            "averageHR": hr, "maxHR": hr + 5 if hr else None, "averageSpeed": speed}


def _act(aid, start: str, type_key, name, dur_s, laps, dist_m=0, hr=None, power=None, np=None):
    return {"summary": {"activityId": aid, "activityName": name, "startTimeLocal": start.replace("T", " "),
                        "activityType": {"typeKey": type_key}, "duration": dur_s, "distance": dist_m,
                        "averageHR": hr, "maxHR": hr + 20 if hr else None, "avgPower": power, "normPower": np,
                        "trainingStressScore": None},
            "splits": {"lapDTOs": laps}}


def make_project(tmp: Path) -> Paths:
    """Copy schemas/docs/athlete data into tmp and write synthetic raw data for 2026-W39..W40."""
    for d in ("schemas", "docs"):
        shutil.copytree(ROOT / d, tmp / d, ignore=shutil.ignore_patterns("reference"))
    p = Paths(tmp)
    p.athlete.mkdir(parents=True, exist_ok=True)
    # tests use only the tracked, invented example files (D-015) — never the athlete's real data
    for name in ("profile", "goals"):
        shutil.copy2(ROOT / "data" / "athlete" / f"{name}.example.json", p.athlete / f"{name}.json")
    p.ensure()
    acts = [
        # W39
        _act(1, "2026-09-22T17:00:00", "virtual_ride", "2x20", 105 * 60,
             [_lap(1, 65 * 60, 170, 140), _lap(2, 20 * 60, 220, 163), _lap(3, 5 * 60, 140, 140),
              _lap(4, 20 * 60, 230, 165), _lap(5, 5 * 60, 120, 130)], hr=150, power=190),
        _act(2, "2026-09-23T07:00:00", "running", "Lugn löpning", 34 * 60,
             [_lap(i, 340, None, 142, 1000 / 340, 1000) for i in range(1, 7)], 6000, hr=142),
        _act(3, "2026-09-24T18:00:00", "strength_training", "Styrka", 35 * 60, [], hr=105),
        _act(4, "2026-09-25T17:00:00", "indoor_cycling", "8x1", 60 * 60,
             [_lap(1, 27 * 60, 173, 135)] + sum([[_lap(2 + 2 * k, 60, 300, 156), _lap(3 + 2 * k, 120, 130, 135)]
                                                for k in range(8)], []) + [_lap(18, 9 * 60, 130, 125)], hr=140, power=180),
        _act(5, "2026-09-27T09:00:00", "road_biking", "Långpass", 150 * 60,
             [_lap(i, 30 * 60, 168, 138 + i) for i in range(1, 6)], 70000, hr=141, power=168),
        _act(6, "2026-09-27T16:00:00", "running", "Lugn löpning", 34 * 60,
             [_lap(i, 335, None, 141, 1000 / 335, 1000) for i in range(1, 7)], 6000, hr=141),
        # W40
        _act(7, "2026-09-29T17:00:00", "virtual_ride", "3x12 SS", 75 * 60,
             [_lap(1, 15 * 60, 160, 128), _lap(2, 12 * 60, 210, 155), _lap(3, 4 * 60, 130, 130),
              _lap(4, 12 * 60, 210, 157), _lap(5, 4 * 60, 130, 130), _lap(6, 12 * 60, 212, 159), _lap(7, 16 * 60, 140, 130)],
             hr=145, power=180),
        _act(8, "2026-09-30T07:00:00", "running", "Lugn löpning", 34 * 60,
             [_lap(i, 338, None, 140, 1000 / 338, 1000) for i in range(1, 7)], 6000, hr=140),
    ]
    for a in acts:
        write_json(p.raw_garmin_act / f"{a['summary']['activityId']}.json", a)
    d = dt.date(2026, 9, 17)
    while d <= dt.date(2026, 9, 30):
        write_json(p.raw_garmin_well / f"{d}.json", {
            "date": d.isoformat(),
            "hrv": {"hrvSummary": {"lastNightAvg": 100, "weeklyAvg": 101, "status": "BALANCED"}},
            "rhr": {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 37}]}}},
            "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 7.5 * 3600, "sleepScores": {"overall": {"value": 80}}}},
        })
        d += dt.timedelta(days=1)
    return p
