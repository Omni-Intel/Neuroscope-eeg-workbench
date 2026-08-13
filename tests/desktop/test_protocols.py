from neuroscope_eeg.desktop.protocols import (
    PRESETS,
    StimulusEvent,
    balanced_accuracy,
    frame_locked_frequencies,
    generate_nback_blocks,
    generate_nback_schedule,
    generate_nback_trials,
    nback_response_is_open,
    generate_oddball_sequence,
    generate_oddball_soa,
    generate_stroop_trials,
    signal_detection_metrics,
)


def test_160_hz_screen_uses_exact_frame_locked_frequencies() -> None:
    assert frame_locked_frequencies(160.0) == (8.0, 10.0, 16.0, 20.0)


def test_60_hz_screen_uses_representable_frequencies() -> None:
    assert frame_locked_frequencies(60.0) == (7.5, 10.0, 12.0, 15.0)


def test_stimulus_event_serializes_payload() -> None:
    event = StimulusEvent(1.0, 2.0, "SSVEP", "start", "SSVEP", {"frequency": 10.0})
    assert event.as_dict()["payload"] == {"frequency": 10.0}


def test_protocol_presets_have_expected_trial_counts() -> None:
    assert PRESETS["快速演示"].rest_duration_sec == 30
    assert PRESETS["快速演示"].rest_repetitions == 1
    assert PRESETS["快速演示"].assr_cycles == 3
    assert PRESETS["快速演示"].nback_blocks_per_level == 1
    assert PRESETS["快速演示"].nback_trials_per_block == 10
    assert PRESETS["快速演示"].nback_targets_per_block == 3
    assert PRESETS["快速演示"].nback_trials == 30
    assert PRESETS["快速演示"].stroop_trials == 30
    assert PRESETS["快速演示"].oddball_trials == 100
    assert PRESETS["快速演示"].emotion_per_category == 3
    assert PRESETS["完整采集"].rest_duration_sec == 60
    assert PRESETS["完整采集"].rest_repetitions == 2
    assert PRESETS["完整采集"].assr_cycles == 10
    assert PRESETS["完整采集"].nback_blocks_per_level == 4
    assert PRESETS["完整采集"].nback_trials_per_block == 40
    assert PRESETS["完整采集"].nback_targets_per_block == 13
    assert PRESETS["完整采集"].nback_trials == 480
    assert PRESETS["完整采集"].stroop_trials == 120
    assert PRESETS["完整采集"].oddball_trials == 300
    assert PRESETS["完整采集"].emotion_per_category == 15


def test_nback_sequences_have_exact_planned_targets_without_accidental_matches() -> None:
    for level in (0, 1, 2):
        sequence = generate_nback_trials(40, 13, nback_level=level, target_symbol="7", seed=17)
        assert len(sequence) == 40
        assert sum(trial.is_target for trial in sequence) == 13
        assert all(trial.nback_level == level for trial in sequence)
        assert all(trial.is_target == (trial.symbol == trial.comparison_symbol) for trial in sequence)
        assert all(not (left.is_target and right.is_target) for left, right in zip(sequence, sequence[1:]))
        assert sequence == generate_nback_trials(
            40, 13, nback_level=level, target_symbol="7", seed=17
        )


def test_nback_blocks_repeat_zero_one_two_four_times() -> None:
    blocks = generate_nback_blocks(4, 40, 13, seed=17)

    assert len(blocks) == 12
    assert [block.nback_level for block in blocks] == [0, 1, 2] * 4
    assert [block.block_index for block in blocks] == list(range(12))
    assert [block.load_block_index for block in blocks] == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert all(len(block.trials) == 40 for block in blocks)
    assert all(sum(trial.is_target for trial in block.trials) == 13 for block in blocks)
    assert all(block.target_symbol is not None for block in blocks if block.nback_level == 0)
    assert blocks == generate_nback_blocks(4, 40, 13, seed=17)


def test_nback_schedule_has_480_trials_and_planned_timing() -> None:
    schedule = generate_nback_schedule(PRESETS["完整采集"])
    formal_trials = [item for item in schedule if item.kind == "trial" and not item.is_practice]
    formal_rules = [item for item in schedule if item.kind == "rule" and not item.is_practice]
    rests = [item for item in schedule if item.kind == "rest"]

    assert len(formal_trials) == 480
    assert [item.formal_trial_index for item in formal_trials] == list(range(480))
    assert [item.nback_level for item in formal_rules] == [0, 1, 2] * 4
    assert all(item.duration_sec == 5.0 for item in formal_rules)
    assert len(rests) == 11
    assert all(item.duration_sec == 25.0 for item in rests)
    for index, item in enumerate(schedule[:-1]):
        if item.kind in {"context", "trial"}:
            assert item.duration_sec == 1.5
            assert schedule[index + 1].kind == "blank"
            assert schedule[index + 1].duration_sec == 0.5
    formal_context = [item for item in schedule if item.kind == "context" and not item.is_practice]
    assert sum(item.nback_level == 0 for item in formal_context) == 0
    assert sum(item.nback_level == 1 for item in formal_context) == 4
    assert sum(item.nback_level == 2 for item in formal_context) == 8


def test_stroop_sequence_is_balanced_and_uses_binary_congruency_keys() -> None:
    for total in (30, 120):
        trials = generate_stroop_trials(total, seed=17)
        congruent = [trial for trial in trials if trial.congruency == "congruent"]
        incongruent = [trial for trial in trials if trial.congruency == "incongruent"]
        assert len(congruent) == len(incongruent) == total // 2
        assert all(trial.word == trial.ink_color for trial in congruent)
        assert all(trial.word != trial.ink_color for trial in incongruent)
        for condition in (congruent, incongruent):
            counts = [sum(trial.ink_color == color for trial in condition) for color in ("红", "绿", "蓝", "黄")]
            assert max(counts) - min(counts) <= 1
        assert {trial.correct_key for trial in congruent} == {"J"}
        assert {trial.correct_key for trial in incongruent} == {"F"}
        assert trials == generate_stroop_trials(total, seed=17)


def test_oddball_presets_keep_eighty_twenty_ratio_without_adjacent_deviants() -> None:
    for total in (100, 300):
        sequence = generate_oddball_sequence(total, seed=17)
        assert sequence.count("deviant") == total // 5
        assert all(left != "deviant" or right != "deviant" for left, right in zip(sequence, sequence[1:]))


def test_oddball_soa_is_repeatable_and_within_planned_range() -> None:
    soa = generate_oddball_soa(310, seed=17)
    assert len(soa) == 310
    assert all(1.2 <= duration <= 1.6 for duration in soa)
    assert soa == generate_oddball_soa(310, seed=17)


def test_signal_detection_metrics_include_half_trial_corrected_d_prime() -> None:
    metrics = signal_detection_metrics(targets=8, hits=8, non_targets=22, false_alarms=0)
    assert metrics["hit_rate"] == 1.0
    assert metrics["false_alarm_rate"] == 0.0
    assert 3.0 < metrics["d_prime"] < 4.0


def test_balanced_accuracy_weights_conditions_equally() -> None:
    assert balanced_accuracy(first_correct=36, first_total=40, second_correct=40, second_total=80) == 0.7


def test_nback_response_window_remains_1500_ms() -> None:
    assert nback_response_is_open(0.0)
    assert nback_response_is_open(1499.999)
    assert not nback_response_is_open(1500.0)
