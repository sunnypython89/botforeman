"""Sequential SCOUT and targeted AUDIT, sharing the existing usage contracts."""

from dataclasses import asdict
import json
import os
from pathlib import Path
from uuid import uuid4

from ..levels.protocol import Limits, ModelReply, RATINGS
from ..levels.runner import timestamp, sum_usage
from .evaluation import EvaluationCache, Meter, StopRun
from .state import Registry, Rules, fingerprint, save_json, select, text_hash


def audit_verdict(records, rules):
    reliable = [r for r in records if r["issue"] != "PROBE_QUALITY_ISSUE"]
    if len({r["probe_id"] for r in reliable}) < rules.audit_confirmation:
        return "NEEDS_MORE_EVIDENCE"
    values = {r["evaluator_result"] for r in reliable}
    if values == {"BAD"}:
        return "CONFIRMED_FAILURE"
    if values == {"GOOD"}:
        return "CONFIRMED_STRENGTH"
    if {"GOOD", "BAD"} <= values:
        return "UNSTABLE"
    return "NEEDS_MORE_EVIDENCE"


def run_adaptive(pool, chain, provider, directory, *, workspace, model, adapter,
                 probe_pool_version, mode="SCOUT", scout=None, seed=42,
                 limits=None, rules=None, cache_enabled=True):
    if mode not in {"SCOUT", "AUDIT"}:
        raise ValueError("Mode must be SCOUT or AUDIT")
    if getattr(provider, "paid", True) is not False:
        raise PermissionError("Paid model generation is disabled")
    if not all(isinstance(v, str) and v for v in (model, adapter, probe_pool_version)):
        raise ValueError("Explicit model, adapter and pool identities are required")
    if type(seed) is not int:
        raise ValueError("Seed must be an integer")
    limits, rules = limits or Limits(), rules or Rules()
    pool = list(pool)
    for item in pool:
        if any(not isinstance(item.get(k), str) or not item[k] for k in ("probe_id", "prompt", "category")):
            raise ValueError("Probe needs ID, prompt and category")
    context = {"model": model, "adapter": adapter, "evaluator_versions": chain.versions(),
               "probe_pool_version": probe_pool_version, "pool_sha256": fingerprint(pool),
               "provider_identity": getattr(provider, "identity", provider.name)}
    if mode == "AUDIT":
        if not scout or scout.get("manifest", {}).get("mode") != "SCOUT":
            raise ValueError("AUDIT requires a SCOUT report")
        if scout["manifest"]["context"] != context:
            raise ValueError("SCOUT model, adapter, pool or evaluator configuration changed")
    directory, workspace = Path(directory), Path(workspace)
    if directory.exists():
        raise FileExistsError(directory)
    workspace.mkdir(parents=True, exist_ok=True)
    lock = workspace / "adaptive.lock"
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        registry = Registry(workspace / "registry.json", context, rules)
        known_failures = {category for category, history in registry.current["skills"].items()
                          if any(entry["result"] == "BAD" for entry in history)}
        before_snapshot = json.loads(json.dumps(registry.current))
        state_before = fingerprint(before_snapshot)
        selected, suspects = select(pool, registry, mode, seed, scout)
        directory.mkdir(parents=True, exist_ok=False)
        save_json(directory / "registry_before.json", before_snapshot)
        if selected:
            registry.current["recent_resolved"] = []
        registry.save()
        manifest = {"run_id": str(uuid4()), "mode": mode, "model": model, "adapter": adapter,
                    "evaluator_versions": chain.versions(), "probe_pool_version": probe_pool_version,
                    "seed": seed, "timestamp": timestamp(), "max_tokens": limits.max_tokens_per_cycle,
                    "max_api_calls": limits.max_api_calls_per_cycle, "max_cost": limits.max_cost_per_cycle,
                    "cache_enabled": cache_enabled, "api_escalation_enabled": chain.allow_api,
                    "context": context, "rules": asdict(rules), "registry_before_sha256": state_before,
                    "scout_run_id": scout["manifest"]["run_id"] if scout else None,
                    "scout_report_sha256": fingerprint(scout) if scout else None,
                    "selected_probes": [{"probe_id": p["probe_id"], "text_hash": text_hash(p["prompt"]),
                                         "category": p["category"]} for p in selected]}
        save_json(directory / "manifest.json", manifest)
        # Snapshot the actual questions, not grading keys, for reproducibility.
        save_json(directory / "selected_probes.json", [{k: v for k, v in p.items() if k != "rubric"} for p in selected])

        def event(value):
            with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"timestamp": timestamp(), **value}, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

        cache = EvaluationCache(workspace / "cache", cache_enabled)
        meter = Meter(limits, event)
        records = []

        def report(finished=False):
            categories = sorted({p["category"] for p in pool})
            verdicts = {c: audit_verdict([r for r in records if r["category"] == c], rules) for c in suspects} if mode == "AUDIT" else {}
            summary = {"NEW_FAILURES": sorted({r["category"] for r in records if r["issue"] == "MODEL_FAILURE"} - known_failures) if mode == "SCOUT" else [],
                       "CONFIRMED_FAILURES": [c for c, v in verdicts.items() if v == "CONFIRMED_FAILURE"],
                       "CONFIRMED_STRENGTHS": [c for c, v in verdicts.items() if v == "CONFIRMED_STRENGTH"],
                       "UNSTABLE": sorted({c for c in categories if registry.skill_state(c) == "UNSTABLE"} | {c for c, v in verdicts.items() if v == "UNSTABLE"}),
                       "NEEDS_MORE_EVIDENCE": ([c for c, v in verdicts.items() if v == "NEEDS_MORE_EVIDENCE"] if mode == "AUDIT"
                                               else sorted({r["category"] for r in records if r["evaluator_result"] == "UNCERTAIN"})),
                       "STABLE_GOOD": [c for c in categories if registry.skill_state(c) == "STABLE_GOOD"],
                       "PROBE_QUALITY_ISSUES": sorted(identifier for identifier, row in registry.current["probes"].items()
                                                      if row["registry_state"] == "WEAK")}
            value = {"manifest": manifest, "status": "complete" if finished and not meter.stop_reason else "incomplete",
                     "stop_reason": meter.stop_reason, "planned_probes": len(selected), "completed_probes": len(records),
                     "counts": {rating: sum(r["evaluator_result"] == rating for r in records) for rating in RATINGS},
                     "suspect_categories": sorted({r["category"] for r in records if r["evaluator_result"] in {"BAD", "UNCERTAIN"}}),
                     "suspect_probes": [r["probe_id"] for r in records if r["evaluator_result"] in {"BAD", "UNCERTAIN"}],
                     "audit_verdicts": verdicts, "summary": summary,
                     "usage": sum_usage(meter.observed), "accounted_usage": sum_usage(meter.accounted),
                     "records": records, "skill_states": {c: registry.skill_state(c) for c in categories}}
            save_json(directory / "report.json", value)
            return value

        report()
        for item in selected:
            before = len(meter.observed)
            try:
                reply = meter.call("MODEL", provider.estimate(item["prompt"]), lambda: provider.generate(item["prompt"]))
                if not isinstance(reply, ModelReply):
                    raise TypeError("Provider must return ModelReply")
            except (Exception, KeyboardInterrupt) as error:
                meter.stop_reason = meter.stop_reason or "generation_error:" + type(error).__name__
                break
            event({"event": "model_output", "probe_id": item["probe_id"], "output": reply.text})
            judgment, trace, cache_only = chain.evaluate(item, reply.text, context, cache, meter,
                                                        manifest["run_id"] + ":" + item["probe_id"])
            observation = registry.observe(item, judgment.result, trace, reply.text, cache_only=cache_only)
            record = {"run_id": manifest["run_id"], "probe_id": item["probe_id"], "text_hash": text_hash(item["prompt"]),
                      "category": item["category"], "input": item["prompt"], "model_output": reply.text,
                      "evaluator_result": judgment.result, "explanation": judgment.explanation,
                      "evaluation_trace": trace, "cache_only": cache_only, "timestamp": timestamp(),
                      "usage": sum_usage(meter.observed[before:]), **observation}
            with (directory / "results.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            records.append(record)
            report()
            if meter.stop_reason:
                break
        return report(finished=True)
    finally:
        lock.unlink()
