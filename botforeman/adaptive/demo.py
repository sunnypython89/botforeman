"""Synthetic SCOUT -> AUDIT example. This is not a measurement of Copycat."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from .. import BotForeman
from ..bots.nativ_roman_bot import NativRomanBot
from ..levels.protocol import ModelReply, Usage


class ScriptedProvider:
    name = "SYNTHETIC-SCOUT-AUDIT-NOT-COPYCAT"
    identity = "synthetic-scout-audit-v1"
    paid = False

    def __init__(self, pool):
        self.pool = {p["prompt"]: p for p in pool}
        self.phase, self.calls, self.failure_category = "SCOUT", 0, None

    def estimate(self, prompt):
        return Usage(total_tokens=1, api_calls=0, cost_usd="0")

    def generate(self, prompt):
        self.calls += 1
        probe = self.pool[prompt]
        if self.phase == "SCOUT" and self.calls == 2:
            return ModelReply("Nu pot decide încă.", self.estimate(prompt))
        if self.phase == "SCOUT" and self.calls == 1:
            self.failure_category = probe["category"]
        result = "BAD" if probe["category"] == self.failure_category else "GOOD"
        letter = next(k for k, v in probe["rubric"].items() if v["result"] == result)
        return ModelReply(letter, self.estimate(prompt))


def run_demo(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    foreman = BotForeman()
    bot = NativRomanBot()
    foreman.attach(bot)
    provider = ScriptedProvider(bot.adaptive_pool())
    options = dict(workspace=directory / "state", model="SYNTHETIC", adapter="none")
    scout = foreman.run_adaptive(bot.name, provider, directory / "scout", **options)
    provider.phase = "AUDIT"
    audit = foreman.run_adaptive(bot.name, provider, directory / "audit", mode="AUDIT", scout=scout, **options)
    return {"source": provider.name, "scout": scout["counts"], "audit": audit["counts"],
            "summary": audit["summary"], "probes": scout["completed_probes"] + audit["completed_probes"],
            "synthetic_tokens": scout["usage"]["total_tokens"] + audit["usage"]["total_tokens"],
            "api_calls": 0, "cost_usd": "0"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_demo(args.output or Path("experiments") / ("adaptive_demo_" + uuid4().hex))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
