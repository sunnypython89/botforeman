"""Defer expensive model loading until a selected probe actually needs it."""

import hashlib
from pathlib import Path

from ..cycle.local_model import MODEL


class LazyCopycat:
    name = "copycat-local-offline"
    paid = False
    model_name = MODEL

    def __init__(self, adapter):
        self.adapter = Path(adapter).resolve(strict=True)
        self.identity = ("copycat:" + hashlib.sha256((self.adapter / "adapter_model.safetensors").read_bytes()).hexdigest()
                         + ":greedy:max_new_tokens=64")
        self._provider = None

    def _load(self):
        if self._provider is None:
            from ..levels.providers import LocalCopycatProvider
            self._provider = LocalCopycatProvider(self.adapter)
        return self._provider

    def estimate(self, prompt):
        return self._load().estimate(prompt)

    def generate(self, prompt):
        return self._load().generate(prompt)
