"""Small data-only contracts; no linguistic rules or model calls."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from ..protocol import validate_text

LEVELS = ("STRAIN", "INCEPATOR", "INTERMEDIAR", "AVANSAT", "NATIV")
EXAMPLES_PER_LEVEL = 5
RATINGS = ("GOOD", "BAD", "UNCERTAIN")
SYMBOLS = dict(zip(RATINGS, "GBU"))


def amount(value):
    if isinstance(value, bool):
        raise ValueError("A monetary value cannot be boolean")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Usage/limits must be finite and nonnegative")
    return result


@dataclass(frozen=True)
class Probe:
    level: str
    example_id: str
    input: str

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError("Unknown level")
        for value in (self.example_id, self.input):
            validate_text(value)
            if not value.strip():
                raise ValueError("Empty probe")


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    api_calls: int | None = None
    cost_usd: str | None = None
    credits: str | None = None

    def __post_init__(self):
        for name in ("input_tokens", "output_tokens", "total_tokens", "api_calls"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Usage counts must be nonnegative integers or None")
        for name in ("cost_usd", "credits"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, str(amount(value)))
        if self.total_tokens is None and self.input_tokens is not None and self.output_tokens is not None:
            object.__setattr__(self, "total_tokens", self.input_tokens + self.output_tokens)
        if self.total_tokens is not None and self.total_tokens < (self.input_tokens or 0) + (self.output_tokens or 0):
            raise ValueError("Total tokens cannot be smaller than input + output")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Limits:
    max_cost_per_cycle: str | None = "0"
    max_tokens_per_cycle: int | None = 100000
    max_api_calls_per_cycle: int | None = 0

    def __post_init__(self):
        if self.max_cost_per_cycle is not None:
            object.__setattr__(self, "max_cost_per_cycle", str(amount(self.max_cost_per_cycle)))
        for name in ("max_tokens_per_cycle", "max_api_calls_per_cycle"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Limits must be nonnegative integers or None")
        if all(value is None for value in asdict(self).values()):
            raise ValueError("At least one consumption limit is required")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ModelReply:
    text: str
    usage: Usage

    def __post_init__(self):
        validate_text(self.text)
        if not isinstance(self.usage, Usage):
            raise TypeError("A reply must include Usage (unknown values may be None)")


def validate_rating(value):
    if not isinstance(value, str) or value not in RATINGS:
        raise ValueError("Only GOOD, BAD and UNCERTAIN are accepted")
    return value
