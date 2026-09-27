import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from botforeman.knowledge import KnowledgeStore


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / (".knowledge-test-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.store = KnowledgeStore(self.root / "store.json")

    def cleanup(self):
        root = self.root.resolve()
        if root.parent != Path(__file__).resolve().parent or not root.name.startswith(".knowledge-test-"):
            raise ValueError("Refuse cleanup outside tests")
        shutil.rmtree(root)

    def propose(self, **kwargs):
        return self.store.propose(source="MANUAL", original_input="old", category="skill", related_probe_id="old-id", **kwargs)["knowledge_id"]

    def verified(self):
        key = self.propose()
        self.store.verify(key, "Approved exact content", "human", "Explicit review")
        return key

    def report(self, rating="BAD", issue="MODEL_FAILURE", audit="CONFIRMED_FAILURE"):
        value = {"manifest": {"mode": "AUDIT", "run_id": "test-run", "model": "fixture"},
                 "audit_verdicts": {"skill": audit}, "records": [{"probe_id": "p1", "category": "skill",
                 "input": "question", "model_output": "answer", "evaluator_result": rating,
                 "issue": issue, "explanation": "fixture reason", "evaluation_trace": [{"name": "fixture"}]}]}
        path = self.root / "report.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_confirmed_failure_proposed_and_extraction_idempotent(self):
        path = self.report()
        item = self.store.extract(path)[0]
        self.assertEqual(item["status"], "PROPOSED")
        self.assertEqual(item["type"], "CORRECTION")
        self.assertIsNone(item["verified_content"])
        self.store.extract(path)
        self.assertEqual(len(self.store.list()), 1)

    def test_uncertain_never_verified(self):
        item = self.store.extract(self.report("UNCERTAIN", None, "NEEDS_MORE_EVIDENCE"))[0]
        self.assertEqual(item["status"], "PROPOSED")
        self.assertEqual(item["type"], "ANALYSIS")
        with self.assertRaises(ValueError):
            self.store.implement(item["knowledge_id"], dry_run=False)

    def test_probe_quality_never_dataset(self):
        item = self.store.extract(self.report("BAD", "PROBE_QUALITY_ISSUE"))[0]
        self.store.verify(item["knowledge_id"], "Review the question", "human", "review")
        with self.assertRaises(ValueError):
            self.store.implement(item["knowledge_id"], destination="DATASET_QUEUE", dry_run=False)
        self.assertEqual(self.store._read()["packets"], {})

    def test_strength_evidence_not_lesson(self):
        item = self.store.extract(self.report("GOOD", None, "CONFIRMED_STRENGTH"))[0]
        self.assertEqual(item["type"], "EVIDENCE")

    def test_only_verified_implemented(self):
        key = self.propose()
        with self.assertRaises(ValueError):
            self.store.implement(key)
        self.store.close(key, "REJECTED", "not accepted")
        with self.assertRaises(ValueError):
            self.store.implement(key, dry_run=False)
        with self.assertRaises(ValueError):
            self.store.verify(key, "text", "human", "reason")
        with self.assertRaises(ValueError):
            self.store.revise(key, "attempt")

    def test_dry_run_no_changes_and_real_implementation(self):
        key = self.verified()
        before = self.store.path.read_bytes()
        preview = self.store.implement(key, destination="GOLD_QUEUE")
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(preview["packet"]["destination"], "GOLD_QUEUE")
        self.assertEqual(preview["packet"]["provenance"]["source"], "MANUAL")
        self.store.implement(key, destination="GOLD_QUEUE", dry_run=False)
        self.assertEqual(self.store.show(key)["status"], "IMPLEMENTED")

    def test_idempotence(self):
        key = self.verified()
        first = self.store.implement(key, dry_run=False)
        second = self.store.implement(key, dry_run=False)
        self.assertEqual(second["action"], "NO_OP")
        self.assertEqual(first["packet"], second["packet"])
        self.assertEqual(len(self.store._read()["packets"]), 1)

    def test_provenance_and_no_invented_correction(self):
        item = self.store.extract(self.report())[0]
        key = item["knowledge_id"]
        self.store.verify(key, "Only this content", "human", "reviewed")
        with self.assertRaises(TypeError):
            self.store.implement(key, verified_correction="invented")
        packet = self.store.implement(key, dry_run=False)["packet"]
        self.assertEqual(packet["verified_correction"], "Only this content")
        self.assertEqual(packet["provenance"]["provenance"], item["provenance"])
        self.assertEqual(packet["provenance"]["verified_by"], "human")
        self.assertEqual(packet["source_run"], "test-run")

    def test_retest_link_new_probe_result_and_no_repeat(self):
        key = self.verified()
        self.store.implement(key, dry_run=False)
        pool = [{"probe_id": "old-id", "prompt": "different", "category": "skill"},
                {"probe_id": "duplicate", "prompt": "old", "category": "skill"},
                {"probe_id": "new-id", "prompt": "new", "category": "skill"}]
        before = self.store.path.read_bytes()
        self.store.retest(key, pool)
        self.assertEqual(before, self.store.path.read_bytes())
        request = self.store.retest(key, pool, dry_run=False)
        self.assertEqual(request["knowledge_id"], key)
        self.assertEqual(request["probe"]["probe_id"], "new-id")
        args = dict(result="RETEST_BAD", source_run="new-run", probe_id="new-id", model_output="wrong", evaluator="fixture")
        result = self.store.record_retest(request["request_id"], **args)
        self.assertEqual(result["result"], "RETEST_BAD")
        self.assertEqual(self.store.show(key)["status"], "RETESTED")
        self.assertEqual(self.store.history(key)[-1]["result"]["result"], "RETEST_BAD")
        with self.assertRaises(ValueError):
            self.store.record_retest(request["request_id"], **args)

    def test_retest_without_new_probe_does_not_claim_completion(self):
        key = self.verified()
        self.store.implement(key, dry_run=False)
        request = self.store.retest(key, [], dry_run=False)
        self.assertTrue(request["needs_new_probe"])
        with self.assertRaises(ValueError):
            self.store.record_retest(request["request_id"], result="RETEST_GOOD", source_run="run", probe_id="any", model_output="x", evaluator="e")
        updated = self.store.retest(key, [{"probe_id": "new", "prompt": "new", "category": "skill"}], dry_run=False)
        self.assertEqual(updated["request_id"], request["request_id"])
        self.assertFalse(updated["needs_new_probe"])
        self.assertEqual(self.store._read()["retests"][request["request_id"]]["probe"]["probe_id"], "new")

    def test_new_version_requires_new_verification(self):
        key = self.verified()
        first = self.store.implement(key, dry_run=False)["packet"]
        self.store.revise(key, "new review")
        with self.assertRaises(ValueError):
            self.store.implement(key, dry_run=False)
        self.store.verify(key, "New approved content", "human", "reviewed again")
        second = self.store.implement(key, dry_run=False)["packet"]
        self.assertNotEqual(first["packet_id"], second["packet_id"])
        self.assertEqual(second["version"], 2)
        self.assertEqual(len(self.store._read()["packets"]), 2)

    def test_retired_packets_are_inactive(self):
        key = self.verified()
        self.store.implement(key, dry_run=False)
        self.store.close(key, "RETIRED", "obsolete")
        self.assertEqual(next(iter(self.store._read()["packets"].values()))["packet_status"], "RETIRED")
        with self.assertRaises(ValueError):
            self.store.implement(key, dry_run=False)

    def test_approval_metadata_required(self):
        key = self.propose()
        for content, actor, reason in [("", "human", "reason"), ("content", "", "reason"), ("content", "human", "")]:
            with self.assertRaises(ValueError):
                self.store.verify(key, content, actor, reason)
        with self.assertRaises(ValueError):
            self.store.verify(key, "content", "human", "reason", approved_source="MODEL_GUESS")

    def test_unknown_destination_rejected(self):
        with self.assertRaises(ValueError):
            self.store.implement(self.verified(), destination="MAIN_DATASET")

    def test_lock_fails_closed(self):
        key = self.verified()
        self.store.path.with_suffix(".json.lock").touch()
        with self.assertRaises(FileExistsError):
            self.store.implement(key, dry_run=False)
        self.assertEqual(self.store.show(key)["status"], "VERIFIED")

    def test_failed_save_does_not_leave_half_implementation(self):
        key = self.verified()
        before = self.store.path.read_bytes()
        with patch("botforeman.knowledge.store.save_json", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.implement(key, dry_run=False)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertFalse(self.store.path.with_suffix(".json.lock").exists())

    def test_revision_cancels_pending_old_retest(self):
        key = self.verified()
        self.store.implement(key, dry_run=False)
        request = self.store.retest(key, [{"probe_id": "new", "prompt": "new", "category": "skill"}], dry_run=False)
        self.store.revise(key, "updated content")
        self.assertEqual(self.store._read()["retests"][request["request_id"]]["status"], "RETIRED")
        with self.assertRaises(ValueError):
            self.store.record_retest(request["request_id"], result="RETEST_GOOD", source_run="run", probe_id="new", model_output="x", evaluator="e")


if __name__ == "__main__":
    unittest.main()
