import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import ROOT, make_project  # noqa: E402
from trainer import analysis, context, metrics, normalize, plans  # noqa: E402
from trainer.config import Paths, read_json, read_jsonl, write_json  # noqa: E402
from trainer.weeks import shift_week, week_bounds, week_of  # noqa: E402


class TestMetrics(unittest.TestCase):
    def test_np_constant(self):
        self.assertAlmostEqual(metrics.np_from_series([200] * 600), 200, places=3)

    def test_np_variable_above_avg(self):
        s = ([300] * 60 + [100] * 60) * 10
        self.assertGreater(metrics.np_from_series(s), 200)

    def test_bike_tss_one_hour_at_ftp(self):
        tss, if_ = metrics.bike_tss(3600, 250, 250)
        self.assertEqual((tss, if_), (100.0, 1.0))

    def test_handoff_2x20_tss_plausible(self):
        # hand-off: IF 0.908 TSS 150.6 → duration ≈ 1.83 h
        tss, _ = metrics.bike_tss(1.827 * 3600, 0.908 * 250, 250)
        self.assertAlmostEqual(tss, 150.6, delta=1)

    def test_decoupling(self):
        laps = [{"duration_s": 600, "avg_power": 170, "avg_hr": h} for h in (135, 136, 140, 142)]
        self.assertGreater(metrics.decoupling_pct(laps), 0)

    def test_pmc(self):
        d0 = dt.date(2026, 1, 1)
        rows = metrics.pmc({d0 + dt.timedelta(days=i): 100 for i in range(100)}, d0, d0 + dt.timedelta(days=99))
        self.assertGreater(rows[-1]["ctl"], 85)
        self.assertLess(abs(rows[-1]["tsb"]), 15)


class TestWeeks(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(week_bounds("2026-W41"), (dt.date(2026, 10, 5), dt.date(2026, 10, 11)))
        self.assertEqual(week_of(dt.date(2026, 10, 1)), "2026-W40")
        self.assertEqual(shift_week("2026-W53", 1), "2027-W01")


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = make_project(Path(self.tmp.name))
        normalize.run(self.p)
        self.acts = read_jsonl(self.p.activities)

    def tearDown(self):
        self.tmp.cleanup()

    def by_name(self, n):
        return next(a for a in self.acts if a["name"] == n)

    def test_classification(self):
        self.assertEqual(self.by_name("2x20")["session_type"], "bike_threshold")
        self.assertEqual(self.by_name("8x1")["session_type"], "bike_vo2")
        self.assertEqual(self.by_name("3x12 SS")["session_type"], "bike_sweetspot")
        self.assertEqual(self.by_name("Långpass")["session_type"], "bike_long")
        self.assertEqual(self.by_name("Styrka")["session_type"], "strength")
        self.assertTrue(all(a["session_type"] == "run_easy" for a in self.acts if a["sport"] == "run"))

    def test_8x1_work_intervals(self):
        wi = self.by_name("8x1")["work_intervals"]
        self.assertEqual(len(wi), 8)
        self.assertTrue(all(w["avg_power"] == 300 for w in wi))

    def test_wellness(self):
        w = read_jsonl(self.p.wellness)
        self.assertEqual(w[0]["rhr_bpm"], 37)
        self.assertEqual(w[0]["sleep_h"], 7.5)

    def test_reference_falls_back_to_profile(self):
        a = self.by_name("2x20")
        prof = read_json(self.p.profile)
        r = next(x for x in prof["reference_sessions"] if x["id"] == "ref-2x20")
        r["date"], r["activity_id"] = "2026-09-01", "garmin:other"
        self.assertEqual(analysis.find_reference(a, self.acts, prof)["id"], "ref-2x20")
        r["activity_id"] = a["id"]  # never compare a session with itself
        self.assertNotEqual((analysis.find_reference(a, self.acts, prof) or {}).get("id"), "ref-2x20")

    def test_reference_uses_history(self):
        runs = [a for a in self.acts if a["sport"] == "run"]
        ref = analysis.find_reference(runs[-1], self.acts, read_json(self.p.profile))
        self.assertEqual(ref["id"], runs[-2]["id"])

    def test_checkin_merges_strength_and_rpe(self):
        write_json(self.p.checkins / "2026-W40.json", {
            "week": "2026-W40", "created": "2026-10-01",
            "knee": [{"date": "2026-09-30", "status": "green", "next_morning": "green"}],
            "sessions": [{"date": "2026-09-29", "sport": "bike", "rpe": 7, "hr_sensor": "strap"}],
            "strength": [{"date": "2026-10-01", "duration_min": 35}]})
        self.assertEqual(plans.validate_checkin(read_json(self.p.checkins / "2026-W40.json"), self.p), [])
        normalize.run(self.p)
        acts = read_jsonl(self.p.activities)
        self.assertEqual(next(a for a in acts if a["name"] == "3x12 SS")["rpe"], 7)
        self.assertEqual(next(a for a in acts if a["name"] == "3x12 SS")["hr_sensor"], "strap")
        self.assertTrue(any(a["source"] == "checkin" and a["sport"] == "strength" for a in acts))

    def test_context_and_flags(self):
        ctx, md = context.run(self.p, "2026-W41", today=dt.date(2026, 10, 1))
        self.assertEqual(ctx["review_week"], "2026-W40")
        rules = {f["rule"] for f in ctx["flags"]}
        self.assertIn("R-RUN-01", rules)  # runs without knee report
        self.assertTrue((self.p.context / "2026-W41.md").exists())
        self.assertIn("Veckobelastning", md)
        w39 = next(r for r in ctx["weekly_load"] if r["week"] == "2026-W39")
        self.assertEqual(w39["run_km"], 12.0)

    def test_compliance_order_independent(self):
        """R-GEN-11: a session done earlier/later (even the week before) counts as done, not missed."""
        plan = plans.skeleton("2026-W40", today=dt.date(2026, 9, 28))
        plan["sessions"][0].update(sport="bike", session_type="bike_sweetspot", title="SS", priority="key", duration_min=75)
        plan["sessions"][4].update(sport="bike", session_type="bike_threshold", title="2x20", priority="key", duration_min=105)
        rows = {r.get("planned"): r for r in analysis.compliance(plan, self.acts, lookback_days=7)}
        self.assertEqual(rows["2x20"]["status"], "done")          # done 22/9, i.e. moved into the previous week
        self.assertTrue(rows["2x20"]["moved"])
        self.assertEqual(rows["SS"]["actual_type"], "bike_sweetspot")
        self.assertNotIn("missed_or_not_synced", {rows["2x20"]["status"], rows["SS"]["status"]})

    def test_compliance_no_borrowing_for_supporting(self):
        """B-009: a supporting session must not be credited with last week's activity."""
        plan = plans.skeleton("2026-W40", today=dt.date(2026, 9, 28))
        plan["sessions"][2].update(sport="strength", session_type="strength", title="Str", priority="supporting", duration_min=35)
        rows = {r.get("planned"): r for r in analysis.compliance(plan, self.acts)}
        self.assertEqual(rows["Str"]["status"], "missed_or_not_synced")  # only strength is 24/9 (W39)

    def test_compliance_explicit_ids_win(self):
        plan = plans.skeleton("2026-W40", today=dt.date(2026, 9, 28))
        vo2 = self.by_name("3x12 SS")
        plan["sessions"][0].update(sport="bike", session_type="bike_long", title="Long", priority="key", duration_min=90)
        plan["sessions"][3].update(sport="bike", session_type="bike_sweetspot", title="SS", priority="key", duration_min=75,
                                   actual_activity_ids=[vo2["id"]], status="done")
        rows = {r.get("planned"): r for r in analysis.compliance(plan, self.acts)}
        self.assertEqual(rows["SS"]["actual_id"], vo2["id"])
        self.assertNotEqual(rows["Long"].get("actual_id"), vo2["id"])

    def test_stacked_hard_flag(self):
        # W39: 2x20 on 22/9 and run on 23/9 not hard → no flag; add hard ride 23/9
        from fixtures import _act, _lap
        write_json(self.p.raw_garmin_act / "99.json", _act(99, "2026-09-30T18:00:00", "virtual_ride", "thr", 3600,
                                                          [_lap(1, 1200, 160, 130), _lap(2, 1200, 225, 165), _lap(3, 1200, 150, 130)]))
        normalize.run(self.p)
        ctx = context.build(self.p, "2026-W41", today=dt.date(2026, 10, 1))
        self.assertIn("R-GEN-07", {f["rule"] for f in ctx["flags"]})


class TestPlans(unittest.TestCase):
    def setUp(self):
        self.p = Paths(ROOT)

    def test_skeleton_valid(self):
        sk = plans.skeleton("2026-W42", today=dt.date(2026, 10, 1))
        sk["targets"]["hours"] = 0
        errs, _ = plans.validate(sk, self.p)
        self.assertEqual(errs, [])

    def test_bad_rule_and_date(self):
        sk = plans.skeleton("2026-W42", today=dt.date(2026, 10, 1))
        sk["rationale"]["rules_applied"] = ["R-XXX-99"]
        sk["sessions"][0]["date"] = "2026-10-01"
        errs, _ = plans.validate(sk, self.p)
        self.assertTrue(any("outside the week" in e for e in errs))
        self.assertTrue(any("Unknown rule IDs" in e for e in errs))

    def test_committed_plans_valid_and_rendered(self):
        for f in sorted((ROOT / "plans").glob("*.json")):
            plan = read_json(f)
            errs, _ = plans.validate(plan, self.p, read_json(self.p.profile))
            self.assertEqual(errs, [], f.name)
            self.assertIn(plan["week"], plans.render(plan))


if __name__ == "__main__":
    unittest.main()


class TestExampleGuard(unittest.TestCase):
    """D-017: planning commands refuse to run on the invented example profile."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.p = make_project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        from trainer.__main__ import main
        return main(["--root", str(self.root), *args])

    def test_profile_state(self):
        from trainer.config import profile_state
        self.assertEqual(profile_state(self.p), "example")
        prof = read_json(self.p.profile)
        prof["source"] = "onboarding 2026-01-01"
        write_json(self.p.profile, prof)
        self.assertEqual(profile_state(self.p), "ok")
        self.p.profile.unlink()
        self.assertEqual(profile_state(self.p), "missing")

    def test_guarded_commands_refuse_example(self):
        self.assertEqual(self.run_cli("new-plan", "--week", "2026-W42"), 3)
        self.assertFalse((self.p.plans / "2026-W42.json").exists())
        self.assertEqual(self.run_cli("new-plan", "--week", "2026-W42", "--allow-example"), 0)
        self.assertTrue((self.p.plans / "2026-W42.json").exists())

    def test_real_profile_passes(self):
        prof = read_json(self.p.profile)
        prof["source"] = "onboarding 2026-01-01"
        write_json(self.p.profile, prof)
        self.assertEqual(self.run_cli("new-plan", "--week", "2026-W42"), 0)


class TestLanguage(unittest.TestCase):
    """D-018: athlete-facing output follows profile.language."""

    def test_lang_of(self):
        from trainer.i18n import lang_of
        self.assertEqual(lang_of({}), "sv")
        self.assertEqual(lang_of({"language": "en"}), "en")
        self.assertEqual(lang_of({"language": "xx"}), "sv")

    def test_both_languages_have_same_keys(self):
        from trainer import i18n
        self.assertEqual(set(i18n._T["sv"]), set(i18n._T["en"]))
        for table in (i18n.TYPE, i18n.PRIO, i18n.STATUS, i18n.ADJ):
            self.assertEqual(set(table["sv"]), set(table["en"]))

    def test_render_english(self):
        sk = plans.skeleton("2026-W42", today=dt.date(2026, 10, 1), lang="en")
        md = plans.render(sk, "en")
        self.assertIn("# Training plan 2026-W42", md)
        self.assertIn("Monday", md)
        self.assertIn("At least 48 h", md)
        self.assertNotIn("Måndag", md)
        self.assertIn("Måndag", plans.render(plans.skeleton("2026-W42", today=dt.date(2026, 10, 1)), "sv"))

    def test_flags_english(self):
        prof = read_json(ROOT / "data" / "athlete" / "profile.example.json")
        prof["language"] = "en"
        out = analysis.flags([], [], None, {}, [], prof, "2026-W40")
        self.assertIn("No training data", out[-1]["msg"])


class TestPrivacy(unittest.TestCase):
    """D-015 / CLAUDE.md A6: tracked files must not contain the athlete's personal values."""

    TRACKED = ["CLAUDE.md", "README.md", "docs/*.md", "schemas/*.json", "trainer/*.py", "tests/*.py", "data/**/*.example.*",
               ".claude/**/*.md", ".claude/*.json"]

    def test_no_personal_values_in_tracked_files(self):
        prof_path = ROOT / "data" / "athlete" / "profile.json"
        goals_path = ROOT / "data" / "athlete" / "goals.json"
        if not prof_path.exists():
            self.skipTest("no personal profile (fresh clone)")
        prof = read_json(prof_path)
        if prof == read_json(ROOT / "data" / "athlete" / "profile.example.json"):
            self.skipTest("profile.json is still the example (fresh clone after init)")
        needles = set(prof["athlete"].split()) | {pb["time"] for pb in prof["run"].get("pbs", [])}
        if goals_path.exists():
            needles |= {g["title"] for g in read_json(goals_path)["goals"]}
        needles = {n for n in needles if len(n) >= 4}
        hits = []
        for pattern in self.TRACKED:
            for f in ROOT.glob(pattern):
                if f.name == "test_trainer.py":
                    continue
                text = f.read_text(encoding="utf-8")
                hits += [f"{f.relative_to(ROOT)}: {n!r}" for n in needles if n in text]
        self.assertEqual(hits, [])

    def test_gitignore_covers_personal_paths(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in (".env", ".garmin_tokens/", "docs/reference/", "data/**", "plans/*", "log/*", ".claude/settings.local.json"):
            self.assertIn(entry, gi)


def _log(*entries, header="# Coach log\n\nNewest first.\n\n---\n\n"):
    return header + "".join(f"## {d} — {t}\n- {body}\n\n" for d, t, body in entries)


class TestBrief(unittest.TestCase):
    """D-019: `trainer brief` is the session-start read — short, fresh, never refuses."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.p = make_project(self.root)
        normalize.run(self.p)
        self.set_profile(language="sv")

    def tearDown(self):
        self.tmp.cleanup()

    def set_profile(self, **kw):
        prof = read_json(self.p.profile)
        prof["source"] = "onboarding 2026-01-01"
        prof.update(kw)
        write_json(self.p.profile, prof)

    def brief(self, week="2026-W41"):
        from trainer import brief
        return brief.build(self.p, week, today=dt.date(2026, 10, 1))

    def test_brief_sections_and_size(self):
        from trainer.i18n import tr
        sk = plans.skeleton("2026-W41", today=dt.date(2026, 9, 28))
        write_json(self.p.plans / "2026-W41.json", sk)
        long_body = "x" * 3000
        self.p.log.write_text(_log(("2026-10-01", "A", long_body), ("2026-09-30", "B", long_body),
                                   ("2026-09-29", "C", long_body), ("2026-09-28", "D", long_body)), encoding="utf-8")
        for lang in ("sv", "en"):
            self.set_profile(language=lang)
            out = self.brief()
            for key in ("b_h_state", "b_h_anchors", "b_h_goals", "b_h_plan", "b_h_recovery",
                        "b_h_checkin", "b_h_log", "b_h_oq", "b_h_next"):
                self.assertIn(f"## {tr(lang, key)}", out, (lang, key))
            self.assertLessEqual(len(out), 4000, lang)
            self.assertNotIn("x" * 700, out)  # log entries are truncated

    def test_brief_example_profile_banner(self):
        import contextlib
        import io
        from trainer.__main__ import main
        prof = read_json(self.p.profile)
        prof["source"] = "INVENTED EXAMPLE template"
        write_json(self.p.profile, prof)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--root", str(self.root), "brief", "--week", "2026-W41"])
        self.assertEqual(rc, 0)
        self.assertIn("onboarding", buf.getvalue().splitlines()[0])

    def test_brief_writes_no_files(self):
        before = sorted(str(f) for f in self.root.rglob("*"))
        self.brief()
        self.assertEqual(before, sorted(str(f) for f in self.root.rglob("*")))

    def test_brief_log_sorted_by_date(self):
        self.p.log.write_text(_log(("2026-10-05", "mid-old", "m1"), ("2026-10-12", "newest", "n1"),
                                   ("2026-10-01", "third", "t1"), ("2026-09-20", "fourth", "f1"),
                                   ("2026-01-01", "ancient", "a1")), encoding="utf-8")
        out = self.brief()
        order = [out.index(t) for t in ("newest", "mid-old", "third")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("fourth", out)
        self.assertNotIn("ancient", out)

    def test_brief_missing_files(self):
        from trainer import brief
        with tempfile.TemporaryDirectory() as t:
            out = brief.build(Paths(t), "2026-W41", today=dt.date(2026, 10, 1))
        self.assertIn("onboarding", out.splitlines()[0])
        self.assertIn("–", out)


class TestContextTrim(unittest.TestCase):
    """D-019: the context file prints only the deltas that matter per session type."""

    SESSIONS_BEFORE = 1375  # fixture W.md sessions section before 0.6.0 (chars); the whole file also gains a note line

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = make_project(Path(self.tmp.name))
        normalize.run(self.p)

    def tearDown(self):
        self.tmp.cleanup()

    def test_context_md_relevant_deltas(self):
        _, md = context.run(self.p, "2026-W41", today=dt.date(2026, 10, 1))
        lines = md.splitlines()
        pairs = [(a, b) for a, b in zip(lines, lines[1:]) if a.startswith("- **") and b.strip().startswith("- ref")]
        self.assertTrue(pairs)
        for line, ref in pairs:
            if " bike_" in line:
                self.assertNotIn("Δpace", ref)
                self.assertNotIn("Δavg_hr", ref)
            if " run_" in line:
                self.assertNotIn("Δnp", ref)

    def test_compare_keeps_all_deltas(self):
        acts = read_jsonl(self.p.activities)
        runs = [a for a in acts if a["sport"] == "run"]
        d = analysis.compare(runs[-1], runs[-2])["delta"]
        self.assertIn("pace", d)
        self.assertEqual(set(analysis.relevant_deltas("bike_vo2", {"pace": 1, "np": 2})), {"np"})

    def test_context_md_size_drops(self):
        _, md = context.run(self.p, "2026-W41", today=dt.date(2026, 10, 1))
        section = md[md.index("## Pass"):md.index("## Check-in")]
        self.assertLess(len(section), self.SESSIONS_BEFORE)
        self.assertIn("D-019", md)


class TestCoachLog(unittest.TestCase):
    """D-021: archive old entries; parser is shared with brief."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "log" / "coach_log.md"
        self.log.parent.mkdir()
        self.log.write_text(_log(("2026-10-10", "new", "n"), ("2026-07-01", "old-jul", "j"),
                                 ("2026-06-15", "old-jun-a", "a"), ("2026-06-20", "old-jun-b", "b")), encoding="utf-8")
        self.today = dt.date(2026, 10, 15)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_archive_moves_old_entries(self):
        from trainer import coachlog
        res = coachlog.archive(self.log, days=60, today=self.today)
        self.assertEqual(res["moved"], 3)
        kept = self.log.read_text(encoding="utf-8")
        self.assertIn("new", kept)
        self.assertIn("Newest first.", kept)  # header block kept
        self.assertNotIn("old-jun", kept)
        jun = (self.log.parent / "archive" / "2026-06.md").read_text(encoding="utf-8")
        self.assertLess(jun.index("old-jun-b"), jun.index("old-jun-a"))  # newest first inside the file
        self.assertTrue((self.log.parent / "archive" / "2026-07.md").exists())

    def test_log_archive_idempotent(self):
        from trainer import coachlog
        coachlog.archive(self.log, days=60, today=self.today)
        snap = {f: f.read_text(encoding="utf-8") for f in self.log.parent.rglob("*.md")}
        res = coachlog.archive(self.log, days=60, today=self.today)
        self.assertEqual(res["moved"], 0)
        self.assertEqual(snap, {f: f.read_text(encoding="utf-8") for f in self.log.parent.rglob("*.md")})


class TestAgentFiles(unittest.TestCase):
    """D-019/D-020/D-021: slim CLAUDE.md, skills with frontmatter, read guards."""

    def test_claude_md_size(self):
        self.assertLessEqual(len((ROOT / "CLAUDE.md").read_text(encoding="utf-8")), 5000)

    def test_skills_have_frontmatter(self):
        skills = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
        self.assertEqual({s.parent.name for s in skills}, {"onboarding", "weekly-loop", "revise-plan"})
        for s in skills:
            text = s.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), s)
            front = text.split("---", 2)[1]
            self.assertIn(f"name: {s.parent.name}", front)
            self.assertIn("description:", front)

    def test_rule_ids_preserved(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        for rid in ("A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2", "B3", "C1", "C2", "C3", "C3a", "C3b", "C4",
                    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"):
            self.assertIn(f"**{rid}**", text, rid)
        for name in ("onboarding", "weekly-loop", "revise-plan"):
            self.assertIn(f".claude/skills/{name}/SKILL.md", text)

    def test_settings_denies_secrets(self):
        deny = read_json(ROOT / ".claude" / "settings.json")["permissions"]["deny"]
        self.assertIn("Read(./.env)", deny)
        self.assertIn("Read(./.garmin_tokens/**)", deny)
        self.assertIn("Read(./data/raw/**)", deny)

def _bike(structure, erg=True, **kw):
    s = {"id": "W-1", "date": "2026-10-22", "sport": "bike", "session_type": "bike_threshold", "title": "2 x 20",
         "priority": "key", "duration_min": 70, "status": "planned", "structure": structure}
    if erg is not None:
        s["erg"] = erg
    s.update(kw)
    return s


def _flat(payload):
    out = []

    def walk(nodes):
        for n in nodes:
            out.append(n)
            walk(n.get("workoutSteps", []))
    walk(payload["workoutSegments"][0]["workoutSteps"])
    return out


class TestGarminWorkouts(unittest.TestCase):
    """D-022 / R-WO-01…05: plan session → Garmin workout JSON."""

    PROFILE = {"language": "sv"}

    def compile(self, s, profile=None):
        from trainer.garmin_workouts import compile_session
        return compile_session(s, "2026-W43", profile or self.PROFILE, "sv")

    def test_erg_span_is_10_w_around_setpoint(self):
        p, e, _ = self.compile(_bike([{"label": "Block", "duration_min": 20, "target": {"power_w": [220, 225]}}]))
        self.assertEqual(e, [])
        st = _flat(p)[0]
        self.assertEqual((st["targetValueOne"], st["targetValueTwo"]), (218, 228))  # setpoint 223 (222.5 rounded up)
        self.assertEqual(st["targetType"]["workoutTargetTypeKey"], "power.zone")

    def test_free_ride_span_widened_to_preference(self):
        p, _, _ = self.compile(_bike([{"label": "Z2", "duration_min": 60, "target": {"power_w": [150, 160]}}], erg=False))
        st = _flat(p)[0]
        self.assertGreaterEqual(st["targetValueTwo"] - st["targetValueOne"], 20)
        self.assertIn("plan 150–160 W", st["description"])

    def test_spans_follow_profile_preference(self):
        prof = {"garmin_workouts": {"bike_erg_power_span_w": 6}}
        p, _, _ = self.compile(_bike([{"label": "B", "duration_min": 5, "target": {"power_w": [200, 200]}}]), prof)
        st = _flat(p)[0]
        self.assertEqual((st["targetValueOne"], st["targetValueTwo"]), (197, 203))

    def test_bike_requires_erg_flag(self):
        p, e, _ = self.compile(_bike([{"label": "B", "duration_min": 5, "target": {"power_w": [200, 210]}}], erg=None))
        self.assertIsNone(p)
        self.assertTrue(any("R-WO-02" in x for x in e))

    def test_every_step_needs_end_condition(self):
        _, e, _ = self.compile(_bike([{"label": "Uppvärmning", "target": {"power_w": [150, 170]}}]))
        self.assertTrue(any("R-WO-01" in x for x in e))

    def test_unprogrammed_substeps_warned(self):
        _, _, w = self.compile(_bike([{"label": "Uppvärmning inkl. 2 × 30 s", "duration_min": 15,
                                       "target": {"power_w": [150, 170]}}]))
        self.assertTrue(any("sub-steps" in x for x in w))

    def test_structure_kinds_repeats_and_order(self):
        p, e, w = self.compile(_bike([
            {"label": "Uppv", "steps": [
                {"label": "Lugnt", "duration_min": 10, "target": {"power_w": [150, 160]}},
                {"label": "Öppnare", "reps": 2, "steps": [
                    {"label": "På", "kind": "interval", "duration_min": 0.5, "target": {"power_w": [250, 250]}},
                    {"label": "Av", "kind": "recovery", "duration_min": 2, "target": {"power_w": [140, 140]}}]}]},
            {"label": "Block", "reps": 2, "duration_min": 20, "recovery_min": 5,
             "recovery_target": {"power_w": [130, 140]}, "target": {"power_w": [220, 225], "cadence_rpm": [88, 95]}},
            {"label": "Nedv", "duration_min": 10, "target": {"power_w": [120, 140]}}]))
        self.assertEqual((e, w), ([], []))
        top = p["workoutSegments"][0]["workoutSteps"]
        self.assertEqual([n["stepType"]["stepTypeKey"] for n in top], ["warmup", "repeat", "repeat", "cooldown"])
        rep = top[2]
        self.assertEqual(rep["numberOfIterations"], 2)
        self.assertEqual([c["stepType"]["stepTypeKey"] for c in rep["workoutSteps"]], ["interval", "recovery"])
        self.assertTrue(all(c["childStepId"] == rep["childStepId"] for c in rep["workoutSteps"]))
        self.assertEqual(rep["workoutSteps"][0]["secondaryTargetType"]["workoutTargetTypeKey"], "cadence")
        orders = [n["stepOrder"] for n in _flat(p)]
        self.assertEqual(orders, list(range(1, len(orders) + 1)))

    def test_run_pace_widened_and_in_m_per_s(self):
        s = {"id": "R-1", "date": "2026-10-24", "sport": "run", "session_type": "run_quality", "title": "Tempo",
             "priority": "key", "duration_min": 40, "status": "planned",
             "structure": [{"label": "Tempo", "duration_min": 10, "target": {"pace_min_km": [4.75, 4.85],
                                                                          "hr_max_bpm": 170}}]}
        p, e, _ = self.compile(s)
        st = _flat(p)[0]
        self.assertEqual(st["targetType"]["workoutTargetTypeKey"], "pace.zone")
        slow, fast = 1000 / st["targetValueOne"], 1000 / st["targetValueTwo"]
        self.assertAlmostEqual(slow - fast, 30, delta=0.5)        # default run_pace_span_min_s_per_km
        self.assertAlmostEqual((slow + fast) / 2, 4.8 * 60, delta=0.5)
        self.assertEqual(st["secondaryTargetType"]["workoutTargetTypeKey"], "heart.rate.zone")

    def test_easy_run_uses_hr_cap(self):
        s = {"id": "R-2", "date": "2026-10-24", "sport": "run", "session_type": "run_easy", "title": "Lugnt",
             "priority": "supporting", "duration_min": 30, "status": "planned",
             "structure": [{"label": "Lugnt", "distance_km": 5, "target": {"pace_min_km": [5.5, 6.0],
                                                                         "hr_max_bpm": 145}}]}
        p, _, _ = self.compile(s)
        st = _flat(p)[0]
        self.assertEqual(st["targetType"]["workoutTargetTypeKey"], "heart.rate.zone")
        self.assertEqual((st["targetValueOne"], st["targetValueTwo"]), (135, 145))
        self.assertEqual(st["endConditionValue"], 5000.0)

    def test_strength_and_done_not_pushed(self):
        from trainer.garmin_workouts import pushable
        self.assertFalse(pushable({"sport": "strength", "status": "planned", "structure": [{"label": "x"}]}))
        self.assertFalse(pushable(_bike([{"label": "B", "duration_min": 5}], status="done")))
        self.assertFalse(pushable(_bike([{"label": "B", "duration_min": 5}], garmin_push=False)))


class _FakeGarmin:
    def __init__(self):
        self.calls, self.n = [], 100

    def upload_workout(self, payload):
        self.n += 1
        self.calls.append(("upload", payload["workoutName"]))
        return {"workoutId": self.n}

    def schedule_workout(self, wid, date):
        self.calls.append(("schedule", wid, date))
        return {"workoutScheduleId": wid * 10}

    def unschedule_workout(self, sid):
        self.calls.append(("unschedule", sid))

    def update_workout(self, wid, payload):
        self.calls.append(("update", wid))

    def delete_workout(self, wid):
        self.calls.append(("delete", wid))


class TestGarminPush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = Paths(self.tmp.name)
        self.plan = {"week": "2026-W43", "sessions": [
            _bike([{"label": "B", "duration_min": 20, "target": {"power_w": [220, 225]}}])]}

    def tearDown(self):
        self.tmp.cleanup()

    def push(self, api):
        from trainer.garmin_client import push
        return push(self.paths, self.plan, {}, "sv", api=api)

    def test_idempotent_lifecycle(self):
        api = _FakeGarmin()
        r = self.push(api)
        self.assertEqual(r["created"], ["W-1"])
        self.assertEqual(api.calls, [("upload", "W43 2 x 20"), ("schedule", 101, "2026-10-22")])
        api.calls.clear()
        self.assertEqual(self.push(api)["unchanged"], ["W-1"])
        self.assertEqual(api.calls, [])
        self.plan["sessions"][0]["structure"][0]["target"]["power_w"] = [225, 230]
        self.assertEqual(self.push(api)["updated"], ["W-1"])
        self.assertEqual(api.calls, [("update", 101)])
        api.calls.clear()
        self.plan["sessions"][0]["date"] = "2026-10-23"
        self.assertEqual(self.push(api)["rescheduled"], ["W-1"])
        self.assertEqual(api.calls, [("unschedule", 1010), ("schedule", 101, "2026-10-23")])
        api.calls.clear()
        self.plan["sessions"][0]["status"] = "missed"
        self.assertEqual(self.push(api)["deleted"], ["W-1"])
        self.assertEqual(read_json(self.paths.garmin_state), {})

    def test_done_session_kept(self):
        api = _FakeGarmin()
        self.push(api)
        self.plan["sessions"][0]["status"] = "done"
        api.calls.clear()
        self.push(api)
        self.assertEqual(api.calls, [])
        self.assertIn("W-1", read_json(self.paths.garmin_state))

    def test_compile_error_blocks_push(self):
        del self.plan["sessions"][0]["erg"]
        with self.assertRaises(ValueError):
            self.push(_FakeGarmin())
