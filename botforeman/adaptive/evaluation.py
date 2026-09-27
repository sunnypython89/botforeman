"""Stage cache, bounded consumption and UNCERTAIN-only escalation. No network code."""

from dataclasses import dataclass
import json
from pathlib import Path

from ..levels.protocol import Usage, amount, validate_rating
from ..levels.runner import accounting_usage, limit_reason, sum_usage, upper_bound_breached
from .state import fingerprint, save_json

ZERO = Usage(input_tokens=0, output_tokens=0, api_calls=0, cost_usd="0")


class StopRun(RuntimeError):
    pass


class Meter:
    def __init__(self, limits, event):
        self.limits, self.event = limits, event
        self.observed, self.accounted = [], []
        self.stop_reason = None

    def check(self, estimate):
        if not isinstance(estimate, Usage):
            raise TypeError("A conservative Usage estimate is required")
        reason = self.stop_reason or limit_reason(self.accounted + [estimate], self.limits)
        if reason:
            self.stop_reason = reason
            raise StopRun(reason)

    def call(self, label, estimate, function):
        self.check(estimate)
        self.event({"event": "reserved", "stage": label, "usage": estimate.to_dict()})
        self.accounted.append(estimate)
        self.observed.append(Usage())
        try:
            reply = function()
            if not isinstance(reply.usage, Usage):
                raise TypeError("Reply needs Usage")
        except (Exception, KeyboardInterrupt) as error:
            self.stop_reason = "call_error:" + type(error).__name__
            self.event({"event": self.stop_reason, "stage": label})
            raise StopRun(self.stop_reason) from error
        self.observed[-1] = reply.usage
        self.accounted[-1] = accounting_usage(reply.usage, estimate)
        self.stop_reason = limit_reason(self.accounted, self.limits)
        if upper_bound_breached(reply.usage, estimate):
            self.stop_reason = self.stop_reason or "provider_exceeded_upper_bound"
        self.event({"event": "consumed", "stage": label, "usage": reply.usage.to_dict()})
        return reply


@dataclass(frozen=True)
class Judgment:
    result: str
    explanation: str
    usage: Usage = ZERO

    def __post_init__(self):
        validate_rating(self.result)
        if not isinstance(self.explanation, str) or not isinstance(self.usage, Usage):
            raise TypeError("Judgment needs explanation and Usage")


class EvaluationCache:
    def __init__(self, directory, enabled=True):
        self.directory, self.enabled = Path(directory), enabled
        if enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    def key(self, context, probe, output, evaluator):
        return fingerprint({**context, "probe_id": probe["probe_id"], "prompt": probe["prompt"],
                            "criterion": probe.get("evaluator_criterion"), "model_output": output,
                            "evaluator": evaluator.name, "evaluator_version": evaluator.version,
                            "evaluator_model": getattr(evaluator, "model", None)})

    def get(self, key):
        path = self.directory / (key + ".json")
        if not self.enabled or not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["key"] != key:
            raise ValueError("Invalid cache identity")
        return Judgment(data["result"], data["explanation"], ZERO)

    def put(self, key, judgment):
        if self.enabled:
            save_json(self.directory / (key + ".json"), {"key": key, "result": judgment.result,
                       "explanation": judgment.explanation})


class EvaluationChain:
    def __init__(self, primary, secondary=None, api=None, *, allow_api=False, api_ledger=None):
        if primary.paid or (secondary is not None and secondary.paid):
            raise ValueError("Primary and secondary evaluators must be local")
        self.primary, self.secondary, self.api = primary, secondary, api
        self.allow_api, self.api_ledger = allow_api, api_ledger

    def versions(self):
        return [{"stage": stage, "name": evaluator.name, "version": evaluator.version,
                 "model": getattr(evaluator, "model", None)}
                for stage, evaluator in (("LOCAL_PRIMARY", self.primary), ("LOCAL_SECONDARY", self.secondary), ("API_EVALUATOR", self.api))
                if evaluator is not None]

    def evaluate(self, probe, output, context, cache, meter, request_id):
        trace, cache_only = [], True
        current = Judgment("UNCERTAIN", "No evaluator evidence")
        for stage, evaluator in (("LOCAL_PRIMARY", self.primary), ("LOCAL_SECONDARY", self.secondary), ("API_EVALUATOR", self.api)):
            if evaluator is None:
                continue
            if stage == "API_EVALUATOR":
                limits = meter.limits
                if (not self.allow_api or self.api_ledger is None
                        or limits.max_api_calls_per_cycle in (None, 0)
                        or limits.max_cost_per_cycle is None or amount(limits.max_cost_per_cycle) == 0):
                    trace.append({"stage": stage, "evaluator": evaluator.name, "version": evaluator.version, "blocked": True})
                    break
            key = cache.key(context, probe, output, evaluator)
            hit = cache.get(key)
            try:
                if hit:
                    current = hit
                else:
                    cache_only = False
                    estimate = evaluator.estimate(probe, output)
                    if stage == "API_EVALUATOR":
                        from ..cycle.budget import quote
                        policy = self.api_ledger.policy
                        priced = quote(policy)  # Missing or stale prices block before any callable API.
                        if getattr(evaluator, "model", None) != policy["model"]:
                            raise PermissionError("Evaluator model differs from approved pricing")
                        estimate = Usage(input_tokens=policy["max_input_tokens"], output_tokens=policy["max_output_tokens"],
                                         api_calls=1, cost_usd=priced["per_call_usd"])
                        meter.check(estimate)
                        self.api_ledger.reserve(request_id)
                    def evaluate_once():
                        result = evaluator.evaluate(probe, output)
                        if stage != "API_EVALUATOR":
                            return result
                        if not isinstance(result, Judgment) or result.usage.input_tokens is None or result.usage.output_tokens is None:
                            raise ValueError("Paid usage must include all billable input/output tokens")
                        pricing = policy["verified_pricing"]
                        cost = (amount(pricing["input_usd_per_million"]) * result.usage.input_tokens
                                + amount(pricing["output_usd_per_million"]) * result.usage.output_tokens) / 1000000
                        return Judgment(result.result, result.explanation, Usage(
                            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
                            total_tokens=result.usage.total_tokens, api_calls=1, cost_usd=str(cost), credits=result.usage.credits))
                    current = meter.call(stage, estimate, evaluate_once)
                    if not isinstance(current, Judgment):
                        raise TypeError("Evaluator must return Judgment")
                    if stage == "API_EVALUATOR":
                        self.api_ledger.settle(request_id, current.usage.input_tokens, current.usage.output_tokens)
                    if not meter.stop_reason:
                        cache.put(key, current)
                trace.append({"stage": stage, "evaluator": evaluator.name, "version": evaluator.version,
                              "result": current.result, "explanation": current.explanation, "cache_hit": hit is not None,
                              "usage": (ZERO if hit else current.usage).to_dict()})
            except (Exception, KeyboardInterrupt) as error:
                meter.stop_reason = meter.stop_reason or "evaluation_error:" + type(error).__name__
                current = Judgment("UNCERTAIN", "Evaluation stopped; no confident judgment")
                trace.append({"stage": stage, "evaluator": evaluator.name, "version": evaluator.version,
                              "result": "UNCERTAIN", "error": type(error).__name__, "cache_hit": False})
                break
            if current.result != "UNCERTAIN" or meter.stop_reason:
                break
        return current, trace, cache_only
