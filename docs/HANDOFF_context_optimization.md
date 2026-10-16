# Hand-off — optimise how the agent reads context (target spec 0.6.0)

**For:** the coding agent implementing this in `training_app`.
**Status:** ready to implement. The analysis is done; this document is the spec.
**Follow `CLAUDE.md` while you work**, in particular A1–A6 (spec in the same change, tests, **no personal values in tracked files**) and B1 (never read `.env` / `.garmin_tokens/`). This file is tracked: it uses keys and invented values only.

---

## 1. Problem

At the start of every session, `CLAUDE.md` §0 makes the agent read about 76k chars (≈ 20–22k tokens) before it does anything. The weekly loop adds about 17k more. This happens even for a one-line message like "RPE was 7".

| Read at session start | ≈ chars | Actually needed for |
|---|---:|---|
| `CLAUDE.md` (auto-loaded) | 9.4k | always — but §0b onboarding (~2.5k) and §A (SDD) are rarely needed |
| `docs/DESIGN.md` | 21.7k | **code/spec changes only** (changelog, fixed bugs, layout, CLI) |
| `docs/COACHING_SPEC.md` | 8.6k | planning / analysis |
| `profile.json` + `goals.json` + `season_plan.md` | 11.9k | planning — but `context` already summarises them |
| latest `plans/*.json` | 12–17k | revising a plan |
| `log/coach_log.md` (read whole) | 12.3k | top 3 entries ≈ 2k |
| weekly loop: `data/context/W.md` + schemas | 6.3k + 10.7k | planning |

Other problems:
- **The same facts are read from several places.** `trainer context` copies profile anchors, goals, the previous plan and the check-in. The agent reads those *and* the raw files, and the context file can be stale (generated before a later plan revision).
- **The coach log is ambiguous.** It is documented as newest-first, but at least one entry sits at the bottom out of order. "Last ~3 entries" means different things depending on where you look, so the agent reads the whole file, which grows without bound.
- **Reference deltas are noisy.** `analysis.compare` emits every delta (Δkm, Δmin, Δavg_w…) for every session type. Sessions are 7.6k of the 21.7k context JSON.
- **Some files are easy to read by mistake.** `data/raw/garmin/wellness/*.json` is ~300 KB per file (39 MB total). `.venv/` and `.mypy_cache/` sit in the root. `/traningsplan_handoff.md` duplicates `docs/reference/traningsplan_handoff.md` (18k).

## 2. Goal and acceptance criteria

| Scenario | Today | Target |
|---|---:|---:|
| Quick question / check-in note | ~76k chars | **≤ 10k chars** (`CLAUDE.md` + `brief`) |
| Weekly loop (§D) | ~93k chars | **≤ 30k chars** |
| `CLAUDE.md` size | 9.4k | **≤ 5,000 chars** (enforced by test) |
| `trainer brief` output on real data | – | **≤ 4,000 chars** (enforced by test on fixture) |

Also required:
- Every rule ID (B1–B3, C1–C4, C3a/C3b, F1–F8, R-…) still exists and means the same thing. Procedures move; rules do not.
- `python -m unittest discover -s tests` passes. `TestPrivacy` passes and covers the new tracked files.
- Measure before and after with the script in §7 and put the numbers in the DESIGN changelog line.

## 3. Before you start

1. **Restore the stashed B-009 fix first.** `stash@{0}` (on `main` @ 8ea07dd) holds a finished, uncommitted bug fix that the current plans and coach log already rely on:
   - `trainer/analysis.py` — `compliance()` rewritten into three passes:
     1. explicit `actual_activity_ids` win, and sessions with `status: missed` are respected;
     2. same `session_type` inside the week, with a lookback (default now **3 days**, was 7) **only for key sessions**;
     3. same sport inside the week.

     Supporting/optional sessions never borrow last week's activities. Unplanned activities are listed from the plan week only.
   - `tests/test_trainer.py` — `test_compliance_order_independent` now passes `lookback_days=7`. New tests: `test_compliance_no_borrowing_for_supporting` and `test_compliance_explicit_ids_win`.
   - `docs/DESIGN.md` — B-009 row in §7 (Fixed) and a changelog row (it duplicates version `0.3.4`; renumber it `0.5.1` when committing).

   Steps: `git stash pop` → run tests → commit as `Fix B-009: compliance matching passes` → then branch `feature/context-optimization`. If the pop conflicts, stop and ask the owner.
   *Line endings:* seen from a Linux shell, `git status` may list `DESIGN.md`, `test_trainer.py` and `analysis.py` as modified even when they aren't. These are CRLF-only differences (`git diff --ignore-cr-at-eol` is empty). Don't commit line-ending churn; use the Windows git (`core.autocrlf=true`) for commits.
2. Run the test suite and record the baseline. Run the §7 measurement and record the baseline.
3. Read `docs/DESIGN.md` in full **once** for this task (it is a system change). Then read `trainer/context.py`, `trainer/analysis.py` (`compact`, `compare`, `wellness_summary`, `flags`), `trainer/__main__.py`, `trainer/i18n.py` and `tests/test_trainer.py`.
4. You may read personal files (`data/athlete/*`, `plans/*`, `log/*`) to test output on real data. **Never copy values from them into tracked files** (A6).

## 4. Work packages (in order; tests green after each)

### WP1 — Spec first (A1/A2)
Edit `docs/DESIGN.md`:
- **D-019 Tiered context reading.** The session start reads `CLAUDE.md` + `python -m trainer brief` only. Further files are read per task tier (§5 below). `data/context/W.md` is the single analysis input for planning; the agent does not re-read profile/goals/plan JSON for facts it contains.
- **D-020 Procedures as on-demand files.** Onboarding, the weekly loop and mid-week revision move from `CLAUDE.md` to `.claude/skills/<name>/SKILL.md`. `CLAUDE.md` keeps rules and an index pointing to these files, so it also works in clients that don't auto-load skills. Rule IDs stay unchanged. Procedure references change from "CLAUDE.md §0b/§D/§E" to "skill `onboarding` / `weekly-loop` / `revise-plan`".
- **D-021 Coach-log contract and read guards.**
  - The log is newest-first; `brief` sorts entries by heading date and does not trust file order.
  - Entries older than 60 days move to `log/archive/YYYY-MM.md` via `trainer log-archive`.
  - `.claude/settings.json` denies reads of secrets, raw data and tool caches. This is defence in depth for B1/C1; the text rules stay because not every client honours it.
- §2.1 layout: add `.claude/settings.json` (tracked), `.claude/skills/` (tracked), `log/archive/` (ignored, covered by `log/*`).
- §2.2 CLI: add `brief` and `log-archive`.
- §9 changelog: `0.6.0` with the before/after measurements.
- Update `COACHING_SPEC.md` line "The agent reads it in step 0 of CLAUDE.md" → "via `trainer brief` / the context file". Update §8 step 1 so that the previous plan is read via the context file (and `plans/W.json` only when revising).

### WP2 — `python -m trainer brief`
New module `trainer/brief.py`, CLI command `brief [--week W]` (default: current ISO week). It prints Markdown to stdout in `profile.language` (all strings in `i18n.py`, both languages). It **writes no files** (always fresh, never stale). It is not guarded: on a missing or example profile, it prints an onboarding banner as its first line ("Profile is missing / invented example → run skill `onboarding`") and the rest of the sections it can build. This replaces §0 step 5.

Sections, in this order, each kept short:

1. **State.** Profile state (`ok` / `example` / `missing`), language, `profile.as_of`. Data freshness: latest activity date, latest wellness date, days since then. If it is > 3 days → a line saying "sync before analysing".
2. **Anchors.** One line each:
   - FTP and its date (from `change_log` if available)
   - zones as compact ranges on one line
   - `run.easy_hr_cap_bpm`, `run.easy_pace_min_km`, `run.lthr_is_calibrated`, max HR
   - `injury.current_status` and `injury.primary_limiter`
   - `budget` (normal range)
3. **Active goals.** Priority, title, deadline, days left (sorted by priority).
4. **Current plan.** Pick `plans/W.json` if it exists, else the latest plan ≤ W. Show:
   - week, revision, status, `adjustment_type`, `focus`
   - a table with one row per session: `id`, date, title, priority, status (`planned` if absent), duration
   - `placement_rules` as one line
   - the last `revision_history` entry
5. **Recovery (3d vs baseline).** HRV, RHR and sleep from `analysis.wellness_summary`, one line each.
6. **Check-in for W.** Present / missing. If present: the last limiter status and how many sessions have RPE.
7. **Coach log — latest 3.** Split `log/coach_log.md` on `^## ` headings, parse the leading `YYYY-MM-DD`, sort by date descending (stable), and print the 3 newest entries **truncated to ~600 chars each**, ending with "…(see log)".
8. **Open questions.** Rows in DESIGN §6 whose question is not struck through/resolved. Print IDs and short text only.
9. **Next step hint.** A static line: "planning → skill `weekly-loop`; revision → `revise-plan`; code/spec → read DESIGN.md".

Hard limit: 4,000 chars. If it is exceeded, truncate the log entries first, then the session table titles.

Tests (use the fixture project, invented data):
- `test_brief_sections_and_size`: both languages, all headings present, `len(out) <= 4000`.
- `test_brief_example_profile_banner`: on the example profile → exit 0 and the banner on line 1.
- `test_brief_log_sorted_by_date`: a synthetic log with one old entry at the bottom and one new entry in the middle → the 3 newest are shown in the right order.
- `test_brief_missing_files`: no plan, no check-in, no log → no crash; "–"/missing markers.
- i18n: the existing `test_both_languages_have_same_keys` must keep passing.

### WP3 — Trim the context file
- In `analysis.py`, add `RELEVANT_DELTAS` per session-type prefix:
  - `bike_*` → `np, if, tss, work_w, work_hr, w_per_bpm, decoupling_pct, min`
  - `run_*` → `pace, avg_hr, km, min, tss`
  - `strength` → `min, avg_hr`
  - `other` → `min, tss`
- `compare()` keeps computing all deltas (the JSON stays complete for future tools, D-007). `context.to_markdown` prints only the relevant ones.
- The Markdown session line drops `name` if it equals the type label, and drops `km` for bike indoor sessions.
- Add a one-line note under the title of `W.md` (i18n): "Profile, goals, previous plan and check-in are summarised here — don't re-read those files for planning (D-019)."
- Tests:
  - `test_context_md_relevant_deltas`: a bike session line contains no `Δpace`; a run line contains no `Δnp`.
  - The existing context tests stay green.
  - Assert that the W.md size drops on the fixture compared with the current output (record the current size in the test as an upper bound).

### WP4 — Coach log
- Add `python -m trainer log-archive [--days 60]`. It moves entries whose heading date is older than N days into `log/archive/YYYY-MM.md` (appending, newest-first inside each file) and keeps the header block of `coach_log.md`. It is idempotent.
- Reuse the same entry parser as `brief` (put it in `trainer/coachlog.py`).
- One-off migration (personal file, not tracked): reorder `log/coach_log.md` newest-first by heading date **without changing any entry text**. Show the owner a diff of the heading order before saving.
- Tests: `test_log_archive_moves_old_entries` and `test_log_archive_idempotent` (synthetic log in a temp dir).

### WP5 — Slim `CLAUDE.md` + skills
Create these files (tracked, English, generic, no personal values):

| File | Content (moved, not rewritten — keep wording and IDs) | Frontmatter `description` (when to use) |
|---|---|---|
| `.claude/skills/onboarding/SKILL.md` | current §0b, steps 0–6 | "New athlete or 'kom igång' / 'get started', or `brief` shows the onboarding banner." |
| `.claude/skills/weekly-loop/SKILL.md` | current §D steps 1–7, plus the reading list for the planning tier (§5) | "'gör veckoplanen', 'analysera veckan', weekly review or planning next week." |
| `.claude/skills/revise-plan/SKILL.md` | current §E | "'revidera planen', mid-week changes, illness, moved sessions." |

Each `SKILL.md` starts with YAML frontmatter (`name`, `description`).

New `CLAUDE.md` (≤ 5,000 chars), structure:
1. Role + language rule (current header, unchanged in meaning).
2. **§0 Start of every session:** run `python -m trainer brief` and read its output. Do **not** read DESIGN.md, the plan JSON or the full coach log unless the task tier requires it (table from §5).
3. **Procedures index:** onboarding / weekly loop / revision → "read `.claude/skills/<name>/SKILL.md`" (explicit path, so it works without skill auto-loading).
4. §A SDD — compressed to ≤ 6 lines. Keep A1–A6 IDs; A6 (privacy) keeps its full sentence.
5. §B security, §C data integrity (C1–C4, C3a, C3b), §F guardrails (F1–F8), §G style: keep the IDs and meaning, tighten the wording. Add to C1: "Never read `data/raw/**` or `data/derived/*.jsonl` directly; use `status`, `brief`, `context`."

Then update every reference to moved sections:
- `grep -rn "CLAUDE.md" trainer tests docs README.md`. Known hits:
  - `__main__.py` (§0b, E)
  - `context.py` docstring (D3)
  - `i18n.py` `f_no_report` (F1 — unchanged)
  - DESIGN D-017 / §2.1.1
  - `README.md` line on "Get started"
- Historic changelog rows in DESIGN stay as they are (they describe the past).

Tests:
- `test_claude_md_size`: ≤ 5,000 chars.
- `test_skills_have_frontmatter`: each `SKILL.md` has `name` and `description`.
- `test_rule_ids_preserved`: B1, B3, C1, C3a, C3b, F1…F8 still appear in `CLAUDE.md`.
- Extend `TestPrivacy.TRACKED` with `.claude/**/*.md` and `.claude/*.json`.

### WP6 — Read guards and clean-up
- Create `.claude/settings.json`:
  ```json
  {"permissions": {"deny": [
    "Read(./.env)", "Read(./.garmin_tokens/**)",
    "Read(./data/raw/**)", "Read(./.venv/**)", "Read(./.mypy_cache/**)"
  ]}}
  ```
  Add `.claude/settings.local.json` to `.gitignore`.
- Remove `/traningsplan_handoff.md` (root). First verify with `cmp` that it is identical to `docs/reference/traningsplan_handoff.md`, and ask the owner before deleting.
- Test `test_settings_denies_secrets`: the JSON parses and contains the `.env` and `.garmin_tokens` denies.

### WP7 — Verify
1. Run the full test suite.
2. Run `python -m trainer brief` on the real data and check: athlete language, ≤ 4,000 chars, correct current plan, log entries newest-first, freshness line. Show the output to the owner (it is personal; do not commit it).
3. Regenerate `python -m trainer context --week <next W>` and compare the size against the baseline.
4. Run §7 again. The acceptance numbers in §2 must hold. Write them in the DESIGN changelog row.
5. Dry run: start a fresh session with the new `CLAUDE.md` and ask a quick question. Confirm that only `CLAUDE.md` + `brief` were read.

## 5. Reading tiers (copy into `CLAUDE.md` §0 and the `weekly-loop` skill)

| Tier | Trigger | Read |
|---|---|---|
| 0 Always | every session | `CLAUDE.md` (auto) + `trainer brief` output |
| 1 Planning / analysis | weekly loop, "how did the week go", session review | + `docs/COACHING_SPEC.md`, `data/context/<W>.md` (regenerate first), `season_plan.md` if periodisation matters |
| 2 Revise plan | mid-week change | + `plans/<W>.json` (the file being edited), `schemas/plan.schema.json` only on validation errors |
| 3 Profile / goal change | new FTP, PB, goal change | + `profile.json` / `goals.json` (the file being edited) |
| 4 System change | code, CLI, schema, spec | + `docs/DESIGN.md`, relevant code and tests |
| Never | – | `.env`, `.garmin_tokens/`, `data/raw/**`, `data/derived/*.jsonl` (use the CLI), `docs/reference/` (unless the owner asks) |

## 6. Out of scope / don't
- Don't change coaching rules, metrics, classification or plan schema semantics.
- Don't edit `data/raw`/`data/derived` (C1). Don't rewrite coach-log entry text. The only allowed change to the log is the order (WP4).
- Don't add dependencies (D-013: stdlib only for core).
- Don't put real values in examples, tests or specs. Use invented ones (e.g. "FTP 250 W").

## 7. Measurement script (run before and after; output is sizes only, safe to share)
```python
from pathlib import Path
R = Path(".")
tiers = {
    "today_session_start": ["CLAUDE.md", "docs/DESIGN.md", "docs/COACHING_SPEC.md",
        "data/athlete/profile.json", "data/athlete/goals.json", "data/athlete/season_plan.md",
        sorted(R.glob("plans/*.json"))[-1], "log/coach_log.md"],
    "weekly_loop_extra": [sorted(R.glob("data/context/*.md"))[-1],
        "schemas/plan.schema.json", "schemas/checkin.schema.json"],
}
for name, files in tiers.items():
    n = sum(len(Path(f).read_text(encoding="utf-8")) for f in files)
    print(f"{name}: {n:,} chars ≈ {n // 3.5:,.0f} tokens")
# after: add len(CLAUDE.md) + len(output of `python -m trainer brief`) for tier 0,
# and tier 0 + COACHING_SPEC + context/W.md for the weekly loop.
```

## 8. Open questions for the owner (ask, don't guess)
- OK to pop and commit the stashed B-009 fix (§3.1) before starting?
- OK to delete the root `traningsplan_handoff.md` duplicate?
- Archive threshold: is 60 days right?
- Should `brief` also include the R-* flags for the current week? (Proposal: no for now. They are in the context file, and computing them makes `brief` slower and longer.)
