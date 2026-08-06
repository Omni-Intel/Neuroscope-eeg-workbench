from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import NormalDist
import random
from typing import Any


@dataclass(frozen=True, slots=True)
class ProtocolPreset:
    label: str
    rest_duration_sec: int
    nback_trials: int
    nback_targets: int
    stroop_trials: int
    oddball_trials: int
    emotion_per_category: int


PRESETS: dict[str, ProtocolPreset] = {
    "快速演示": ProtocolPreset("快速演示", 30, 30, 8, 30, 100, 3),
    "完整采集": ProtocolPreset("完整采集", 60, 60, 15, 60, 200, 15),
}

PROTOCOL_VERSION = "2026.08"
TIMING_STATUS = "software_sync_uncalibrated"


@dataclass(frozen=True, slots=True)
class NBackTrial:
    trial_index: int
    symbol: str
    two_back_symbol: str
    is_target: bool


@dataclass(frozen=True, slots=True)
class StroopTrial:
    trial_index: int
    word: str
    ink_color: str
    congruency: str
    correct_key: str


STROOP_KEY_MAP = {"红": "D", "绿": "F", "蓝": "J", "黄": "K"}


def _nonadjacent_positions(total: int, count: int, rng: random.Random) -> set[int]:
    if count < 0 or count * 2 > total + 1:
        raise ValueError("count cannot be placed without adjacent positions")
    compressed = sorted(rng.sample(range(total - count + 1), count))
    return {position + offset for offset, position in enumerate(compressed)}


def generate_nback_trials(trials: int, targets: int, *, seed: int = 17) -> tuple[NBackTrial, ...]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    rng = random.Random(seed)
    target_positions = _nonadjacent_positions(trials, targets, rng)
    history = [str(rng.randrange(10)), str(rng.randrange(10))]
    result: list[NBackTrial] = []
    for trial_index in range(trials):
        two_back = history[trial_index]
        if trial_index in target_positions:
            symbol = two_back
        else:
            choices = [str(value) for value in range(10) if str(value) != two_back]
            symbol = rng.choice(choices)
        history.append(symbol)
        result.append(NBackTrial(trial_index, symbol, two_back, trial_index in target_positions))
    return tuple(result)


def generate_stroop_trials(trials: int, *, seed: int = 17) -> tuple[StroopTrial, ...]:
    if trials <= 0 or trials % 2:
        raise ValueError("trials must be a positive even number")
    rng = random.Random(seed)
    colors = tuple(STROOP_KEY_MAP)
    per_condition = trials // 2
    congruent: list[tuple[str, str, str]] = []
    incongruent: list[tuple[str, str, str]] = []
    for index in range(per_condition):
        ink = colors[index % len(colors)]
        congruent.append((ink, ink, "congruent"))
        word = colors[(index + 1 + index // len(colors)) % len(colors)]
        if word == ink:
            word = colors[(colors.index(ink) + 1) % len(colors)]
        incongruent.append((word, ink, "incongruent"))
    candidates = congruent + incongruent
    for _attempt in range(1000):
        rng.shuffle(candidates)
        keys = [STROOP_KEY_MAP[ink] for _word, ink, _condition in candidates]
        if all(len(set(keys[index : index + 4])) > 1 for index in range(len(keys) - 3)):
            return tuple(
                StroopTrial(index, word, ink, condition, STROOP_KEY_MAP[ink])
                for index, (word, ink, condition) in enumerate(candidates)
            )
    raise RuntimeError("could not generate Stroop sequence without long response runs")


def signal_detection_metrics(
    *,
    targets: int,
    hits: int,
    non_targets: int,
    false_alarms: int,
) -> dict[str, float]:
    hit_rate = hits / targets if targets else 0.0
    false_alarm_rate = false_alarms / non_targets if non_targets else 0.0
    corrected_hit_rate = (hits + 0.5) / (targets + 1.0) if targets else 0.5
    corrected_false_alarm_rate = (false_alarms + 0.5) / (non_targets + 1.0) if non_targets else 0.5
    d_prime = NormalDist().inv_cdf(corrected_hit_rate) - NormalDist().inv_cdf(corrected_false_alarm_rate)
    return {
        "hit_rate": hit_rate,
        "false_alarm_rate": false_alarm_rate,
        "d_prime": d_prime,
    }


def frame_locked_frequencies(refresh_hz: float) -> tuple[float, ...]:
    """Return four frequencies whose cycles use an integer number of display frames."""
    refresh = max(30.0, float(refresh_hz))
    if refresh >= 150.0:
        frames_per_cycle = (20, 16, 10, 8)
    elif refresh >= 100.0:
        frames_per_cycle = (15, 12, 10, 8)
    else:
        frames_per_cycle = (8, 6, 5, 4)
    return tuple(round(refresh / frames, 3) for frames in frames_per_cycle)


def generate_oddball_sequence(
    trials: int,
    *,
    deviant_probability: float = 0.2,
    seed: int = 17,
) -> tuple[str, ...]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0.0 < deviant_probability < 0.5:
        raise ValueError("deviant_probability must be between 0 and 0.5")
    deviant_count = max(1, int(round(trials * deviant_probability)))
    if deviant_count * 2 > trials + 1:
        raise ValueError("too many deviants to keep them non-adjacent")

    rng = random.Random(seed)
    compressed = sorted(rng.sample(range(trials - deviant_count + 1), deviant_count))
    deviant_positions = {position + offset for offset, position in enumerate(compressed)}
    return tuple("deviant" if index in deviant_positions else "standard" for index in range(trials))


@dataclass(frozen=True, slots=True)
class StimulusEvent:
    monotonic_time: float
    wall_time: float
    paradigm: str
    phase: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["payload"] = dict(self.payload)
        return result
