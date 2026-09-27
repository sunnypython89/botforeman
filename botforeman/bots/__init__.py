"""Evaluators are attached explicitly; importing does not register plugins."""

from .base import ForemanBot
from .counting_bot import CountingBot

__all__ = ["ForemanBot", "CountingBot"]
