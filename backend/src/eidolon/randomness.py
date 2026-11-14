"""Chance, as every module that needs it takes it: a function tests can replace, as they do
the clock."""

import secrets
from collections.abc import Callable, Sequence

Random = Callable[[int], int]
"""A number below the one given, from 0, each as likely as another."""

secure_random: Random = secrets.randbelow
"""The system's own, fit for what users would game."""


def falls_in(weights: Sequence[int], drawn: int) -> int:
    """Which of the candidates their chances `weights` pick, `drawn` a number below their
    sum: weighted draws (an outing's encounter, who of several replies) land here."""
    running = 0
    for index, weight in enumerate(weights):
        running += weight
        if drawn < running:
            return index
    return len(weights) - 1
