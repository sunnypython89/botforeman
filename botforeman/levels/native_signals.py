"""Persistent selection cursor and transparent cross-cycle consistency counts."""

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys

from ..bots.native_pool import CATEGORIES
from .protocol import RATINGS, validate_rating


def reserve_selection(path):
    """Reserve once even for interrupted cycles. Fail closed on malformed state/lock."""
    path = Path(path)
    lock = path.with_suffix(path.suffix + ".lock")
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"next_cycle_index": 0}
        index = state["next_cycle_index"]
        if type(index) is not int or index < 0:
            raise ValueError("Invalid native selection cursor")
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump({"next_cycle_index": index + 1}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return index
    finally:
        lock.unlink()


@dataclass(frozen=True)
class StabilityRules:
    window_cycles: int = 5
    min_cycles_detected: int = 2
    min_cycles_consistent: int = 5
    min_good_per_cycle: int = 4
    max_bad_per_cycle: int = 1

    def __post_init__(self):
        if any(type(v) is not int for v in asdict(self).values()):
            raise ValueError("Stability rules must be integers")
        if not 2 <= self.min_cycles_detected <= self.min_cycles_consistent <= self.window_cycles:
            raise ValueError("Consistency requires multiple cycles within the window")
        if not 1 <= self.min_good_per_cycle <= 5 or not 0 <= self.max_bad_per_cycle <= 5:
            raise ValueError("Cycle thresholds must refer to five native probes")


def native_signal_stability(reports, rules=None):
    rules = rules or StabilityRules()
    eligible, excluded, seen_cycles = [], [], set()
    for report in reports:
        cycle_id = report["cycle_id"]
        if cycle_id in seen_cycles:
            raise ValueError("Duplicate cycle_id must not inflate stability")
        seen_cycles.add(cycle_id)
        native = [row for row in report["records"] if row["level"] == "NATIV"]
        if report["status"] != "complete" or len(native) != 5 or not report.get("native_evaluation"):
            excluded.append({"cycle_id": cycle_id, "reason": "incomplete_or_legacy_cycle"})
            continue
        if [row.get("category") for row in native] != list(CATEGORIES):
            raise ValueError("NATIV requires exactly one probe per category in the declared order")
        if len({row["probe_id"] for row in native}) != 5:
            raise ValueError("Repeated native probe in cycle")
        for row in native:
            validate_rating(row["evaluator_result"])
            if row.get("result") != row["evaluator_result"] or row.get("evaluator_name") != "nativ_roman.bot":
                raise ValueError("Native evaluator identity/result mismatch")
        counts = {rating: sum(row["result"] == rating for row in native) for rating in RATINGS}
        eligible.append((report, native, counts))
    eligible.sort(key=lambda item: (item[0]["timestamp"], item[0]["cycle_id"]))
    window = eligible[-rules.window_cycles:]
    contexts = {json.dumps(item[0]["native_evaluation"]["comparison_context"], sort_keys=True) for item in window}
    if len(contexts) > 1:
        raise ValueError("Do not combine different models, providers, pools or evaluator versions")
    cycles, seen_probes = [], set()
    independent = True
    category_counts = {category: {rating: 0 for rating in RATINGS} for category in CATEGORIES}
    for report, native, counts in window:
        ids = {row["probe_id"] for row in native}
        if ids & seen_probes:
            independent = False
        seen_probes.update(ids)
        qualifies = counts["GOOD"] >= rules.min_good_per_cycle and counts["BAD"] <= rules.max_bad_per_cycle
        cycles.append({"cycle_id": report["cycle_id"], **counts, "supports_native_signal": qualifies})
        for row in native:
            category_counts[row["category"]][row["result"]] += 1
    supported = sum(cycle["supports_native_signal"] for cycle in cycles)
    status = "native_signal_inconclusive"
    if independent and len(cycles) >= rules.min_cycles_consistent and supported == len(cycles):
        status = "native_signal_consistent"
    elif independent and len(cycles) >= rules.min_cycles_detected and supported >= rules.min_cycles_detected:
        status = "native_signal_detected"
    return {"native_signal_stability": status, "rules": asdict(rules), "cycles": cycles,
            "cycles_considered": len(cycles), "supporting_cycles": supported,
            "category_counts": category_counts, "unique_probes": len(seen_probes),
            "distinct_probes_in_window": independent, "excluded_cycles": excluded,
            "comparison_context": window[0][0]["native_evaluation"]["comparison_context"] if window else None,
            "interpretation": "Consistency on these controlled contextual probes only; not a language certification."}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Aggregate comparable native cycles; never train or call an API")
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--rules", type=Path, help="Optional JSON with StabilityRules fields")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rules = StabilityRules(**json.loads(args.rules.read_text(encoding="utf-8"))) if args.rules else StabilityRules()
    report = native_signal_stability([json.loads(path.read_text(encoding="utf-8")) for path in args.reports], rules)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
