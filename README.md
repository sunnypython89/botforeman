# BotForeman

**BotForeman** is an experimental orchestrator for small, inspectable bots. Its first prototype coordinates deterministic evaluators and collects their judgments; the longer-term research direction is to compose bot capabilities into reusable workflows.

> Give each bot a clear job. Keep the decision trace visible.

## Status

**Prototype v0.1.** The local implementation currently supports attaching and detaching evaluators, collecting serializable results, and a deterministic `counting.bot` demo. Its judgments use `PASS`, `FAIL`, or `UNCERTAIN`, with a score and a `KEEP` / `OMIT` / `UNCERTAIN` plan. The existing local demo has 15 passing tests. The implementation and tests have **not yet been added to this repository**.

Capability stacking, macro-skills, Shatterglass constraints, a simulator UI, chat control, cost accounting, and Codex integration are **design goals**, not implemented features of this repository.

## Why build it?

The research question is whether specialized bots can be combined into more capable behavior while keeping each decision inspectable, reproducible, and affordable.

A deterministic evaluator should judge an answer without silently rewriting it. BotForeman coordinates the evaluators and records their results; the rules for a specific judgment belong to the bot that makes it.

## Current prototype

```text
input
  ↓
BotForeman ── attach evaluators
  ↓
counting.bot ── apply its own counting rules
  ↓
serializable judgment + score + action plan
```

The current prototype does not train a model or change an answer. It is a small foundation for experiments, not a general agent platform yet.

## Research direction

A future BotForeman could register capabilities such as `COUNT`, `COMPARE`, and `TRACE`, execute them in a defined order, and measure whether the composition improves results. A useful, tested sequence could become a named **macro-skill**.

```text
COUNT → COMPARE → TRACE → STRUCTURAL_AUDIT
```

A proposed **Shatterglass** constraint can describe an invariant (`r`), dimensions that may vary (`D`), allowed actions (`A`), and checks (`C`): `SG = (r, D, A, C)`. This is a design model under exploration, not a claim that those properties are already enforced in code.

A proposed simulator would show the active bots, their execution trace, judgments, replayable runs, and the cost of each step. Chat could become the control surface; Codex could implement and test proposed changes. External model calls would require an explicit budget before execution.

## Design principles

- **Small roles:** Each evaluator owns its own rules.
- **Visible decisions:** Keep judgments, uncertainty, and evidence inspectable.
- **No silent rewriting:** Evaluation does not secretly replace an answer.
- **Measured composition:** A larger stack must justify its extra time and cost.
- **Explicit constraints:** State invariants and checks where they can be reviewed.
- **Honest status:** Separate working features from experiments and plans.

## Relationship to Copycat

[Copycat](https://github.com/sunnypython89/copycat-ro) explores Romanian-language behavior and evaluation. BotForeman is intended as a reusable orchestration layer that can support those experiments without being tied to one language model. This repository is its independent home.

## Running the project

The local prototype's source, tests, dependency list, and verified run commands are being migrated. Installation instructions will be added after those files are present. For now, this repository documents the scope and design; it is not yet an installable package.

## License

No license has been selected yet. Until one is added, please do not assume permission to reuse or redistribute the code when it arrives.
