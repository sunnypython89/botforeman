"""Local providers. No API transport or training entry point."""

from .protocol import ModelReply, Usage


class FixtureProvider:
    """Explicitly synthetic output for plumbing tests, never Copycat measurements."""
    name = "synthetic-fixture-not-copycat"
    paid = False

    def estimate(self, prompt):
        return Usage(total_tokens=1, api_calls=0, cost_usd="0")

    def generate(self, prompt):
        return ModelReply("A", self.estimate(prompt))


class LocalCopycatProvider:
    name = "copycat-local-offline"
    paid = False

    def __init__(self, adapter, max_new_tokens=64):
        if type(max_new_tokens) is not int or max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be positive")
        from ..cycle.local_model import load
        self.model, self.tokenizer = load(adapter, trainable=False)
        self.max_new_tokens = max_new_tokens
        import hashlib
        from pathlib import Path
        self.identity = ("copycat:" + hashlib.sha256((Path(adapter) / "adapter_model.safetensors").read_bytes()).hexdigest()
                         + f":greedy:max_new_tokens={max_new_tokens}")

    def _input_tokens(self, prompt):
        text = self.tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                                  tokenize=False, system_message="")
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"])

    def estimate(self, prompt):
        return Usage(input_tokens=self._input_tokens(prompt), output_tokens=self.max_new_tokens,
                     api_calls=0, cost_usd="0")

    def generate(self, prompt):
        from ..cycle.local_model import generate
        text, tokens = generate(self.model, self.tokenizer, prompt, self.max_new_tokens)
        return ModelReply(text, Usage(input_tokens=self._input_tokens(prompt), output_tokens=tokens,
                                     api_calls=0, cost_usd="0"))
