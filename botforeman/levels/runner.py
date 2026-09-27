"""Sequential orchestration and durable cost-limited results. No domain rules."""

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import uuid4

from .protocol import (EXAMPLES_PER_LEVEL, LEVELS, RATINGS, SYMBOLS, Limits,
                       ModelReply, Probe, Usage, amount, validate_rating)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def validate_probes(probes):
    expected = [level for level in LEVELS for _ in range(EXAMPLES_PER_LEVEL)]
    if any(not isinstance(p, Probe) for p in probes) or [p.level for p in probes] != expected:
        raise ValueError("Cycle requires exactly five probes per level in the fixed order")
    if len({p.example_id for p in probes}) != len(probes):
        raise ValueError("Example IDs must be unique")
    for level in LEVELS:
        if len({" ".join(p.input.casefold().split()) for p in probes if p.level == level}) != EXAMPLES_PER_LEVEL:
            raise ValueError("The five inputs of a level must be distinct")


def sum_usage(usages):
    result = {}
    for key in Usage.__dataclass_fields__:
        values = [getattr(usage, key) for usage in usages]
        if any(value is None for value in values):
            result[key] = None
        elif key in {"cost_usd", "credits"}:
            result[key] = str(sum((amount(value) for value in values), Decimal(0)))
        else:
            result[key] = sum(values)
    return result


def limit_reason(usages, limits):
    """Enforce each known configured metric; require a usable fallback if cost is unknown."""
    totals = sum_usage(usages)
    for key, limit in (("total_tokens", limits.max_tokens_per_cycle),
                       ("api_calls", limits.max_api_calls_per_cycle)):
        if limit is not None and totals[key] is None:
            return "usage_unavailable:" + key
    pairs = (("cost_usd", limits.max_cost_per_cycle),
             ("total_tokens", limits.max_tokens_per_cycle),
             ("api_calls", limits.max_api_calls_per_cycle))
    usable = 0
    for key, limit in pairs:
        if limit is None or totals[key] is None:
            continue
        usable += 1
        if amount(totals[key]) > amount(limit):
            return f"limit_reached:{key}"
    if not usable:
        return "usage_unavailable:no_enforceable_limit"
    return None


def upper_bound_breached(actual, estimate):
    for key in ("total_tokens", "api_calls", "cost_usd"):
        observed, bound = getattr(actual, key), getattr(estimate, key)
        if observed is not None and bound is not None and amount(observed) > amount(bound):
            return True
    return False


def accounting_usage(actual, estimate):
    """Unknown observed usage remains unknown in reports, but consumes its reservation."""
    values = {key: getattr(actual, key) if getattr(actual, key) is not None else getattr(estimate, key)
              for key in ("total_tokens", "api_calls", "cost_usd", "credits")}
    # Provider total may include reasoning not exposed as output tokens.
    return Usage(**values)


def build_report(cycle_id, records, observed, accounted, limits, *, stop_reason=None, finished=False):
    summaries = []
    for level in LEVELS:
        selected = [row for row in records if row["level"] == level]
        summaries.append({"level": level, **{rating: sum(r["evaluator_result"] == rating for r in selected) for rating in RATINGS},
                          "completed": len(selected), "expected": EXAMPLES_PER_LEVEL})
    complete = finished and len(records) == len(LEVELS) * EXAMPLES_PER_LEVEL and stop_reason is None
    matrix = [f"{level:<12} " + " ".join(SYMBOLS[row["evaluator_result"]] for row in records if row["level"] == level)
              for level in LEVELS]
    return {"cycle_id": cycle_id, "status": "complete" if complete else "incomplete",
            "stop_reason": stop_reason, "completed_probes": len(records),
            "expected_probes": len(LEVELS) * EXAMPLES_PER_LEVEL, "levels": summaries,
            "totals": {rating: sum(row["evaluator_result"] == rating for row in records) for rating in RATINGS},
            "matrix": matrix, "usage": sum_usage(observed), "accounted_usage": sum_usage(accounted),
            "usage_note": "null means unavailable; accounted_usage includes conservative reservations",
            "limits": limits.to_dict(), "records": records, "timestamp": timestamp()}


def format_report(report, *, include_levels=True):
    lines = []
    for summary in report["levels"] if include_levels else ():
        lines.extend([summary["level"], *(f"{rating}: {summary[rating]}" for rating in RATINGS),
                      f"{summary['completed']}/{summary['expected']} probes", ""])
    lines.extend(report["matrix"])
    lines.extend(f"{rating} total: {report['totals'][rating]}" for rating in RATINGS)
    lines.append(f"{report['completed_probes']}/{report['expected_probes']} probes — {report['status']}")
    lines.append("USAGE: " + json.dumps(report["usage"], ensure_ascii=False))
    if report["stop_reason"]:
        lines.append("STOP: " + report["stop_reason"])
    return "\n".join(lines)


def run_cycle(bot, provider, directory, *, limits=None, on_level=None, native_bot=None):
    """provider.estimate(input) is an upper bound, not a typical-token guess.

    Only local/trusted providers are enabled. Paid transports remain blocked;
    enabling one later additionally requires the existing verified-price approval gate.
    The attached evaluator must be a side-effect-free local ForemanBot.
    """
    limits = limits or Limits()
    if not isinstance(limits, Limits):
        raise TypeError("Expected Limits")
    if getattr(provider, "paid", True) is not False:
        raise PermissionError("Paid providers are disabled; no approved paid transport is installed")
    if not isinstance(getattr(provider, "name", None), str) or not provider.name.strip():
        raise ValueError("Provider needs a nonempty name")
    if not callable(getattr(bot, "level_tests", None)) or not callable(getattr(bot, "evaluate_rating", None)):
        raise TypeError("Attached bot must implement level_tests and evaluate_rating")
    probes = tuple(bot.level_tests())
    validate_probes(probes)
    cycle_id = str(uuid4())
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    native_cases, native_evaluation = {}, None
    if native_bot is not None:
        from .native_signals import reserve_selection
        # The evaluator owns category/rubric details; the runner only routes NATIV.
        index = reserve_selection(directory.parent / "native_selection.json")
        selected = native_bot.native_probes(index)
        native_cases = {item["probe_id"]: item for item in selected}
        replacements = tuple(Probe("NATIV", item["probe_id"], item["prompt"]) for item in selected)
        probes = tuple(p for p in probes if p.level != "NATIV") + replacements
        validate_probes(probes)
        native_evaluation = {"selection_index": index,
            "comparison_context": {"provider": provider.name,
                "model_identity": getattr(provider, "identity", provider.name),
                **native_bot.native_identity()}}
    records, observed, accounted = [], [], []
    report = None

    def save(reason=None, finished=False):
        nonlocal report
        report = build_report(cycle_id, records, observed, accounted, limits,
                              stop_reason=reason, finished=finished)
        if native_evaluation is not None:
            report["native_evaluation"] = native_evaluation
        temporary = directory / "report.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "report.json")

    def event(value):
        with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"cycle_id": cycle_id, "timestamp": timestamp(), **value}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    save()
    for probe in probes:
        try:
            estimate = provider.estimate(probe.input)
            if not isinstance(estimate, Usage):
                raise TypeError("Provider must supply Usage as its upper bound")
        except Exception as error:
            save("estimate_error:" + type(error).__name__)
            return report
        reason = limit_reason(accounted + [estimate], limits)
        if reason:
            save(reason)
            return report
        event({"event": "reserved", "example_id": probe.example_id, "usage": estimate.to_dict()})
        accounted.append(estimate)
        observed.append(Usage())
        save("request_in_progress")
        try:
            reply = provider.generate(probe.input)
            if not isinstance(reply, ModelReply):
                raise TypeError("Provider must return ModelReply")
        except (Exception, KeyboardInterrupt) as error:
            event({"event": "provider_error", "example_id": probe.example_id, "error_type": type(error).__name__})
            save("provider_error:" + type(error).__name__)
            return report
        observed[-1] = reply.usage
        accounted[-1] = accounting_usage(reply.usage, estimate)
        event({"event": "model_returned", "example_id": probe.example_id,
               "model_output": reply.text, "usage": reply.usage.to_dict()})
        evaluation_error = None
        evaluator = native_bot if probe.example_id in native_cases else bot
        details = None
        try:
            if evaluator is native_bot:
                details = evaluator.evaluate_native(probe.input, reply.text)
                if not isinstance(details, dict) or not isinstance(details.get("explanation"), str):
                    raise TypeError("Native evaluation needs a result and internal explanation")
                rating = validate_rating(details["result"])
            else:
                rating = validate_rating(evaluator.evaluate_rating(probe.input, reply.text))
        except (Exception, KeyboardInterrupt) as error:
            rating = "UNCERTAIN"
            evaluation_error = type(error).__name__
            details = None
        record = {"cycle_id": cycle_id, "level": probe.level, "example_id": probe.example_id,
                  "input": probe.input, "model_output": reply.text, "evaluator_result": rating,
                  "evaluator_name": evaluator.name, "timestamp": timestamp(), "usage": reply.usage.to_dict(),
                  "provider_name": provider.name, "evaluation_error": evaluation_error}
        record["evaluator_version"] = getattr(evaluator, "version", None)
        if probe.example_id in native_cases:
            case = native_cases[probe.example_id]
            record.update({key: value for key, value in case.items() if key != "rubric"})
            record.update(result=rating, explanation=(details or {}).get("explanation", "Evaluator error; no confident judgment."),
                          evaluator_version=evaluator.native_version)
        with (directory / "probes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        records.append(record)
        reason = limit_reason(accounted, limits)
        if upper_bound_breached(reply.usage, estimate):
            reason = reason or "provider_exceeded_upper_bound"
        if evaluation_error:
            reason = reason or "evaluator_error:" + evaluation_error
        save(reason)
        if len(records) % EXAMPLES_PER_LEVEL == 0 and on_level is not None:
            try:
                on_level(next(s for s in report["levels"] if s["level"] == probe.level))
            except Exception as error:
                save("summary_callback_error:" + type(error).__name__)
                return report
        if reason:
            return report
    save(finished=True)
    return report
