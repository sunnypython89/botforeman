"""Reversible LoRA continuation, gated on human Gold and a complete baseline."""

import argparse
import json
from pathlib import Path
import sys

from .workflow import (ROOT, benchmark_rows, digest, normalized, now, protected_prompts,
                       read_json, rows, verify, write_json)


def validated_gold(directory, gold):
    directory, gold = Path(directory), Path(gold)
    validation = read_json(str(gold) + ".validation.json")
    queue_path = directory / "review_queue.jsonl"
    decisions_path = Path(validation["decisions"])
    if (digest(gold) != validation["gold_sha256"]
            or digest(queue_path) != validation["queue_sha256"]
            or digest(decisions_path) != validation["decisions_sha256"]):
        raise ValueError("Gold, queue or review changed after validation")
    data = rows(gold)
    if not data or len(data) != validation["count"]:
        raise ValueError("Empty/inconsistent Gold")
    queue = {r["id"]: r for r in rows(queue_path)}
    decisions = {r["id"]: r for r in rows(decisions_path)}
    probes = {r["id"]: r for r in rows(directory / "probes.jsonl")}
    protected = protected_prompts() | {normalized(p["prompt"]) for p in probes.values() if p["split"] != "lesson"}
    seen = set()
    for record in data:
        identifier = record["id"]
        if identifier in seen:
            raise ValueError("Duplicate Gold ID")
        seen.add(identifier)
        decision = decisions[identifier]
        item, probe = queue[identifier], probes[identifier]
        if (decision["decision"] not in {"confirm", "correct"}
                or not decision.get("reviewer") or not decision.get("reviewed_at")
                or decision["queue_sha256"] != digest(queue_path)):
            raise ValueError("Gold needs explicit human review")
        target = item["candidate"] if decision["decision"] == "confirm" else decision["target"]
        if (probe["split"] != "lesson" or item["prompt"] != probe["prompt"]
                or normalized(item["prompt"]) in protected
                or record["messages"] != [{"role": "user", "content": probe["prompt"]},
                                          {"role": "assistant", "content": target}]
                or record["provenance"]["human_review"] != decision):
            raise ValueError("Gold provenance or target mismatch")
    return data


def check_baseline(directory, baseline):
    meta = read_json(str(baseline) + ".meta.json")
    config = read_json(Path(directory) / "config.json")
    if (meta["output_sha256"] != digest(baseline) or meta["botforeman_attached"] is not False
            or meta["adapter_sha256"] != digest(Path(config["starting_adapter"]) / "adapter_model.safetensors")
            or meta["generation"] != config["generation"]):
        raise ValueError("Baseline must use the starting checkpoint and fixed generation settings")
    expected = {(r.get("benchmark", "new_probes"), r["id"]): r["prompt"]
                for r in rows(Path(directory) / "probes.jsonl") + benchmark_rows()}
    data = rows(baseline)
    actual = {(r["benchmark"], r["id"]): r["prompt"] for r in data}
    if actual != expected or len(data) != len(expected):
        raise ValueError("Complete baseline required: 10 new + 196 frozen probes")


def plan(directory, gold=None, baseline=None):
    directory = Path(directory)
    verify(directory)
    config = read_json(directory / "config.json")
    blockers = []
    count = 0
    if gold:
        count = len(validated_gold(directory, gold))
    else:
        blockers.append("No human-validated Gold supplied")
    if baseline:
        check_baseline(directory, baseline)
    else:
        blockers.append("Fresh standalone baseline required: all 196 old + 10 new probes")
    return {"status": "blocked" if blockers else "ready_for_explicit_execution",
            "blockers": blockers, "starting_adapter": config["starting_adapter"],
            "configuration": config["training"], "validated_examples": count,
            "optimizer_steps": (count + config["training"]["gradient_accumulation"] - 1) // config["training"]["gradient_accumulation"],
            "output": str(directory / "adapter_candidate"), "api_cost_usd": 0,
            "regression": {"frozen": 196, "new_holdout": 4, "lesson_diagnostic_only": 6,
                           "promotion": "Manual review; reject any unaccepted per-suite regression",
                           "scoring": "Exact match diagnostic plus fresh human semantic/route judgments"},
            "limitations": ["Six draft lesson examples are a pilot, not evidence of generalized improvement",
                            "No replay in the first isolated pilot; regression risk must be measured"]}


def train(directory, gold, baseline):
    directory = Path(directory)
    report = plan(directory, gold, baseline)
    if report["blockers"]:
        raise ValueError(report["blockers"])
    output = directory / "adapter_candidate"
    if output.exists():
        raise FileExistsError("Candidate already exists; never overwrite or resume implicitly")
    data = validated_gold(directory, gold)
    config = report["configuration"]
    # Heavy imports are deliberately below all validation gates.
    import random
    import torch
    from .local_model import load
    random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    output.mkdir()  # Reserve isolated destination; a failed run is never promoted.
    write_json(output / "run_started.json", {"at": now(), "plan": report,
               "gold_sha256": digest(gold), "baseline_sha256": digest(baseline)})
    model, tokenizer = load(report["starting_adapter"], trainable=True)
    adapter_config = model.peft_config["default"]
    if (adapter_config.r != config["r"] or adapter_config.lora_alpha != config["alpha"]
            or adapter_config.lora_dropout != config["dropout"]
            or set(adapter_config.target_modules) != set(config["target_modules"])):
        raise ValueError("Unexpected starting LoRA configuration")
    encoded = []
    for record in data:
        prompt = tokenizer.apply_chat_template(record["messages"][:1], tokenize=False, system_message="")
        full = tokenizer.apply_chat_template(record["messages"], tokenize=False, system_message="")
        prefix = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        tokens = tokenizer(full, add_special_tokens=False, return_tensors="pt")
        ids = tokens["input_ids"]
        if ids.shape[1] > config["max_length"] or ids[0, :len(prefix)].tolist() != prefix:
            raise ValueError("Sequence too long or chat-template prefix mismatch; no silent truncation")
        labels = ids.clone()
        labels[:, :len(prefix)] = -100
        if torch.all(labels == -100):
            raise ValueError("No assistant training tokens")
        encoded.append((tokens, labels))
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=config["learning_rate"])
    order = list(range(len(encoded)))
    random.Random(config["seed"]).shuffle(order)
    losses = []
    accumulation = config["gradient_accumulation"]
    for start in range(0, len(order), accumulation):
        batch = order[start:start + accumulation]
        optimizer.zero_grad(set_to_none=True)
        for index in batch:
            tokens, labels = encoded[index]
            loss = model(**{k: v.to(model.device) for k, v in tokens.items()},
                         labels=labels.to(model.device)).loss
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite loss")
            (loss / len(batch)).backward()
            losses.append(loss.item())
        torch.nn.utils.clip_grad_norm_(parameters, 1.0)
        optimizer.step()
    verify(directory)
    model.save_pretrained(output)
    tokenizer.save_pretrained(output)
    write_json(output / "training_complete.json", {"at": now(), "plan": report,
               "gold_sha256": digest(gold), "mean_loss": sum(losses) / len(losses),
               "adapter_sha256": digest(output / "adapter_model.safetensors"),
               "promoted": False, "botforeman_attached": False})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--gold")
    parser.add_argument("--baseline")
    parser.add_argument("--execute", action="store_true", help="Explicit local training; still requires validated Gold and baseline")
    args = parser.parse_args()
    report = plan(args.directory, args.gold, args.baseline)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.execute:
        if report["blockers"]:
            parser.error("Training blocked: " + "; ".join(report["blockers"]))
        train(args.directory, args.gold, args.baseline)


if __name__ == "__main__":
    main()
