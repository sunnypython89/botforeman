"""Explicit synthetic imported teacher comparison; no real Copycat failure claimed."""

import argparse
import json
from pathlib import Path

from .runner import run
from .offline import ImportedComparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="experiments/teacher_delta_synthetic")
    args = parser.parse_args()
    root = Path(args.output)
    if root.exists():
        raise FileExistsError(root)
    prompt = "Ce înseamnă în context expresia «nu te mai satură Dumnezeu»?"
    output = "Înseamnă că Dumnezeu nu se poate odihni."
    criterion = "Interpretarea idiomatică în contextul exemplului sintetic furnizat."
    report = {"manifest": {"run_id": "SYNTHETIC", "context": {"model": "SYNTHETIC_COPYCAT",
               "adapter": "none", "evaluator_versions": ["synthetic-v1"], "probe_pool_version": "synthetic-v1"}},
              "usage": {"total_tokens": 0}, "records": [{"probe_id": "synthetic-idiom", "input": prompt,
              "model_output": output, "category": "IDIOM", "evaluator_result": "BAD", "evaluator_criterion": criterion}]}
    teacher = ImportedComparison({"teacher_identity": "SYNTHETIC_REFERENCE", "teacher_model": "fixture",
        "teacher_version": "1", "cases": [{"probe_id": "synthetic-idiom", "prompt": prompt,
        "copycat_output": output, "criterion": criterion,
        "teacher_output": {"ESSENTIAL_MEANING": ["reproș față de dorință/lăcomie excesivă"],
                           "NATIVE_SIGNAL": ["expresie idiomatică, nu literală"],
                           "CRITICAL_ERROR_IF_ANY": ["interpretare literală"]},
        "delta": {"KNOWN_BY_BOTH": [], "MISSING_IN_COPYCAT": ["sens idiomatic de reproș"],
                  "WRONG_IN_COPYCAT": ["interpretare literală"], "EXTRA_IN_COPYCAT": [], "UNCERTAIN_DELTA": [],
                  "learning_value": "HIGH", "reason": "IDIOM"}}]})
    first = run(report, teacher, teacher, root / "first", cache_directory=root / "cache", knowledge_path=root / "knowledge.json")
    second = run(report, teacher, teacher, root / "cached", cache_directory=root / "cache", knowledge_path=root / "knowledge.json")
    print(json.dumps({"synthetic": True, "first": first["cost_report"], "cached": second["cost_report"],
                      "knowledge_id": first["records"][0]["knowledge_id"], "status": "PROPOSED"}, indent=2))


if __name__ == "__main__":
    main()
