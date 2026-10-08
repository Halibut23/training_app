"""CLI: python -m trainer <command>. See DESIGN §2.2."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from . import analysis, context, fit_import, normalize, plans
from .config import Paths, profile_state, read_json, write_json
from .i18n import lang_of
from .weeks import next_week, parse_date, shift_week, week_of


def _p(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


GUARDED = ("checkin", "context", "new-plan")   # refuse on example/missing profile (D-017)
WARNED = ("status", "validate", "render")


def _profile(paths: Paths) -> dict:
    return read_json(paths.profile) if paths.profile.exists() else {}


def _profile_guard(paths: Paths, cmd: str, allow_example: bool) -> int | None:
    state = profile_state(paths)
    if state == "ok" or allow_example or cmd not in GUARDED + WARNED:
        return None
    msg = ("data/athlete/profile.json is missing — run 'python -m trainer init'" if state == "missing" else
           "data/athlete/profile.json is still the invented example")
    msg += "; onboard the athlete first (CLAUDE.md §0b, DESIGN D-017). Override: --allow-example."
    if cmd in GUARDED:
        print(f"ERROR: {msg}", file=sys.stderr)
        return 3
    print(f"WARNING: {msg}", file=sys.stderr)
    return None


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):  # Windows console: avoid UnicodeEncodeError on å/ä/ö (C-T5)
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="trainer")
    ap.add_argument("--root", help="Project root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--allow-example", action="store_true",
                        help="run on the invented example profile (demo/testing only, D-017)")

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    add("init", help="copy *.example.* templates to real names if missing (D-015)")
    add("login")
    f = add("fetch"); f.add_argument("--days", type=int, default=21); f.add_argument("--refetch", action="store_true")
    add("import")
    add("normalize")
    sy = add("sync"); sy.add_argument("--days", type=int, default=21)
    st = add("status"); st.add_argument("--days", type=int, default=14)
    for name in ("checkin", "context", "new-plan"):
        x = add(name); x.add_argument("--week", default=None)
    v = add("validate"); v.add_argument("path")
    r = add("render"); r.add_argument("path")
    a = ap.parse_args(argv)
    paths = Paths(a.root) if a.root else Paths()
    paths.ensure()
    rc = _profile_guard(paths, a.cmd, a.allow_example)
    if rc is not None:
        return rc

    if a.cmd == "init":
        import shutil
        for ex in sorted(paths.data.rglob("*.example.*")):
            real = ex.with_name(ex.name.replace(".example", ""))
            if real.exists():
                print(f"already exists: {real.relative_to(paths.root)}")
            else:
                shutil.copy2(ex, real)
                print(f"created {real.relative_to(paths.root)} from example — edit it with your own values")
        if not paths.env.exists():
            print("Copy .env.example to .env and fill in your Garmin credentials.")
    elif a.cmd == "login":
        from .garmin_client import login
        login(paths)
    elif a.cmd in ("fetch", "sync"):
        from .garmin_client import GarminUnavailable, fetch
        try:
            _p({"fetch": fetch(paths, days=a.days, refetch=getattr(a, "refetch", False))})
        except GarminUnavailable as e:
            print(f"[garmin] {e}", file=sys.stderr)
            if a.cmd == "fetch":
                return 2
        if a.cmd == "sync":
            _p({"import": fit_import.run(paths), "normalize": normalize.run(paths)})
    elif a.cmd == "import":
        _p(fit_import.run(paths))
    elif a.cmd == "normalize":
        _p(normalize.run(paths))
    elif a.cmd == "status":
        acts, _ = normalize.load(paths)
        since = dt.date.today() - dt.timedelta(days=a.days)
        for x in acts:
            if parse_date(x["date"]) >= since:
                c = analysis.compact(x)
                print(f"{c['date']} {c.get('type', ''):15} {c.get('min', 0):>4} min  "
                      + " ".join(f"{k}={c[k]}" for k in ("km", "np", "if", "tss", "avg_hr", "pace") if k in c))
        w = week_of(dt.date.today())
        _p(analysis.weekly_summary(acts, [shift_week(w, -i) for i in range(3, -1, -1)]))
    elif a.cmd == "checkin":
        week = a.week or week_of(dt.date.today())
        out = paths.checkins / f"{week}.json"
        if out.exists():
            errs = plans.validate_checkin(read_json(out), paths)
            print(f"{out} already exists." + (f" Errors: {errs}" if errs else " Valid."))
        else:
            write_json(out, plans.checkin_template(week))
            print(f"Created {out}")
    elif a.cmd == "context":
        week = a.week or next_week()
        _, md = context.run(paths, week)
        print(md)
        print(f"[saved] data/context/{week}.json + .md", file=sys.stderr)
    elif a.cmd == "new-plan":
        week = a.week or next_week()
        out = paths.plans / f"{week}.json"
        if out.exists():
            print(f"{out} already exists — revise it instead (CLAUDE.md E).", file=sys.stderr)
            return 1
        write_json(out, plans.skeleton(week, lang=lang_of(_profile(paths))))
        print(f"Created {out}")
    elif a.cmd in ("validate", "render"):
        plan = read_json(a.path)
        errs, warns = plans.validate(plan, paths, read_json(paths.profile))
        for w_ in warns:
            print(f"WARNING: {w_}")
        for e in errs:
            print(f"ERROR: {e}")
        if errs:
            return 1
        if a.cmd == "validate":
            print("OK")
        else:
            from pathlib import Path
            out = Path(a.path).with_suffix(".md")
            out.write_text(plans.render(plan, lang_of(_profile(paths))), encoding="utf-8")
            print(f"Rendered {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
