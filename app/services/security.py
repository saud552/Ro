from __future__ import annotations

from secrets import SystemRandom
from typing import Sequence

_secure_rand = SystemRandom()


def draw_unique(sample: Sequence[int], k: int) -> list[int]:
    k = max(0, min(k, len(sample)))
    # Fisher-Yates selection without replacement for stability
    indices = list(range(len(sample)))
    for i in range(k):
        j = _secure_rand.randrange(i, len(indices))
        indices[i], indices[j] = indices[j], indices[i]
    return [sample[indices[i]] for i in range(k)]
