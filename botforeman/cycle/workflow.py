"""Artifacts, provenance and manual review gates. All writes are new files."""

import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
PROBES = Path(__file__).with_name("probes.jsonl")
BENCHMARKS = {
    "editare_36": "benchmark_copycat_03_on_04.py",
    "lectia_05": "benchmark_romana_05.jsonl",
    "lectia_06": "benchmark_ambiguitate_06.jsonl",
    "lectia_07": "benchmark_eliminare_07.jsonl",
    "lectia_08": "benchmark_prag_08.jsonl",
    "lectia_09": "benchmark_eliminare_secventiala_09.jsonl",
    "lectia_10": "benchmark_consolidare_10.jsonl",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_rows(path, values):
    with Path(path).open("x", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def benchmark_rows(root=ROOT):
    result = []
    for name, filename in BENCHMARKS.items():
        if filename.endswith(".py"):
            tree = ast.parse((root / filename).read_text(encoding="utf-8"))
            tests = next(ast.literal_eval(node.value) for node in tree.body
                         if isinstance(node, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == "TESTS" for t in node.targets))
            values = [{"id": identifier, "prompt": prompt, "reference": reference}
                      for identifier, prompt, reference in tests]
        else:
            values = rows(root / filename)
        result.extend({**item, "benchmark": name, "split": "regression"} for item in values)
    return result


def protected_prompts(root=ROOT):
    prompts = {normalized(item["prompt"]) for item in benchmark_rows(root)}
    for path in list(root.glob("gold*.jsonl")) + list(root.glob("replay*.jsonl")):
        for item in rows(path):
            if "prompt" in item:
                prompts.add(normalized(item["prompt"]))
            for message in item.get("messages", []):
                if message.get("role") == "user":
                    prompts.add(normalized(message["content"]))
    return prompts


def prepare(directory):
    directory = Path(directory)
    probes = rows(PROBES)
    protected = protected_prompts()
    if len({p["id"] for p in probes}) != len(probes):
        raise ValueError("Duplicate probe IDs")
    if len({normalized(p["prompt"]) for p in probes}) != len(probes):
        raise ValueError("Duplicate probes")
    if any(normalized(p["prompt"]) in protected for p in probes):
        raise ValueError("Probe overlaps protected Gold/benchmark")
    adapter = ROOT / "copycat_07_epoch1_adapter"
    manifest = {str(p.relative_to(ROOT)): digest(p)
                for p in ROOT.rglob("*") if p.is_file()
                and (p.name.startswith(("gold", "replay", "benchmark", "chat_copycat", "copycat.py"))
                     or p.parent == adapter)}
    config = {
        "cycle": "botforeman_nr01", "created_at": now(), "starting_adapter": str(adapter),
        "selection_evidence": "RAPORT_COPYCAT_10_CONSOLIDARE.md: minimum normalized L06-L09 score 07=53.1%, 10=50.0%",
        "training": {"epochs": 1, "learning_rate": 0.000005, "seed": 42, "batch_size": 1,
                     "gradient_accumulation": 4, "max_length": 384, "r": 8, "alpha": 16,
                     "dropout": 0.05, "target_modules": ["q_proj", "v_proj"]},
        "training_enabled": False, "api_enabled": False, "api_budget_usd": 0,
        "generation": {"max_new_tokens": 384, "do_sample": False, "system_message": ""},
        "counts": dict(Counter(p["split"] for p in probes)), "gold_count": 0,
        "benchmark_count": len(benchmark_rows()),
    }
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "config.json", config)
    write_json(directory / "protected_manifest.json", manifest)
    write_rows(directory / "probes.jsonl", probes)
    write_json(directory / "probe_manifest.json", {"sha256": digest(directory / "probes.jsonl"),
               "source_sha256": digest(PROBES), "author": "Codex draft; not human validated",
               "protected_prompt_count": len(protected), "exact_normalized_overlap": 0,
               "limitation": "Exact normalized deduplication does not exclude semantic similarity."})
    write_json(directory / "api_policy.json", {
        "enabled": False, "model": None, "verified_pricing": None,
        "max_calls": 0, "max_input_tokens": 0, "max_output_tokens": 0,
        "budget_usd": "0", "approval": None, "automatic_retries": 0,
        "transport": "not_implemented; no API calls possible in this cycle",
    })
    write_rows(directory / "api_usage.jsonl", [{"event": "local_cycle_initialized", "at": now(),
               "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": "0"}])
    return config


def verify(directory):
    directory = Path(directory)
    for relative, expected in read_json(directory / "protected_manifest.json").items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Protected source changed: {relative}")
    if digest(directory / "probes.jsonl") != read_json(directory / "probe_manifest.json")["sha256"]:
        raise ValueError("Probe snapshot changed")


def infer(directory, output, *, adapter=None, regression=False):
    from .local_model import load, generate, MODEL
    directory, output = Path(directory), Path(output)
    verify(directory)
    if output.exists() or Path(str(output) + ".meta.json").exists():
        raise FileExistsError(output)
    config = read_json(directory / "config.json")
    adapter = Path(adapter or config["starting_adapter"]).resolve(strict=True)
    probes = rows(directory / "probes.jsonl")
    if regression:
        probes += benchmark_rows()
    adapter_hash = digest(adapter / "adapter_model.safetensors")
    metadata = {"adapter": str(adapter), "adapter_sha256": adapter_hash, "model": MODEL,
                "generation": config["generation"], "botforeman_attached": False,
                "api_calls": 0, "started_at": now(), "requested_count": len(probes)}
    # Reserve output before loading the model; a failure is explicit, never fabricated.
    with output.open("x", encoding="utf-8") as stream:
        model, tokenizer = load(adapter)
        for item in probes:
            answer, tokens = generate(model, tokenizer, item["prompt"],
                                      config["generation"]["max_new_tokens"])
            record = {"id": item["id"], "split": item["split"], "prompt": item["prompt"],
                      "benchmark": item.get("benchmark", "new_probes"),
                      "output": answer, "generated_tokens": tokens,
                      "possibly_truncated": tokens >= config["generation"]["max_new_tokens"],
                      "adapter_sha256": adapter_hash, "source": "local_copycat_inference", "at": now()}
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            print(f"{record['benchmark']}/{item['id']}: {answer}", flush=True)
    verify(directory)
    metadata.update(completed_at=now(), output_sha256=digest(output), completed_count=len(probes))
    write_json(str(output) + ".meta.json", metadata)


def review(directory, observations):
    from .. import BotForeman
    from ..bots.nativ_roman_bot import NativRomanBot
    directory, observations = Path(directory), Path(observations)
    verify(directory)
    meta = read_json(str(observations) + ".meta.json")
    if meta["output_sha256"] != digest(observations) or meta["botforeman_attached"] is not False:
        raise ValueError("Unverified inference artifact")
    probes = rows(directory / "probes.jsonl")
    by_id = {item["id"]: item for item in probes}
    bot = NativRomanBot(probes)
    foreman = BotForeman()
    foreman.attach(bot)
    queue, evaluated = [], []
    for observation in rows(observations):
        if observation["benchmark"] != "new_probes":
            continue  # Frozen benchmark responses can never become training candidates.
        probe = by_id[observation["id"]]
        if observation["prompt"] != probe["prompt"]:
            raise ValueError("Prompt mismatch")
        evaluation = foreman.evaluate(probe["prompt"], observation["output"])[0].to_dict()
        details = bot.analyze(probe["prompt"], observation["output"])
        item = {**observation, "evaluation": evaluation, "details": details,
                "category": probe["category"], "review_status": "pending",
                "provenance": {"observations": str(observations.resolve()),
                    "observations_sha256": digest(observations), "probe_sha256": digest(directory / "probes.jsonl"),
                    "evaluator": bot.version, "candidate_author": "Codex draft; not Gold"}}
        evaluated.append(item)
        if probe["split"] == "lesson":
            queue.append({**item, "candidate": probe["candidate"], "question": probe["question"]})
    if {item["id"] for item in evaluated} != set(by_id):
        raise ValueError("Missing new probe observations")
    write_rows(directory / "evaluations.jsonl", evaluated)
    write_rows(directory / "review_queue.jsonl", queue)
    write_rows(directory / "review_template.jsonl", [
        {"id": item["id"], "decision": "pending", "target": None, "reviewer": None,
         "reviewed_at": None, "notes": "", "queue_sha256": digest(directory / "review_queue.jsonl")}
        for item in queue])
    groups = {}
    for item in queue:
        groups.setdefault(item["category"], []).append(item["id"])
    write_json(directory / "lesson_proposals.json", {"groups": groups,
               "status": "hypotheses_not_confirmed_errors", "gold_count": 0})
    lines = ["# Revizuire nativ_roman.bot — propuneri, nu Gold", "",
             "Toate verdictele locale sunt UNCERTAIN. Răspunsurile sunt inferențe Copycat reale.", ""]
    for item in queue:
        lines += [f"## {item['id']} — {item['category']}", "", f"INPUT: {item['prompt']}", "",
                  f"COPYCAT: {item['output']}", "", "STATUS: UNCERTAIN", ""]
        for signal in ("KEEP", "OMIT", "UNCERTAIN"):
            lines += [f"{signal}: {json.dumps(item['evaluation'][signal.lower()], ensure_ascii=False)}", ""]
        lines += ["MOTIV: verificări lexicale limitate; sensul, naturalețea, registrul și certitudinea cer judecată umană.",
                  "", f"CANDIDAT NEVALIDAT: {item['candidate']}", "", f"ÎNTREBARE: {item['question']}", ""]
        for criterion, finding in item["details"]["dimensions"].items():
            lines += [f"- {criterion}: {finding['reason']}"]
        lines.append("")
    with (directory / "review.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def export_gold(directory, decisions, output):
    directory, decisions, output = Path(directory), Path(decisions), Path(output)
    verify(directory)
    queue_path = directory / "review_queue.jsonl"
    queue = {item["id"]: item for item in rows(queue_path)}
    probes = {p["id"]: p for p in rows(directory / "probes.jsonl")}
    protected = protected_prompts() | {normalized(p["prompt"]) for p in probes.values() if p["split"] != "lesson"}
    accepted, seen = [], set()
    for decision in rows(decisions):
        identifier = decision["id"]
        if identifier in seen or identifier not in queue:
            raise ValueError("Duplicate/unknown review ID")
        seen.add(identifier)
        if decision["queue_sha256"] != digest(queue_path):
            raise ValueError("Review applies to another queue")
        if decision["decision"] == "pending":
            continue
        if decision["decision"] not in {"confirm", "correct", "reject"}:
            raise ValueError("Invalid review decision")
        if not decision.get("reviewer") or not decision.get("reviewed_at"):
            raise ValueError("Human reviewer identity and timestamp required")
        datetime.fromisoformat(decision["reviewed_at"])
        if decision["decision"] == "reject":
            continue
        item = queue[identifier]
        probe = probes[identifier]
        if item["split"] != "lesson" or item["prompt"] != probe["prompt"] or normalized(item["prompt"]) in protected:
            raise ValueError("Holdout/benchmark contamination")
        target = item["candidate"] if decision["decision"] == "confirm" else decision.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("A corrected target must be nonempty text")
        accepted.append({"id": identifier, "messages": [{"role": "user", "content": item["prompt"]},
                         {"role": "assistant", "content": target}],
                         "provenance": {**item["provenance"], "human_review": decision,
                                        "queue_sha256": digest(queue_path), "decisions_sha256": digest(decisions)}})
    if not accepted:
        raise ValueError("No human-validated examples; Gold not created")
    write_rows(output, accepted)
    write_json(str(output) + ".validation.json", {"gold_sha256": digest(output), "count": len(accepted),
               "decisions": str(decisions.resolve()), "decisions_sha256": digest(decisions),
               "queue_sha256": digest(queue_path), "created_at": now()})
    return len(accepted)
