---
name: revise-plan
description: "revidera planen", mid-week changes, illness, moved sessions.
---

# Mid-week revision (DESIGN D-009, D-020)
Rules in `CLAUDE.md` (F1–F8) apply throughout. Extra reading (tier 2): `plans/<W>.json` (the file being edited); `schemas/plan.schema.json` only on validation errors.

- Revise only remaining days. Increase `revision`, append to `revision_history` (date, reason), keep completed days unchanged, re-validate, re-render, log it (newest entry at the top of `log/coach_log.md`).
