"""Deterministic integer sequences. Prompt: COUNT <start> <stop> <step>.

The stop is inclusive and must be reachable. Output is a JSON integer array.
No free-form language inference, code execution, or partial-number extraction.
"""

from collections import Counter
import json
import re

from .base import ForemanBot
from ..protocol import TestCase, validate_text
from ..result import EvaluationResult, OmissionPlan


class CountingBot(ForemanBot):
    name = "counting.bot"
    max_elements = 1000
    max_integer = 10**9

    def generate_tests(self, context=None):
        if context:
            raise ValueError("counting.bot v0.1 has no context options")
        return (
            TestCase("ascending", "COUNT 1 5 1"),
            TestCase("descending", "COUNT 5 1 -1"),
            TestCase("stride", "COUNT -2 4 2"),
            TestCase("singleton", "COUNT 0 0 1"),
        )

    def _expected(self, prompt):
        match = re.fullmatch(r"COUNT (-?[0-9]{1,10}) (-?[0-9]{1,10}) (-?[0-9]{1,10})", prompt.strip())
        if not match:
            return None
        start, stop, step = map(int, match.groups())
        if any(abs(n) > self.max_integer for n in (start, stop, step)):
            return None
        if step == 0 or (stop - start) * step < 0 or (stop - start) % step:
            return None
        size = (stop - start) // step + 1
        if size > self.max_elements:
            return None
        return [start + i * step for i in range(size)], step

    def _uncertain(self, reason):
        return EvaluationResult(self.name, "UNCERTAIN", None,
                                OmissionPlan(uncertain=(reason,)))

    def evaluate(self, prompt, output):
        validate_text(prompt)
        validate_text(output)
        specification = self._expected(prompt)
        if specification is None:
            return self._uncertain("unsupported_prompt")
        expected, step = specification
        try:
            actual = json.loads(output)
        except (ValueError, RecursionError):
            return self._uncertain("output_not_json_integer_array")
        if not isinstance(actual, list) or any(type(n) is not int for n in actual):
            return self._uncertain("output_not_json_integer_array")
        if len(actual) > self.max_elements or any(abs(n) > self.max_integer for n in actual):
            return self._uncertain("output_out_of_bounds")
        if actual == expected:
            return EvaluationResult(self.name, "PASS", 1.0,
                                    OmissionPlan(keep=("exact_sequence",)))

        counts = Counter(actual)
        expected_set = set(expected)
        missing = [n for n in expected if n not in counts]
        duplicates = sorted(n for n, count in counts.items() if count > 1)
        unexpected = sorted(set(actual) - expected_set)
        omit, notes = [], []
        for code, values in (("missing_element", missing), ("duplicate_element", duplicates),
                             ("unexpected_element", unexpected)):
            if values:
                omit.append(code)
                notes.append(f"{code}: {values}")
        # Reversal/inversion among valid elements, independently of missing items.
        positions = {n: i for i, n in enumerate(expected)}
        ranks = [positions[n] for n in actual if n in positions]
        if any(a > b for a, b in zip(ranks, ranks[1:])):
            omit.append("wrong_order")
        # One endpoint omitted/added, or the complete sequence shifted by one step.
        endpoint_error = actual in (
            expected[:-1], expected[1:],
            [expected[0] - step] + expected, expected + [expected[-1] + step],
        )
        shifted = actual in ([n - step for n in expected], [n + step for n in expected])
        if endpoint_error or shifted:
            omit.append("off_by_one")
        return EvaluationResult(self.name, "FAIL", 0.0,
                                OmissionPlan(omit=tuple(omit)), tuple(notes))
