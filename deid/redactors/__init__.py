"""Redactors.

`rules` and `transformer` run locally. `llm` transmits note text off-machine
and is imported lazily so that importing this package never pulls in the
Anthropic SDK, and never makes an offsite redactor available by accident.
"""

from .base import BaseRedactor, Redactor
from .rules import RuleRedactor

__all__ = ["BaseRedactor", "Redactor", "RuleRedactor"]
