import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from botforeman.teacher_delta.manual import export_packets, import_responses, CATEGORIES
from botforeman.knowledge import KnowledgeStore


class ManualTeacherTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / (".manual-test-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.registry = self.root / "registry.json"
        self.store = self.root / "knowledge.json"
        self.report = {"manifest": {"model": "fixture", "adapter": "v1", "run_id": "run"}, "records": [
            {"probe_id": str(i), "category": c, "input": "Context and prompt " + str(i), "model_output": "output",
             "evaluator_result": "GOOD", "explanation": "local reason"} for i, c in enumerate(CATEGORIES * 2)]}
        self.n = 0

    def cleanup(self):
        path = self.root.resolve()
        if path.parent != Path(__file__).resolve().parent or not path.name.startswith(".manual-test-"):
            raise ValueError("Unsafe cleanup")
        shutil.rmtree(path)

    def export(self, **kw):
        self.n += 1
        return export_packets([self.report], self.root / str(self.n), self.registry,
                              teacher_identity="fixture-chat", teacher_version="1", **kw)

    def import_(self, replies):
        self.n += 1
        path = self.root / "replies.json"
        path.write_text(json.dumps(replies), encoding="utf-8")
        return import_responses(path, self.registry, self.store, self.root / f"import{self.n}.json",
                                teacher_identity="fixture-chat", teacher_version="1")

    def test_five_diverse_export_and_pending_dedup(self):
        packets = self.export()
        self.assertEqual(len(packets), 5)
        self.assertEqual({p["CATEGORY"] for p in packets}, set(CATEGORIES))
        text = (self.root / "1/teacher_packets.txt").read_text(encoding="utf-8")
        self.assertIn("TEACHER_PACKET", text)
        self.assertIn("COPYCAT_OUTPUT", text)
        second = self.export()
        self.assertFalse({p["PROBE_ID"] for p in packets} & {p["PROBE_ID"] for p in second})
        self.assertEqual(self.export(), [])
        self.assertEqual(len(self.export(override=True)), 5)

    def test_empty_and_successful_dedup(self):
        packet = self.export()[0]
        reply = {"PACKET_ID": packet["PACKET_ID"], "DELTA_EMPTY": True}
        result = self.import_(reply)
        self.assertEqual(result["DELTA_EMPTY"], 1)
        self.assertFalse(self.store.exists())
        again = self.import_(reply)
        self.assertEqual(again["teacher_responses_imported"], 0)
        self.assertNotIn(packet["PROBE_ID"], {p["PROBE_ID"] for p in self.export()})

    def test_delta_proposed_and_calibration(self):
        packet = self.export()[0]
        reply = {"PACKET_ID": packet["PACKET_ID"], "DELTA_EMPTY": False, "ESSENTIAL_MEANING": ["missing signal"],
                 "LEARNING_VALUE": "HIGH", "teacher_tokens": 15}
        result = self.import_(reply)
        self.assertEqual(result["LOCAL_EVALUATOR_MISSED_SIGNAL"], [packet["PACKET_ID"]])
        self.assertEqual(result["PROPOSED_created"], 1)
        self.assertEqual(result["API_calls"], 0)
        self.assertEqual(result["teacher_tokens"], 15)
        item = KnowledgeStore(self.store).list()[0]
        self.assertEqual(item["status"], "PROPOSED")
        self.assertIsNone(item["verified_content"])
        self.assertEqual(item["provenance"]["packet"]["RUN_ID"], "run")
        again = self.import_(reply)
        self.assertEqual(again["PROPOSED_created"], 0)
        self.assertEqual(len(KnowledgeStore(self.store).list()), 1)

    def test_unknown_and_mismatch_rejected_before_writes(self):
        packet = self.export()[0]
        for reply in ({"PACKET_ID": "unknown", "DELTA_EMPTY": True},
                      {"PACKET_ID": packet["PACKET_ID"], "DELTA_EMPTY": True, "RUN_ID": "wrong"},
                      {"PACKET_ID": packet["PACKET_ID"], "DELTA_EMPTY": "true"}):
            with self.assertRaises(ValueError):
                self.import_(reply)
        self.assertFalse(self.store.exists())

    def test_weak_and_context_excluded_unless_explicit(self):
        self.report["records"][0]["registry_state"] = "WEAK"
        self.report["records"][1]["context_sufficient"] = False
        packets = self.export()
        self.assertNotIn("0", {p["PROBE_ID"] for p in packets})
        self.assertNotIn("1", {p["PROBE_ID"] for p in packets})
        packets = self.export(explicit=["0"], override=True)
        self.assertIn("0", {p["PROBE_ID"] for p in packets})

    def test_conflicting_reply_and_teacher_version_rejected(self):
        packet = self.export()[0]
        self.import_({"PACKET_ID": packet["PACKET_ID"], "DELTA_EMPTY": True})
        with self.assertRaises(ValueError):
            self.import_({"PACKET_ID": packet["PACKET_ID"], "DELTA_EMPTY": False, "NATIVE_SIGNAL": ["signal"]})
        with self.assertRaises(ValueError):
            import_responses(self.root / "replies.json", self.registry, self.store, self.root / "other.json",
                             teacher_identity="fixture-chat", teacher_version="2")

    def test_no_rating_defaults_low_and_no_false_calibration(self):
        packet = self.export()[0]
        result = self.import_({"PACKET_ID": packet["PACKET_ID"], "DELTA_EMPTY": False, "NATIVE_SIGNAL": ["signal"]})
        self.assertEqual(result["LOW"], 1)
        self.assertEqual(result["LOCAL_EVALUATOR_MISSED_SIGNAL"], [])

    def test_batch_prevalidation_and_duplicate_text(self):
        self.report["records"][1]["input"] = self.report["records"][0]["input"]
        packets = self.export()
        self.assertEqual(len({p["PROMPT"] for p in packets}), len(packets))
        with self.assertRaises(ValueError):
            self.import_([{"PACKET_ID": packets[0]["PACKET_ID"], "DELTA_EMPTY": False, "NATIVE_SIGNAL": ["signal"]},
                          {"PACKET_ID": "unknown", "DELTA_EMPTY": True}])
        self.assertFalse(self.store.exists())


if __name__ == "__main__":
    unittest.main()
