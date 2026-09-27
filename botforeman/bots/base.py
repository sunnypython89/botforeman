"""Extension point for trusted, side-effect-free local evaluators."""

from abc import ABC, abstractmethod
from typing import Mapping

from ..protocol import TestCase
from ..result import EvaluationResult, OmissionPlan


class ForemanBot(ABC):
    name: str

    @abstractmethod
    def generate_tests(self, context: Mapping | None = None) -> tuple[TestCase, ...]:
        """Return controlled prompts; never invoke the model or external actions."""

    @abstractmethod
    def evaluate(self, prompt: str, output: str) -> EvaluationResult:
        """Evaluate immutable text without rewriting it."""

    def omission_plan(self, prompt: str, output: str,
                      evaluation: EvaluationResult) -> OmissionPlan:
        """Override when a bot needs a separate distillation planning step."""
        return evaluation.plan
