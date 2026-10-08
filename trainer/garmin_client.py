"""Garmin Connect fetch via the unofficial `garminconnect` library (DESIGN D-003, D-004).

Raw responses are stored unchanged under data/raw/garmin (D-005). Parsing happens in normalize.py.
NOTE (B-001/B-004): requires garminconnect >= 0.3 (native auth; garth was blocked by Garmin in March 2026).
"""
from __future__ import annotations

import datetime as dt
import getpass
import sys
import time

from .config import Paths, load_env, write_json


class GarminUnavailable(RuntimeError):
    pass


def _import_lib():
    try:
        import garminconnect  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise GarminUnavailable(
            "Package 'garminconnect' saknas. Installera: pip install -r requirements.txt"
        ) from e
    ver = getattr(garminconnect, "__version__", None)
    if ver is None:
        try:
            from importlib.metadata import version
            ver = version("garminconnect")
        except Exception:
            ver = "0"
    if int(str(ver).split(".")[0]) == 0 and int(str(ver).split(".")[1]) < 3:
        raise GarminUnavailable(
            f"garminconnect {ver} använder garth, vilket Garmin blockerar sedan mars 2026 (401). "
            "Kräver garminconnect >= 0.3 (Python >= 3.12) + curl_cffi. Se README och DESIGN B-004."
        )
    return garminconnect


def _credentials(paths: Paths) -> tuple[str | None, str | None]:
    env = load_env(paths.env)
    import os
    email = os.environ.get("GARMIN_EMAIL") or env.get("GARMIN_EMAIL")
    pw = os.environ.get("GARMIN_PASSWORD") or env.get("GARMIN_PASSWORD")
    return email, pw


def connect(paths: Paths, interactive: bool = False):
    """Return a logged-in Garmin client (garminconnect >= 0.3, native auth, no garth).

    Tokens are cached in .garmin_tokens/garmin_tokens.json and auto-refreshed by the library.
    MFA needs `interactive=True` (run `python -m trainer login` in a terminal) – CLAUDE.md B3.
    """
    gc = _import_lib()
    tokenstore = str(paths.tokens)
    paths.tokens.mkdir(parents=True, exist_ok=True)
    # 1) cached tokens
    if (paths.tokens / "garmin_tokens.json").exists():
        try:
            api = gc.Garmin()
            api.login(tokenstore)
            return api
        except Exception as e:  # tokens expired / invalid
            print(f"[garmin] Sparade tokens fungerade inte ({type(e).__name__}), loggar in igen.", file=sys.stderr)
    # 2) credentials
    email, pw = _credentials(paths)
    if interactive:
        email = email or input("Garmin e-post: ")
        pw = pw or getpass.getpass("Garmin lösenord: ")
    if not email or not pw:
        raise GarminUnavailable(
            "Inga Garmin-uppgifter. Lägg GARMIN_EMAIL/GARMIN_PASSWORD i .env och kör "
            "'python -m trainer login' i en egen terminal."
        )
    kwargs = {"prompt_mfa": (lambda: input("MFA-kod från Garmin: "))} if interactive else {}
    api = gc.Garmin(email=email, password=pw, **kwargs)
    try:
        api.login(tokenstore)  # also writes garmin_tokens.json
    except Exception as e:
        raise GarminUnavailable(
            f"Inloggning misslyckades ({type(e).__name__}: {str(e)[:200]}). "
            "Kontrollera: garminconnect >= 0.3 + curl_cffi installerat (DESIGN B-004), "
            "rätt lösenord i .env, och kör 'python -m trainer login' interaktivt om MFA krävs."
        ) from e
    return api


def login(paths: Paths) -> None:
    connect(paths, interactive=True)
    print("[garmin] Inloggning OK, tokens sparade i .garmin_tokens/ (git-ignorerad).")


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"[:300]}


def fetch(paths: Paths, days: int = 21, refetch: bool = False, sleep_s: float = 0.5) -> dict:
    """Fetch activities (+ laps) and daily wellness for the last `days` days."""
    paths.ensure()
    api = connect(paths)
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    acts = api.get_activities_by_date(start.isoformat(), end.isoformat())
    n_new = 0
    for a in acts or []:
        aid = a.get("activityId")
        if aid is None:
            continue
        out = paths.raw_garmin_act / f"{aid}.json"
        if out.exists() and not refetch:
            continue
        splits = _safe(api.get_activity_splits, aid)
        write_json(out, {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
                         "summary": a, "splits": splits})
        n_new += 1
        time.sleep(sleep_s)
    n_well = 0
    d = start
    while d <= end:
        out = paths.raw_garmin_well / f"{d.isoformat()}.json"
        # today's/yesterday's values may still change → always refetch last 2 days
        if refetch or not out.exists() or (end - d).days <= 1:
            ds = d.isoformat()
            write_json(out, {
                "date": ds,
                "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
                "hrv": _safe(api.get_hrv_data, ds),
                "rhr": _safe(api.get_rhr_day, ds),
                "sleep": _safe(api.get_sleep_data, ds),
            })
            n_well += 1
            time.sleep(sleep_s)
        d += dt.timedelta(days=1)
    return {"activities_listed": len(acts or []), "activities_new": n_new, "wellness_days": n_well}
