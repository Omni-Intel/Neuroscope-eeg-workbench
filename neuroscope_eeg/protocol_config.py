"""Versioned acquisition plan shared by presentation and offline assessment (no Qt)."""
import math
from dataclasses import asdict, dataclass, fields, replace

SSVEP_FIELDS = {'ssvep_mode', 'prep_sec', 'screen_diagonal_in', 'target_size_cm', 'viewing_distance_cm'}


@dataclass(frozen=True)
class AssessmentProtocol:
    paradigm: str
    total_trials: int = 80
    block_trials: int = 40
    practice_per_condition: int = 1
    cue_sec: float = 2
    task_sec: float = 5
    rest_sec: float = 2
    fixation_sec: float = 2
    eyes_open_sec: float = 60
    eyes_closed_sec: float = 60
    close_prepare_sec: float = 10
    open_recovery_sec: float = 10
    block_rest_sec: float = 60
    prep_sec: float = 1
    screen_diagonal_in: float = 0
    target_size_cm: float = 6
    viewing_distance_cm: float = 0
    ssvep_mode: str = 'sequential_eight_v5'
    mi_mode: str = 'four_class_collection_v4'

    @classmethod
    def defaults(cls, paradigm):
        if paradigm == "运动想象":
            return cls(paradigm, total_trials=120, block_trials=40,
                       practice_per_condition=2, cue_sec=1, task_sec=4)
        if paradigm != "SSVEP":
            raise ValueError("该范式不使用 SSVEP / 运动想象协议设置")
        return cls(paradigm, fixation_sec=1.5, cue_sec=1, rest_sec=4, target_size_cm=3)

    @property
    def single_target(self):
        return self.paradigm == 'SSVEP' and self.ssvep_mode == 'single_target_v2'

    @property
    def eight_target(self):
        return self.paradigm == 'SSVEP' and self.ssvep_mode in {'simultaneous_eight_v3', 'sequential_eight_v5'}

    @property
    def sequential_eight(self):
        return self.paradigm == 'SSVEP' and self.ssvep_mode == 'sequential_eight_v5'

    @property
    def stimulus_mode(self):
        return 'sequential_eight' if self.sequential_eight else 'simultaneous_eight' if self.eight_target else 'single_target' if self.single_target else 'simultaneous_quadrants'

    @property
    def mi_collection(self):
        return self.paradigm == '运动想象' and self.mi_mode == 'four_class_collection_v4'

    @property
    def mi_labels(self):
        return ('左手', '右手', '双脚', '舌头') if self.mi_collection else ('左手', '右手', '静息')

    @property
    def conditions(self):
        return (8 if self.eight_target else 4) if self.paradigm == "SSVEP" else len(self.mi_labels)

    @property
    def phases(self):
        if self.single_target or self.eight_target:
            return [('fixation', self.fixation_sec), ('cue', self.cue_sec), ('prep', self.prep_sec),
                    ('flicker', self.task_sec), ('rest', self.rest_sec)]
        return (([("fixation", self.fixation_sec)] if self.paradigm == "运动想象" else [])
                + [("cue", self.cue_sec),
                   ("flicker" if self.paradigm == "SSVEP" else "imagery", self.task_sec),
                   ("rest", self.rest_sec)])

    @property
    def minimum_duration_sec(self):
        return (sum(duration for _, duration in self.phases)
                * (self.total_trials + self.conditions * self.practice_per_condition)
                + self.eyes_open_sec + self.eyes_closed_sec + self.close_prepare_sec + self.open_recovery_sec
                + (math.ceil(self.total_trials / self.block_trials) - 1) * self.block_rest_sec)

    def validate(self):
        if self.paradigm not in {"SSVEP", "运动想象"}:
            raise ValueError("未知的评估范式")
        if self.ssvep_mode not in {'single_target_v2', 'simultaneous_quadrants_v1', 'simultaneous_eight_v3', 'sequential_eight_v5'}:
            raise ValueError('未知 SSVEP 刺激模式')
        if self.mi_mode not in {'four_class_collection_v4', 'left_right_rest_v1'}:
            raise ValueError('未知运动想象协议模式')
        for name in ("total_trials", "block_trials", "practice_per_condition"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("试次数必须是整数")  # noqa: TRY004 - public configuration validation uses ValueError
        for name in ("total_trials", "block_trials"):
            value = getattr(self, name)
            if not self.conditions <= value <= 4000 or value % self.conditions:
                raise ValueError(f"总试次和每组试次须为 {self.conditions} 的正整数倍，各条件等量")
        if not 0 <= self.practice_per_condition <= 20:
            raise ValueError("每条件练习次数范围为 0–20")
        limits = {"cue_sec": (.5, 30), "task_sec": (3, 60), "rest_sec": (.5, 60),
                  "fixation_sec": (1.5, 30), "eyes_open_sec": (5, 600), "eyes_closed_sec": (5, 600),
                  "close_prepare_sec": (3, 60), "open_recovery_sec": (3, 60), "block_rest_sec": (5, 600)}
        for name, (lo, hi) in limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{name} 的时长须在 {lo}–{hi} 秒之间")
        for name, (lo, hi) in {'prep_sec': (.5, 30), 'screen_diagonal_in': (0, 100),
                               'target_size_cm': (2, 15), 'viewing_distance_cm': (0, 300)}.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'{name} 须在 {lo}–{hi} 之间；屏幕尺寸与观看距离的 0 表示未测量')
        return self

    def to_dict(self):
        data = asdict(self)
        if not (self.single_target or self.eight_target):
            data = {k:v for k,v in data.items() if k not in SSVEP_FIELDS}
        if not self.mi_collection:
            data.pop('mi_mode')
        version = ('guided-assessment-v4' if self.mi_collection else 'guided-assessment-v5' if self.sequential_eight else 'guided-assessment-v3' if self.eight_target
                   else 'guided-assessment-v2' if self.single_target else 'guided-assessment-v1')
        return {"version": version, **data,
                "condition_order": "ascending_frequency_cyclic" if self.single_target or self.eight_target else "cyclic_balanced", "minimum_duration_sec": self.minimum_duration_sec,
                "duration_excludes_space_waits": True}

    @classmethod
    def from_dict(cls, data):
        if data.get("version") not in {"guided-assessment-v1", "guided-assessment-v2", "guided-assessment-v3", "guided-assessment-v4", "guided-assessment-v5"}:
            raise ValueError("不支持的实验协议版本")
        names = {f.name for f in fields(cls)}
        unknown = set(data) - names - {"version", "condition_order", "minimum_duration_sec", "duration_excludes_space_waits"}
        if unknown:
            raise ValueError("未知实验协议字段：" + ", ".join(sorted(unknown)))
        required = names - {'mi_mode'}
        if data['version'] in {'guided-assessment-v1', 'guided-assessment-v4'}:
            required -= SSVEP_FIELDS
        if data['version'] == 'guided-assessment-v4':
            required.add('mi_mode')
        if not required <= data.keys():
            raise ValueError("实验协议字段不完整")
        values = {k: data[k] for k in names if k in data}
        if data['version'] != 'guided-assessment-v4' and data.get('paradigm') == '运动想象':
            values['mi_mode'] = 'left_right_rest_v1'
        if data['version'] == 'guided-assessment-v4':
            if data.get('paradigm') != '运动想象' or data.get('mi_mode') != 'four_class_collection_v4' or data.get('condition_order') != 'cyclic_balanced':
                raise ValueError('运动想象四条件采集协议与固定循环顺序须一致')
        elif data['version'] == 'guided-assessment-v1':
            values['ssvep_mode'] = 'simultaneous_quadrants_v1'
        elif data.get('ssvep_mode') != {'guided-assessment-v2':'single_target_v2', 'guided-assessment-v3':'simultaneous_eight_v3', 'guided-assessment-v5':'sequential_eight_v5'}[data['version']] or data.get('paradigm') != 'SSVEP' or data.get('condition_order') != 'ascending_frequency_cyclic':
            raise ValueError('SSVEP 协议版本、刺激模式与频率升序循环须一致')
        return cls(**values).validate()

    def for_new_run(self):
        """Upgrade saved UI preferences only; never reinterpret an old recording."""
        if self.paradigm == '运动想象' and not self.mi_collection:
            return replace(self, mi_mode='four_class_collection_v4', ssvep_mode='sequential_eight_v5',
                           total_trials=min(4000, self.total_trials//3*4), block_trials=min(4000, self.block_trials//3*4))
        if self.paradigm == 'SSVEP' and not self.eight_target:
            legacy_v1 = self.ssvep_mode == 'simultaneous_quadrants_v1'
            return replace(self, ssvep_mode='sequential_eight_v5', fixation_sec=1.5 if legacy_v1 else self.fixation_sec,
                           total_trials=math.ceil(self.total_trials/8)*8, block_trials=math.ceil(self.block_trials/8)*8,
                           cue_sec=1 if legacy_v1 and self.cue_sec == 2 else self.cue_sec,
                           rest_sec=4 if legacy_v1 and self.rest_sec == 2 else self.rest_sec)
        return self

    def analysis_windows(self):
        return {"ssvep_window_relative_flicker_sec": [.5, self.task_sec - .5],
                "mi_baseline_relative_fixation_sec": [.2, self.fixation_sec - .2],
                "mi_task_relative_imagery_sec": [.5, self.task_sec - .5]}
