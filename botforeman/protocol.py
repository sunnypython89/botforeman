"""Data-only common protocol. Domain-specific expectations belong to bots."""

from dataclasses import dataclass


MAX_TEXT_LENGTH = 65536


def validate_text(value):
    if not isinstance(value, str):
        raise TypeError("Expected text")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError("Text exceeds sandbox limit")


@dataclass(frozen=True)
class TestCase:
    name: str
    prompt: str

    def __post_init__(self):
        validate_text(self.name)
        validate_text(self.prompt)
