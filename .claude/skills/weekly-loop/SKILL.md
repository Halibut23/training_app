---
name: weekly-loop
description: "gör veckoplanen", "analysera veckan", weekly review or planning next week.
---

# Weekly loop (default procedure, DESIGN D-019/D-020)
Rules in `CLAUDE.md` (C2, F1–F8, G) apply throughout. Start from the `trainer brief` output already read at session start.

**Reading list (tier 1 — planning / analysis).** In addition to `CLAUDE.md` + `brief`:
- `docs/COACHING_SPEC.md`
- `data/context/<W>.md` — regenerate first (step 3). It summarises profile, goals, previous plan, compliance, check-in and flags: do **not** re-read those files for facts it contains.
- `data/athlete/season_plan.md` only if periodisation matters.
- Not needed: `docs/DESIGN.md`, `schemas/*.json` (only on a validation error), `plans/<prev>.json` (only when revising), the full coach log.

**Procedure**
1. `python -m trainer sync` (fetch + import + normalize). If Garmin is unreachable from your shell, ask the athlete to run `python -m trainer sync` locally, or use files in `data/inbox/`.
2. Ask the athlete for the check-in — **briefly**, only what data can't tell: primary-limiter status per run (grön/gul/röd + next morning), RPE on key sessions, strength done?, sleep/stress/illness, goal changes, constraints next week (travel, work), **and sessions the athlete has already scheduled themselves** (group rides, races, own plans) — plan around them, never on top of them. Write it with `python -m trainer checkin --week <W>` + fill in.
3. `python -m trainer context --week <next W>` → read `data/context/<W>.md`.
4. Analyse per COACHING_SPEC §8: compare with relevant references, interpret, choose **one** adjustment type.
5. Write `plans/<W>.json` (start from `python -m trainer new-plan --week <W>`) including `placement_rules`, then `validate` and `render`.
6. Append to `log/coach_log.md` (in `profile.language`) as the **newest entry at the top**, heading `## YYYY-MM-DD — title`: week, data highlights, decision, adjustment type, rules applied, open questions.
7. Give the athlete a short summary in chat: what changed vs last week and why (≤ 10 lines), and point to `plans/<W>.md`.
