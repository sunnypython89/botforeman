"""Offline packet export/import. Teacher assertions are never verified facts."""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from uuid import uuid4

from ..adaptive.state import fingerprint, save_json
from ..knowledge.store import KnowledgeStore, now, required
from ..levels.protocol import validate_rating
from .runner import TEACHER_FIELDS, validate_content

CATEGORIES = ("IDIOM", "PRAGMATICS", "REGISTER", "COLLOCATION_NATURALNESS", "IMPLICIT_MEANING")
TASK = ("Spune numai ce informație relevantă lipsește sau este greșită în răspunsul Copycat. "
        "Maxim 3 puncte. Nu rescrie răspunsul complet dacă nu este necesar. "
        "Dacă răspunsul Copycat este deja suficient, spune DELTA_EMPTY. "
        "În ESSENTIAL_MEANING și NATIVE_SIGNAL pune numai lipsuri relevante, nu informații deja cunoscute. "
        "În CRITICAL_ERROR_IF_ANY pune numai erori. Returnează JSON cu PACKET_ID, cele trei liste, "
        "DELTA_EMPTY boolean și, opțional, LEARNING_VALUE LOW/MEDIUM/HIGH (LOW pentru stil).")


@contextmanager
def registry(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"packets": {}, "responses": {}}
        yield data
        save_json(path, data)
    finally:
        lock.unlink()


def export_packets(reports, output, registry_path, *, teacher_identity, teacher_version, explicit=(), override=False):
    required(teacher_identity)
    required(teacher_version)
    explicit = set(explicit)
    candidates = []
    weak = set()
    for report in reports:
        weak.update(report.get("summary", {}).get("PROBE_QUALITY_ISSUES", []))
    for report in reversed(reports):
        manifest = report["manifest"]
        for row in report["records"]:
            validate_rating(row["evaluator_result"])
            if not row.get("input", "").strip() or not row.get("model_output", "").strip():
                continue
            if row["probe_id"] not in explicit and (row["probe_id"] in weak or row.get("registry_state") in {"WEAK", "RETIRED"}):
                continue
            # The self-contained original prompt is required; never reconstruct missing context.
            if row.get("context_sufficient") is False:
                continue
            key = fingerprint([row["probe_id"], manifest["model"], manifest["adapter"], row["model_output"], teacher_identity, teacher_version])
            candidates.append((key, row, manifest, fingerprint(report)))
    known = {row["probe_id"] for _, row, _, _ in candidates}
    if not explicit <= known:
        raise ValueError("Explicit probes unavailable or missing context")
    candidates.sort(key=lambda c: (c[1]["probe_id"] not in explicit,
                     CATEGORIES.index(c[1]["category"]) if c[1]["category"] in CATEGORIES else len(CATEGORIES)))
    directory = Path(output)
    batch_id = uuid4().hex
    with registry(registry_path) as state:
        selected, ids, texts, categories = [], set(), set(), set()
        for diverse in (True, False):
            for key, row, manifest, report_hash in candidates:
                if len(selected) == 5:
                    break
                if row["probe_id"] in ids or row["input"] in texts or (diverse and row["category"] in categories):
                    continue
                if not override and any(p["dedup_key"] == key for p in state["packets"].values()):
                    continue
                packet = {"PACKET_ID": uuid4().hex, "batch_id": batch_id, "RUN_ID": manifest["run_id"], "PROBE_ID": row["probe_id"],
                          "CATEGORY": row["category"], "PROMPT": row["input"], "COPYCAT_OUTPUT": row["model_output"],
                          "LOCAL_VERDICT": row["evaluator_result"], "LOCAL_REASON": row.get("explanation", ""), "TASK": TASK,
                          "teacher_identity": teacher_identity, "teacher_version": teacher_version,
                          "dedup_key": key, "created_at": now(),
                          "provenance": {"manifest": manifest, "record": row, "report_hash": report_hash}}
                selected.append(packet)
                ids.add(row["probe_id"])
                texts.add(row["input"])
                categories.add(row["category"])
        directory.mkdir(parents=True, exist_ok=False)
        save_json(directory / "teacher_packets.json", {"mode": "TEACHER_PACKET_MANUAL", "packets": selected})
        text = "\n\n---\n\n".join("TEACHER_PACKET\n\n" + "\n".join(f"{k}: {p[k]}" for k in
               ("PACKET_ID", "RUN_ID", "PROBE_ID", "CATEGORY", "PROMPT", "COPYCAT_OUTPUT", "LOCAL_VERDICT", "LOCAL_REASON", "TASK")) for p in selected)
        (directory / "teacher_packets.txt").write_text(text + "\n", encoding="utf-8")
        for packet in selected:
            state["packets"][packet["PACKET_ID"]] = packet
        save_json(directory / "report.json", {"total_packets": len(selected), "teacher_responses_imported": 0,
                  "API_calls": 0, "cost_usd": "0", "teacher_tokens": None})
    return selected


def import_responses(response_file, registry_path, knowledge_path, output, *, teacher_identity, teacher_version):
    required(teacher_identity)
    required(teacher_version)
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    path = Path(response_file).resolve()
    replies = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(replies, dict):
        replies = [replies]
    if not isinstance(replies, list):
        raise ValueError("Expected JSON object or list")
    with registry(registry_path) as state:
        checked, seen = [], set()
        # Validate the entire batch before changing knowledge or the response registry.
        for reply in replies:
            identifier = reply["PACKET_ID"]
            if identifier not in state["packets"] or identifier in seen:
                raise ValueError("Unknown or duplicate PACKET_ID")
            seen.add(identifier)
            packet = state["packets"][identifier]
            if (teacher_identity, teacher_version) != (packet["teacher_identity"], packet["teacher_version"]):
                raise ValueError("Teacher identity/version mismatch")
            for key in ("RUN_ID", "PROBE_ID"):
                if key in reply and reply[key] != packet[key]:
                    raise ValueError("Run/probe mismatch")
            if type(reply.get("DELTA_EMPTY")) is not bool:
                raise ValueError("DELTA_EMPTY must be boolean")
            content = {k: reply.get(k, []) for k in TEACHER_FIELDS}
            if reply["DELTA_EMPTY"]:
                if any(content.values()):
                    raise ValueError("DELTA_EMPTY contradicts supplied delta points")
            else:
                validate_content(content)
            value = reply.get("LEARNING_VALUE", "LOW")
            if value not in {"LOW", "MEDIUM", "HIGH"}:
                raise ValueError("Invalid learning value")
            tokens = reply.get("teacher_tokens")
            if tokens is not None and (type(tokens) is not int or tokens < 0):
                raise ValueError("Invalid manual token usage")
            previous = state["responses"].get(identifier)
            if previous and previous["response_hash"] != fingerprint(reply):
                raise ValueError("Conflicting response; export a new packet with override")
            checked.append((packet, reply, content, value, previous))
        results = []
        for packet, reply, content, value, previous in checked:
            if previous:
                results.append({**previous, "no_op": True})
                continue
            delta = {"KNOWN_BY_BOTH": [], "MISSING_IN_COPYCAT": list(dict.fromkeys(content["ESSENTIAL_MEANING"] + content["NATIVE_SIGNAL"])),
                     "WRONG_IN_COPYCAT": content["CRITICAL_ERROR_IF_ANY"], "EXTRA_IN_COPYCAT": [], "UNCERTAIN_DELTA": []}
            delta["MISSING_IN_COPYCAT"] = [s for s in delta["MISSING_IN_COPYCAT"] if s not in delta["WRONG_IN_COPYCAT"]]
            result = {"packet_id": packet["PACKET_ID"], "category": packet["CATEGORY"], "probe_id": packet["PROBE_ID"],
                      "local_verdict": packet["LOCAL_VERDICT"], "delta": delta, "learning_value": None if reply["DELTA_EMPTY"] else value,
                      "learning_value_source": "teacher_declared" if "LEARNING_VALUE" in reply else "conservative_default",
                      "status": "NO_MEANINGFUL_DELTA" if reply["DELTA_EMPTY"] else "PROPOSED",
                      "calibration_flag": None, "teacher_identity": teacher_identity, "teacher_version": teacher_version,
                      "teacher_tokens": reply.get("teacher_tokens"), "timestamp": now(), "response_hash": fingerprint(reply),
                      "response_file": str(path), "response": reply, "packet": packet, "API_calls": 0, "cost_usd": "0"}
            if not reply["DELTA_EMPTY"]:
                if packet["LOCAL_VERDICT"] == "GOOD" and value in {"MEDIUM", "HIGH"}:
                    result["calibration_flag"] = "LOCAL_EVALUATOR_MISSED_SIGNAL"
                weak = packet["provenance"]["record"].get("registry_state") in {"WEAK", "RETIRED"} or packet["provenance"]["record"].get("issue") == "PROBE_QUALITY_ISSUE"
                item = KnowledgeStore(knowledge_path).propose(source="MANUAL_TEACHER_UNVERIFIED", original_input=packet["PROMPT"],
                    model_output=packet["COPYCAT_OUTPUT"], category=packet["CATEGORY"], source_run_id=packet["RUN_ID"],
                    related_probe_id=packet["PROBE_ID"], type="PROBE_REVIEW" if weak else "CORRECTION", provenance=result,
                    knowledge_id=fingerprint(["manual-teacher", packet["PACKET_ID"], reply]))
                result["knowledge_id"] = item["knowledge_id"]
            state["responses"][packet["PACKET_ID"]] = result
            results.append(result)
        batches = {r["packet"]["batch_id"] for r in results}
        summary = {"total_packets": sum(p["batch_id"] in batches for p in state["packets"].values()), "teacher_responses_imported": sum(not r.get("no_op") for r in results),
                   "DELTA_EMPTY": sum(r["status"] == "NO_MEANINGFUL_DELTA" for r in results),
                   **{v: sum(r["learning_value"] == v for r in results) for v in ("LOW", "MEDIUM", "HIGH")},
                   "LOCAL_EVALUATOR_MISSED_SIGNAL": [r["packet_id"] for r in results if r["calibration_flag"]],
                   "PROPOSED_created": sum(r["status"] == "PROPOSED" and not r.get("no_op") for r in results),
                   "teacher_tokens": sum(r["teacher_tokens"] for r in results) if all(r["teacher_tokens"] is not None for r in results) else None,
                   "API_calls": 0, "cost_usd": "0", "results": results}
        output = Path(output)
        if output.exists():
            raise FileExistsError(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        save_json(output, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="TEACHER_PACKET_MANUAL: no API")
    parser.add_argument("--registry", default="experiments/teacher_manual/registry.json")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("reports", nargs="+")
    export.add_argument("--explicit", nargs="*", default=[])
    export.add_argument("--override", action="store_true")
    imp = sub.add_parser("import")
    imp.add_argument("responses")
    imp.add_argument("--store", default="experiments/teacher_manual/knowledge.json")
    for command in (export, imp):
        command.add_argument("--teacher", required=True)
        command.add_argument("--version", required=True)
        command.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "export":
        reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.reports]
        result = export_packets(reports, args.output, args.registry, teacher_identity=args.teacher,
                                teacher_version=args.version, explicit=args.explicit, override=args.override)
        print(json.dumps({"total_packets": len(result), "output": args.output, "API_calls": 0, "cost_usd": "0"}))
    else:
        result = import_responses(args.responses, args.registry, args.store, args.output,
                                  teacher_identity=args.teacher, teacher_version=args.version)
        print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
