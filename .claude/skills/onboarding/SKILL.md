---
name: onboarding
description: New athlete or "kom igång" / "get started", or `python -m trainer brief` shows the onboarding banner.
---

# Onboarding a new athlete (DESIGN D-017, D-020)
Rules in `CLAUDE.md` (A6, B1–B3, C1–C4, F1–F8) apply throughout.

Goal: a real `profile.json`, `goals.json` and `season_plan.md` built from the athlete's answers and their own data. Keep it conversational and short; group questions, max ~5 per message.
0. **Language.** Reply in the language the athlete writes in (Swedish or English; if unclear, ask). Confirm it and store it as `profile.language` in step 5. All later questions, files and summaries use it.
1. **Setup.** Check that `pip install -r requirements.txt` has been done. If profile/goals/season plan are missing, run `python -m trainer init`. The athlete creates `.env` from `.env.example` and runs `python -m trainer login` themselves (B1–B3).
2. **History.** Ask the athlete to run `python -m trainer sync --days 120` (or put `.fit` files / `manual_sessions.csv` in `data/inbox/`). Then `python -m trainer status --days 120 --allow-example` for an overview.
3. **Intake interview** — only what data can't tell:
   - Name (for `profile.athlete`), sports, equipment (power meter, smart trainer, chest strap vs wrist HR — C-M7).
   - Weekly time budget (normal range), strength sessions/week, fixed constraints (days, work, travel), sessions they already have (clubs, group rides).
   - Goals: event/metric, date, priority; test protocol for performance goals.
   - Known anchors **with date and how measured**: FTP, threshold/race paces, PBs, LTHR, max HR (chest strap only — C3a).
   - Primary limiter: current injury/niggle/recurring problem, or none. History of injuries that affected training.
   - Last 3–6 months: typical week, longest/hardest sessions, breaks. Preferences (indoor/outdoor, favourite session formats).
4. **Derive from data, don't guess.** From synced history: typical hours and sport mix per week, reference sessions (`activity_id`), RHR/HRV/sleep baselines (wellness). Zones are computed only from a confirmed anchor (R-BIKE-02). Anything unknown → `null` / `"unknown"` and listed as an open question (F5). If there is no limiter, write that in `profile.injury.primary_limiter`; the check-in still records run status (🟢 = no symptoms, R-RUN-02).
5. **Write** `profile.json` (set `source` to `"onboarding <date>"`, `as_of`, first `change_log` entry), `goals.json` (each goal with a `history` entry), `season_plan.md` (priority order per R-PRI-01, periodisation towards goal dates, COACHING_SPEC §7). Remove all `Exempel` text. Validate JSON against `schemas/`.
6. **Log and hand over.** Start `log/coach_log.md` with an onboarding entry (sources, derived values, assumptions, open questions). The log is newest-first, entries start with `## YYYY-MM-DD — title` (D-021). Summarise the profile and season plan to the athlete for confirmation, then continue with skill `weekly-loop` for the next week.
