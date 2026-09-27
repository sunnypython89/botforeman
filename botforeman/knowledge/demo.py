"""Synthetic lifecycle only; all content and retest results are fixtures."""

import argparse
import json
from pathlib import Path

from .store import KnowledgeStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="experiments/knowledge_synthetic_demo")
    args = parser.parse_args()
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=False)
    store = KnowledgeStore(directory / "store.json")
    item = store.propose(source="SYNTHETIC_FIXTURE", original_input="Return the fixture label.",
                         category="fixture", model_output="fixture-wrong", related_probe_id="fixture-1")
    key = item["knowledge_id"]
    store.verify(key, "fixture-correct", "SYNTHETIC_TEST_VERIFIER", "Fixture assertion only", approved_source="MANUAL")
    preview = store.implement(key, destination="DATASET_QUEUE")
    packet = store.implement(key, destination="DATASET_QUEUE", dry_run=False)
    request = store.retest(key, [{"probe_id": "fixture-2", "prompt": "Return another fixture label.",
                                  "category": "fixture"}], dry_run=False)
    result = store.record_retest(request["request_id"], result="RETEST_GOOD", source_run="SYNTHETIC_RUN",
                                 probe_id="fixture-2", model_output="fixture-correct", evaluator="SYNTHETIC_EVALUATOR")
    print(json.dumps({"synthetic": True, "knowledge_id": key, "dry_run_action": preview["action"],
                      "packet_id": packet["packet"]["packet_id"], "status": store.show(key)["status"],
                      "retest_result": result["result"], "api_calls": 0, "tokens": 0, "cost_usd": 0}, indent=2))


if __name__ == "__main__":
    main()
