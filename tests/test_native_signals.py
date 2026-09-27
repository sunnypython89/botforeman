"""Local, synthetic tests; no API, model loading, Gold validation or training."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from botforeman import BotForeman
from botforeman.bots.native_pool import CATEGORIES, POOL, select_probes
from botforeman.bots.nativ_roman_bot import NativRomanBot
from botforeman.bots.romanian_levels_bot import RomanianLevelsBot
from botforeman.levels import Limits, ModelReply, RATINGS, Usage
from botforeman.levels.native_demo import ScriptedNativeProvider
from botforeman.levels.native_signals import StabilityRules, native_signal_stability, reserve_selection


class NativeRubricTests(unittest.TestCase):
    def setUp(self):
        self.bot = NativRomanBot()

    def test_exact_categories_and_distinct_pool(self):
        self.assertEqual(CATEGORIES, ("IDIOM", "PRAGMATICS", "REGISTER", "COLLOCATION_NATURALNESS", "IMPLICIT_MEANING"))
        self.assertEqual(len(POOL), 25)
        ids, prompts = set(), set()
        for index in range(5):
            probes = self.bot.native_probes(index)
            self.assertEqual([p["category"] for p in probes], list(CATEGORIES))
            self.assertEqual(len(probes), 5)
            for probe in probes:
                self.assertNotIn(probe["probe_id"], ids)
                self.assertNotIn(probe["prompt"], prompts)
                ids.add(probe["probe_id"])
                prompts.add(probe["prompt"])
                self.assertTrue(probe["context"] and probe["tested_properties"] and probe["evaluator_criterion"])

    def test_determinism_and_rotation(self):
        self.assertEqual(select_probes(2), select_probes(2))
        self.assertNotEqual(select_probes(0), select_probes(1))
        self.assertEqual([p["probe_id"] for p in select_probes(0)], [p["probe_id"] for p in select_probes(5)])

    def grade(self, index, category, wanted):
        item = next(p for p in self.bot.native_probes(index) if p["category"] == category)
        letter = next(k for k, v in item["rubric"].items() if v["result"] == wanted)
        result = self.bot.evaluate_native(item["prompt"], item["answer_options"][letter])
        self.assertEqual(result["result"], wanted)
        self.assertTrue(result["explanation"])
        return item, letter

    def test_natural_idiom_good_and_literal_bad(self):
        self.grade(0, "IDIOM", "GOOD")
        self.grade(0, "IDIOM", "BAD")

    def test_irony_and_indirect_pragmatics(self):
        self.grade(0, "PRAGMATICS", "GOOD")
        self.grade(0, "PRAGMATICS", "BAD")
        self.grade(1, "PRAGMATICS", "UNCERTAIN")

    def test_register_including_explicit_vulgar_style(self):
        for index in (0, 1, 3):
            self.grade(index, "REGISTER", "GOOD")
            self.grade(index, "REGISTER", "BAD")

    def test_translation_artifact_is_bad(self):
        probe = next(p for p in self.bot.native_probes(2) if p["category"] == "COLLOCATION_NATURALNESS")
        self.assertEqual(self.bot.evaluate_native(probe["prompt"], "Sunt 28 de ani vechi.")["result"], "BAD")
        self.assertEqual(self.bot.evaluate_native(probe["prompt"], "Am 28 de ani.")["result"], "GOOD")

    def test_ambiguous_and_regional_variants_uncertain(self):
        self.grade(1, "IMPLICIT_MEANING", "UNCERTAIN")
        self.grade(2, "IMPLICIT_MEANING", "UNCERTAIN")
        self.grade(4, "REGISTER", "UNCERTAIN")
        self.grade(3, "COLLOCATION_NATURALNESS", "UNCERTAIN")

    def test_all_rubrics_use_only_three_results(self):
        for index in range(5):
            for item in self.bot.native_probes(index):
                for letter, expected in item["rubric"].items():
                    result = self.bot.evaluate_native(item["prompt"], letter)
                    self.assertIn(result["result"], RATINGS)
                    self.assertEqual(result, expected)
        self.assertEqual(self.bot.evaluate_native("unknown", "A")["result"], "UNCERTAIN")

    def test_conflicting_label_or_unrecognized_free_text_uncertain(self):
        item = self.bot.native_probes(0)[0]
        self.assertEqual(self.bot.evaluate_native(item["prompt"], "A: " + item["answer_options"]["B"])["result"], "UNCERTAIN")
        self.assertEqual(self.bot.evaluate_native(item["prompt"], "O explicație nouă, posibil corectă.")["result"], "UNCERTAIN")


class NativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.temp = self.root / (".native-test-" + uuid4().hex)
        self.temp.mkdir()
        self.addCleanup(self.cleanup)
        self.foreman = BotForeman()
        self.base = RomanianLevelsBot()
        self.native = NativRomanBot()
        self.foreman.attach(self.base)
        self.foreman.attach(self.native)
        self.provider = ScriptedNativeProvider()

    def cleanup(self):
        resolved = self.temp.resolve()
        if resolved.parent != self.root or not resolved.name.startswith(".native-test-"):
            raise ValueError("Refuse cleanup outside test directory")
        shutil.rmtree(resolved)

    def run_cycle(self, index, limits=None):
        return self.foreman.run_level_cycle(self.base.name, self.provider, self.temp / f"cycle_{index}",
                                            limits=limits, native_evaluator=self.native.name)

    def test_first_four_levels_unchanged_and_native_schema(self):
        report = self.run_cycle(0)
        self.assertEqual(report["completed_probes"], 25)
        self.assertEqual([r["input"] for r in report["records"][:20]], [p.input for p in self.base.level_tests()[:20]])
        self.assertTrue(all(r["evaluator_name"] == self.base.name for r in report["records"][:20]))
        native = report["records"][20:]
        self.assertEqual([r["category"] for r in native], list(CATEGORIES))
        required = {"probe_id", "category", "context", "prompt", "answer_options", "evaluator_criterion",
                    "result", "explanation", "model_output", "cycle_id", "level", "evaluator_name", "usage", "timestamp"}
        for row in native:
            self.assertTrue(required <= row.keys())
            self.assertEqual(row["evaluator_name"], self.native.name)
            self.assertEqual(row["result"], row["evaluator_result"])
            self.assertNotIn("rubric", row)  # internal grading key is not sent to the model
        self.assertEqual(json.loads(json.dumps(report)), report)

    def test_persistent_cursor_rotates_across_new_foreman_instances(self):
        first = self.run_cycle(0)
        self.foreman = BotForeman()
        self.foreman.attach(self.base)
        self.foreman.attach(self.native)
        second = self.run_cycle(1)
        self.assertNotEqual([r["example_id"] for r in first["records"][20:]], [r["example_id"] for r in second["records"][20:]])
        self.assertEqual(second["native_evaluation"]["selection_index"], 1)

    def test_five_cycle_stability_counts(self):
        reports = [self.run_cycle(i) for i in range(5)]
        result = native_signal_stability(reports)
        self.assertEqual([r["GOOD"] for r in result["cycles"]], [5, 4, 5, 5, 4])
        self.assertEqual(result["native_signal_stability"], "native_signal_consistent")
        self.assertEqual(result["unique_probes"], 25)
        self.assertEqual(result["category_counts"]["IDIOM"], {"GOOD": 3, "BAD": 2, "UNCERTAIN": 0})
        strict = native_signal_stability(reports, StabilityRules(min_good_per_cycle=5, max_bad_per_cycle=0))
        self.assertEqual(strict["native_signal_stability"], "native_signal_detected")

    def test_single_perfect_cycle_is_inconclusive_never_certification(self):
        report = self.run_cycle(0)
        result = native_signal_stability([report])
        self.assertEqual(result["cycles"][0]["GOOD"], 5)
        self.assertEqual(result["native_signal_stability"], "native_signal_inconclusive")
        self.assertNotIn("CERTIFIED_NATIVE", json.dumps(result))
        with self.assertRaises(ValueError):
            StabilityRules(min_cycles_detected=1, min_cycles_consistent=1)

    def test_incomplete_cycles_excluded_and_token_limit_preserved(self):
        report = self.run_cycle(0, Limits(max_tokens_per_cycle=22))
        self.assertEqual(report["completed_probes"], 22)
        self.assertEqual(report["status"], "incomplete")
        result = native_signal_stability([report])
        self.assertEqual(result["cycles_considered"], 0)
        self.assertEqual(len(result["excluded_cycles"]), 1)
        self.assertEqual(report["usage"]["cost_usd"], "0")

    def test_cost_and_api_call_limits_still_apply(self):
        with patch.object(self.provider, "estimate", return_value=Usage(total_tokens=1, api_calls=1, cost_usd="0.1")):
            report = self.run_cycle(0, Limits(max_cost_per_cycle="0", max_api_calls_per_cycle=1))
        self.assertEqual(report["completed_probes"], 0)
        self.assertEqual(report["stop_reason"], "limit_reached:cost_usd")
        with patch.object(self.provider, "estimate", return_value=Usage(total_tokens=1, api_calls=1, cost_usd="0")):
            report = self.run_cycle(1, Limits())
        self.assertEqual(report["stop_reason"], "limit_reached:api_calls")

    def test_mixed_models_duplicates_and_repeated_probes(self):
        first, second = self.run_cycle(0), self.run_cycle(1)
        with self.assertRaises(ValueError):
            native_signal_stability([first, first])
        second["native_evaluation"]["comparison_context"]["model_identity"] = "another-checkpoint"
        with self.assertRaises(ValueError):
            native_signal_stability([first, second])
        repeated = deepcopy(first)
        repeated["cycle_id"] = "another-cycle-id"
        result = native_signal_stability([first, repeated])
        self.assertFalse(result["distinct_probes_in_window"])
        self.assertEqual(result["native_signal_stability"], "native_signal_inconclusive")

    def test_bad_evaluator_response_saved_as_uncertain(self):
        with patch.object(self.native, "evaluate_native", return_value="GOOD"):
            report = self.run_cycle(0)
        self.assertEqual(report["completed_probes"], 21)
        self.assertEqual(report["records"][-1]["result"], "UNCERTAIN")
        self.assertTrue(report["stop_reason"].startswith("evaluator_error"))

    def test_selection_lock_and_corrupt_cursor_fail_closed(self):
        path = self.temp / "state.json"
        path.with_suffix(".json.lock").touch()
        with self.assertRaises(FileExistsError):
            reserve_selection(path)
        path.with_suffix(".json.lock").unlink()
        path.write_text('{"next_cycle_index": -1}', encoding="utf-8")
        with self.assertRaises(ValueError):
            reserve_selection(path)


if __name__ == "__main__":
    unittest.main()
