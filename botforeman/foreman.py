"""Domain-agnostic evaluation with explicit attachment and optional persisted cycles."""

from dataclasses import replace

from .bots.base import ForemanBot
from .protocol import validate_text
from .result import EvaluationResult, OmissionPlan


class BotForeman:
    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self._bots = {}

    def attach(self, bot: ForemanBot):
        if not isinstance(bot, ForemanBot):
            raise TypeError("Evaluator must implement ForemanBot")
        if not isinstance(bot.name, str) or not bot.name.strip():
            raise ValueError("Evaluator needs a name")
        if bot.name in self._bots:
            raise ValueError(f"Evaluator already attached: {bot.name}")
        self._bots[bot.name] = bot

    def detach(self, name):
        return self._bots.pop(name)

    def generate_tests(self, name, context=None):
        return self._bots[name].generate_tests(context)

    def run_level_cycle(self, name, provider, directory, *, limits=None, on_level=None,
                        native_evaluator=None):
        """Optional persisted 5x5 cycle; linguistic rules stay in the attached bot."""
        if not self.enabled:
            raise ValueError("BotForeman is disabled; no cycle started")
        from .levels.runner import run_cycle
        native_bot = self._bots[native_evaluator] if native_evaluator is not None else None
        return run_cycle(self._bots[name], provider, directory, limits=limits,
                         on_level=on_level, native_bot=native_bot)

    def evaluate(self, prompt: str, output: str) -> list[EvaluationResult]:
        if not self.enabled:
            return []
        validate_text(prompt)
        validate_text(output)
        results = []
        for name, bot in self._bots.items():
            try:
                result = bot.evaluate(prompt, output)
                if not isinstance(result, EvaluationResult) or result.bot != name:
                    raise ValueError("Invalid evaluator result or identity")
                plan = bot.omission_plan(prompt, output, result)
                results.append(replace(result, plan=plan))
            except Exception as error:
                # A failed evaluator must not become negative training evidence.
                results.append(EvaluationResult(
                    name, "UNCERTAIN", None,
                    OmissionPlan(uncertain=("evaluator_error",)),
                    (f"Evaluator failed: {type(error).__name__}",),
                ))
        return results

    def run_adaptive(self, name, provider, directory, *, workspace, model, adapter,
                     mode="SCOUT", scout=None, **options):
        """Optional small SCOUT/AUDIT runs; the attached bot owns the probe pool."""
        if not self.enabled:
            raise ValueError("BotForeman is disabled")
        from .adaptive.runner import run_adaptive
        from .adaptive.evaluation import EvaluationChain
        bot = self._bots[name]
        pool = bot.adaptive_pool()
        chain = EvaluationChain(*bot.adaptive_evaluators())
        identity = bot.adaptive_identity()
        return run_adaptive(pool, chain, provider, directory, workspace=workspace,
                            model=model, adapter=adapter, mode=mode, scout=scout,
                            probe_pool_version=identity["pool_version"], **options)
