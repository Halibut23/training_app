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
        rows = {r.get("planned"): r for r in analysis.compliance(plan, self.acts)}
        self.assertEqual(rows["2x20"]["status"], "done")          # done 22/9, i.e. moved into the previous week
        self.assertTrue(rows["2x20"]["moved"])
        self.assertEqual(rows["SS"]["actual_type"], "bike_sweetspot")
        self.assertNotIn("missed_or_not_synced", {rows["2x20"]["status"], rows["SS"]["status"]})

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
        self.assertTrue(any("utanför" in e for e in errs))
        self.assertTrue(any("Okända" in e for e in errs))

    def test_committed_plans_valid_and_rendered(self):
        for f in sorted((ROOT / "plans").glob("*.json")):
            plan = read_json(f)
            errs, _ = plans.validate(plan, self.p, read_json(self.p.profile))
            self.assertEqual(errs, [], f.name)
            self.assertIn(plan["week"], plans.render(plan))


if __name__ == "__main__":
    unittest.main()


class TestPrivacy(unittest.TestCase):
    """D-015 / CLAUDE.md A6: tracked files must not contain the athlete's personal values."""

    TRACKED = ["CLAUDE.md", "README.md", "docs/*.md", "schemas/*.json", "trainer/*.py", "tests/*.py", "data/**/*.example.*"]

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
        for entry in (".env", ".garmin_tokens/", "docs/reference/", "data/**", "plans/*", "log/*"):
            self.assertIn(entry, gi)
