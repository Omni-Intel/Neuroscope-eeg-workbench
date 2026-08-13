from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import NormalDist
import random
from typing import Any


@dataclass(frozen=True, slots=True)
class ProtocolPreset:
    label: str
    rest_duration_sec: int
    rest_repetitions: int
    assr_cycles: int
    nback_blocks_per_level: int
    nback_trials_per_block: int
    nback_targets_per_block: int
    stroop_trials: int
    oddball_trials: int
    emotion_per_category: int

    @property
    def nback_trials(self) -> int:
        return len(NBACK_LEVELS) * self.nback_blocks_per_level * self.nback_trials_per_block

    @property
    def nback_targets(self) -> int:
        return len(NBACK_LEVELS) * self.nback_blocks_per_level * self.nback_targets_per_block


ASSR_CONDITIONS = ("binaural", "right", "left")


def generate_assr_sequence(trials_per_condition: int, *, seed: int = 17) -> tuple[str, ...]:
    """Generate balanced ASSR conditions in randomized three-trial blocks."""
    if trials_per_condition <= 0:
        raise ValueError("trials_per_condition must be positive")
    rng = random.Random(seed)
    sequence: list[str] = []
    for _ in range(trials_per_condition):
        block = list(ASSR_CONDITIONS)
        rng.shuffle(block)
        sequence.extend(block)
    return tuple(sequence)


PRESETS: dict[str, ProtocolPreset] = {
    "快速演示": ProtocolPreset("快速演示", 30, 1, 2, 1, 10, 3, 30, 100, 3),
    "完整采集": ProtocolPreset("完整采集", 60, 2, 12, 4, 40, 13, 120, 300, 15),
}

PROTOCOL_VERSION = "2026.08.11"
TIMING_STATUS = "software_sync_uncalibrated"
NBACK_STIMULUS_DURATION_SEC = 1.5
NBACK_BLANK_DURATION_SEC = 0.5
NBACK_RULE_DURATION_SEC = 5.0
NBACK_BLOCK_REST_DURATION_SEC = 25.0
NBACK_RESPONSE_WINDOW_MS = NBACK_STIMULUS_DURATION_SEC * 1000.0
NBACK_LEVELS = (0, 1, 2)


def nback_response_is_open(response_time_ms: float) -> bool:
    return 0.0 <= response_time_ms < NBACK_RESPONSE_WINDOW_MS


@dataclass(frozen=True, slots=True)
class NBackTrial:
    trial_index: int
    symbol: str
    comparison_symbol: str
    is_target: bool
    nback_level: int


@dataclass(frozen=True, slots=True)
class NBackBlock:
    block_index: int
    load_block_index: int
    nback_level: int
    target_symbol: str | None
    sequence_seed: int
    trials: tuple[NBackTrial, ...]


@dataclass(frozen=True, slots=True)
class NBackScheduleItem:
    kind: str
    duration_sec: float
    label: str
    is_practice: bool
    nback_level: int
    block_index: int = -1
    load_block_index: int = -1
    formal_trial_index: int = -1
    target_symbol: str | None = None
    sequence_seed: int = -1
    trial: NBackTrial | None = None


@dataclass(frozen=True, slots=True)
class StroopTrial:
    trial_index: int
    word: str
    ink_color: str
    congruency: str
    correct_key: str


STROOP_RESPONSE_KEYS = {"congruent": "J", "incongruent": "F"}


def _nonadjacent_positions(total: int, count: int, rng: random.Random) -> set[int]:
    if count < 0 or count * 2 > total + 1:
        raise ValueError("count cannot be placed without adjacent positions")
    compressed = sorted(rng.sample(range(total - count + 1), count))
    return {position + offset for offset, position in enumerate(compressed)}


def generate_nback_trials(
    trials: int,
    targets: int,
    *,
    nback_level: int = 2,
    target_symbol: str | None = None,
    seed: int = 17,
) -> tuple[NBackTrial, ...]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if nback_level not in NBACK_LEVELS:
        raise ValueError("nback_level must be 0, 1, or 2")
    rng = random.Random(seed)
    target_positions = _nonadjacent_positions(trials, targets, rng)
    if nback_level == 0:
        comparison_target = target_symbol if target_symbol is not None else str(rng.randrange(10))
        if comparison_target not in tuple(str(value) for value in range(10)):
            raise ValueError("target_symbol must be a digit from 0 to 9")
        history: list[str] = []
    else:
        comparison_target = ""
        history = [str(rng.randrange(10)) for _ in range(nback_level)]
    result: list[NBackTrial] = []
    for trial_index in range(trials):
        comparison = comparison_target if nback_level == 0 else history[trial_index]
        if trial_index in target_positions:
            symbol = comparison
        else:
            choices = [str(value) for value in range(10) if str(value) != comparison]
            symbol = rng.choice(choices)
        if nback_level:
            history.append(symbol)
        result.append(
            NBackTrial(trial_index, symbol, comparison, trial_index in target_positions, nback_level)
        )
    return tuple(result)


def generate_nback_blocks(
    blocks_per_level: int,
    trials_per_block: int,
    targets_per_block: int,
    *,
    seed: int = 17,
) -> tuple[NBackBlock, ...]:
    if blocks_per_level <= 0:
        raise ValueError("blocks_per_level must be positive")
    blocks: list[NBackBlock] = []
    for load_block_index in range(blocks_per_level):
        for nback_level in NBACK_LEVELS:
            block_index = len(blocks)
            sequence_seed = seed + block_index * 1009
            target_symbol = (
                str(random.Random(sequence_seed).randrange(10)) if nback_level == 0 else None
            )
            blocks.append(
                NBackBlock(
                    block_index=block_index,
                    load_block_index=load_block_index,
                    nback_level=nback_level,
                    target_symbol=target_symbol,
                    sequence_seed=sequence_seed,
                    trials=generate_nback_trials(
                        trials_per_block,
                        targets_per_block,
                        nback_level=nback_level,
                        target_symbol=target_symbol,
                        seed=sequence_seed,
                    ),
                )
            )
    return tuple(blocks)


def _nback_sequence_items(
    trials: tuple[NBackTrial, ...],
    *,
    is_practice: bool,
    nback_level: int,
    block_index: int,
    load_block_index: int,
    target_symbol: str | None,
    sequence_seed: int,
    formal_trial_start: int,
) -> list[NBackScheduleItem]:
    items: list[NBackScheduleItem] = []
    context = tuple(trial.comparison_symbol for trial in trials[:nback_level])
    for symbol in context:
        items.append(
            NBackScheduleItem(
                "context",
                NBACK_STIMULUS_DURATION_SEC,
                symbol,
                is_practice,
                nback_level,
                block_index,
                load_block_index,
                target_symbol=target_symbol,
                sequence_seed=sequence_seed,
            )
        )
        items.append(
            NBackScheduleItem(
                "blank",
                NBACK_BLANK_DURATION_SEC,
                "",
                is_practice,
                nback_level,
                block_index,
                load_block_index,
                target_symbol=target_symbol,
                sequence_seed=sequence_seed,
            )
        )
    for trial in trials:
        formal_trial_index = -1 if is_practice else formal_trial_start + trial.trial_index
        items.append(
            NBackScheduleItem(
                "trial",
                NBACK_STIMULUS_DURATION_SEC,
                trial.symbol,
                is_practice,
                nback_level,
                block_index,
                load_block_index,
                formal_trial_index,
                target_symbol,
                sequence_seed,
                trial,
            )
        )
        items.append(
            NBackScheduleItem(
                "blank",
                NBACK_BLANK_DURATION_SEC,
                "",
                is_practice,
                nback_level,
                block_index,
                load_block_index,
                formal_trial_index,
                target_symbol,
                sequence_seed,
                trial,
            )
        )
    return items


def generate_nback_schedule(preset: ProtocolPreset) -> tuple[NBackScheduleItem, ...]:
    items: list[NBackScheduleItem] = []
    practice_targets = 3
    for nback_level in NBACK_LEVELS:
        sequence_seed = 11 + nback_level
        target_symbol = str(random.Random(sequence_seed).randrange(10)) if nback_level == 0 else None
        trials = generate_nback_trials(
            10,
            practice_targets,
            nback_level=nback_level,
            target_symbol=target_symbol,
            seed=sequence_seed,
        )
        rule = f"{nback_level}-back"
        if target_symbol is not None:
            rule += f"｜目标数字 {target_symbol}"
        items.append(
            NBackScheduleItem(
                "rule",
                NBACK_RULE_DURATION_SEC,
                rule,
                True,
                nback_level,
                target_symbol=target_symbol,
                sequence_seed=sequence_seed,
            )
        )
        items.extend(
            _nback_sequence_items(
                trials,
                is_practice=True,
                nback_level=nback_level,
                block_index=-1,
                load_block_index=-1,
                target_symbol=target_symbol,
                sequence_seed=sequence_seed,
                formal_trial_start=-1,
            )
        )

    blocks = generate_nback_blocks(
        preset.nback_blocks_per_level,
        preset.nback_trials_per_block,
        preset.nback_targets_per_block,
    )
    formal_trial_start = 0
    for block in blocks:
        rule = f"{block.nback_level}-back"
        if block.target_symbol is not None:
            rule += f"｜目标数字 {block.target_symbol}"
        items.append(
            NBackScheduleItem(
                "rule",
                NBACK_RULE_DURATION_SEC,
                rule,
                False,
                block.nback_level,
                block.block_index,
                block.load_block_index,
                target_symbol=block.target_symbol,
                sequence_seed=block.sequence_seed,
            )
        )
        items.extend(
            _nback_sequence_items(
                block.trials,
                is_practice=False,
                nback_level=block.nback_level,
                block_index=block.block_index,
                load_block_index=block.load_block_index,
                target_symbol=block.target_symbol,
                sequence_seed=block.sequence_seed,
                formal_trial_start=formal_trial_start,
            )
        )
        formal_trial_start += len(block.trials)
        if block.block_index < len(blocks) - 1:
            items.append(
                NBackScheduleItem(
                    "rest",
                    NBACK_BLOCK_REST_DURATION_SEC,
                    "休息",
                    False,
                    block.nback_level,
                    block.block_index,
                    block.load_block_index,
                    target_symbol=block.target_symbol,
                    sequence_seed=block.sequence_seed,
                )
            )
    return tuple(items)


def generate_stroop_trials(trials: int, *, seed: int = 17) -> tuple[StroopTrial, ...]:
    if trials <= 0 or trials % 2:
        raise ValueError("trials must be a positive even number")
    rng = random.Random(seed)
    colors = ("红", "绿", "蓝", "黄")
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
    rng.shuffle(congruent)
    rng.shuffle(incongruent)
    conditions = (congruent, incongruent) if rng.random() < 0.5 else (incongruent, congruent)
    candidates = [item for pair in zip(*conditions) for item in pair]
    return tuple(
        StroopTrial(index, word, ink, condition, STROOP_RESPONSE_KEYS[condition])
        for index, (word, ink, condition) in enumerate(candidates)
    )


def balanced_accuracy(
    *, first_correct: int, first_total: int, second_correct: int, second_total: int
) -> float:
    first_rate = first_correct / first_total if first_total else 0.0
    second_rate = second_correct / second_total if second_total else 0.0
    return (first_rate + second_rate) / 2.0


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


def generate_oddball_soa(trials: int, *, seed: int = 17) -> tuple[float, ...]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    rng = random.Random(seed)
    return tuple(rng.uniform(1.2, 1.6) for _ in range(trials))


@dataclass(frozen=True, slots=True)
class StimulusEvent:
    monotonic_time: float
    wall_time: float
    paradigm: str
    phase: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)
    intent_time: float | None = None
    onset_hook_time: float | None = None
    hook_type: str = "software"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["payload"] = dict(self.payload)
        return result
