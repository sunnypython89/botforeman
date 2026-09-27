from copy import deepcopy
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from botforeman.teacher_delta.runner import Config, TeacherReply, run, validate_content
from botforeman.levels.protocol import Usage
from botforeman.knowledge import KnowledgeStore


def fixture_report():
    return {"manifest": {"run_id": "SYNTHETIC", "context": {"model": "fixture-copycat", "adapter": "v1",
            "evaluator_versions": ["fixture-v1"], "probe_pool_version": "v1"}},
            "usage": {"total_tokens": 5}, "records": [{"probe_id": "fixture", "input": "synthetic prompt",
            "model_output": "synthetic wrong", "category": "fixture", "evaluator_result": "BAD",
            "evaluator_criterion": "synthetic criterion", "explanation": "fixture failure", "history": "EXCLUDE THIS"}]}


class Fixture:
    paid = False
    name = model = "SYNTHETIC_TEACHER"
    version = "1"

    def __init__(self):
        self.calls = 0
        self.requests = []
        self.cost = "0"
        self.output_tokens = 10
        self.delta = {"KNOWN_BY_BOTH": [], "MISSING_IN_COPYCAT": ["synthetic missing fact"],
                      "WRONG_IN_COPYCAT": [], "EXTRA_IN_COPYCAT": [], "UNCERTAIN_DELTA": [],
                      "learning_value": "HIGH", "reason": "FALSE_INFORMATION"}

    def estimate(self, request):
        return Usage(10, min(self.output_tokens, request["max_output_tokens"]), api_calls=0, cost_usd=self.cost)

    def generate(self, request):
        self.calls += 1
        self.requests.append(request)
        return TeacherReply({"ESSENTIAL_MEANING": ["synthetic essential fact"], "NATIVE_SIGNAL": [],
                             "CRITICAL_ERROR_IF_ANY": []}, Usage(10, self.output_tokens, api_calls=0, cost_usd=self.cost))

    def extract(self, request, content):
        return deepcopy(self.delta)


class TeacherTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / (".teacher-test-" + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.teacher = Fixture()
        self.report = fixture_report()
        self.n = 0

    def cleanup(self):
        path = self.root.resolve()
        if path.parent != Path(__file__).resolve().parent or not path.name.startswith(".teacher-test-"):
            raise ValueError("Unsafe cleanup")
        shutil.rmtree(path)

    def run_case(self, **kwargs):
        self.n += 1
        return run(self.report, self.teacher, self.teacher, self.root / str(self.n),
                   cache_directory=self.root / "cache", knowledge_path=self.root / "knowledge.json", **kwargs)

    def test_good_skips(self):
        self.report["records"][0]["evaluator_result"] = "GOOD"
        result = self.run_case()
        self.assertEqual(self.teacher.calls, 0)
        self.assertEqual(result["records"][0]["status"], "SKIP_TEACHER")

    def test_bad_uncertain_unstable_and_manual(self):
        for rating in ("BAD", "UNCERTAIN"):
            self.report["records"][0]["evaluator_result"] = rating
            self.assertEqual(self.run_case()["records"][0]["status"], "PROPOSED")
        row = self.report["records"][0]
        row["evaluator_result"] = "GOOD"
        row["skill_state"] = "UNSTABLE"
        self.assertEqual(self.run_case()["records"][0]["status"], "PROPOSED")
        del row["skill_state"]
        self.assertEqual(self.run_case(mode="TEACHER_DELTA_MANUAL", selected=["fixture"])["records"][0]["status"], "PROPOSED")

    def test_compact_schema(self):
        with self.assertRaises(ValueError):
            validate_content({"ESSENTIAL_MEANING": ["a", "b", "c", "d"], "NATIVE_SIGNAL": [], "CRITICAL_ERROR_IF_ANY": []})

    def test_empty_no_knowledge(self):
        self.teacher.delta.update(MISSING_IN_COPYCAT=[], KNOWN_BY_BOTH=["shared"], learning_value="LOW", reason="NONE")
        self.assertEqual(self.run_case()["records"][0]["status"], "DELTA_EMPTY")
        self.assertFalse((self.root / "knowledge.json").exists())

    def test_proposed_not_verified_and_short_context(self):
        result = self.run_case()
        item = KnowledgeStore(self.root / "knowledge.json").show(result["records"][0]["knowledge_id"])
        self.assertEqual(item["status"], "PROPOSED")
        self.assertIsNone(item["verified_content"])
        self.assertNotIn("history", self.teacher.requests[0])
        self.assertIn("teacher_output", item["provenance"])

    def test_cache_and_invalidation(self):
        self.run_case()
        self.assertEqual(self.run_case()["cost_report"]["cache_hits"], 1)
        self.assertEqual(self.teacher.calls, 1)
        self.report["manifest"]["context"]["adapter"] = "v2"
        self.run_case()
        self.assertEqual(self.teacher.calls, 2)
        self.teacher.version = "2"
        self.run_case()
        self.assertEqual(self.teacher.calls, 3)

    def test_cost_and_calls_limit(self):
        self.teacher.cost = "0.1"
        result = self.run_case()
        self.assertEqual(self.teacher.calls, 0)
        self.assertEqual(result["status"], "incomplete")
        self.teacher.cost = "0"
        self.assertEqual(self.run_case(config=Config(max_teacher_calls_per_run=0))["stop_reason"], "max_teacher_calls_per_run")

    def test_token_cap_and_overrun(self):
        result = self.run_case(config=Config(max_teacher_tokens=2))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(self.teacher.requests[0]["max_output_tokens"], 2)
        self.assertFalse((self.root / "knowledge.json").exists())

    def test_paid_blocked(self):
        self.teacher.paid = True
        with self.assertRaises(PermissionError):
            self.run_case()
        self.assertEqual(self.teacher.calls, 0)

    def test_uncertain_delta_not_claimed_empty(self):
        self.teacher.delta.update(MISSING_IN_COPYCAT=[], UNCERTAIN_DELTA=["needs review"], learning_value="LOW", reason="UNKNOWN")
        self.assertEqual(self.run_case()["records"][0]["status"], "UNCERTAIN_DELTA")

    def test_weak_probe_not_model_lesson(self):
        self.report["records"][0]["issue"] = "PROBE_QUALITY_ISSUE"
        result = self.run_case()
        item = KnowledgeStore(self.root / "knowledge.json").show(result["records"][0]["knowledge_id"])
        self.assertEqual(item["type"], "PROBE_REVIEW")

    def test_duplicate_explanations_rejected(self):
        self.teacher.delta["WRONG_IN_COPYCAT"] = self.teacher.delta["MISSING_IN_COPYCAT"]
        self.assertEqual(self.run_case()["status"], "incomplete")
