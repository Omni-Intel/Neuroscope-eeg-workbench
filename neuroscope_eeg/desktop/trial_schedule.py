"""Finite balanced schedules; original nine-second trial timing is unchanged."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TrialSchedule:
    conditions: int
    per_condition: int
    practice: bool = False
    block_size: int = 10
    rest_seconds: float = 60.0

    def __post_init__(self):
        if any(not isinstance(value, int) or value < 1 for value in (self.conditions, self.per_condition, self.block_size)):
            raise ValueError("试次数必须为正整数")

    @property
    def total(self):
        return self.conditions * self.per_condition

    @property
    def duration(self):
        return (self.total + self.conditions * self.practice) * 9 + self.rest_seconds * (math.ceil(self.per_condition / self.block_size) - 1)

    def position(self, elapsed):
        elapsed = max(0., elapsed)
        practice_count = self.conditions if self.practice else 0
        if elapsed < practice_count * 9:
            trial = int(elapsed // 9)
            return {"trial": trial, "formal_trial_index": -1, "is_practice": True, "block": 0,
                        "condition_index": trial, "within": elapsed % 9, "stage": "trial"}
        elapsed -= practice_count * 9
        completed = 0
        for block in range(math.ceil(self.per_condition / self.block_size)):
            count = min(self.block_size, self.per_condition - block * self.block_size) * self.conditions
            if elapsed < count * 9:
                trial = completed + int(elapsed // 9)
                return {"trial": practice_count + trial, "formal_trial_index": trial, "is_practice": False,
                            "block": block + 1, "condition_index": trial % self.conditions,
                            "within": elapsed % 9, "stage": "trial"}
            elapsed -= count * 9
            completed += count
            if completed < self.total:
                if elapsed < self.rest_seconds:
                    return {"stage": "block_rest", "block": block + 1, "remaining": self.rest_seconds - elapsed}
                elapsed -= self.rest_seconds
        return {"stage": "complete"}
