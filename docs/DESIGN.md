# DESIGN — Agent-driven training planner (PoC)

> **Living document.** This is the single source of truth for design choices, constraints, known bugs and nice-to-haves.
> Any change to architecture, data formats, workflow or coaching logic MUST be reflected here *in the same change* (see `CLAUDE.md`, rule A1).
> Domain/coaching rules live in [`COACHING_SPEC.md`](COACHING_SPEC.md); this file covers the system.

| | |
|---|---|
| Owner | see git history |
| Status | PoC |
| Last updated | 2026-10-08 |
| Spec version | 0.3.5 |

---

## 1. Purpose and scope

**Goal of the PoC:** prove the feedback loop

```
initial condition ─► goals ─► weekly plan ─► training (Garmin) ─► data + check-in ─► analysis ─► revised plan
       ▲                ▲                                                                         │
       └── profile updates (new FTP, PBs)   goal adjustments at any time ◄────────────────────────┘
```

**In scope:** fetching Garmin data, normalising it, computing load metrics, comparing sessions to relevant references, building an analysis context for the agent, and producing validated weekly plans (JSON + Markdown).

**Out of scope (PoC):** UI, multi-user, hosted service, automatic push of workouts to Garmin, medical advice.

## 2. Architecture

The "agent" is Claude (Cowork / Claude Code) operating in this folder, steered by `CLAUDE.md`. Python provides deterministic tools; Claude provides judgement.

```
Garmin Connect ──(garminconnect lib)──► data/raw/garmin/…   (immutable raw JSON)
FIT / CSV files ──(data/inbox)────────► data/raw/fit/…, data/inbox/manual_sessions.csv
                                             │
                                  python -m trainer normalize
                                             ▼
                         data/derived/activities.jsonl, wellness.jsonl   (rebuildable)
                                             │
 data/athlete/profile.json ─┐                │
 data/athlete/goals.json ───┼──► python -m trainer context --week W ──► data/context/W.json + .md
 data/checkins/W.json ──────┤
 plans/<prev week>.json ────┘
                                             ▼
                                  Claude analyses (COACHING_SPEC)
                                             ▼
                plans/W.json ──validate──► render ──► plans/W.md   + log/coach_log.md entry
```

### 2.1 Folder layout

| Path | Content | Edited by | Git |
|---|---|---|---|
| `CLAUDE.md` | Agent operating rules (always followed) | Human + agent (with log) | ✅ tracked |
| `docs/DESIGN.md` | This document | Agent + human | ✅ tracked |
| `docs/COACHING_SPEC.md` | Normative, generic coaching rules with IDs | Agent + human | ✅ tracked |
| `docs/reference/` | Original personal hand-off (read-only source) | Nobody | 🚫 ignored |
| `data/athlete/*.example.*` | Invented example profile/goals/season plan (templates + test fixtures) | Agent + human | ✅ tracked |
| `data/athlete/profile.json` | Initial condition: history, zones, references, constraints | Agent (logged) | 🚫 ignored |
| `data/athlete/goals.json` | Goals with change history | Agent on user request | 🚫 ignored |
| `data/athlete/season_plan.md` | Priorities + periodisation (dates, races) | Agent (logged) | 🚫 ignored |
| `data/raw/` | Raw fetched/imported data, never edited | Tools only | 🚫 ignored |
| `data/inbox/` | Drop zone for `.fit` files and `manual_sessions.csv` (template: `manual_sessions.example.csv`) | Human | 🚫 ignored (except example) |
| `data/derived/` | Normalised data — can always be deleted and rebuilt | Tools only | 🚫 ignored |
| `data/checkins/` | Subjective weekly check-ins (RPE, limiter status, sleep, notes) | Agent from conversation | 🚫 ignored |
| `data/context/` | Analysis bundles fed to the agent | Tools only | 🚫 ignored |
| `plans/` | `YYYY-Www.json` (source of truth) + `.md` (rendered) | Agent | 🚫 ignored |
| `log/coach_log.md` | Chronological decisions, in Swedish | Agent | 🚫 ignored |
| `schemas/` | JSON Schemas for plan, check-in, goals | Agent + human | ✅ tracked |
| `trainer/`, `tests/` | Python package (stdlib + optional libs) and tests | Agent + human | ✅ tracked |
| `.env`, `.garmin_tokens/`, `.venv*/` | Secrets, tokens, local environment | Human / tools | 🚫 ignored |

Empty ignored folders keep a tracked `.gitkeep` so a fresh clone has the full structure.

### 2.1.1 Version control and personal data (D-015)
- **Rule:** everything that describes *the system* (code, schemas, tests, SDD specs, example files) is versioned; everything that describes *the athlete* (health, training data, plans, logs, goals, dates of personal events, credentials) is git-ignored.
- Tracked specs refer to athlete values by key (`profile.run.easy_hr_cap_bpm`) and use invented values in examples (CLAUDE.md A6).
- A fresh clone works with `python -m trainer init`, which copies `*.example.*` to the real file names if they are missing; tests run against the example files only.
- Before a commit: `git status` must show no files under `data/` (except `*.example.*`, `.gitkeep`), `plans/`, `log/`, `docs/reference/`.

### 2.2 CLI

```
python -m trainer init                  # copy *.example.* templates to profile/goals/season plan if missing
python -m trainer login                 # interactive, one-time (MFA) – run by the athlete in a terminal
python -m trainer fetch [--days 21]     # Garmin → data/raw (activities, laps, HRV, RHR, sleep)
python -m trainer import                # data/inbox → data/raw (FIT) / manual CSV
python -m trainer normalize             # raw → data/derived (idempotent rebuild)
python -m trainer status                # last 14 days + load summary (quick look)
python -m trainer checkin --week W      # creates check-in template
python -m trainer context --week W      # analysis bundle for planning week W
python -m trainer new-plan --week W     # plan skeleton
python -m trainer validate plans/W.json
python -m trainer render plans/W.json   # → plans/W.md
python -m trainer sync                  # fetch + import + normalize
```

## 3. Design decisions (ADR log)

Add new decisions at the bottom. Never delete; mark superseded ones.

| ID | Date | Decision | Rationale | Status |
|---|---|---|---|---|
| D-001 | 2026-10-01 | Claude is the agent; Python only does deterministic work (fetch, parse, metrics, validation, rendering). | Fastest PoC; no API key; judgement stays inspectable in plans/log. | Active |
| D-002 | 2026-10-01 | Spec-driven: `DESIGN.md` + `COACHING_SPEC.md` are updated in the same change as code/process. | User requirement (SDD). | Active |
| D-003 | 2026-10-01 | Garmin access via unofficial `garminconnect` library, with FIT/CSV inbox as fallback. | No official personal API; fallback keeps the loop alive if the library breaks. | Active |
| D-004 | 2026-10-01 | Credentials only in local `.env`; OAuth tokens cached in `.garmin_tokens/`. Both git-ignored; the agent never reads/prints them. | Security. MFA only needed at first login. | Active |
| D-005 | 2026-10-01 | Raw data immutable; derived data rebuildable from raw at any time. | Re-running with new metric logic must not require re-fetching. | Active |
| D-006 | 2026-10-01 | Load metrics computed by us from profile FTP (not Garmin's TSS) when power exists. | Garmin's FTP setting may differ from the working FTP (`profile.bike.ftp_w`); consistency across sources. Garmin TSS kept as `garmin_tss` for reference. | Active |
| D-007 | 2026-10-01 | Plans are JSON (schema-validated) + rendered Markdown. JSON is source of truth. | Machine-readable for future React view; Markdown for reading. | Active |
| D-008 | 2026-10-01 | Docs/code in English; plans, coach log and athlete-facing text in Swedish. | User preference. | Active |
| D-009 | 2026-10-01 | Plan revisions are kept inside the same week file (`revision` + `revision_history`), not new files. | One file per week; history still traceable. | Active |
| D-010 | 2026-10-01 | Coaching rules have stable IDs (e.g. `R-RUN-02`); plans cite rule IDs in `rationale.rules_applied`. | Traceability from decision to rule. | Active |
| D-011 | 2026-10-01 | Session matching uses a rule-based `session_type` classifier (IF + lap structure), references include hand-off sessions. | Compare like with like (hand-off §19 step 3). | Active |
| D-012 | 2026-10-01 | Subjective data (RPE, limiter traffic light, next-day response) is collected by the agent in conversation and stored as a weekly check-in. | Garmin does not hold these, and they dominate run decisions. | Active |
| D-013 | 2026-10-01 | Python stdlib only for core; `garminconnect`, `fitdecode`, `jsonschema` are optional imports with clear error messages. | Works in restricted environments (sandbox without PyPI). | Active |
| D-014 | 2026-10-01 | Use `garminconnect` ≥ 0.3 (native auth, `curl_cffi` TLS impersonation, tokens in `.garmin_tokens/garmin_tokens.json`); drop garth. Refines D-003/D-004. | garth-based login returns 401 since Garmin's Cloudflare/TLS-fingerprint change (Mar 2026). | Active |
| D-015 | 2026-10-01 | Git: system (code, schemas, tests, SDD specs, examples) tracked; athlete data (profile, goals, season plan, check-ins, plans, logs, raw/derived data, hand-off, secrets) ignored. Specs reference personal values by key. | Share the system with colleagues without exposing health/training data. | Active |
| D-016 | 2026-10-03 | Plans are order-independent menus: `placement_rules` (plan) and `completed_date` (session, may precede the week) in the schema; compliance matches planned↔done by session type over week start − 7 d … week end, never by exact date. | Athlete reorders sessions by purpose/intensity (R-GEN-11/12). | Active |

## 4. Constraints

### 4.1 Technical
- **C-T1** Python ≥ 3.10 for the core (stdlib only). **Garmin fetch requires Python ≥ 3.12** (garminconnect ≥ 0.3).
- **C-T2** `garminconnect` is unofficial and can break on Garmin changes; pin the version in `requirements.txt`.
- **C-T3** First Garmin login with MFA is interactive → must be done by the athlete in a local terminal (`python -m trainer login`). The agent's shell may also lack network access to Garmin → then the athlete runs `python -m trainer sync` and the agent continues from `normalize`/`context`.
- **C-T4** Garmin rate limits: fetch only the needed window (default 21 days; 120 days at bootstrap). Raw files are cached; already-fetched activities are skipped.
- **C-T5** Windows host is the primary environment: use `pathlib`, UTF-8 explicitly on all file I/O.

### 4.2 Domain
Athlete-specific constraints are data, not spec (D-015): budget and strength in `profile.budget`, run limits in `profile.run`, limiter in `profile.injury`, priorities/periodisation in `season_plan.md`. Rules that use them: `COACHING_SPEC.md`.
- **C-D1** This is load management, not medical advice.

### 4.3 Data/metric assumptions
- **C-M1** Bike TSS = h × IF² × 100 with IF = NP / FTP(profile at activity date).
- **C-M2** Run load = hrTSS = h × (avgHR / LTHR)² × 100. **LTHR is an estimate (`profile.run.lthr_bpm_estimate`)** until calibrated — see OQ-1.
- **C-M3** Strength load = 0.6 TSS/min (moderate, 1–3 RIR). Rough assumption.
- **C-M4** CTL/ATL = exponentially weighted daily load with 42 / 7 day time constants; TSB = CTL − ATL. Needs ≥ 6 weeks history to be meaningful.
- **C-M5** NP from laps is approximated by duration-weighted lap power when no per-second data exists.
- **C-M6** Max HR is only accepted as plausible when the lap containing it has an average HR within ~10 bpm of the max (sustained effort); isolated spikes are treated as sensor artefacts. A plausible new value is only a *candidate*: the athlete confirms the sensor (chest strap) before the profile is updated (CLAUDE.md C3a).
- **C-M7** HR source matters. Wrist (optical) HR is acceptable for easy sessions and long steady blocks (≈ ≥ 6 min at stable power); for short hard intervals, sprints and steep climbs it lags or locks onto cadence and is treated as low-confidence unless the check-in says `hr_sensor: strap`. Power and RPE are then primary.

## 5. Data contracts

### 5.1 Normalised activity (`data/derived/activities.jsonl`, one JSON per line)
```json
{"id": "garmin:123", "source": "garmin|fit|manual", "date": "2026-09-28", "start_local": "2026-09-28T17:30:00",
 "sport": "bike|run|strength|other", "environment": "indoor|outdoor|unknown", "name": "…",
 "duration_s": 3600, "distance_km": 30.1, "elevation_m": 120,
 "avg_hr": 140, "max_hr": 165, "avg_power": 180, "max_power": 400, "np": 195,
 "if": 0.855, "tss": 73.1, "tss_method": "power|hr|duration|strength", "garmin_tss": 70.2,
 "avg_cadence": 88, "pace_min_km": null,
 "laps": [{"i": 1, "duration_s": 600, "distance_m": 0, "avg_power": 220, "avg_hr": 160, "max_hr": 165, "avg_speed_ms": null}],
 "work_intervals": [{"i": 3, "duration_s": 600, "avg_power": 220, "avg_hr": 160, "pct_ftp": 0.965}],
 "decoupling_pct": 3.2, "session_type": "bike_threshold", "rpe": null, "notes": null}
```

### 5.2 Wellness (`data/derived/wellness.jsonl`)
`{"date", "hrv_last_night_ms", "hrv_weekly_avg_ms", "hrv_status", "rhr_bpm", "sleep_h", "sleep_score"}`

### 5.3 Plan — `schemas/plan.schema.json`
### 5.4 Check-in — `schemas/checkin.schema.json`
### 5.5 Goals — `schemas/goals.schema.json`

### 5.6 Session types
`bike_recovery, bike_z2, bike_long, bike_tempo, bike_sweetspot, bike_threshold, bike_vo2, bike_test, run_easy, run_quality, run_long, strength, other`

## 6. Open questions

| ID | Question | Impact |
|---|---|---|
| OQ-1 | Run LTHR unknown — calibrate from a recent threshold run or race HR. | Run load accuracy (C-M2). |
| OQ-2 | ~~Does Garmin Connect FTP equal `profile.bike.ftp_w`?~~ **Resolved 2026-10-01:** `garmin_tss` ≈ our TSS (±1) → Garmin uses the profile FTP. | – |
| OQ-3 | ~~Which ramp-test protocol/app?~~ **Resolved 2026-10-01:** ramp test; protocol recorded in `goals.json` (`test_protocol`). | – |
| OQ-4 | Should plans be pushed to Garmin as structured workouts? | Nice-to-have N-3. |

## 7. Known bugs / limitations

| ID | Description | Workaround | Status |
|---|---|---|---|
| B-001 | (garminconnect part verified 2026-10-01: 0.3.17, 88 activities/121 wellness days parsed.) `garminconnect` and `fitdecode` adapters could not be tested in the dev sandbox (no PyPI access). Field names follow the libraries' documented responses; parsing is defensive. | Verify on first real `sync`; raw JSON is stored so normalisation can be fixed without re-fetch. | Open |
| B-004 | `python -m trainer login` gave 401 at `sso.garmin.com/sso/signin` with garminconnect 0.2.40/garth 0.6.3 (pinned `<0.3`). Cause: Garmin blocks garth-style login since 2026-03. | Fixed in code: require garminconnect ≥ 0.3 + curl_cffi on Python ≥ 3.12; version guard gives clear error. Still unofficial — may break again (C-T2). FIT inbox remains fallback. | Fixed (pending verification) |
| B-005 | Garmin running power (~400 W) was stored as `avg_power`/`np` for runs. | Fixed: moved to `run_power`; run laps power cleared. | Fixed |
| B-006 | Trainer rides arrive as typeKey `cycling` → classified outdoor. | Fixed: no `startLatitude` ⇒ `indoor`. | Fixed |
| B-007 | Outdoor rides with high variability (avg power well below NP, e.g. invented: avg 170 W, NP 205 W, IF 0.90) classified `bike_sweetspot` although executed as base ride. Hilly/group rides inflate NP. | Agent overrides via check-in `session_type_override`; consider VI-based rule (N-8). | Open |
| B-008 | Rides ≥ 150 min are always `bike_long` (0.1.2 rule), so a long outdoor ride built around structured 2 × 20 min blocks loses its threshold label. | Agent reads work intervals and name; override via check-in. Consider: ≥ 2 work intervals ≥ 15 min at ≥ 0.95 FTP → threshold even when long. | Open |
| B-002 | Outdoor rides with auto-laps (e.g. every 5 km) can be misclassified as interval sessions. | Agent overrides `session_type` via check-in `overrides`. | Open |
| B-003 | NP from laps (C-M5) underestimates NP for variable efforts inside laps. | Use FIT records when available. | Open |

## 8. Nice-to-haves / backlog

| ID | Idea | Value |
|---|---|---|
| N-1 | React viewer reading `plans/*.json` + `activities.jsonl` (fits the team's existing stack). | Visual feed |
| N-2 | Scheduled weekly run (Sunday evening) that syncs and drafts next week's plan for review. | Automation |
| N-3 | Push planned bike sessions as Garmin structured workouts. | Less manual work |
| N-4 | Planned-vs-actual chart per week (hours, TSS, run km). | Insight |
| N-5 | Auto-detect FTP test / new PBs and propose profile updates. | Less manual bookkeeping |
| N-6 | Parse Garmin Connect activity CSV export (locale-dependent headers). | Better fallback |
| N-8 | Use variability index (NP/avg) and lap structure to separate outdoor 'hard by terrain' from structured intervals. | Better classification (B-007) |
| N-9 | Auto-detect max-HR candidates (and later LTHR) with the C-M6 plausibility rule and flag them in `context` as a question to the athlete (never auto-update, C3a). | Correct zones without manual digging |
| N-7 | Weather/daylight input for outdoor vs trainer choice. | Planning realism |

## 9. Changelog

| Date | Version | Change |
|---|---|---|
| 2026-10-08 | 0.3.5 | D-008 enforced: README, CLI/login messages and plan-validation errors translated to English. Athlete-facing output (rendered plans, context file, coaching warnings, weekday/session labels) stays Swedish. |
| 2026-10-08 | 0.3.4 | A6 clean-up before sharing: personal values (FTP, LTHR, test equipment) in D-006, C-M2, OQ-2/3 replaced by profile keys; limiter-neutral wording in analysis/context messages and README; tests use invented FTP. |
| 2026-10-06 | 0.3.3 | C-M7 HR-source rule; check-in `sessions[].hr_sensor`; normalize carries it to activities; CLAUDE.md C3b. |
| 2026-10-06 | 0.3.2 | CLAUDE.md C3a: HR anchors updated only after the athlete confirms chest strap. |
| 2026-10-06 | 0.3.1 | C-M6 max-HR plausibility rule; N-9. |
| 2026-10-03 | 0.3.0 | D-016: order-independent plans (schema `placement_rules`, `completed_date`; type-based compliance; render shows days as suggestions). |
| 2026-10-03 | 0.2.1 | Weekly loop (CLAUDE.md D2): check-in now asks for sessions the athlete has already scheduled. B-008 logged. |
| 2026-10-01 | 0.2.0 | Git policy D-015: `.gitignore`, layout table with Git column, §2.1.1, `trainer init`, example files; personal values removed from tracked specs (§4.2 now points to profile). |
| 2026-10-01 | 0.1.2 | First real sync. Classifier: rides ≥ 150 min are always `bike_long` (refines D-011). Fixed B-005, B-006; logged B-007; OQ-2 resolved; hand-off references linked to Garmin activities. |
| 2026-10-01 | 0.1.1 | Garmin auth moved to garminconnect ≥ 0.3 (D-014, B-004); Python ≥ 3.12 for fetch. |
| 2026-10-01 | 0.1.0 | Initial spec, PoC scaffold, profile/goals from hand-off, first draft plan 2026-W41. |
