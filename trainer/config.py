"""Paths and environment. Stdlib only (DESIGN D-013)."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("TRAINER_ROOT", Path(__file__).resolve().parent.parent))


class Paths:
    """All project paths, derived from a root so tests can use a temp dir."""

    def __init__(self, root: Path | str = ROOT):
        r = Path(root)
        self.root = r
        self.data = r / "data"
        self.athlete = self.data / "athlete"
        self.profile = self.athlete / "profile.json"
        self.goals = self.athlete / "goals.json"
        self.raw_garmin_act = self.data / "raw" / "garmin" / "activities"
        self.raw_garmin_well = self.data / "raw" / "garmin" / "wellness"
        self.raw_fit = self.data / "raw" / "fit"
        self.inbox = self.data / "inbox"
        self.manual_csv = self.inbox / "manual_sessions.csv"
        self.derived = self.data / "derived"
        self.activities = self.derived / "activities.jsonl"
        self.wellness = self.derived / "wellness.jsonl"
        self.checkins = self.data / "checkins"
        self.context = self.data / "context"
        self.plans = r / "plans"
        self.log = r / "log" / "coach_log.md"
        self.schemas = r / "schemas"
        self.env = r / ".env"
        self.tokens = r / ".garmin_tokens"

    def ensure(self) -> None:
        for d in (self.raw_garmin_act, self.raw_garmin_well, self.raw_fit, self.inbox,
                  self.derived, self.checkins, self.context, self.plans, self.log.parent):
            d.mkdir(parents=True, exist_ok=True)


def load_env(path: Path) -> dict[str, str]:
    """Minimal .env parser (KEY=VALUE, # comments). Values are never printed (CLAUDE.md B1)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


EXAMPLE_MARKER = "INVENTED EXAMPLE"


def profile_state(paths: "Paths") -> str:
    """'missing', 'example' (still the init template) or 'ok' — guards planning commands (DESIGN D-017)."""
    if not paths.profile.exists():
        return "missing"
    return "example" if str(read_json(paths.profile).get("source", "")).startswith(EXAMPLE_MARKER) else "ok"


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
