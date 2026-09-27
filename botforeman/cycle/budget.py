"""Fail-closed accounting for a FUTURE paid transport; no network code here.

Prices and a concrete approval must be supplied after human-visible verification.
Reserve worst-case cost before a request. An unknown outcome stays fully charged.
No retry/resume operation exists. Amounts use decimal USD, never binary floats.
"""

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def money(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid monetary amount")
    return result


def fingerprint(policy):
    document = {key: value for key, value in policy.items() if key not in {"approval", "enabled"}}
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()


def quote(policy):
    pricing = policy.get("verified_pricing")
    if not pricing or not policy.get("model"):
        raise ValueError("No verified model pricing; paid requests blocked")
    if pricing.get("model") != policy["model"] or not pricing.get("source_url", "").startswith("https://"):
        raise ValueError("Pricing must identify the model and official source")
    checked = datetime.fromisoformat(pricing["verified_at"])
    age = datetime.now(timezone.utc) - checked
    if age < timedelta(0) or age > timedelta(hours=24):
        raise ValueError("Pricing verification expired; verify again before running")
    for name in ("max_calls", "max_input_tokens", "max_output_tokens"):
        if type(policy[name]) is not int or policy[name] <= 0:
            raise ValueError("Positive integer request/token limits required")
    input_rate = money(pricing["input_usd_per_million"])
    output_rate = money(pricing["output_usd_per_million"])
    per_call = (input_rate * policy["max_input_tokens"] + output_rate * policy["max_output_tokens"]) / 1_000_000
    return {"model": policy["model"], "max_calls": policy["max_calls"],
            "max_input_tokens_total": policy["max_calls"] * policy["max_input_tokens"],
            "max_output_tokens_total": policy["max_calls"] * policy["max_output_tokens"],
            "worst_case_usd": str(per_call * policy["max_calls"]),
            "per_call_usd": str(per_call), "budget_usd": str(money(policy["budget_usd"])),
            "policy_sha256": fingerprint(policy), "pricing": pricing}


class BudgetLedger:
    def __init__(self, policy, path):
        self.policy = policy
        self.path = Path(path)

    @contextmanager
    def _locked(self):
        lock = Path(str(self.path) + ".lock")
        # Exclusive creation prevents concurrent check-then-spend races.
        with lock.open("x", encoding="utf-8"):
            pass
        try:
            yield
        finally:
            lock.unlink()

    def _events(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def _append(self, event):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
            stream.flush()
            import os
            os.fsync(stream.fileno())

    def reserve(self, request_id):
        policy = self.policy
        if policy.get("enabled") is not True:
            raise PermissionError("Paid requests are disabled")
        estimate = quote(policy)
        approval = policy.get("approval") or {}
        if (approval.get("policy_sha256") != estimate["policy_sha256"]
                or not approval.get("approved_by") or not approval.get("approved_at")
                or money(approval.get("budget_usd", -1)) != money(policy["budget_usd"])):
            raise PermissionError("Explicit approval of this exact budget and policy is required")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("A unique request ID is required")
        with self._locked():
            events = self._events()
            reserved = [e for e in events if e["event"] == "reserved"]
            if any(e.get("event") == "usage_violation" for e in events):
                raise PermissionError("Provider usage exceeded limits; ledger blocked")
            if any(e["request_id"] == request_id for e in reserved):
                raise PermissionError("No automatic retries or duplicate request IDs")
            if any(e["policy_sha256"] != estimate["policy_sha256"] for e in reserved):
                raise PermissionError("Policy changed; a separately approved run is required")
            settlements = {e["request_id"]: money(e["cost_usd"]) for e in events if e["event"] == "settled"}
            spent = sum((settlements.get(e["request_id"], money(e["reserved_usd"])) for e in reserved), Decimal(0))
            if len(reserved) >= policy["max_calls"] or spent + money(estimate["per_call_usd"]) > money(policy["budget_usd"]):
                raise PermissionError("Call or cost ceiling reached")
            self._append({"event": "reserved", "request_id": request_id,
                          "reserved_usd": estimate["per_call_usd"],
                          "policy_sha256": estimate["policy_sha256"],
                          "at": datetime.now(timezone.utc).isoformat()})
        return estimate

    def settle(self, request_id, input_tokens, output_tokens):
        # output_tokens MUST include billable reasoning tokens; cached input is
        # conservatively charged at the full input rate. No tools/extra fees allowed.
        with self._locked():
            events = self._events()
            reserved = next((e for e in events if e["event"] == "reserved" and e["request_id"] == request_id), None)
            if not reserved or any(e["event"] in {"settled", "usage_violation"} and e["request_id"] == request_id for e in events):
                raise ValueError("Unknown or already settled request")
            if reserved["policy_sha256"] != fingerprint(self.policy):
                raise PermissionError("Policy changed during the request")
            if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
                raise ValueError("Invalid usage; reservation remains charged")
            pricing = self.policy["verified_pricing"]
            cost = (input_tokens * money(pricing["input_usd_per_million"])
                    + output_tokens * money(pricing["output_usd_per_million"])) / 1_000_000
            violation = input_tokens > self.policy["max_input_tokens"] or output_tokens > self.policy["max_output_tokens"]
            self._append({"event": "usage_violation" if violation else "settled", "request_id": request_id,
                          "input_tokens": input_tokens, "output_tokens": output_tokens,
                          "cost_usd": str(cost), "at": datetime.now(timezone.utc).isoformat()})
            if violation:
                raise PermissionError("Usage exceeded the reserved limits; further requests blocked")
