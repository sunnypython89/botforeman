import argparse
from pathlib import Path
import sys
from uuid import uuid4

from .. import BotForeman
from ..bots.romanian_levels_bot import RomanianLevelsBot
from ..bots.nativ_roman_bot import NativRomanBot
from .protocol import Limits, RATINGS
from .providers import FixtureProvider, LocalCopycatProvider
from .runner import format_report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Fixed 5x5 Romanian evaluation; no paid API or training")
    parser.add_argument("--provider", choices=("fixture", "copycat"), default="fixture")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-cost", default="0", help="USD per cycle")
    parser.add_argument("--max-tokens", type=int, default=100000)
    parser.add_argument("--max-api-calls", type=int, default=0)
    args = parser.parse_args()
    limits = Limits(args.max_cost, args.max_tokens, args.max_api_calls)
    output = args.output or Path("experiments") / ("romanian_levels_" + uuid4().hex)
    if output.exists():
        parser.error("Output already exists; use a new directory")
    if args.provider == "copycat" and args.adapter is None:
        parser.error("--adapter is required for local Copycat")
    provider = FixtureProvider() if args.provider == "fixture" else LocalCopycatProvider(args.adapter)
    foreman = BotForeman()
    bot = RomanianLevelsBot()
    foreman.attach(bot)
    native_bot = NativRomanBot()
    foreman.attach(native_bot)

    def show_level(summary):
        print(summary["level"], flush=True)
        for rating in RATINGS:
            print(f"{rating}: {summary[rating]}", flush=True)

    print("PROVIDER:", provider.name, flush=True)
    report = foreman.run_level_cycle(bot.name, provider, output, limits=limits,
                                    on_level=show_level, native_evaluator=native_bot.name)
    print(format_report(report, include_levels=False))
    print("SAVED:", output.resolve())


if __name__ == "__main__":
    main()
