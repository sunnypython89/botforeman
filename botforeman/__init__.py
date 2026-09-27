"""BotForeman v0.1: optional, data-only omission distillation."""

__version__ = "0.1.0"

from .foreman import BotForeman
from .result import EvaluationResult, OmissionPlan

__all__ = ["BotForeman", "EvaluationResult", "OmissionPlan"]
