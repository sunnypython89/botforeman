"""Five SYNTHETIC cycles demonstrating aggregation, never Copycat measurements."""

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from .. import BotForeman
from ..bots.nativ_roman_bot import NativRomanBot
from ..bots.romanian_levels_bot import RomanianLevelsBot
from .protocol import ModelReply, Usage
from .native_signals import native_signal_stability


class ScriptedNativeProvider:
    name = "SYNTHETIC-native-stability-demo-NOT-Copycat"
    identity = "synthetic-5-4-5-5-4-v1"
    paid = False

    def __init__(self):
        self.answers = {}
        bot = NativRomanBot()
        for cycle_index in range(5):
            for item in bot.native_probes(cycle_index):
                target = "BAD" if cycle_index in {1, 4} and item["category"] == "IDIOM" else "GOOD"
                self.answers[item["prompt"]] = next(k for k, rubric in item["rubric"].items() if rubric["result"] == target)

    def estimate(self, prompt):
        return Usage(total_tokens=1, api_calls=0, cost_usd="0")

    def generate(self, prompt):
        return ModelReply(self.answers.get(prompt, "A"), self.estimate(prompt))


def run_demo(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    provider = ScriptedNativeProvider()
    foreman = BotForeman()
    foreman.attach(RomanianLevelsBot())
    foreman.attach(NativRomanBot())
    reports = [foreman.run_level_cycle("romanian_levels.bot", provider, directory / f"cycle_{index + 1}",
                                      native_evaluator="nativ_roman.bot") for index in range(5)]
    report = {"source": provider.name, **native_signal_stability(reports)}
    with (directory / "stability.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    directory = args.output or Path("experiments") / ("native_demo_" + uuid4().hex)
    report = run_demo(directory)
    print(report["source"])
    for index, cycle in enumerate(report["cycles"], 1):
        print(f"Cycle {index} NATIV: GOOD={cycle['GOOD']} BAD={cycle['BAD']} UNCERTAIN={cycle['UNCERTAIN']}")
    print("native_signal_stability:", report["native_signal_stability"])
    print("Unique native probes:", report["unique_probes"])
    print("No certification. API calls: 0. Cost: 0 USD.")
    print("SAVED:", directory.resolve())


if __name__ == "__main__":
    main()
