# COACHING_SPEC — normative coaching rules

> **Living document, versioned in git — keep it generic.** No personal values here (D-015): athlete-specific numbers are referenced by key, e.g. `profile.run.easy_hr_cap_bpm`.
> Rules have stable IDs. Plans cite them in `rationale.rules_applied`. Changing a rule = edit here + changelog entry + `log/coach_log.md` note.
> Personal, git-ignored: `data/athlete/profile.json` (facts, zones, baselines, limiter), `data/athlete/goals.json` (goals, priorities, test protocol), `data/athlete/season_plan.md` (periodisation).
> "Primary limiter" = `profile.injury.primary_limiter`; its traffic-light status is recorded in check-in field `knee` (historical name).

## 1. Planning principles

| ID | Rule |
|---|---|
| R-GEN-01 | Plans are **goal-, data- and iteration-driven**. No static multi-week schedule followed regardless of response. |
| R-GEN-02 | Each week is based on: previous plan, completed sessions, recovery, primary-limiter/symptom status, total load, progress toward goals. |
| R-GEN-03 | **What was actually done outweighs the planned label.** Classify by data, not by plan name. |
| R-GEN-04 | **No automatic progression.** A good session does not by itself make the next one harder; progress is chosen from the observed response. |
| R-GEN-05 | **Minimal effective change.** When things work, change one variable a little (e.g. 3×10 → 3×12 min at the same power, not +10 W and extra reps). |
| R-GEN-06 | When things don't work, first diagnose the cause (intensity, volume, recovery, limiter symptoms, strength fatigue, general recovery), then change the smallest relevant variable. |
| R-GEN-07 | **Don't stack intensity.** At least one easy/rest day between key bike quality sessions; never VO2 the day after a TSS > 150 threshold effort. |
| R-GEN-08 | Avoid: turning quality days into tests; raising volume and intensity simultaneously without reason; treating IF/TSS as absolute truth. |
| R-GEN-09 | Each plan picks exactly one adjustment type: `progression`, `hold`, `deload`, `replacement`, `restructure`. |
| R-GEN-10 | Compare a session with the **closest relevant previous session** of the same type (threshold↔threshold, Z2↔Z2, run volume↔last tolerated volume). |
| R-GEN-11 | **The plan is a weekly menu, not a fixed schedule.** Each session states purpose and approximate intensity; days are suggestions. The athlete may reorder sessions or move them to adjacent days/weeks to fit life. Evaluate whether the *purpose* was fulfilled, not whether the date matched. A moved session is never "missed". |
| R-GEN-12 | Every plan states `placement_rules`: the spacing constraints that must hold when sessions are moved (e.g. ≥ 48 h between key quality sessions, no VO2 the day after a TSS > 150 session, heavy leg strength not the day before a key session or a run). When the athlete has already moved a session, re-plan the rest of the week around what was actually done (R-GEN-03). |

## 2. Priorities and budget

| ID | Rule |
|---|---|
| R-PRI-01 | Priority follows `goals.json` `priority` (1 = highest). Continuity & symptom control is always priority 1. The current order and its rationale are in `season_plan.md`. |
| R-PRI-02 | While running is load-limited, running does not have to carry aerobic quality — the bike provides aerobic load with low impact. |
| R-BUD-01 | Normal week within `profile.budget.normal_range_hours`, strength included. Bigger weeks allowed, followed by easier ones. |
| R-BUD-02 | Time-crunch order: keep 1 bike quality → keep long Z2 → keep 2 strength → keep tolerated run volume → remove extra intensity first. |
| R-BUD-03 | Default week: 1 bike threshold/sweet spot, 1 bike VO2/other quality, 1 longer bike Z2, 2 runs, 2 strength. |
| R-BUD-04 | Load pattern: typically 2–3 build weeks then 1 lighter week (~60–70 % of load), adjusted by response. |

## 3. Running (most sensitive)

| ID | Rule |
|---|---|
| R-RUN-01 | **Primary-limiter symptoms outweigh the calendar.** |
| R-RUN-02 | 🟢 **Green** (none/very mild discomfort, no increase during run, no worse next morning) → planned progression may be considered. |
| R-RUN-03 | 🟡 **Yellow** (clearer pain, increases during run, unusual stiffness/soreness next day) → hold or reduce; no new progression. |
| R-RUN-04 | 🔴 **Red** (clear pain, altered gait, clearly worse next day, persistent worsening) → back off; replace with bike or rest. |
| R-RUN-05 | Never increase run volume, run speed and total load at the same time. |
| R-RUN-06 | Run quality increases only after run volume is stable and tolerated (≥ 2 consecutive green weeks at that volume). |
| R-RUN-07 | Volume steps are small: max +1–2 km/week or one extra short run; only after a green week. |
| R-RUN-08 | Easy run = `profile.run.easy_pace_min_km` at ≤ `profile.run.easy_hr_cap_bpm`; HR cap wins over pace. A long run averaging above the cap is *not* easy. |
| R-RUN-09 | Quality progression path: strides → short pickups → short intervals → longer intervals → threshold / race-specific pace. |
| R-RUN-10 | Run tolerance is judged by limiter response, never by aerobic fitness. Don't increase running because bike fitness improved. |

## 4. Cycling

| ID | Rule |
|---|---|
| R-BIKE-01 | Power is the primary target on the trainer; HR and RPE are control variables for how costly the session was. |
| R-BIKE-02 | Zones use the current working FTP in `profile.json` (zone table there). Recompute when FTP changes. |
| R-BIKE-03 | Outdoor without reliable power/HR → steer by RPE. |
| R-BIKE-04 | Sessions with TSS > 300 require easy days around them. |
| R-BIKE-05 | Intervals: judge whether the last reps hold together (power stable, HR drift, RPE). Last rep ≤ 7/10 and stable → candidate for extended duration (R-GEN-05). |
| R-BIKE-06 | FTP test: protocol and date from the FTP goal in `goals.json` (`test_protocol`, `deadline`), under comparable conditions (same trainer, protocol, calibration, fan/temperature, low fatigue). Taper the preceding ~7–10 days. |

## 5. Strength

| ID | Rule |
|---|---|
| R-STR-01 | `profile.budget.strength_sessions_per_week` × `strength_minutes_per_session`; focus per `profile.strength.focus`. |
| R-STR-02 | Not to failure; reps in reserve per `profile.strength.rir`. |
| R-STR-03 | Strength counts in total load; avoid heavy leg strength the day before a key bike session or a run. |

## 6. Recovery signals

| ID | Rule |
|---|---|
| R-REC-01 | HRV and resting HR are **secondary** signals; a single deviation is never a decision rule on its own. |
| R-REC-02 | Decide from the combination: HRV trend and RHR vs `profile.recovery_baseline`, sleep, subjective fatigue, warm-up performance, power/HR response, musculoskeletal symptoms. |
| R-REC-03 | ≥ 2 negative signals for ≥ 3 days (e.g. HRV below baseline + RHR +4 bpm + poor sleep) → reduce intensity before volume. |
| R-REC-04 | After a session aborted because of recovery signals, plan 2–3 easy days before the next quality session; don't follow an abort with the hardest session of the week. |

## 7. Periodisation

Personal and date-bound → `data/athlete/season_plan.md` (git-ignored). The agent reads it in step 0 of `CLAUDE.md` and updates it (with a coach-log note) when goals or dates change.

## 8. Weekly review procedure (the loop)

1. Read the previous plan (latest revision).
2. Collect actual data (sync) + check-in: power, NP, IF, TSS, HR, RPE, interval consistency, time, run km/pace, **limiter status**, next-day response, strength, sleep/recovery.
3. Compare with closest relevant history (R-GEN-10).
4. Interpret: load reasonable? capacity improved? harder/easier than expected? accumulated fatigue? limiter reaction? clear reason to change?
5. Choose adjustment type (R-GEN-09).
6. Write plan + coach log entry; update profile if a new reference/benchmark was set.

## Changelog

| Date | Change |
|---|---|
| 2026-10-03 | v0.3 — Added R-GEN-11 (weekly menu, order free) and R-GEN-12 (placement rules), from athlete feedback: they read purpose + intensity and place sessions themselves. |
| 2026-10-01 | v0.2 — Genericised for git (D-015): personal values replaced by profile/goals keys; periodisation moved to `data/athlete/season_plan.md`. Added R-REC-04 (lesson from an aborted session followed by a very hard one). |
| 2026-10-01 | v0.1.1 — R-BIKE-06: protocol taken from the FTP goal. |
| 2026-10-01 | v0.1 — extracted from hand-off. R-GEN-07 (≥1 easy day between bike quality), R-RUN-06/07 numeric thresholds and R-BUD-04 are **new interpretations** for operationalisation; confirm with the athlete. |
