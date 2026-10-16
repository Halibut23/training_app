"""Coach-log parsing and archiving (DESIGN D-021). Stdlib only (D-013).

Contract: `log/coach_log.md` is a header block followed by entries that start with `## YYYY-MM-DD — title`.
Newest first is the convention, but nothing here trusts file order: entries are sorted by heading date.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b", re.M)
ENTRY_START = re.compile(r"^## ", re.M)


def split_log(text: str) -> tuple[str, list[dict]]:
    """Return (header, entries). Each entry: {date: 'YYYY-MM-DD' | '', heading, text (raw, incl. heading)}."""
    starts = [m.start() for m in ENTRY_START.finditer(text)]
    if not starts:
        return text, []
    header = text[:starts[0]]
    entries = []
    for a, b in zip(starts, starts[1:] + [len(text)]):
        raw = text[a:b]
        heading = raw.split("\n", 1)[0].strip()
        m = HEADING.match(raw)
        entries.append({"date": m.group(1) if m else "", "heading": heading, "text": raw})
    return header, entries


def sort_newest_first(entries: list[dict]) -> list[dict]:
    """Stable sort by heading date, descending; undated entries last."""
    return sorted(entries, key=lambda e: e["date"], reverse=True)


def read_entries(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return sort_newest_first(split_log(path.read_text(encoding="utf-8"))[1])


def archive(log: Path, days: int = 60, today: dt.date | None = None) -> dict:
    """Move entries older than `days` into `log/archive/YYYY-MM.md`. Idempotent. Undated entries stay."""
    log = Path(log)
    if not log.exists():
        return {"moved": 0, "kept": 0, "files": []}
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    header, entries = split_log(log.read_text(encoding="utf-8"))
    old = [e for e in entries if e["date"] and e["date"] < cutoff]
    keep = [e for e in entries if e not in old]
    if not old:
        return {"moved": 0, "kept": len(keep), "files": []}
    by_month: dict[str, list[dict]] = {}
    for e in old:
        by_month.setdefault(e["date"][:7], []).append(e)
    out_dir = log.parent / "archive"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for month, new in sorted(by_month.items()):
        f = out_dir / f"{month}.md"
        ahead, have = split_log(f.read_text(encoding="utf-8")) if f.exists() else (f"# Coach log archive {month}\n\n", [])
        seen = {e["text"].strip() for e in have}
        merged = sort_newest_first(have + [e for e in new if e["text"].strip() not in seen])
        f.write_text(ahead + "".join(_terminated(e["text"]) for e in merged), encoding="utf-8")
        files.append(str(f.relative_to(log.parent.parent)).replace("\\", "/"))
    log.write_text(header + "".join(e["text"] for e in keep), encoding="utf-8")  # raw slices: kept text is untouched
    return {"moved": len(old), "kept": len(keep), "files": files}


def _terminated(text: str) -> str:
    return text if text.endswith("\n\n") else text.rstrip("\n") + "\n\n"
