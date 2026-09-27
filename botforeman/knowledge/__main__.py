"""Local, explicit knowledge lifecycle commands. No inference or network calls."""

import argparse
import json
from pathlib import Path

from .store import KnowledgeStore, DESTINATIONS, SOURCES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="experiments/knowledge/store.json")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("status", nargs="?")
    for name in ("show", "history"):
        commands.add_parser(name).add_argument("knowledge_id")
    commands.add_parser("extract").add_argument("report")
    proposal = commands.add_parser("propose")
    proposal.add_argument("json_file", help="JSON keyword arguments for propose")
    verify = commands.add_parser("verify")
    verify.add_argument("knowledge_id")
    verify.add_argument("--content-file", required=True)
    verify.add_argument("--by", required=True)
    verify.add_argument("--reason", required=True)
    verify.add_argument("--approved-source", choices=sorted(SOURCES), default="EXPLICIT_CORRECTION")
    for name in ("implement", "retest"):
        command = commands.add_parser(name)
        command.add_argument("knowledge_id")
        group = command.add_mutually_exclusive_group()
        group.add_argument("--apply", action="store_true", help="Write intermediate queue only")
        group.add_argument("--dry-run", action="store_true")
        if name == "implement":
            command.add_argument("--destination", choices=sorted(DESTINATIONS))
        else:
            command.add_argument("--pool", required=True, help="JSON list with probe_id, prompt, category")
    result = commands.add_parser("record-retest")
    result.add_argument("request_id")
    result.add_argument("json_file", help="result, source_run, probe_id, model_output, evaluator")
    revise = commands.add_parser("revise")
    revise.add_argument("knowledge_id")
    revise.add_argument("--reason", required=True)
    close = commands.add_parser("close")
    close.add_argument("knowledge_id")
    close.add_argument("status", choices=["REJECTED", "RETIRED"])
    close.add_argument("--reason", required=True)
    args = parser.parse_args()
    store = KnowledgeStore(args.store)
    read = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    if args.command == "list":
        output = store.list(args.status)
    elif args.command in {"show", "history"}:
        output = getattr(store, args.command)(args.knowledge_id)
    elif args.command == "extract":
        output = store.extract(args.report)
    elif args.command == "propose":
        output = store.propose(**read(args.json_file))
    elif args.command == "verify":
        output = store.verify(args.knowledge_id, Path(args.content_file).read_text(encoding="utf-8"),
                              args.by, args.reason, approved_source=args.approved_source)
    elif args.command == "implement":
        output = store.implement(args.knowledge_id, destination=args.destination, dry_run=not args.apply)
    elif args.command == "retest":
        output = store.retest(args.knowledge_id, read(args.pool), dry_run=not args.apply)
    elif args.command == "record-retest":
        output = store.record_retest(args.request_id, **read(args.json_file))
    elif args.command == "revise":
        output = store.revise(args.knowledge_id, args.reason)
    else:
        output = store.close(args.knowledge_id, args.status, args.reason)
    print(json.dumps(output, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
