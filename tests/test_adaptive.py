from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from botforeman import BotForeman
from botforeman.bots.nativ_roman_bot import NativRomanBot
from botforeman.adaptive.demo import ScriptedProvider
from botforeman.adaptive.evaluation import EvaluationCache, EvaluationChain, Judgment, Meter, ZERO
from botforeman.adaptive.native import NativePrimary, NativeSecondary
from botforeman.adaptive.runner import audit_verdict, run_adaptive
from botforeman.adaptive.state import Registry, Rules, learning_state, select, text_hash
from botforeman.cycle.budget import BudgetLedger, fingerprint as budget_fingerprint
from botforeman.levels.protocol import Limits, Usage


class Stage:
    paid = False
    version = "test-v1"

    def __init__(self, name, result):
        self.name, self.result, self.calls = name, result, 0

    def estimate(self, probe, output):
        return ZERO

    def evaluate(self, probe, output):
        self.calls += 1
        return Judgment(self.result, "Synthetic judgment only", ZERO)


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.temp = self.root / (".adaptive-test-" + uuid4().hex)
        self.temp.mkdir()
        self.addCleanup(self.cleanup)
        self.bot = NativRomanBot()
        self.pool = self.bot.adaptive_pool()
        self.chain = EvaluationChain(NativePrimary(self.bot), NativeSecondary(self.bot))
        self.provider = ScriptedProvider(self.pool)
        self.context = {"model": "test-model", "adapter": "test-adapter", "probe_pool_version": "pool1"}

    def cleanup(self):
        path = self.temp.resolve()
        if path.parent != self.root or not path.name.startswith(".adaptive-test-"):
            raise ValueError("Refuse cleanup outside test workspace")
        shutil.rmtree(path)

    def run_workflow(self, name, **kwargs):
        return run_adaptive(self.pool, self.chain, self.provider, self.temp / name,
                            workspace=self.temp / "state", **self.context, **kwargs)

    def test_scout_small_diverse_and_manifest_saved(self):
        report = self.run_workflow("scout")
        self.assertEqual(report["completed_probes"], 3)
        self.assertLess(report["completed_probes"], 25)
        self.assertEqual(len({r["category"] for r in report["records"]}), 3)
        self.assertEqual(report["counts"], {"GOOD": 1, "BAD": 1, "UNCERTAIN": 1})
        manifest = json.loads((self.temp / "scout" / "manifest.json").read_text(encoding="utf-8"))
        for key in ("run_id", "mode", "model", "adapter", "evaluator_versions", "probe_pool_version", "seed", "timestamp",
                    "max_tokens", "max_api_calls", "max_cost", "cache_enabled"):
            self.assertIn(key, manifest)
        self.assertEqual(json.loads((self.temp / "scout" / "report.json").read_text(encoding="utf-8")), report)

    def test_audit_only_suspects_and_new_questions(self):
        scout = self.run_workflow("scout")
        self.provider.phase = "AUDIT"
        audit = self.run_workflow("audit", mode="AUDIT", scout=scout)
        self.assertEqual(audit["completed_probes"], 4)
        self.assertEqual(set(audit["audit_verdicts"]), set(scout["suspect_categories"]))
        self.assertTrue({r["category"] for r in audit["records"]} <= set(scout["suspect_categories"]))
        self.assertFalse({r["probe_id"] for r in scout["records"]} & {r["probe_id"] for r in audit["records"]})
        self.assertFalse({r["text_hash"] for r in scout["records"]} & {r["text_hash"] for r in audit["records"]})
        self.assertEqual(set(audit["audit_verdicts"].values()), {"CONFIRMED_FAILURE", "CONFIRMED_STRENGTH"})
        self.assertEqual(len(audit["summary"]["PROBE_QUALITY_ISSUES"]), 1)

    def test_changed_scout_configuration_rejected(self):
        scout = self.run_workflow("scout")
        scout["manifest"]["context"]["adapter"] = "changed"
        with self.assertRaises(ValueError):
            self.run_workflow("audit", mode="AUDIT", scout=scout)

    def test_learning_states_distinct_probes_and_alternation(self):
        rules = Rules()
        history = lambda outcomes: [{"probe_id": str(i), "text_hash": str(i), "result": value} for i, value in enumerate(outcomes)]
        self.assertEqual(learning_state(history(["BAD"]), rules), "NEEDS_RETEST")
        self.assertEqual(learning_state(history(["UNCERTAIN"]), rules), "NEEDS_RETEST")
        self.assertEqual(learning_state(history(["GOOD"] * 3), rules), "STABLE_GOOD")
        self.assertEqual(learning_state(history(["GOOD", "BAD", "GOOD", "BAD"]), rules), "UNSTABLE")
        repeated = [{"probe_id": "same", "text_hash": "same", "result": "GOOD"}] * 3
        self.assertNotEqual(learning_state(repeated, rules), "STABLE_GOOD")

    def test_registry_prioritizes_retest_and_avoids_stable(self):
        reg = Registry(self.temp / "registry.json", self.context, Rules())
        cats = sorted({p["category"] for p in self.pool})
        for category in cats:
            reg.current["skills"][category] = [{"probe_id": str(i), "text_hash": str(i), "result": "GOOD"} for i in range(3)]
        reg.current["skills"][cats[-1]] = [{"probe_id": "bad", "text_hash": "bad", "result": "BAD"}]
        selected, _ = select(self.pool, reg, "SCOUT", 42)
        self.assertEqual(selected[0]["category"], cats[-1])

    def test_secondary_only_after_uncertain(self):
        cache = EvaluationCache(self.temp / "cache")
        for i, result in enumerate(("GOOD", "BAD", "UNCERTAIN")):
            primary, secondary, api = Stage("p", result), Stage("s", "GOOD"), Stage("api", "BAD")
            chain = EvaluationChain(primary, secondary, api)
            verdict, trace, _ = chain.evaluate(self.pool[0], str(i), self.context, cache, Meter(Limits(), lambda e: None), str(i))
            self.assertEqual(primary.calls, 1)
            self.assertEqual(secondary.calls, int(result == "UNCERTAIN"))
            self.assertEqual(api.calls, 0)

    def test_api_blocked_by_default_even_if_uncertain(self):
        primary, secondary, api = Stage("p", "UNCERTAIN"), Stage("s", "UNCERTAIN"), Stage("api", "GOOD")
        chain = EvaluationChain(primary, secondary, api)
        result, trace, _ = chain.evaluate(self.pool[0], "unknown", self.context,
                                         EvaluationCache(self.temp / "cache"), Meter(Limits(), lambda e: None), "test")
        self.assertEqual(result.result, "UNCERTAIN")
        self.assertEqual(api.calls, 0)
        self.assertTrue(trace[-1]["blocked"])

    def paid_chain(self):
        api = Stage("api", "GOOD")
        api.paid, api.model = True, "SYNTHETIC-NOT-A-PROVIDER"
        def evaluate(probe, output):
            api.calls += 1
            return Judgment("GOOD", "Synthetic", Usage(input_tokens=10, output_tokens=10, api_calls=1, cost_usd="0"))
        api.evaluate = evaluate
        policy = {"enabled": True, "model": api.model, "max_calls": 2, "max_input_tokens": 10,
                  "max_output_tokens": 10, "budget_usd": "0.1", "automatic_retries": 0,
                  "verified_pricing": {"model": api.model, "source_url": "https://example.invalid/test-only",
                      "verified_at": datetime.now(timezone.utc).isoformat(), "input_usd_per_million": "1000", "output_usd_per_million": "1000"}}
        policy["approval"] = {"approved_by": "SYNTHETIC-TEST", "approved_at": datetime.now(timezone.utc).isoformat(),
                              "budget_usd": policy["budget_usd"], "policy_sha256": budget_fingerprint(policy)}
        ledger = BudgetLedger(policy, self.temp / "paid-test.jsonl")
        return EvaluationChain(Stage("p", "UNCERTAIN"), Stage("s", "UNCERTAIN"), api,
                               allow_api=True, api_ledger=ledger), api

    def test_api_zero_limits_and_unverified_prices_never_call(self):
        chain, api = self.paid_chain()
        for limits in (Limits(max_cost_per_cycle="0", max_api_calls_per_cycle=2),
                       Limits(max_cost_per_cycle="1", max_api_calls_per_cycle=0)):
            chain.evaluate(self.pool[0], "unknown", self.context, EvaluationCache(self.temp / "cache"),
                           Meter(limits, lambda e: None), "test")
        self.assertEqual(api.calls, 0)
        chain.api_ledger.policy["verified_pricing"] = None
        chain.evaluate(self.pool[0], "unknown", self.context, EvaluationCache(self.temp / "cache"),
                       Meter(Limits(max_cost_per_cycle="1", max_api_calls_per_cycle=2), lambda e: None), "test")
        self.assertEqual(api.calls, 0)

    def test_approved_synthetic_api_accounted_at_verified_rate(self):
        chain, api = self.paid_chain()
        meter = Meter(Limits(max_cost_per_cycle="0.02", max_api_calls_per_cycle=2), lambda e: None)
        cache = EvaluationCache(self.temp / "cache")
        result, _, _ = chain.evaluate(self.pool[0], "unknown", self.context, cache, meter, "one")
        self.assertEqual(result.result, "GOOD")
        self.assertEqual(api.calls, 1)
        self.assertEqual(meter.observed[-1].cost_usd, "0.02")
        chain.evaluate(self.pool[1], "unknown", self.context, cache, meter, "two")
        self.assertEqual(api.calls, 1)  # run budget prevents a second synthetic call

    def test_cache_identity_and_invalidations(self):
        stage = Stage("primary", "GOOD")
        cache = EvaluationCache(self.temp / "cache")
        chain = EvaluationChain(stage)
        for _ in range(2):
            chain.evaluate(self.pool[0], "same-output", self.context, cache, Meter(Limits(), lambda e: None), "test")
        self.assertEqual(stage.calls, 1)
        for field in ("model", "adapter", "probe_pool_version"):
            changed = {**self.context, field: "changed"}
            chain.evaluate(self.pool[0], "same-output", changed, cache, Meter(Limits(), lambda e: None), "test")
        stage.version = "test-v2"
        chain.evaluate(self.pool[0], "same-output", self.context, cache, Meter(Limits(), lambda e: None), "test")
        self.assertEqual(stage.calls, 5)

    def test_weak_probe_is_not_model_failure_and_core_manual(self):
        registry = Registry(self.temp / "registry.json", self.context, Rules(weak_uncertain=2))
        item = self.pool[0]
        trace = [{"evaluator": "p", "version": "1", "result": "UNCERTAIN"}]
        registry.observe(item, "UNCERTAIN", trace, "one")
        result = registry.observe(item, "UNCERTAIN", trace, "two")
        self.assertEqual(result["registry_state"], "WEAK")
        self.assertEqual(result["issue"], "PROBE_QUALITY_ISSUE")
        result = registry.observe(item, "BAD", [], "bad")
        self.assertEqual(result["issue"], "PROBE_QUALITY_ISSUE")
        registry.observe(self.pool[1], "GOOD", [], "good")
        self.assertEqual(registry.probe(self.pool[1])["registry_state"], "NORMAL")
        registry.set_probe_state(self.pool[1], "CORE")
        self.assertEqual(registry.probe(self.pool[1])["registry_state"], "CORE")

    def test_cached_replay_does_not_inflate_weak_counts(self):
        registry = Registry(self.temp / "registry.json", self.context, Rules())
        for _ in range(4):
            registry.observe(self.pool[0], "UNCERTAIN", [], "same", cache_only=True)
        self.assertEqual(registry.probe(self.pool[0])["uncertain_count"], 0)

    def test_anti_duplicate_ids_text_recent_and_retired(self):
        reg = Registry(self.temp / "registry.json", self.context, Rules())
        duplicate = {**self.pool[0], "probe_id": "alias"}
        retired = self.pool[1]
        reg.set_probe_state(retired, "RETIRED")
        reg.current["recent_resolved"] = [{"probe_id": self.pool[2]["probe_id"], "text_hash": text_hash(self.pool[2]["prompt"])}]
        selected, _ = select(self.pool + [self.pool[0], duplicate], reg, "SCOUT", 42)
        self.assertEqual(len(selected), len({p["probe_id"] for p in selected}))
        self.assertEqual(len(selected), len({text_hash(p["prompt"]) for p in selected}))
        self.assertNotIn(retired["probe_id"], [p["probe_id"] for p in selected])
        self.assertNotIn(self.pool[2]["probe_id"], [p["probe_id"] for p in selected])

    def test_token_cap_and_partial_results(self):
        report = self.run_workflow("limited", limits=Limits(max_tokens_per_cycle=2))
        self.assertEqual(report["completed_probes"], 2)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["usage"]["total_tokens"], 2)
        self.assertEqual(len((self.temp / "limited" / "results.jsonl").read_text(encoding="utf-8").splitlines()), 2)

    def test_audit_internal_verdicts(self):
        def records(values):
            return [{"probe_id": str(i), "evaluator_result": v, "issue": None} for i, v in enumerate(values)]
        self.assertEqual(audit_verdict(records(["GOOD", "BAD"]), Rules()), "UNSTABLE")
        self.assertEqual(audit_verdict(records(["GOOD", "UNCERTAIN"]), Rules()), "NEEDS_MORE_EVIDENCE")
        self.assertEqual(audit_verdict(records(["BAD"]), Rules()), "NEEDS_MORE_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
