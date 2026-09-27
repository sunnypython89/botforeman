"""Compare standalone runs; never reuse historical ID-based pass labels."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

from .workflow import benchmark_rows, digest, read_json, rows, write_json, write_rows


def load_run(path):
    meta = read_json(str(path) + ".meta.json")
    if meta["botforeman_attached"] is not False or meta["output_sha256"] != digest(path):
        raise ValueError("Run is not a verified standalone Copycat evaluation")
    data = rows(path)
    indexed = {(item["benchmark"], item["id"]): item for item in data}
    if len(indexed) != len(data) or len(data) != meta["completed_count"]:
        raise ValueError("Duplicate or incomplete run")
    return meta, indexed


def compare(before, after, output, judgments=None):
    before, after, output = Path(before), Path(after), Path(output)
    bm, old = load_run(before)
    am, new = load_run(after)
    if old.keys() != new.keys() or bm["generation"] != am["generation"] or bm["model"] != am["model"]:
        raise ValueError("Runs need identical cases, base model and generation settings")
    references = {(item["benchmark"], item["id"]): item.get("reference", "") for item in benchmark_rows()}
    scores, review = defaultdict(lambda: {"total": 0, "changed": 0, "exact_before": 0, "exact_after": 0}), []
    for key, left in old.items():
        right = new[key]
        if left["prompt"] != right["prompt"] or left["split"] != right["split"]:
            raise ValueError("Prompt/split mismatch")
        suite = key[0] if key[0] != "new_probes" else "new_" + left["split"]
        values = scores[suite]
        values["total"] += 1
        values["changed"] += left["output"] != right["output"]
        if key in references:
            values["exact_before"] += left["output"] == references[key]
            values["exact_after"] += right["output"] == references[key]
        review.append({"benchmark": key[0], "id": key[1], "split": left["split"],
                       "prompt": left["prompt"], "before": left["output"], "after": right["output"],
                       "before_sha256": digest(before), "after_sha256": digest(after),
                       "semantic_before": None, "semantic_after": None,
                       "route_before": None, "route_after": None,
                       "reviewer": None, "reviewed_at": None, "reason": ""})
    regressions, improvements, reviewed = [], [], 0
    if judgments:
        seen = set()
        for item in rows(judgments):
            key = (item["benchmark"], item["id"])
            if key in seen or key not in old:
                raise ValueError("Duplicate/unknown judgment")
            seen.add(key)
            if (item["before_sha256"] != digest(before) or item["after_sha256"] != digest(after)
                    or not item.get("reviewer") or not item.get("reviewed_at")):
                raise ValueError("Fresh human review tied to both runs is required")
            for field in ("semantic_before", "semantic_after", "route_before", "route_after"):
                if item.get(field) is not None and type(item[field]) is not bool:
                    raise ValueError("Judgments must be true, false or null (uncertain)")
            reviewed += 1
            for criterion in ("semantic", "route"):
                left, right = item.get(criterion + "_before"), item.get(criterion + "_after")
                label = {"benchmark": key[0], "id": key[1], "criterion": criterion}
                if left is True and right is False:
                    regressions.append(label)
                if left is False and right is True:
                    improvements.append(label)
    report = {"before_sha256": digest(before), "after_sha256": digest(after),
              "botforeman_attached": False, "suites": dict(scores), "reviewed": reviewed,
              "regressions": regressions, "improvements": improvements,
              "conclusion": "Manual acceptance required; exact match is only a diagnostic outside strict editing",
              "lesson_probe_warning": "Lesson probes are training-exposed and excluded from generalization claims"}
    write_json(output, report)
    write_rows(str(output) + ".review.jsonl", review)
    return report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("output")
    parser.add_argument("--judgments")
    args = vars(parser.parse_args())
    print(json.dumps(compare(**args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
