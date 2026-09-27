import argparse
import json
import sys

from . import workflow


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Offline, human-reviewed BotForeman cycle")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("directory")
    infer = sub.add_parser("infer")
    infer.add_argument("directory")
    infer.add_argument("output")
    infer.add_argument("--adapter")
    infer.add_argument("--regression", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("directory")
    review.add_argument("observations")
    gold = sub.add_parser("export-gold")
    gold.add_argument("directory")
    gold.add_argument("decisions")
    gold.add_argument("output")
    args = vars(parser.parse_args())
    command = args.pop("command").replace("-", "_")
    result = getattr(workflow, command)(**args)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
