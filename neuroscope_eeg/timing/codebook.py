from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


CODEBOOK_VERSION = 1


@dataclass(frozen=True, slots=True)
class EventCodeDefinition:
    code: int
    symbol: str
    paradigm: str
    phase: str
    condition: str
    description_zh: str
    critical: bool = True
    dcp_command: str = "immediate_event"

    def as_dict(self) -> dict[str, Any]:
        return {"codebook_version": CODEBOOK_VERSION, **asdict(self)}


def _definition(
    code: int,
    symbol: str,
    description_zh: str,
    *,
    paradigm: str = "common",
    phase: str = "",
    condition: str = "",
) -> EventCodeDefinition:
    return EventCodeDefinition(code, symbol, paradigm, phase, condition, description_zh)


EVENT_CODES: tuple[EventCodeDefinition, ...] = (
    _definition(1, "MI_LEFT_HAND", "左手运动想象 cue", paradigm="motor_imagery", phase="cue", condition="left_hand"),
    _definition(2, "MI_RIGHT_HAND", "右手运动想象 cue", paradigm="motor_imagery", phase="cue", condition="right_hand"),
    _definition(3, "MI_BOTH_FEET", "双脚运动想象 cue", paradigm="motor_imagery", phase="cue", condition="both_feet"),
    _definition(4, "MI_TONGUE", "舌部运动想象 cue", paradigm="motor_imagery", phase="cue", condition="tongue"),
    _definition(10, "FIXATION", "公共注视开始", phase="fixation"),
    *tuple(
        _definition(
            10 + index,
            f"SSVEP_TARGET_{index}",
            f"SSVEP 目标 {index} 闪烁开始",
            paradigm="ssvep",
            phase="flicker",
            condition=f"target_{index}",
        )
        for index in range(1, 9)
    ),
    _definition(19, "SSVEP_FLICKER_OFFSET", "SSVEP 闪烁结束", paradigm="ssvep", phase="rest"),
    _definition(20, "REST", "公共休息开始", phase="rest"),
    _definition(21, "VISUAL_NONTARGET_ONSET", "视觉识别非目标出现", paradigm="visual_awareness", phase="stimulus", condition="non_target"),
    _definition(22, "VISUAL_TARGET_ONSET", "视觉识别目标出现", paradigm="visual_awareness", phase="stimulus", condition="target"),
    _definition(23, "VISUAL_STIMULUS_OFFSET", "视觉识别刺激结束", paradigm="visual_awareness", phase="stimulus_offset"),
    _definition(31, "ATTENTION_PROBLEM_ONSET", "注意力题目出现", paradigm="attention", phase="problem"),
    _definition(32, "ATTENTION_REST_ONSET", "注意力休息开始", paradigm="attention", phase="rest"),
    _definition(33, "ATTENTION_PROBLEM_OFFSET", "注意力题目结束", paradigm="attention", phase="problem_offset"),
    _definition(41, "EYES_OPEN_ONSET", "睁眼阶段开始", paradigm="resting_eyes", phase="eyes_open"),
    _definition(42, "EYES_CLOSED_ONSET", "闭眼阶段开始", paradigm="resting_eyes", phase="eyes_closed"),
    _definition(43, "EYES_TRANSITION", "睁闭眼过渡提示", paradigm="resting_eyes", phase="transition"),
    _definition(50, "NBACK_0_NONTARGET", "0-back 非目标出现", paradigm="working_memory_nback", phase="nback_trial", condition="non_target"),
    _definition(51, "NBACK_0_TARGET", "0-back 目标出现", paradigm="working_memory_nback", phase="nback_trial", condition="target"),
    _definition(52, "NBACK_1_NONTARGET", "1-back 非目标出现", paradigm="working_memory_nback", phase="nback_trial", condition="non_target"),
    _definition(53, "NBACK_1_TARGET", "1-back 目标出现", paradigm="working_memory_nback", phase="nback_trial", condition="target"),
    _definition(54, "NBACK_2_NONTARGET", "2-back 非目标出现", paradigm="working_memory_nback", phase="nback_trial", condition="non_target"),
    _definition(55, "NBACK_2_TARGET", "2-back 目标出现", paradigm="working_memory_nback", phase="nback_trial", condition="target"),
    _definition(56, "NBACK_STIMULUS_OFFSET", "N-back 数字结束", paradigm="working_memory_nback", phase="nback_blank"),
    _definition(61, "STROOP_CONGRUENT_ONSET", "Stroop 一致刺激出现", paradigm="stroop", phase="stroop_stimulus", condition="congruent"),
    _definition(62, "STROOP_INCONGRUENT_ONSET", "Stroop 不一致刺激出现", paradigm="stroop", phase="stroop_stimulus", condition="incongruent"),
    _definition(63, "STROOP_STIMULUS_OFFSET", "Stroop 刺激结束", paradigm="stroop", phase="stroop_blank"),
    _definition(71, "EMOTION_POSITIVE_ONSET", "正向情绪图片出现", paradigm="emotion_arousal", phase="emotion_image", condition="positive"),
    _definition(72, "EMOTION_NEGATIVE_ONSET", "负向情绪图片出现", paradigm="emotion_arousal", phase="emotion_image", condition="negative"),
    _definition(73, "EMOTION_NEUTRAL_ONSET", "中性情绪图片出现", paradigm="emotion_arousal", phase="emotion_image", condition="neutral"),
    _definition(74, "EMOTION_IMAGE_OFFSET", "情绪图片结束", paradigm="emotion_arousal", phase="emotion_trial_complete"),
    _definition(75, "EMOTION_BASELINE_ONSET", "情绪基线开始", paradigm="emotion_arousal", phase="emotion_baseline"),
    _definition(81, "ASSR_ONSET", "ASSR 声音开始", paradigm="auditory_assr", phase="stimulation"),
    _definition(82, "ASSR_OFFSET", "ASSR 声音结束", paradigm="auditory_assr", phase="audio_offset"),
    _definition(83, "ODDBALL_STANDARD_ONSET", "Oddball 标准音开始", paradigm="auditory_oddball", phase="standard"),
    _definition(84, "ODDBALL_DEVIANT_ONSET", "Oddball 偏差音开始", paradigm="auditory_oddball", phase="deviant"),
    _definition(85, "AUDITORY_STIMULUS_OFFSET", "Oddball 声音结束", paradigm="auditory_oddball", phase="audio_offset"),
    _definition(90, "BLOCK_START", "block 开始", phase="block_start"),
    _definition(91, "BLOCK_END", "block 结束", phase="block_end"),
    _definition(100, "EXPERIMENT_START", "实验开始", phase="start"),
    _definition(101, "EXPERIMENT_END", "实验正常结束", phase="stop"),
    _definition(110, "RESPONSE", "普通行为反应", phase="response"),
    _definition(111, "RESPONSE_CORRECT", "正确反应", phase="response", condition="correct"),
    _definition(112, "RESPONSE_INCORRECT", "错误反应", phase="response", condition="incorrect"),
    _definition(113, "OMISSION", "漏答", phase="omission"),
    _definition(114, "FALSE_ALARM", "误报", phase="response", condition="false_alarm"),
    _definition(120, "TRIGGER_PATH_CALIBRATION", "Trigger 通道自检", phase="calibration"),
    _definition(127, "ABORT", "中止或异常结束", phase="abort"),
)

_BY_SYMBOL = {definition.symbol: definition for definition in EVENT_CODES}


def definition_by_symbol(symbol: str) -> EventCodeDefinition:
    return _BY_SYMBOL[symbol]


def _paradigm_key(paradigm: str) -> str:
    return {
        "SSVEP": "ssvep",
        "运动想象": "motor_imagery",
        "视觉图像识别": "visual_awareness",
        "注意力": "attention",
        "静息睁眼/闭眼": "resting_eyes",
        "N-back 工作记忆": "working_memory_nback",
        "Stroop 色词冲突": "stroop",
        "情绪图片唤醒": "emotion_arousal",
        "听觉 ASSR": "auditory_assr",
        "听觉 Oddball": "auditory_oddball",
    }.get(paradigm, paradigm)


def event_code_for(
    paradigm: str,
    phase: str,
    payload: dict[str, Any],
    label: str = "",
) -> EventCodeDefinition | None:
    if phase == "start":
        return definition_by_symbol("EXPERIMENT_START")
    if phase == "stop":
        return definition_by_symbol(
            "EXPERIMENT_END" if payload.get("stop_reason", "completed") == "completed" else "ABORT"
        )
    if phase in {"abort", "escape", "manual_stop", "window_closed"}:
        return definition_by_symbol("ABORT")
    if phase.endswith("block_start") or phase == "block_start":
        return definition_by_symbol("BLOCK_START")
    if phase.endswith("block_end") or phase in {"block_end", "nback_block_rest"}:
        return definition_by_symbol("BLOCK_END")
    if phase == "omission":
        return definition_by_symbol("OMISSION")
    if phase == "response":
        if payload.get("is_correct") is True or payload.get("correct") is True:
            return definition_by_symbol("RESPONSE_CORRECT")
        if payload.get("target_present") is False and payload.get("actual_response"):
            return definition_by_symbol("FALSE_ALARM")
        if payload.get("is_correct") is False or payload.get("correct") is False:
            return definition_by_symbol("RESPONSE_INCORRECT")
        return definition_by_symbol("RESPONSE")

    key = _paradigm_key(paradigm)
    if key == "ssvep":
        if phase == "flicker":
            frequencies = tuple(payload.get("ssvep_frequencies", ()))
            target = payload.get("target_frequency")
            try:
                index = frequencies.index(target) + 1
            except ValueError:
                index = int(payload.get("target_index", 0)) + 1
            return definition_by_symbol(f"SSVEP_TARGET_{max(1, min(index, 8))}")
        if phase == "rest":
            return definition_by_symbol("SSVEP_FLICKER_OFFSET")
    elif key == "motor_imagery":
        if phase == "fixation":
            return definition_by_symbol("FIXATION")
        if phase == "rest" or label == "静息":
            return definition_by_symbol("REST")
        if phase == "cue":
            symbol = {
                "左手": "MI_LEFT_HAND",
                "右手": "MI_RIGHT_HAND",
                "双脚": "MI_BOTH_FEET",
                "舌": "MI_TONGUE",
            }.get(label)
            return definition_by_symbol(symbol) if symbol else None
    elif key == "visual_awareness":
        if phase == "stimulus":
            return definition_by_symbol(
                "VISUAL_TARGET_ONSET" if payload.get("target_present") else "VISUAL_NONTARGET_ONSET"
            )
        if phase == "stimulus_offset":
            return definition_by_symbol("VISUAL_STIMULUS_OFFSET")
    elif key == "attention":
        return {
            "problem": definition_by_symbol("ATTENTION_PROBLEM_ONSET"),
            "rest": definition_by_symbol("ATTENTION_REST_ONSET"),
            "problem_offset": definition_by_symbol("ATTENTION_PROBLEM_OFFSET"),
        }.get(phase)
    elif key == "resting_eyes":
        return {
            "eyes_open": definition_by_symbol("EYES_OPEN_ONSET"),
            "eyes_closed": definition_by_symbol("EYES_CLOSED_ONSET"),
            "transition": definition_by_symbol("EYES_TRANSITION"),
        }.get(phase)
    elif key == "working_memory_nback":
        if phase == "nback_trial":
            level = int(payload.get("nback_level", -1))
            suffix = "TARGET" if payload.get("is_target") else "NONTARGET"
            symbol = f"NBACK_{level}_{suffix}"
            return _BY_SYMBOL.get(symbol)
        if phase == "nback_blank":
            return definition_by_symbol("NBACK_STIMULUS_OFFSET")
    elif key == "stroop":
        if phase == "stroop_stimulus":
            symbol = (
                "STROOP_CONGRUENT_ONSET"
                if payload.get("congruency") == "congruent"
                else "STROOP_INCONGRUENT_ONSET"
            )
            return definition_by_symbol(symbol)
        if phase == "stroop_blank":
            return definition_by_symbol("STROOP_STIMULUS_OFFSET")
    elif key == "emotion_arousal":
        if phase == "emotion_image":
            symbol = {
                "positive": "EMOTION_POSITIVE_ONSET",
                "negative": "EMOTION_NEGATIVE_ONSET",
                "neutral": "EMOTION_NEUTRAL_ONSET",
            }.get(str(payload.get("valence", "")))
            return definition_by_symbol(symbol) if symbol else None
        return {
            "emotion_trial_complete": definition_by_symbol("EMOTION_IMAGE_OFFSET"),
            "emotion_baseline": definition_by_symbol("EMOTION_BASELINE_ONSET"),
        }.get(phase)
    elif key == "auditory_assr":
        if phase == "stimulation":
            return definition_by_symbol("ASSR_ONSET")
        if phase == "audio_offset":
            return definition_by_symbol("ASSR_OFFSET")
    elif key == "auditory_oddball":
        return {
            "standard": definition_by_symbol("ODDBALL_STANDARD_ONSET"),
            "deviant": definition_by_symbol("ODDBALL_DEVIANT_ONSET"),
            "audio_offset": definition_by_symbol("AUDITORY_STIMULUS_OFFSET"),
        }.get(phase)
    return None
