"""A frame-acknowledged sequence: no elapsed-time catch-up across unseen screens."""
from dataclasses import dataclass, field

from neuroscope_eeg.protocol_config import AssessmentProtocol


@dataclass(frozen=True)
class Step:
    phase: str
    label: str
    duration: float | None = None
    body: str = ""
    payload: dict = field(default_factory=dict)


def protocol_steps(plan: AssessmentProtocol):
    plan.validate()
    steps = [Step("instructions", plan.paradigm + "实验说明", body=(
        "本次记录用于观察脑电信号与任务相关响应，不是能力测验。\n"
        "请坐姿稳定、身体放松，双手自然放在腿上，避免说话和大幅动作。\n"
        "需要眨眼时可以自然眨眼；试次间和组间休息时可适当调整。\n"
        "流程：任务指导 → 练习 → 睁眼与闭眼静息 → 正式实验。")),
        Step("task_instructions", "如何完成任务", body=(
            "先注视中央十字，再按箭头看向目标；目标常亮时完成定位。\n"
            "每次只有指定目标闪烁，请持续注视；其他三个目标保持暗态。\n"
            "四个频率从小到大循环；休息时可眨眼，下一次重新看中央十字。\n"
            "无需按键判断；不适时可按 Esc 停止。"
            if plan.single_target else
            "注视红框提示的方块；闪烁阶段八个方块同时闪烁，请始终注视该目标。\n八个频率从小到大循环；休息时可眨眼，无需按键判断。"
            if plan.eight_target else
            "按目标提示注视相应频率区域；四个目标同时闪烁。无需按键判断。"
            if plan.paradigm == 'SSVEP' else
            "注视中央十字；← 左手、→ 右手、↓ 双脚（双腿）、↑ 舌头，按此顺序循环。\n"
            "提示时做好准备，进入想象阶段后想象对应部位运动的感觉，不要实际运动。\n"
            "左／右手想象反复握拳、松开；双脚想象双脚同时上下活动；舌头想象在口内移动。\n"
            "保持手脚、舌头和下颌放松，不咬牙、不说话；休息提示出现后停止想象。"
            if plan.mi_collection else
            "注视中央十字；左箭头表示左手，右箭头表示右手，圆点表示静息。\n"
            "进入想象阶段后，想象对应手反复握拳、松开的感觉，手和手臂保持不动。\n"
            "静息条件只需放松，不进行运动想象。出现休息提示时停止想象。"))]

    def trials(count, practice, first=0, block=0):
        for i in range(count):
            formal = first + i
            payload = {"trial": formal if practice else plan.conditions * plan.practice_per_condition + formal,
                       "formal_trial_index": None if practice else formal,
                       "is_practice": practice, "block": block, "condition_index": formal % plan.conditions,
                       "segment": "practice" if practice else "formal"}
            if plan.mi_collection:
                payload.update(condition=plan.mi_labels[formal % plan.conditions],
                               condition_code=formal % plan.conditions + 1,
                               condition_order='cyclic_balanced', mi_mode=plan.mi_mode)
            for phase, duration in plan.phases:
                steps.append(Step(phase, "", duration, payload=payload))

    if plan.practice_per_condition:
        steps.append(Step("practice_ready", "先练习，再正式记录", body=(
            f"每个条件练习 {plan.practice_per_condition} 次，共 {plan.conditions * plan.practice_per_condition} 次。\n"
            "练习不计入正式任务指标，也不用于个体化校准。")))
        trials(plan.conditions * plan.practice_per_condition, True)
    steps.extend([
        Step("baseline_ready", "准备采集静息基线", body=(
            f"先睁眼注视中央十字 {plan.eyes_open_sec:g} 秒，再闭眼放松 {plan.eyes_closed_sec:g} 秒。\n"
            "看到闭眼提示后轻轻闭眼；屏幕显示剩余时间，不播放声音提示。\n"
            "请先与主试约定无声的睁眼提醒方式；主试在倒计时结束、出现“请睁眼”后提醒。\n"
            "本次范式独立采集基线，不复用上一范式的静息数据。")),
        Step("baseline_eyes_open", "睁眼静息", plan.eyes_open_sec),
        Step("baseline_close_prepare", "请轻轻闭眼", plan.close_prepare_sec,
             "闭眼并保持放松；收到与主试事先约定的无声提醒后再睁眼。"),
        Step("baseline_eyes_closed", "闭眼静息", plan.eyes_closed_sec,
             "请保持闭眼、身体放松。\n主试请观察倒计时，出现“请睁眼”后再按约定方式提醒。"),
        Step("baseline_open_recovery", "请睁眼", plan.open_recovery_sec, "轻轻睁眼，重新注视中央。"),
        Step("formal_ready", "准备正式实验", body=(
            f"共 {plan.total_trials} 个正式试次，每组最多 {plan.block_trials} 个。\n"
            f"组间至少休息 {plan.block_rest_sec:g} 秒，休息结束后按空格继续。\n"
            "任务过程中不需要按空格；Esc 可停止并保留已记录数据。")),
    ])
    for first in range(0, plan.total_trials, plan.block_trials):
        block = first // plan.block_trials + 1
        if first:
            steps.extend([Step("block_rest", "组间休息", plan.block_rest_sec, "可以放松、眨眼，调整坐姿。", {"block": block - 1}),
                          Step("block_ready", f"准备第 {block} 组", body="休息时间已满足；准备好后按空格继续。", payload={"block": block})])
        trials(min(plan.block_trials, plan.total_trials - first), False, first, block)
    steps.append(Step("protocol_complete", "本次实验已结束", body="感谢配合。按空格返回主控台查看保存与报告状态。"))
    return tuple(steps)


class GuidedFlow:
    def __init__(self, plan):
        self.plan = plan.validate()
        self.steps = protocol_steps(plan)
        self.index = 0
        self.presented_at = None

    @property
    def step(self):
        return self.steps[self.index]

    def acknowledge_frame(self, now):
        if self.presented_at is None:
            self.presented_at = now

    def ready(self, now):
        return (self.presented_at is not None and self.step.duration is not None
                and now - self.presented_at >= self.step.duration)

    def advance(self):
        if self.index + 1 >= len(self.steps):
            return False
        self.index += 1
        self.presented_at = None
        return True
