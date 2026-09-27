"""One atomic JSON transaction contains entries, provenance, packets and queues."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from ..adaptive.state import fingerprint, save_json

DESTINATIONS = {"GOLD_QUEUE", "DATASET_QUEUE", "RETEST_QUEUE", "BENCHMARK_FIX_QUEUE",
                "DOCUMENTATION", "KNOWLEDGE_ONLY"}
SOURCES = {"EXPLICIT_CORRECTION", "APPROVED_GOLD", "VALIDATED_BENCHMARK_RULE",
           "CONFIRMED_AUDIT", "STABLE_ARCHITECTURE", "APPROVED_DOCUMENTATION", "MANUAL"}
TERMINAL = {"REJECTED", "RETIRED"}


def now():
    return datetime.now(timezone.utc).isoformat()


def required(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A nonempty explicit value is required")
    return value


class KnowledgeStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return {"schema_version": 1, "items": {}, "packets": {}, "retests": {}, "history": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        with lock.open("x", encoding="utf-8"):
            pass
        try:
            data = self._read()
            yield data
            save_json(self.path, data)
        finally:
            lock.unlink()

    def _event(self, data, item, action, **details):
        item["updated_at"] = now()
        data["history"].append({"knowledge_id": item["knowledge_id"], "action": action,
                                "timestamp": item["updated_at"], "snapshot": deepcopy(item), **details})

    def list(self, status=None):
        return [v for v in self._read()["items"].values() if status is None or v["status"] == status.upper()]

    def show(self, knowledge_id):
        return self._read()["items"][knowledge_id]

    def history(self, knowledge_id):
        return [e for e in self._read()["history"] if e["knowledge_id"] == knowledge_id]

    def propose(self, *, source, original_input, category, type="CORRECTION", destination="KNOWLEDGE_ONLY",
                model_output=None, source_run_id=None, related_probe_id=None, provenance=None, knowledge_id=None):
        if destination not in DESTINATIONS:
            raise ValueError("Unknown destination")
        required(source)
        item = {"knowledge_id": knowledge_id or str(uuid4()), "type": required(type), "source": source,
                "source_run_id": source_run_id, "related_probe_id": related_probe_id,
                "skill": required(category), "category": category, "original_input": original_input,
                "model_output": model_output, "verified_content": None, "verification_reason": None,
                "verified_by": None, "created_at": now(), "updated_at": now(), "status": "PROPOSED",
                "destination": destination, "version": 1, "provenance": deepcopy(provenance or {}),
                "approved_source": None}
        with self._transaction() as data:
            if item["knowledge_id"] in data["items"]:
                return deepcopy(data["items"][item["knowledge_id"]])
            data["items"][item["knowledge_id"]] = item
            self._event(data, item, "PROPOSED")
        return deepcopy(item)

    def extract(self, report_path):
        path = Path(report_path).resolve()
        report = json.loads(path.read_text(encoding="utf-8"))
        manifest = report["manifest"]
        if manifest["mode"] not in {"SCOUT", "AUDIT"}:
            raise ValueError("Expected SCOUT/AUDIT")
        result = []
        digest = fingerprint(report)
        for row in report["records"]:
            verdict = row["evaluator_result"]
            if verdict not in {"GOOD", "BAD", "UNCERTAIN"}:
                raise ValueError("Invalid verdict")
            if row.get("issue") == "PROBE_QUALITY_ISSUE":
                kind = "PROBE_REVIEW"
            elif verdict == "UNCERTAIN":
                kind = "ANALYSIS"
            elif (verdict == "BAD" and row.get("issue") == "MODEL_FAILURE"
                  and report.get("audit_verdicts", {}).get(row["category"]) == "CONFIRMED_FAILURE"):
                kind = "CORRECTION"
            elif (verdict == "GOOD" and report.get("audit_verdicts", {}).get(row["category"]) == "CONFIRMED_STRENGTH"):
                kind = "EVIDENCE"
            else:
                continue
            result.append(self.propose(source="SCOUT_AUDIT_REPORT", original_input=row["input"],
                category=row["category"], type=kind, model_output=row["model_output"],
                source_run_id=manifest["run_id"], related_probe_id=row["probe_id"],
                provenance={"report_path": str(path), "report_sha256": digest,
                            "manifest": manifest, "record": row,
                            "audit_verdict": report.get("audit_verdicts", {}).get(row["category"])},
                knowledge_id=fingerprint([digest, row["probe_id"], kind])))
        return result

    def verify(self, knowledge_id, verified_content, verified_by, reason, *, approved_source="EXPLICIT_CORRECTION"):
        for value in (verified_content, verified_by, reason):
            required(value)
        if approved_source not in SOURCES:
            raise ValueError("Source is not approved")
        with self._transaction() as data:
            item = data["items"][knowledge_id]
            if item["status"] != "PROPOSED":
                raise ValueError("Only PROPOSED can be verified")
            item.update(status="VERIFIED", verified_content=verified_content, verified_by=verified_by,
                        verification_reason=reason, approved_source=approved_source)
            self._event(data, item, "VERIFIED")
        return deepcopy(item)

    def revise(self, knowledge_id, reason):
        required(reason)
        with self._transaction() as data:
            item = data["items"][knowledge_id]
            if item["status"] in TERMINAL:
                raise ValueError("Terminal knowledge cannot be revised")
            for request in data["retests"].values():
                if request["knowledge_id"] == knowledge_id and request["status"] == "PENDING":
                    request["status"] = "RETIRED"
            item.update(version=item["version"] + 1, status="PROPOSED", verified_content=None,
                        verified_by=None, verification_reason=None, approved_source=None)
            self._event(data, item, "REVISED", reason=reason)
        return deepcopy(item)

    def close(self, knowledge_id, status, reason):
        if status not in TERMINAL:
            raise ValueError("Expected REJECTED or RETIRED")
        required(reason)
        with self._transaction() as data:
            item = data["items"][knowledge_id]
            if item["status"] in TERMINAL:
                raise ValueError("Terminal knowledge")
            item["status"] = status
            for packet in data["packets"].values():
                if packet["knowledge_id"] == knowledge_id:
                    packet["packet_status"] = status
            for request in data["retests"].values():
                if request["knowledge_id"] == knowledge_id:
                    request["status"] = status
            self._event(data, item, status, reason=reason)

    def _implementation(self, data, knowledge_id, destination):
        item = data["items"][knowledge_id]
        destination = destination or item["destination"]
        if destination not in DESTINATIONS:
            raise ValueError("Unknown destination")
        if item["status"] in TERMINAL or item["status"] == "PROPOSED":
            raise ValueError("Explicit verification required")
        key = fingerprint([knowledge_id, item["version"], destination, item["verified_content"]])
        if key in data["packets"]:
            return {"action": "NO_OP", "packet": deepcopy(data["packets"][key])}
        if item["status"] != "VERIFIED" or item["approved_source"] not in SOURCES:
            raise ValueError("Only VERIFIED knowledge can be implemented")
        if item["type"] in {"EVIDENCE", "ANALYSIS", "PROBE_REVIEW"} and destination in {"GOLD_QUEUE", "DATASET_QUEUE"}:
            raise ValueError("Evidence/uncertainty/probe issues are not model lessons")
        record = item["provenance"].get("record", {})
        packet = {"packet_id": key, "knowledge_id": knowledge_id, "version": item["version"],
                  "source_run": item["source_run_id"], "skill": item["skill"], "category": item["category"],
                  "probe_id": item["related_probe_id"], "input": item["original_input"],
                  "model_output": item["model_output"], "verdict": record.get("evaluator_result"),
                  "failure_reason": record.get("explanation"), "verified_correction": item["verified_content"],
                  "destination": destination, "packet_status": "IMPLEMENTED", "created_at": now(),
                  "implemented_at": None, "retested_at": None,
                  "content_hash": fingerprint(item["verified_content"]), "provenance": deepcopy(item)}
        return {"action": "ENQUEUE", "packet": packet}

    def implement(self, knowledge_id, *, destination=None, dry_run=True):
        if dry_run:
            return {"dry_run": True, **self._implementation(self._read(), knowledge_id, destination)}
        with self._transaction() as data:
            result = self._implementation(data, knowledge_id, destination)
            if result["action"] == "NO_OP":
                return result
            packet = result["packet"]
            packet["implemented_at"] = now()
            data["packets"][packet["packet_id"]] = packet
            item = data["items"][knowledge_id]
            item.update(status="IMPLEMENTED", destination=packet["destination"])
            self._event(data, item, "IMPLEMENTED", packet_id=packet["packet_id"])
        return result

    def retest(self, knowledge_id, pool, *, dry_run=True):
        def build(data):
            item = data["items"][knowledge_id]
            if item["status"] != "IMPLEMENTED":
                raise ValueError("Retest requires IMPLEMENTED")
            key = fingerprint([knowledge_id, item["version"], "RETEST"])
            if key in data["retests"] and data["retests"][key]["probe"] is not None:
                return deepcopy(data["retests"][key])
            candidates = [p for p in pool if p["category"] == item["category"]
                          and p["probe_id"] != item["related_probe_id"] and p["prompt"] != item["original_input"]]
            chosen = sorted(candidates, key=lambda p: p["probe_id"])[0] if candidates else None
            return {"request_id": key, "knowledge_id": knowledge_id, "version": item["version"],
                    "destination": "RETEST_QUEUE", "status": "PENDING", "created_at": now(),
                    "probe": deepcopy(chosen), "needs_new_probe": chosen is None,
                    "provenance": deepcopy(item)}
        if dry_run:
            return {"dry_run": True, **build(self._read())}
        with self._transaction() as data:
            request = build(data)
            previous = data["retests"].get(request["request_id"])
            if previous is None or (previous["probe"] is None and request["probe"] is not None):
                data["retests"][request["request_id"]] = request
                self._event(data, data["items"][knowledge_id], "RETEST_REQUESTED", request_id=request["request_id"])
        return request

    def record_retest(self, request_id, *, result, source_run, probe_id, model_output, evaluator):
        if result not in {"RETEST_GOOD", "RETEST_BAD", "RETEST_UNCERTAIN"}:
            raise ValueError("Invalid retest result")
        for value in (source_run, probe_id, evaluator):
            required(value)
        with self._transaction() as data:
            request = data["retests"][request_id]
            item = data["items"][request["knowledge_id"]]
            if item["status"] != "IMPLEMENTED" or request["version"] != item["version"] or request["status"] != "PENDING":
                raise ValueError("Stale or completed retest")
            if request["probe"] is None or request["probe"]["probe_id"] != probe_id:
                raise ValueError("Result must match requested new probe")
            request.update(status="RETESTED", result=result, source_run=source_run,
                           model_output=model_output, evaluator=evaluator, retested_at=now())
            item["status"] = "RETESTED"
            for packet in data["packets"].values():
                if packet["knowledge_id"] == item["knowledge_id"] and packet["version"] == item["version"]:
                    packet.update(packet_status="RETESTED", retested_at=request["retested_at"], retest=deepcopy(request))
            self._event(data, item, "RETESTED", result=deepcopy(request))
        return deepcopy(request)
