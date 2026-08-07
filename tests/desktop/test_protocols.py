from neuroscope_eeg.desktop.protocols import (
    PRESETS,
    StimulusEvent,
    balanced_accuracy,
    frame_locked_frequencies,
    generate_nback_trials,
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
    assert PRESETS["快速演示"].nback_trials == 30
    assert PRESETS["快速演示"].stroop_trials == 30
    assert PRESETS["快速演示"].oddball_trials == 100
    assert PRESETS["快速演示"].emotion_per_category == 3
    assert PRESETS["完整采集"].rest_duration_sec == 60
    assert PRESETS["完整采集"].rest_repetitions == 2
    assert PRESETS["完整采集"].assr_cycles == 10
    assert PRESETS["完整采集"].nback_trials == 120
    assert PRESETS["完整采集"].nback_targets == 40
    assert PRESETS["完整采集"].stroop_trials == 120
    assert PRESETS["完整采集"].oddball_trials == 300
    assert PRESETS["完整采集"].emotion_per_category == 15


def test_nback_sequence_has_exact_planned_targets_without_accidental_matches() -> None:
    for trials, targets in ((30, 8), (120, 40)):
        sequence = generate_nback_trials(trials, targets, seed=17)
        assert len(sequence) == trials
        assert sum(trial.is_target for trial in sequence) == targets
        assert all(trial.is_target == (trial.symbol == trial.two_back_symbol) for trial in sequence)
        assert all(not (left.is_target and right.is_target) for left, right in zip(sequence, sequence[1:]))
        assert sequence == generate_nback_trials(trials, targets, seed=17)


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
