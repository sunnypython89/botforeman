"""Conservative local triage, NOT a native-speaker oracle or Gold generator."""

import json
import re

from .base import ForemanBot
from ..protocol import TestCase, validate_text
from ..result import EvaluationResult, OmissionPlan


class NativRomanBot(ForemanBot):
    name = "nativ_roman.bot"
    version = "0.1-local-triage"
    criteria = ("meaning", "naturalness", "register", "unsolicited_changes", "uncertainty")

    def __init__(self, probes=()):
        self._probes = {item["prompt"]: dict(item) for item in probes}
        self._native_probes = {}

    native_version = "1.0-contextual-native-signals"

    def adaptive_pool(self):
        from ..adaptive.native import native_pool
        return native_pool(self)

    def adaptive_evaluators(self):
        from ..adaptive.native import NativePrimary, NativeSecondary
        return NativePrimary(self), NativeSecondary(self)

    def adaptive_identity(self):
        return self.native_identity()

    def native_identity(self):
        from .native_pool import pool_fingerprint, POOL_VERSION
        return {"evaluator": self.name, "evaluator_version": self.native_version,
                "pool_version": POOL_VERSION, "pool_sha256": pool_fingerprint()}

    def native_probes(self, cycle_index):
        """Pure deterministic selection; the orchestrator owns persistence."""
        from .native_pool import select_probes
        selected = select_probes(cycle_index)
        self._native_probes.update({p["prompt"]: p for p in selected})
        return selected

    def evaluate_native(self, prompt, output):
        """Controlled contextual grading; unrecognized free text stays uncertain."""
        validate_text(prompt)
        validate_text(output)
        probe = self._native_probes.get(prompt)
        if probe is None:
            return {"result": "UNCERTAIN", "explanation": "Probă nativă necunoscută; fără criteriu verificabil."}
        normalize = lambda text: " ".join(text.split()).rstrip(".!?")
        text = output.strip()
        options = probe["answer_options"]
        letter = re.fullmatch(r"([A-Z])[.!]?", text)
        selected = letter.group(1) if letter else None
        labelled = re.fullmatch(r"([A-Z])\s*[:.)-]\s*(.+)", text, re.DOTALL)
        if labelled:
            key, content = labelled.groups()
            if key in options and normalize(content) == normalize(options[key]):
                selected = key
        if selected is None:
            selected = next((key for key, content in options.items() if normalize(text) == normalize(content)), None)
        if selected not in options:
            return {"result": "UNCERTAIN", "explanation": "Alegere neclară, contradictorie sau text liber neacoperit de rubrică."}
        return dict(probe["rubric"][selected])

    def evaluate_rating(self, prompt, output):
        return self.evaluate_native(prompt, output)["result"]

    def generate_tests(self, context=None):
        if context:
            raise ValueError("Configure probes in the constructor")
        return tuple(TestCase(item["id"], prompt) for prompt, item in self._probes.items())

    def analyze(self, prompt, output):
        validate_text(prompt)
        validate_text(output)
        probe = self._probes.get(prompt, {})
        dimensions = {name: {"status": "UNCERTAIN", "reason": reason} for name, reason in zip(
            self.criteria, (
                "Lexical matches do not prove preservation of meaning.",
                "Natural Romanian requires a native speaker's contextual judgment.",
                "Register requires checking audience, politeness and context.",
                "Only explicit surface markers are inspected locally.",
                "A human must judge whether confidence matches the available evidence.",
            ))}
        spans = []
        missing_anchors = [anchor for anchor in probe.get("anchors", []) if anchor not in output]
        if missing_anchors:
            dimensions["meaning"]["reason"] = "Source anchors not found verbatim (inflection/paraphrase may be valid): " + repr(missing_anchors)
        for anchor in probe.get("anchors", []):
            for match in re.finditer(re.escape(anchor), output):
                spans.append({"signal": "KEEP", "criterion": "meaning", "start": match.start(),
                              "end": match.end(), "text": match.group(),
                              "reason": "Source anchor retained verbatim; lexical evidence only."})
        if probe.get("only_text"):
            match = re.match(r"\s*(?:Sigur[!,.:]?|Desigur[!,.:]?|Iată[^\n:]*:)\s*", output, re.I)
            if match:
                spans.append({"signal": "OMIT", "criterion": "unsolicited_changes",
                              "start": match.start(), "end": match.end(), "text": match.group(),
                              "reason": "Possible unsolicited preamble; confirm manually."})
                dimensions["unsolicited_changes"] = {
                    "status": "UNCERTAIN", "reason": "Possible unsolicited preamble detected."}
        if probe.get("category") == "register" and re.match(r"\s*(Dă-mi|Spune-mi)\b", output, re.I):
            match = re.match(r"\s*(Dă-mi|Spune-mi)\b", output, re.I)
            dimensions["register"]["reason"] = "Informal imperative detected in a requested formal-register task."
            spans.append({"signal": "OMIT", "criterion": "register", "start": match.start(),
                          "end": match.end(), "text": match.group(),
                          "reason": "Tentatively omit informal address; native review required."})
        if probe.get("category") == "uncertainty" and not re.search(
                r"poate|posibil|ambig|nu (?:se |putem |este )|mai multe", output, re.I):
            dimensions["uncertainty"]["reason"] = "No common uncertainty marker detected; may be unjustified certainty."
        if "condiți" in prompt.casefold() and not re.search(r"dacă|numai|doar|decât", output, re.I):
            dimensions["meaning"]["reason"] += " Conditional marker not detected; check logical equivalence."
        if "diacritice" in prompt.casefold() and re.search(r"\b(?:Sambata|Maine|lasam|asezam|langa|postala)\b", output, re.I):
            dimensions["naturalness"]["reason"] = "Possible missing Romanian diacritics; narrow lexical check only."
        spans.append({"signal": "UNCERTAIN", "criterion": "all", "start": 0,
                      "end": len(output), "text": output,
                      "reason": "Whole response needs human review; surface signals are not a verdict."})
        return {"evaluator_version": self.version, "mode": "local_heuristic",
                "dimensions": dimensions, "spans": spans, "missing_anchors": missing_anchors,
                "review_required": True, "confidence": None}

    def evaluate(self, prompt, output):
        details = self.analyze(prompt, output)
        signals = {key: tuple(span["text"] for span in details["spans"] if span["signal"] == key)
                   for key in ("KEEP", "OMIT", "UNCERTAIN")}
        return EvaluationResult(self.name, "UNCERTAIN", None,
                                OmissionPlan(signals["KEEP"], signals["OMIT"], signals["UNCERTAIN"]),
                                ("Heuristic suggestions only; never automatic Gold.",
                                 json.dumps(details["dimensions"], ensure_ascii=False)))
