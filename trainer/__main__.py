"""CLI: python -m trainer <command>. See DESIGN §2.2."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from . import analysis, context, fit_import, normalize, plans
from .config import Paths, read_json, write_json
from .weeks import next_week, parse_date, shift_week, week_of


def _p(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):  # Windows console: avoid UnicodeEncodeError on å/ä/ö (C-T5)
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="trainer")
    ap.add_argument("--root", help="Project root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="copy *.example.* templates to real names if missing (D-015)")
    sub.add_parser("login")
    f = sub.add_parser("fetch"); f.add_argument("--days", type=int, default=21); f.add_argument("--refetch", action="store_true")
    sub.add_parser("import")
    sub.add_parser("normalize")
    sy = sub.add_parser("sync"); sy.add_argument("--days", type=int, default=21)
    st = sub.add_parser("status"); st.add_argument("--days", type=int, default=14)
    for name in ("checkin", "context", "new-plan"):
        x = sub.add_parser(name); x.add_argument("--week", default=None)
    v = sub.add_parser("validate"); v.add_argument("path")
    r = sub.add_parser("render"); r.add_argument("path")
    a = ap.parse_args(argv)
    paths = Paths(a.root) if a.root else Paths()
    paths.ensure()

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
            print(f"{out} finns redan." + (f" Fel: {errs}" if errs else " Giltig."))
        else:
            write_json(out, plans.checkin_template(week))
            print(f"Skapade {out}")
    elif a.cmd == "context":
        week = a.week or next_week()
        _, md = context.run(paths, week)
        print(md)
        print(f"[sparat] data/context/{week}.json + .md", file=sys.stderr)
    elif a.cmd == "new-plan":
        week = a.week or next_week()
        out = paths.plans / f"{week}.json"
        if out.exists():
            print(f"{out} already exists — revise it instead (CLAUDE.md E).", file=sys.stderr)
            return 1
        write_json(out, plans.skeleton(week))
        print(f"Skapade {out}")
    elif a.cmd in ("validate", "render"):
        plan = read_json(a.path)
        errs, warns = plans.validate(plan, paths, read_json(paths.profile))
        for w_ in warns:
            print(f"VARNING: {w_}")
        for e in errs:
            print(f"FEL: {e}")
        if errs:
            return 1
        if a.cmd == "validate":
            print("OK")
        else:
            from pathlib import Path
            out = Path(a.path).with_suffix(".md")
            out.write_text(plans.render(plan), encoding="utf-8")
            print(f"Renderade {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
