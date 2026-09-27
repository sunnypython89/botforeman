"""Synthetic tests only; test reviews never validate production Gold."""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import shutil
import uuid
import unittest
from unittest.mock import patch

from botforeman import BotForeman
from botforeman.bots.nativ_roman_bot import NativRomanBot
from botforeman.cycle.budget import BudgetLedger, fingerprint, quote
from botforeman.cycle import workflow as w
from botforeman.cycle.experiment import validated_gold, check_baseline, plan
from botforeman.cycle.compare import compare


# Public tests use a tiny synthetic workspace, never private model/data files.
_ORIGINAL_ROOT = w.ROOT
_PATCHES = []
_FIXTURE_ROOT = None


def setUpModule():
    global _FIXTURE_ROOT
    _FIXTURE_ROOT = Path(__file__).resolve().parent / (".cycle-fixture-" + uuid.uuid4().hex)
    _FIXTURE_ROOT.mkdir()
    (_FIXTURE_ROOT / "tests").mkdir()
    for filename in w.BENCHMARKS.values():
        target = _FIXTURE_ROOT / filename
        if target.suffix == ".py":
            target.write_text("TESTS = [('fixture', 'Synthetic protected prompt', 'Synthetic answer')]", encoding="utf-8")
        else:
            target.write_text(json.dumps({"id": "fixture", "prompt": "Synthetic protected prompt", "reference": "Synthetic answer"}) + "\n", encoding="utf-8")
    adapter = _FIXTURE_ROOT / "copycat_07_epoch1_adapter"
    adapter.mkdir()
    (adapter / "adapter_model.safetensors").write_bytes(b"NOT MODEL WEIGHTS: synthetic integrity fixture")
    original_benchmarks, original_protected = w.benchmark_rows, w.protected_prompts
    benchmarks = lambda root=None: original_benchmarks(root or _FIXTURE_ROOT)
    protected = lambda root=None: original_protected(root or _FIXTURE_ROOT)
    from botforeman.cycle import experiment
    import importlib
    comparison = importlib.import_module("botforeman.cycle.compare")
    for target, name, value in ((w, "ROOT", _FIXTURE_ROOT), (w, "benchmark_rows", benchmarks),
                               (w, "protected_prompts", protected), (experiment, "benchmark_rows", benchmarks),
                               (experiment, "protected_prompts", protected), (comparison, "benchmark_rows", benchmarks)):
        replacement = patch.object(target, name, value)
        replacement.start()
        _PATCHES.append(replacement)


def tearDownModule():
    for replacement in reversed(_PATCHES):
        replacement.stop()
    root = _FIXTURE_ROOT.resolve()
    if root.parent != Path(__file__).resolve().parent or not root.name.startswith(".cycle-fixture-"):
        raise ValueError("Unsafe fixture cleanup")
    shutil.rmtree(root)


class WorkspaceTemporaryDirectory:
    """Use ordinary workspace ACLs under the Windows sandbox."""
    def __init__(self):
        self.path = w.ROOT / "tests" / (".cycle-test-" + uuid.uuid4().hex)
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self):
        resolved = self.path.resolve()
        if resolved.parent != (w.ROOT / "tests").resolve() or not resolved.name.startswith(".cycle-test-"):
            raise ValueError("Refuse cleanup outside the test workspace")
        shutil.rmtree(resolved)


class NativeBotTests(unittest.TestCase):
    def test_compatible_and_never_certifies_native_quality(self):
        probes = w.rows(w.PROBES)
        bot = NativRomanBot(probes)
        foreman = BotForeman()
        foreman.attach(bot)
        for probe in probes:
            output = probe.get("candidate", "Un răspuns.")
            result = foreman.evaluate(probe["prompt"], output)[0]
            self.assertEqual(result.status, "UNCERTAIN")
            self.assertIsNone(result.score)
            details = bot.analyze(probe["prompt"], output)
            self.assertEqual(set(details["dimensions"]), set(bot.criteria))
            for span in details["spans"]:
                self.assertEqual(output[span["start"]:span["end"]], span["text"])

    def test_tentative_informal_register_signal(self):
        probe = w.rows(w.PROBES)[1]
        result = NativRomanBot([probe]).evaluate(probe["prompt"], "Dă-mi oferta joi la 11:30.")
        self.assertIn("Dă-mi", result.plan.omit)
        self.assertEqual(result.status, "UNCERTAIN")

    def test_probe_separation(self):
        probes = w.rows(w.PROBES)
        protected = w.protected_prompts()
        self.assertEqual(len(probes), 10)
        self.assertEqual(sum(p["split"] == "lesson" for p in probes), 6)
        self.assertTrue(all(w.normalized(p["prompt"]) not in protected for p in probes))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = WorkspaceTemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "usage.jsonl"
        self.policy = {"enabled": True, "model": "SYNTHETIC-TEST-NOT-A-REAL-MODEL",
            "verified_pricing": {"model": "SYNTHETIC-TEST-NOT-A-REAL-MODEL",
                "source_url": "https://example.invalid/synthetic-test-pricing",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "input_usd_per_million": "1", "output_usd_per_million": "2"},
            "max_calls": 2, "max_input_tokens": 100, "max_output_tokens": 100,
            "budget_usd": "0.0006", "automatic_retries": 0}
        self.approve()

    def approve(self):
        self.policy["approval"] = {"approved_by": "SYNTHETIC UNIT TEST",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "budget_usd": self.policy["budget_usd"], "policy_sha256": fingerprint(self.policy)}

    def test_disabled_and_unapproved(self):
        self.policy["enabled"] = False
        with self.assertRaises(PermissionError):
            BudgetLedger(self.policy, self.path).reserve("1")
        self.policy["enabled"] = True
        self.policy["approval"] = None
        with self.assertRaises(PermissionError):
            BudgetLedger(self.policy, self.path).reserve("1")
        self.assertFalse(self.path.exists())

    def test_missing_expired_or_invalid_price(self):
        bad = deepcopy(self.policy)
        bad["verified_pricing"] = None
        with self.assertRaises(ValueError):
            quote(bad)
        self.policy["verified_pricing"]["verified_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):
            quote(self.policy)

    def test_restart_cap_and_no_retries(self):
        ledger = BudgetLedger(self.policy, self.path)
        ledger.reserve("one")
        with self.assertRaises(PermissionError):
            ledger.reserve("one")
        BudgetLedger(self.policy, self.path).reserve("two")
        with self.assertRaises(PermissionError):
            ledger.reserve("three")

    def test_cost_cap_before_call(self):
        self.policy["budget_usd"] = "0.00029"
        self.approve()
        with self.assertRaises(PermissionError):
            BudgetLedger(self.policy, self.path).reserve("one")
        self.assertFalse(self.path.exists())

    def test_usage_settlement_and_breach(self):
        ledger = BudgetLedger(self.policy, self.path)
        ledger.reserve("one")
        ledger.settle("one", 50, 20)
        self.assertEqual(w.rows(self.path)[-1]["cost_usd"], "0.00009")
        ledger.reserve("two")
        with self.assertRaises(PermissionError):
            ledger.settle("two", 101, 20)
        with self.assertRaises(PermissionError):
            ledger.reserve("three")

    def test_lock_and_changed_policy_fail_closed(self):
        Path(str(self.path) + ".lock").touch()
        with self.assertRaises(FileExistsError):
            BudgetLedger(self.policy, self.path).reserve("one")
        Path(str(self.path) + ".lock").unlink()
        self.policy["max_calls"] = 3
        with self.assertRaises(PermissionError):
            BudgetLedger(self.policy, self.path).reserve("one")


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = WorkspaceTemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "cycle"
        w.prepare(self.directory)
        self.probes = w.rows(self.directory / "probes.jsonl")
        self.observations = self.directory / "synthetic.jsonl"
        self.make_run(self.observations)
        w.review(self.directory, self.observations)

    def make_run(self, path, answer="Synthetic test output"):
        data = [{"id": p["id"], "split": p["split"], "prompt": p["prompt"],
                 "benchmark": "new_probes", "output": answer,
                 "source": "SYNTHETIC_TEST_ONLY"} for p in self.probes]
        w.write_rows(path, data)
        config = w.read_json(self.directory / "config.json")
        w.write_json(str(path) + ".meta.json", {"output_sha256": w.digest(path),
            "botforeman_attached": False, "completed_count": len(data),
            "model": "synthetic", "generation": config["generation"],
            "adapter_sha256": w.digest(Path(config["starting_adapter"]) / "adapter_model.safetensors")})

    def test_pending_review_cannot_create_gold(self):
        with self.assertRaises(ValueError):
            w.export_gold(self.directory, self.directory / "review_template.jsonl", self.directory / "gold.jsonl")
        self.assertFalse((self.directory / "gold.jsonl").exists())
        self.assertEqual(len(w.rows(self.directory / "review_queue.jsonl")), 6)

    def test_confirm_correct_and_provenance(self):
        decisions = w.rows(self.directory / "review_template.jsonl")
        for item in decisions[:2]:
            item.update(decision="confirm", reviewer="SYNTHETIC TEST", reviewed_at=w.now())
        decisions[1].update(decision="correct", target="Corecție sintetică de test.")
        decision_path = self.directory / "test_decisions.jsonl"
        w.write_rows(decision_path, decisions)
        gold = self.directory / "test_gold.jsonl"
        self.assertEqual(w.export_gold(self.directory, decision_path, gold), 2)
        data = validated_gold(self.directory, gold)
        self.assertEqual(data[1]["messages"][1]["content"], "Corecție sintetică de test.")
        with gold.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        with self.assertRaises(ValueError):
            validated_gold(self.directory, gold)

    def test_holdout_and_stale_reviews_rejected(self):
        decision = w.rows(self.directory / "review_template.jsonl")[0]
        decision.update(id="NRH01", decision="confirm", reviewer="TEST", reviewed_at=w.now())
        path = self.directory / "bad.jsonl"
        w.write_rows(path, [decision])
        with self.assertRaises(ValueError):
            w.export_gold(self.directory, path, self.directory / "gold.jsonl")
        decision.update(id="NR01", queue_sha256="stale")
        path2 = self.directory / "stale.jsonl"
        w.write_rows(path2, [decision])
        with self.assertRaises(ValueError):
            w.export_gold(self.directory, path2, self.directory / "gold.jsonl")

    def test_training_gates_without_gpu(self):
        self.assertEqual(plan(self.directory)["status"], "blocked")
        with self.assertRaises(ValueError):
            check_baseline(self.directory, self.observations)

    def test_no_overwrite_or_changed_probes(self):
        with self.assertRaises(FileExistsError):
            w.prepare(self.directory)
        with (self.directory / "probes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("\n")
        with self.assertRaises(ValueError):
            w.verify(self.directory)

    def test_comparison_requires_new_human_labels(self):
        after = self.directory / "after.jsonl"
        self.make_run(after, "Different synthetic response")
        report_path = self.directory / "compare.json"
        report = compare(self.observations, after, report_path)
        self.assertEqual(report["reviewed"], 0)
        self.assertEqual(report["suites"]["new_holdout"]["changed"], 4)
        self.assertEqual(report["regressions"], [])
        judgments = w.rows(str(report_path) + ".review.jsonl")[:1]
        judgments[0].update(semantic_before=True, semantic_after=False,
                            reviewer="SYNTHETIC TEST", reviewed_at=w.now())
        path = self.directory / "judgments.jsonl"
        w.write_rows(path, judgments)
        scored = compare(self.observations, after, self.directory / "scored.json", path)
        self.assertEqual(len(scored["regressions"]), 1)


if __name__ == "__main__":
    unittest.main()
