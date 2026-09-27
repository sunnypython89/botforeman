"""Adapters for the existing native evaluator. No domain logic in orchestration."""

import re

from ..bots.native_pool import POOL, CATEGORIES
from .evaluation import Judgment, ZERO


def native_pool(bot):
    per_category = max(sum(p.category == c for p in POOL) for c in CATEGORIES)
    return [p for index in range(per_category) for p in bot.native_probes(index)]


class NativePrimary:
    paid = False

    def __init__(self, bot):
        self.bot = bot
        self.name, self.version = bot.name, bot.native_version

    def estimate(self, probe, output):
        return ZERO

    def evaluate(self, probe, output):
        result = self.bot.evaluate_native(probe["prompt"], output)
        return Judgment(result["result"], result["explanation"])


class NativeSecondary(NativePrimary):
    """Only recognizes one extra explicit answer wrapper, never guesses semantics."""
    def __init__(self, bot):
        super().__init__(bot)
        self.name = "nativ_roman.secondary"
        self.version = "1.0-explicit-option-wrapper"

    def evaluate(self, probe, output):
        match = re.fullmatch(r"\s*(?:Varianta|Aleg varianta|Răspunsul este)\s+([A-Z])[.!]?\s*", output)
        if not match:
            return Judgment("UNCERTAIN", "Secondary parser has no additional unambiguous evidence")
        result = self.bot.evaluate_native(probe["prompt"], match.group(1))
        return Judgment(result["result"], "Explicit option wrapper: " + result["explanation"])
