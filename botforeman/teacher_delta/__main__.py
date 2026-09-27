import argparse
import json
from pathlib import Path

from .runner import Config, run
from .offline import ImportedComparison, UnavailableTeacher, UncertainExtractor


def main():
    parser = argparse.ArgumentParser(description="Selective teacher comparisons; paid API disabled")
    parser.add_argument("report")
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache", default="experiments/teacher_delta/cache")
    parser.add_argument("--store", default="experiments/teacher_delta/knowledge.json")
    parser.add_argument("--bundle", help="Externally supplied compact teacher outputs and specialist deltas")
    parser.add_argument("--criteria", help="JSON probe_id -> criterion")
    parser.add_argument("--mode", choices=["TEACHER_DELTA_AUTO", "TEACHER_DELTA_MANUAL"], default="TEACHER_DELTA_AUTO")
    parser.add_argument("--select", nargs="*", default=[])
    parser.add_argument("--max-teacher-tokens", type=int, default=128)
    parser.add_argument("--max-teacher-calls-per-run", type=int, default=2)
    parser.add_argument("--max-teacher-cost", default="0")
    args = parser.parse_args()
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    teacher, extractor = UnavailableTeacher(), UncertainExtractor()
    if args.bundle:
        teacher = extractor = ImportedComparison(read(args.bundle))
    result = run(read(args.report), teacher, extractor, args.output, cache_directory=args.cache,
                 knowledge_path=args.store, criteria=read(args.criteria) if args.criteria else {},
                 mode=args.mode, selected=args.select,
                 config=Config(args.max_teacher_tokens, args.max_teacher_calls_per_run, args.max_teacher_cost))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
