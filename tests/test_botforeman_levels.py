import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from botforeman import BotForeman
from botforeman.bots.romanian_levels_bot import RomanianLevelsBot
from botforeman.levels import LEVELS, RATINGS, Limits, ModelReply, Probe, Usage
from botforeman.levels.protocol import validate_rating
from botforeman.levels.runner import format_report


class SyntheticProvider:
    name = "synthetic-unit-test-only"
    paid = False

    def __init__(self, usage=None, actual=None, fail_at=None):
        self.usage = usage or Usage(total_tokens=1, api_calls=0, cost_usd="0")
        self.actual = actual or self.usage
        self.fail_at = fail_at
        self.inputs = []

    def estimate(self, prompt):
        return self.usage

    def generate(self, prompt):
        self.inputs.append(prompt)
        if len(self.inputs) == self.fail_at:
            raise RuntimeError("Synthetic failure")
        return ModelReply("A", self.actual)


class LevelCycleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.temp = self.root / (".levels-test-" + uuid4().hex)
        self.temp.mkdir()
        self.addCleanup(self.cleanup)
        self.bot = RomanianLevelsBot()
        self.foreman = BotForeman()
        self.foreman.attach(self.bot)

    def cleanup(self):
        resolved = self.temp.resolve()
        if resolved.parent != self.root or not resolved.name.startswith(".levels-test-"):
            raise ValueError("Refuse cleanup outside test workspace")
        shutil.rmtree(resolved)

    def run_cycle(self, provider=None, limits=None, callback=None, name="cycle"):
        return self.foreman.run_level_cycle(self.bot.name, provider or SyntheticProvider(),
                                            self.temp / name, limits=limits, on_level=callback)

    def test_exactly_25_in_fixed_order_five_per_level(self):
        report = self.run_cycle()
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed_probes"], 25)
        self.assertEqual([row["level"] for row in report["records"]],
                         [level for level in LEVELS for _ in range(5)])
        self.assertEqual([summary["completed"] for summary in report["levels"]], [5] * 5)

    def test_all_inputs_distinct_within_levels(self):
        probes = self.bot.level_tests()
        for level in LEVELS:
            self.assertEqual(len({p.input for p in probes if p.level == level}), 5)

    def test_only_three_ratings(self):
        for rating in RATINGS:
            self.assertEqual(validate_rating(rating), rating)
        for rating in ("PASS", "FAIL", "good", "", None, 1, []):
            with self.subTest(rating=rating), self.assertRaises(ValueError):
                validate_rating(rating)
        probe = self.bot.level_tests()[0]
        self.assertEqual(self.bot.evaluate_rating(probe.input, "A"), "GOOD")
        self.assertEqual(self.bot.evaluate_rating(probe.input, "B"), "BAD")
        self.assertEqual(self.bot.evaluate_rating(probe.input, "A sau B"), "UNCERTAIN")

    def test_cycle_record_serialization_and_required_fields(self):
        report = self.run_cycle()
        saved = json.loads((self.temp / "cycle" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, report)
        self.assertEqual(json.loads(json.dumps(report)), report)
        required = {"cycle_id", "level", "example_id", "input", "model_output",
                    "evaluator_result", "evaluator_name", "timestamp", "usage"}
        for record in report["records"]:
            self.assertTrue(required <= record.keys())
            self.assertNotIn("score", record)
            self.assertEqual(record["model_output"], "A")

    def test_unambiguous_choice_formats_and_contradictions(self):
        probe = self.bot.level_tests()[0]
        for output in ("A", "A.", "A: Bună dimineața!", "A:Bună dimineața"):
            self.assertEqual(self.bot.evaluate_rating(probe.input, output), "GOOD")
        self.assertEqual(self.bot.evaluate_rating(probe.input, "B: Noapte bună!"), "BAD")
        for output in ("A: Noapte bună!", "A: Bună dimi", "A dar poate B", "C"):
            self.assertEqual(self.bot.evaluate_rating(probe.input, output), "UNCERTAIN")

    def test_summaries_and_final_matrix(self):
        report = self.run_cycle()
        self.assertEqual(report["levels"][0]["GOOD"], 3)
        self.assertEqual(report["levels"][0]["BAD"], 2)
        self.assertEqual(report["levels"][0]["UNCERTAIN"], 0)
        self.assertEqual(report["totals"], {"GOOD": 12, "BAD": 13, "UNCERTAIN": 0})
        self.assertEqual(report["matrix"][0].split(), ["STRAIN", "G", "B", "G", "B", "G"])
        text = format_report(report)
        self.assertIn("GOOD total: 12", text)
        self.assertIn("25/25 probes — complete", text)

    def test_level_summary_before_next_level_generation(self):
        provider = SyntheticProvider()
        counts = []
        self.run_cycle(provider, callback=lambda s: counts.append((s["level"], len(provider.inputs))))
        self.assertEqual(counts, list(zip(LEVELS, (5, 10, 15, 20, 25))))

    def test_monetary_limit_prevents_next_call(self):
        provider = SyntheticProvider(Usage(total_tokens=1, api_calls=0, cost_usd="0.01"))
        report = self.run_cycle(provider, Limits(max_cost_per_cycle="0.05"))
        self.assertEqual(len(provider.inputs), 5)
        self.assertEqual(report["usage"]["cost_usd"], "0.05")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["stop_reason"], "limit_reached:cost_usd")

    def test_partial_results_saved_on_token_limit(self):
        report = self.run_cycle(limits=Limits(max_tokens_per_cycle=7))
        lines = (self.temp / "cycle" / "probes.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 7)
        saved = json.loads((self.temp / "cycle" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, report)
        self.assertEqual(report["records"][-1]["level"], "INCEPATOR")
        self.assertEqual(report["levels"][1]["completed"], 2)

    def test_unknown_cost_falls_back_to_api_call_limit(self):
        # Synthetic usage only: no network provider exists.
        provider = SyntheticProvider(Usage(api_calls=1))
        limits = Limits(max_cost_per_cycle="1", max_tokens_per_cycle=None, max_api_calls_per_cycle=2)
        report = self.run_cycle(provider, limits)
        self.assertEqual(report["completed_probes"], 2)
        self.assertIsNone(report["usage"]["cost_usd"])
        self.assertEqual(report["usage"]["api_calls"], 2)

    def test_unavailable_usage_blocks_without_spending(self):
        provider = SyntheticProvider(Usage())
        report = self.run_cycle(provider)
        self.assertEqual(provider.inputs, [])
        self.assertEqual(report["completed_probes"], 0)
        self.assertTrue(report["stop_reason"].startswith("usage_unavailable"))

    def test_provider_overrun_stops_immediately_and_is_recorded(self):
        provider = SyntheticProvider(actual=Usage(total_tokens=6, api_calls=0, cost_usd="0"))
        report = self.run_cycle(provider, Limits(max_tokens_per_cycle=5))
        self.assertEqual(report["completed_probes"], 1)
        self.assertEqual(report["usage"]["total_tokens"], 6)
        self.assertEqual(len(provider.inputs), 1)

    def test_unknown_observed_usage_retains_reservation(self):
        provider = SyntheticProvider(actual=Usage())
        report = self.run_cycle(provider, Limits(max_tokens_per_cycle=3))
        self.assertEqual(report["completed_probes"], 3)
        self.assertIsNone(report["usage"]["total_tokens"])
        self.assertEqual(report["accounted_usage"]["total_tokens"], 3)

    def test_provider_error_keeps_partial_results_and_no_retry(self):
        provider = SyntheticProvider(fail_at=3)
        report = self.run_cycle(provider)
        self.assertEqual(report["completed_probes"], 2)
        self.assertEqual(len(provider.inputs), 3)
        self.assertEqual(report["accounted_usage"]["total_tokens"], 3)
        self.assertTrue(report["stop_reason"].startswith("provider_error"))

    def test_new_cycle_restarts_and_has_new_id(self):
        first = self.run_cycle(limits=Limits(max_tokens_per_cycle=7))
        second = self.run_cycle(name="new_cycle")
        self.assertNotEqual(first["cycle_id"], second["cycle_id"])
        self.assertEqual(second["records"][0]["level"], "STRAIN")
        self.assertEqual(second["completed_probes"], 25)

    def test_bad_curriculum_is_rejected_before_any_call(self):
        original = list(self.bot.level_tests())
        variants = [original[:-1], original[::-1], original + original[:1]]
        duplicate = original[:]
        duplicate[1] = Probe("STRAIN", "distinct_id", original[0].input)
        variants.append(duplicate)
        for probes in variants:
            provider = SyntheticProvider()
            with patch.object(self.bot, "level_tests", return_value=probes), self.assertRaises(ValueError):
                self.run_cycle(provider)
            self.assertEqual(provider.inputs, [])

    def test_invalid_evaluator_result_stops_with_uncertain_record(self):
        with patch.object(self.bot, "evaluate_rating", return_value="PASS"):
            report = self.run_cycle()
        self.assertEqual(report["completed_probes"], 1)
        self.assertEqual(report["records"][0]["evaluator_result"], "UNCERTAIN")
        self.assertEqual(report["stop_reason"], "evaluator_error:ValueError")

    def test_no_overwrite_and_disabled_or_paid_no_calls(self):
        self.run_cycle()
        provider = SyntheticProvider()
        with self.assertRaises(FileExistsError):
            self.run_cycle(provider)
        self.foreman.enabled = False
        with self.assertRaises(ValueError):
            self.run_cycle(provider, name="disabled")
        self.foreman.enabled = True
        provider.paid = True
        with self.assertRaises(PermissionError):
            self.run_cycle(provider, name="paid")
        self.assertEqual(provider.inputs, [])

    def test_usage_validation_and_credit_totals(self):
        for kwargs in ({"max_cost_per_cycle": "NaN"}, {"max_tokens_per_cycle": -1},
                       {"max_api_calls_per_cycle": True}):
            with self.assertRaises(ValueError):
                Limits(**kwargs)
        with self.assertRaises(ValueError):
            Usage(input_tokens=3, output_tokens=2, total_tokens=4)
        provider = SyntheticProvider(Usage(input_tokens=1, output_tokens=1, api_calls=0,
                                           cost_usd="0", credits="0.2"))
        report = self.run_cycle(provider)
        self.assertEqual(report["usage"]["credits"], "5.0")
        self.assertEqual(report["usage"]["total_tokens"], 50)


if __name__ == "__main__":
    unittest.main()
