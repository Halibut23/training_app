# training_app — agent-driven training planning (PoC)

Claude is the coach; the Python tools fetch and analyse Garmin data. The work is spec-driven:

- `CLAUDE.md` — rules the agent always follows
- `docs/DESIGN.md` — design decisions, constraints, known bugs, nice-to-haves (living)
- `docs/COACHING_SPEC.md` — coaching rules with IDs (living)
- `data/athlete/profile.json` / `goals.json` — starting point and goals
- `plans/YYYY-Www.json|.md` — weekly plans · `log/coach_log.md` — decision log

Language (DESIGN D-008): code, schemas and docs are in English; plans, the coach log and athlete-facing text are in Swedish.

## Getting started (Windows, once)

```powershell
cd <path>\training_app
py -3.12 -m venv .venv      # requires Python >= 3.12 (garminconnect >= 0.3)
.venv\Scripts\activate
pip install -r requirements.txt
python -m trainer init      # creates profile/goals/season_plan from *.example.* if missing
copy .env.example .env      # fill in GARMIN_EMAIL / GARMIN_PASSWORD in .env
python -m trainer login     # interactive login (MFA code if you have it enabled)
python -m trainer sync --days 120   # first fetch: ~4 months of history
python -m unittest discover -s tests
```

Login tokens are stored in `.garmin_tokens/`, so `sync` then works without a password until they expire.

## Every week

Tell Claude: **"Gör veckoplanen"** (make the weekly plan). The agent runs `sync` → asks for the check-in (primary limiter, RPE, strength, sleep) → `context` → writes the plan → `validate`/`render` → logs the decision.
If the agent can't reach Garmin from its environment: run `python -m trainer sync` yourself first.

Other requests:
- **"Revidera planen"** (revise the plan) mid-week — new revision number; completed days are left untouched.
- **"Ändra mål …"** (change goal …) — updates `goals.json` with history and re-checks the plan.
- No Garmin access? Put `.fit` files in `data/inbox/` or fill in `data/inbox/manual_sessions.csv`, then run `python -m trainer import` and `normalize`.

## Commands
`login · fetch · import · normalize · sync · status · checkin · context · new-plan · validate · render` — see `docs/DESIGN.md` §2.2.

## Git and personal data
The code, schemas, tests and SDD specs (`CLAUDE.md`, `docs/*.md`) are version-controlled. All personal data (profile, goals, season plan, check-ins, plans, coach log, Garmin data, hand-off, `.env`, tokens) is git-ignored; see `.gitignore` and `docs/DESIGN.md` D-015.
The specs refer to personal values by key (e.g. `profile.run.easy_hr_cap_bpm`). The `TestPrivacy` test flags names, PB times or goal titles that end up in a tracked file.
