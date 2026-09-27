import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from .. import BotForeman
from ..bots.nativ_roman_bot import NativRomanBot
from ..levels.protocol import Limits
from ..levels.providers import FixtureProvider
from .providers import LazyCopycat
from .state import Rules


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Low-cost SCOUT/AUDIT; no paid transport or training")
    parser.add_argument("mode", choices=("SCOUT", "AUDIT"))
    parser.add_argument("--workspace", type=Path, default=Path("experiments/adaptive_state"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scout", type=Path, help="SCOUT report.json required for AUDIT")
    parser.add_argument("--provider", choices=("fixture", "copycat"), default="fixture")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tokens", type=int, default=10000)
    parser.add_argument("--max-api-calls", type=int, default=0)
    parser.add_argument("--max-cost", default="0")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--rules", type=Path, help="Optional JSON Rules overrides")
    args = parser.parse_args()
    if args.mode == "AUDIT" and not args.scout:
        parser.error("AUDIT requires --scout")
    if args.provider == "copycat" and not args.adapter:
        parser.error("Local Copycat requires --adapter")
    limits = Limits(args.max_cost, args.max_tokens, args.max_api_calls)
    rules = Rules(**json.loads(args.rules.read_text(encoding="utf-8"))) if args.rules else Rules()
    directory = args.output or Path("experiments") / (args.mode.lower() + "_" + uuid4().hex)
    if directory.exists():
        parser.error("Output directory exists; use a new name")
    provider = FixtureProvider() if args.provider == "fixture" else LazyCopycat(args.adapter)
    model = "SYNTHETIC-FIXTURE" if args.provider == "fixture" else provider.model_name
    adapter = "none-synthetic" if args.provider == "fixture" else provider.identity
    scout = json.loads(args.scout.read_text(encoding="utf-8")) if args.scout else None
    foreman = BotForeman()
    foreman.attach(NativRomanBot())
    result = foreman.run_adaptive("nativ_roman.bot", provider, directory, workspace=args.workspace,
        model=model, adapter=adapter, mode=args.mode, scout=scout, seed=args.seed, limits=limits,
        rules=rules, cache_enabled=not args.no_cache)
    print(json.dumps({k: result[k] for k in ("status", "completed_probes", "counts", "suspect_categories", "summary", "usage", "stop_reason")}, ensure_ascii=False, indent=2))
    print("SAVED:", directory.resolve())


if __name__ == "__main__":
    main()
