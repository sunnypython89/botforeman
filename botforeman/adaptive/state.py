"""Small explicit counters and deterministic selection, without linguistic rules."""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class Rules:
    scout_probes: int = 3
    audit_per_category: int = 2
    max_audit_probes: int = 6
    stable_good_distinct: int = 3
    alternations: int = 3
    history_window: int = 6
    weak_uncertain: int = 3
    weak_unresolved_evaluators: int = 2
    audit_confirmation: int = 2

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError("Thresholds must be positive integers")
        if self.scout_probes >= 25:
            raise ValueError("SCOUT must use fewer than 25 probes")
        if self.stable_good_distinct < 2 or self.audit_confirmation < 2:
            raise ValueError("Confirmation requires distinct probes, not one result")
        if self.history_window < max(self.stable_good_distinct, self.alternations + 1):
            raise ValueError("History window too short for the configured rules")


def learning_state(history, rules):
    history = history[-rules.history_window:]
    if not history:
        return "ACTIVE"
    clear = [row["result"] for row in history if row["result"] in {"GOOD", "BAD"}]
    if sum(a != b for a, b in zip(clear, clear[1:])) >= rules.alternations:
        return "UNSTABLE"
    if history[-1]["result"] != "GOOD":
        return "NEEDS_RETEST"
    streak = []
    for row in reversed(history):
        if row["result"] != "GOOD":
            break
        streak.append(row)
    if len({row["probe_id"] for row in streak}) >= rules.stable_good_distinct and len({row["text_hash"] for row in streak}) >= rules.stable_good_distinct:
        return "STABLE_GOOD"
    return "ACTIVE"


class Registry:
    def __init__(self, path, context, rules):
        self.path, self.rules = Path(path), rules
        self.context_id = fingerprint(context)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"contexts": {}}
        self.current = self.data["contexts"].setdefault(self.context_id, {
            "context": context, "skills": {}, "probes": {}, "evidence": [], "recent_resolved": []})

    def save(self):
        save_json(self.path, self.data)

    def probe(self, item):
        row = self.current["probes"].setdefault(item["probe_id"], {
            "text_hash": text_hash(item["prompt"]), "category": item["category"],
            "registry_state": "NORMAL", "history": [], "uncertain_count": 0})
        if row["text_hash"] != text_hash(item["prompt"]) or row["category"] != item["category"]:
            raise ValueError("Probe identity changed without changing the pool version")
        return row

    def set_probe_state(self, item, state):
        if state not in {"CORE", "NORMAL", "WEAK", "RETIRED"}:
            raise ValueError("Invalid probe registry state")
        self.probe(item)["registry_state"] = state
        self.save()

    def skill_state(self, category):
        return learning_state(self.current["skills"].get(category, []), self.rules)

    def observe(self, item, result, trace, model_output, *, cache_only=False):
        row = self.probe(item)
        evidence = fingerprint({"probe_id": item["probe_id"], "output": model_output,
                                "result": result, "trace": [{k: t.get(k) for k in ("evaluator", "version", "result")} for t in trace]})
        # Identical cached replays add no evidence. A changed model answer is a
        # new observation even if its evaluation was cached in an earlier run.
        fresh = evidence != row.get("last_evidence") and (not cache_only or row.get("last_evidence") is not None)
        if fresh:
            row["last_evidence"] = evidence
            self.current["evidence"].append(evidence)
            if result == "UNCERTAIN":
                row["uncertain_count"] += 1
            unresolved = {t["evaluator"] for t in trace if t.get("result") == "UNCERTAIN" and not t.get("error")}
            if (row["uncertain_count"] >= self.rules.weak_uncertain
                    or len(unresolved) >= self.rules.weak_unresolved_evaluators):
                if row["registry_state"] != "RETIRED":
                    row["registry_state"] = "WEAK"
        quality = row["registry_state"] in {"WEAK", "RETIRED"}
        if quality:
            for old in self.current["skills"].get(item["category"], []) + row["history"]:
                if old["probe_id"] == item["probe_id"]:
                    old["result"] = "UNCERTAIN"
        if fresh:
            entry = {"probe_id": item["probe_id"], "text_hash": row["text_hash"],
                     "result": "UNCERTAIN" if quality else result}
            row["history"].append(entry)
            self.current["skills"].setdefault(item["category"], []).append(entry)
        if result in {"GOOD", "BAD"}:
            self.current["recent_resolved"].append({"probe_id": item["probe_id"], "text_hash": row["text_hash"]})
            self.current["recent_resolved"] = self.current["recent_resolved"][-25:]
        self.save()
        return {"registry_state": row["registry_state"],
                "probe_state": learning_state(row["history"], self.rules),
                "skill_state": self.skill_state(item["category"]),
                "issue": "PROBE_QUALITY_ISSUE" if quality else ("MODEL_FAILURE" if result == "BAD" else None),
                "quality_flag": "WEAK_PROBE" if row["registry_state"] == "WEAK" else None,
                "fresh_evidence": fresh}


def select(pool, registry, mode, seed, scout=None):
    rules = registry.rules
    source = scout["records"] if scout else []
    suspects = sorted({r["category"] for r in source if r["evaluator_result"] in {"BAD", "UNCERTAIN"}})
    categories = suspects if mode == "AUDIT" else sorted({p["category"] for p in pool})
    priority = {"UNSTABLE": 0, "NEEDS_RETEST": 0, "ACTIVE": 1, "STABLE_GOOD": 2}
    categories.sort(key=lambda c: (priority[registry.skill_state(c)],
                                   len(registry.current["skills"].get(c, [])), fingerprint([seed, c])))
    excluded = source + registry.current["recent_resolved"]
    used_ids = {row["probe_id"] for row in excluded}
    used_texts = {row.get("text_hash") or text_hash(row["input"]) for row in excluded}
    selected = []
    for category in categories:
        candidates = [p for p in pool if p["category"] == category]
        candidates.sort(key=lambda p: (
            len(registry.probe(p)["history"]),
            registry.probe(p)["registry_state"] != "CORE", fingerprint([seed, p["probe_id"]])))
        needed = 1 if mode == "SCOUT" else rules.audit_per_category
        count = 0
        for item in candidates:
            identifier, digest = item["probe_id"], text_hash(item["prompt"])
            if identifier in used_ids or digest in used_texts or registry.probe(item)["registry_state"] in {"WEAK", "RETIRED"}:
                continue
            selected.append(item)
            used_ids.add(identifier)
            used_texts.add(digest)
            count += 1
            if count >= needed or len(selected) >= (rules.scout_probes if mode == "SCOUT" else rules.max_audit_probes):
                break
        if len(selected) >= (rules.scout_probes if mode == "SCOUT" else rules.max_audit_probes):
            break
    return selected, suspects
