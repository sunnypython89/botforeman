"""Generic, immutable evaluation and omission signals (never training actions)."""

from dataclasses import asdict, dataclass
import json
import math


@dataclass(frozen=True)
class OmissionPlan:
    keep: tuple[str, ...] = ()
    omit: tuple[str, ...] = ()
    uncertain: tuple[str, ...] = ()

    def __post_init__(self):
        for field in (self.keep, self.omit, self.uncertain):
            if not isinstance(field, tuple) or any(not isinstance(x, str) for x in field):
                raise TypeError("Signals must be tuples of strings")


@dataclass(frozen=True)
class EvaluationResult:
    bot: str
    status: str
    score: float | None
    plan: OmissionPlan = OmissionPlan()
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.bot, str) or not self.bot.strip():
            raise ValueError("bot must be a nonempty name")
        if self.status not in {"PASS", "FAIL", "UNCERTAIN"}:
            raise ValueError("Unknown evaluation status")
        if self.score is not None and (
            type(self.score) not in (int, float)
            or not math.isfinite(self.score) or not 0 <= self.score <= 1
        ):
            raise ValueError("score must be finite in [0, 1], or None")
        if not isinstance(self.plan, OmissionPlan):
            raise TypeError("plan must be an OmissionPlan")
        if not isinstance(self.notes, tuple) or any(not isinstance(x, str) for x in self.notes):
            raise TypeError("notes must be a tuple of strings")

    def to_dict(self):
        return {
            "bot": self.bot, "status": self.status,
            **{key: list(value) for key, value in asdict(self.plan).items()},
            "score": self.score, "notes": list(self.notes),
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)
