from __future__ import annotations

from neuroscope_eeg.timing.codebook import CODEBOOK_VERSION, EVENT_CODES, event_code_for


def test_codebook_v1_is_unique_and_preserves_confirmed_codes() -> None:
    assert CODEBOOK_VERSION == 1
    codes = [definition.code for definition in EVENT_CODES]
    assert len(codes) == len(set(codes))
    assert all(1 <= code <= 127 for code in codes)
    lookup = {definition.symbol: definition.code for definition in EVENT_CODES}
    assert lookup["MI_LEFT_HAND"] == 1
    assert lookup["MI_RIGHT_HAND"] == 2
    assert lookup["MI_BOTH_FEET"] == 3
    assert lookup["MI_TONGUE"] == 4
    assert lookup["FIXATION"] == 10
    assert lookup["REST"] == 20
    assert lookup["NBACK_0_NONTARGET"] == 50
    assert lookup["NBACK_0_TARGET"] == 51
    assert lookup["NBACK_1_NONTARGET"] == 52
    assert lookup["NBACK_1_TARGET"] == 53
    assert lookup["NBACK_2_NONTARGET"] == 54
    assert lookup["NBACK_2_TARGET"] == 55
    assert lookup["BLOCK_START"] == 90
    assert lookup["BLOCK_END"] == 91
    assert lookup["EXPERIMENT_START"] == 100
    assert lookup["EXPERIMENT_END"] == 101
    assert lookup["ABORT"] == 127


def test_event_mapper_covers_nback_visual_audio_and_responses() -> None:
    assert event_code_for("N-back 工作记忆", "nback_trial", {"nback_level": 2, "is_target": True}).code == 55
    assert event_code_for("N-back 工作记忆", "nback_trial", {"nback_level": 0, "is_target": False}).code == 50
    assert event_code_for("Stroop 色词冲突", "stroop_stimulus", {"congruency": "incongruent"}).code == 62
    assert event_code_for("情绪图片唤醒", "emotion_image", {"valence": "negative"}).code == 72
    assert event_code_for("听觉 Oddball", "standard", {}).code == 83
    assert event_code_for("听觉 Oddball", "deviant", {}).code == 84
    assert event_code_for("N-back 工作记忆", "response", {"is_correct": True}).code == 111
    assert event_code_for("N-back 工作记忆", "omission", {}).code == 113


def test_noncritical_metadata_event_has_no_hardware_code() -> None:
    assert event_code_for("N-back 工作记忆", "nback_rule", {"nback_level": 1}) is None


def test_nback_rest_closes_block_and_assr_offset_is_not_duplicated() -> None:
    assert event_code_for("N-back 工作记忆", "nback_block_rest", {}).symbol == "BLOCK_END"
    assert event_code_for("听觉 ASSR", "baseline", {"cycle": 1}) is None
    assert event_code_for("听觉 ASSR", "audio_offset", {}).symbol == "ASSR_OFFSET"
