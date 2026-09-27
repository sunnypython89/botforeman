# BotForeman

BotForeman orchestrates trusted, specialized evaluators and returns inspectable judgments. It evaluates model output without rewriting it. **v0.1.0 is experimental research software.**

## Why BotForeman

Small evaluators can expose concrete failures and uncertainty without becoming autonomous teachers. Domain rules belong to each evaluator; orchestration, provenance and explicit review remain separate.

## Architecture

```text
input + model output -> BotForeman -> attached evaluators
                                  -> serializable results + omission plans
```

The core attaches/detaches evaluators, calls each once per evaluation, isolates evaluator exceptions as UNCERTAIN, and collects results. It does not aggregate scores or infer consensus. Counting rules remain in `bots/counting_bot.py`. Disabling BotForeman returns an empty result list and calls no evaluator.

## Current status and features

**Implemented core:** explicit attachment, duplicate-name rejection, text limits, immutable results, PASS/FAIL/UNCERTAIN, KEEP/OMIT/UNCERTAIN plans, deterministic counting (missing, duplicate, ordering and off-by-one errors).

**Implemented experimental workflows:** fixed 5x5 GOOD/BAD/UNCERTAIN cycles; selective SCOUT/AUDIT; usage limits; evaluation cache; probe registry; explicit Verified Knowledge Store; manual teacher packet export/import and review queues. These modules retain their own documented contracts. Their three-way ratings do not replace the core status protocol.

**Limitations:** Romanian evaluators are narrow rules/parsers, not reliable native-language judges. Teacher deltas require imported assertions or a supplied specialist. No live paid teacher transport is included. No automatic Gold validation, response correction, dataset application, or training occurs through evaluation. A legacy, explicitly gated Copycat training experiment exists in `cycle/experiment.py`; it requires external artifacts, human-reviewed data, baseline evidence and explicit execution. It is not part of quick start or CI.

## Quick start

Python 3.10+; core and tests need only the standard library. Packaging uses setuptools.

```sh
git clone https://github.com/sunnypython89/botforeman.git
cd botforeman
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install .
python -m botforeman.demo
python -m unittest discover -s tests -v
```

No API key, GPU, model download or private data is needed. Tests use synthetic fixtures and mocked model dependencies. The two chat compatibility snapshots in `tests/fixtures` are test inputs, not recommended executable demos.

## Example

```python
from botforeman import BotForeman
from botforeman.bots import CountingBot

foreman = BotForeman()
foreman.attach(CountingBot())
result = foreman.evaluate("COUNT 1 5 1", "[1,2,4,5]")[0]
print(result.to_json())
foreman.detach("counting.bot")
```

```json
{"bot":"counting.bot","status":"FAIL","keep":[],"omit":["missing_element"],"uncertain":[],"score":0.0,"notes":["missing_element: [3]"]}
```

Notes may contain additional diagnostic details. Counting accepts a strict JSON integer array and an inclusive `COUNT start stop step` prompt. Unsupported formats return UNCERTAIN. KEEP/OMIT describe behaviors, not instructions to edit text. Scores across different evaluators are not inherently comparable.

## Evaluator interface

Implement `ForemanBot` from `botforeman.bots.base`:

- `name`: unique evaluator identity.
- `generate_tests(context)`: controlled `TestCase` values.
- `evaluate(prompt, output)`: `EvaluationResult` with an `OmissionPlan`.
- `omission_plan(prompt, output, evaluation)`: optional refinement; defaults to the result plan.

Attach instances explicitly. Evaluators must be trusted, bounded, side-effect-free Python code. Text/data sandboxing is a contract, **not OS isolation of hostile plugins**. Do not execute untrusted evaluator modules.

## Design direction: feedback-driven correction

```text
system -> observation -> evaluators -> correction -> next state
```

In the experimental ecosystem, Copycat is the adaptive system; BotForeman is the regulator/orchestrator; Shatterglass is a proposed reference space or set of bounds; `r` may represent a reference or stability signal.

Alignment is treated as a continuing feedback process rather than a finished state. This is a research direction, not a claim that AI alignment is solved. Correction currently means an inspectable proposal and explicit review, not autonomous rewriting or learning. Shatterglass is not implemented.

## Cost safety

External API access is disabled by default (`api_enabled=False`, zero API/cost limits in the relevant workflows). All demos and tests are offline/synthetic by default. Chat subscriptions are not treated as API credits.

- Core: one evaluation and one omission-plan call per attached evaluator; no retry loop or network transport. Callers control the finite attached set.
- Level/adaptive workflows: configurable token/call/cost caps, conservative reservation before provider execution, usage logging, partial-result persistence and stop on overrun/error. No automatic paid retries.
- Teacher delta: defaults of 128 output tokens, two teacher calls per run, zero cost. Paid teachers are blocked, including when a positive cost limit is supplied.
- Optional API evaluator injection must use the existing approval ledger with verified pricing, explicit approval and finite limits. No network implementation is bundled.

A provider must enforce its generation cap. Reporting an overrun cannot undo consumed tokens. Unknown usage is not represented as proven zero. Records may contain user text: keep experiment directories private.

**Planned provider contract:** per-evaluator and total call ceilings, max attached evaluators, bounded request timeout and retry limit zero. Generic in-process Python evaluators currently have no hard timeout or OS isolation; do not attach expensive/unbounded callables. Any future network integration must enforce timeout and budgets before it is enabled.

## Workflow documentation

- [Core/counting protocol](botforeman/README.md)
- [Fixed level cycles](botforeman/levels/README.md)
- [SCOUT/AUDIT](botforeman/adaptive/README.md)
- [Knowledge Store](botforeman/knowledge/README.md)
- [Teacher delta](botforeman/teacher_delta/README.md) and [manual packets](botforeman/teacher_delta/MANUAL.md)

Some workflow guides describe an external Copycat research workspace. Referenced adapters, historical reports, benchmarks, Gold and experiment paths are **not shipped**. Commands using them require that external workspace. Local GPU inference additionally needs a compatible CUDA/PyTorch, transformers, peft and bitsandbytes installation plus cached model weights; none are core dependencies or downloaded automatically by BotForeman's local provider. A supplied model has its own license.

## Roadmap

Planned: evaluator discovery registry; modular capability stacking and composition; explicit aggregation/confidence semantics; portable Copycat configuration; UI and visual simulator; Shatterglass reference layer; optional API providers with timeout/budget enforcement. Persistent experimental run history and review queues already exist. Stacking should compose controlled capabilities without moving specialist logic into the orchestrator.

## Project status

Experimental / research sandbox. Version is defined only in `botforeman.__version__`; packaging reads it. Public tests are reproducible without private datasets. Production authentication, hostile-plugin isolation and semantic certification are outside v0.1.

## License

[MIT](LICENSE), copyright 2026 Sunny Python. Model weights, adapters, private datasets and experimental outputs are not distributed here.
