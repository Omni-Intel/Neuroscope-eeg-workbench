from __future__ import annotations

from bisect import bisect_right
from itertools import accumulate
import math
import random
from statistics import median
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QKeyEvent, QPaintEvent, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from neuroscope_eeg.desktop.audio import AudioPlayer
from neuroscope_eeg.desktop.emotion_assets import EmotionImage, load_emotion_manifest, select_emotion_images
from neuroscope_eeg.desktop.protocols import (
    PRESETS,
    PROTOCOL_VERSION,
    STROOP_RESPONSE_KEYS,
    TIMING_STATUS,
    NBACK_LEVELS,
    NBackScheduleItem,
    ProtocolPreset,
    StimulusEvent,
    StroopTrial,
    balanced_accuracy,
    frame_locked_frequencies,
    generate_nback_schedule,
    generate_oddball_sequence,
    generate_oddball_soa,
    generate_stroop_trials,
    nback_response_is_open,
    signal_detection_metrics,
)


class StimulusWindow(QWidget):
    event_emitted = Signal(object)
    stopped = Signal()

    def __init__(self, audio_player=None) -> None:
        super().__init__()
        self.setWindowTitle("NeuroScope 刺激呈现")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.paradigm = "SSVEP"
        self.preset_label = "快速演示"
        self.preset: ProtocolPreset = PRESETS[self.preset_label]
        self.refresh_hz = 60.0
        self.ssvep_frequencies = frame_locked_frequencies(self.refresh_hz)
        self.started_at = 0.0
        self.frame_index = 0
        self._last_tick = 0.0
        self._last_phase = ""
        self._trial_index = -1
        self._rng = random.Random(17)
        self.current_symbol = "+"
        self.current_target = False
        self._responded_to_item = False
        self._last_item_at = 0.0
        self._math_problem = ""
        self._math_answer = 0
        self._typed_answer = ""
        self._last_problem_at = 0.0
        self._emotion_category = "中性"
        self._emotion_prompt = "平静地观察呼吸"
        self._emotion_images: tuple[EmotionImage, ...] = ()
        self._emotion_index = -1
        self._emotion_image: EmotionImage | None = None
        self._emotion_pixmap = QPixmap()
        self._emotion_phase = "warning"
        self._emotion_phase_started_at = 0.0
        self._emotion_warning_confirmed = False
        self._ssvep_target_index = 0
        self._audio_player = audio_player
        self._oddball_sequence = generate_oddball_sequence(1000)
        self._oddball_soa = generate_oddball_soa(1000)
        self._oddball_index = 0
        self._next_tone_at = 0.0
        self._false_alarms = 0
        self._current_started_at = 0.0
        self._current_payload: dict = {}
        self._response_times_ms: list[float] = []
        self._nback_items: tuple[NBackScheduleItem, ...] = ()
        self._nback_item_ends: tuple[float, ...] = ()
        self._nback_item_index = -1
        self._nback_condition_trials = {"target": 0, "non_target": 0}
        self._nback_condition_correct = {"target": 0, "non_target": 0}
        self._nback_condition_rts: dict[str, list[float]] = {"target": [], "non_target": []}
        self._nback_omissions = 0
        self._nback_load_condition_trials = self._new_nback_load_condition_counts()
        self._nback_load_condition_correct = self._new_nback_load_condition_counts()
        self._nback_load_condition_rts = self._new_nback_load_condition_rts()
        self._nback_load_false_alarms = {level: 0 for level in NBACK_LEVELS}
        self._nback_load_omissions = {level: 0 for level in NBACK_LEVELS}
        self._nback_block_condition_trials = {"target": 0, "non_target": 0}
        self._nback_block_condition_correct = {"target": 0, "non_target": 0}
        self._nback_block_condition_rts: dict[str, list[float]] = {"target": [], "non_target": []}
        self._nback_block_false_alarms = 0
        self._nback_block_omissions = 0
        self._nback_last_completed_block = -1
        self._stroop_practice: tuple[StroopTrial, ...] = ()
        self._stroop_formal: tuple[StroopTrial, ...] = ()
        self._stroop_item_index = -1
        self._stroop_condition_trials = {"congruent": 0, "incongruent": 0}
        self._stroop_condition_correct = {"congruent": 0, "incongruent": 0}
        self._stroop_condition_rts: dict[str, list[float]] = {"congruent": [], "incongruent": []}
        self._feedback_text = ""
        self._task_started_at = 0.0
        self.trials = 0
        self.targets = 0
        self.hits = 0
        self.responses = 0
        self.missed_frames = 0
        self.stop_reason = "completed"

    def start_protocol(self, paradigm: str, screen, preset_label: str = "快速演示") -> None:
        if paradigm in {"听觉 ASSR", "听觉 Oddball"} and self._audio_player is None:
            self._audio_player = AudioPlayer()
        self.paradigm = paradigm
        self.preset_label = preset_label
        self.preset = PRESETS[preset_label]
        self.refresh_hz = max(30.0, float(screen.refreshRate()))
        self.ssvep_frequencies = frame_locked_frequencies(self.refresh_hz)
        self.started_at = time.monotonic()
        self.frame_index = 0
        self._last_tick = self.started_at
        self._last_phase = ""
        self._trial_index = -1
        self._rng = random.Random(17)
        self._last_item_at = 0.0
        self._last_problem_at = 0.0
        self._ssvep_target_index = 0
        self._oddball_index = 0
        self._next_tone_at = self.started_at + 1.0
        self._false_alarms = 0
        self._current_started_at = 0.0
        self._current_payload = {}
        self._response_times_ms = []
        self._feedback_text = ""
        self._task_started_at = self.started_at
        self.stop_reason = "completed"
        self._prepare_protocol()
        self.current_target = False
        self._responded_to_item = False
        self.trials = self.targets = self.hits = self.responses = self.missed_frames = 0
        self.winId()
        if self.windowHandle() is not None:
            self.windowHandle().setScreen(screen)
        self.showNormal()
        self._place_on_screen(screen)
        interval = max(4, round(1000.0 / self.refresh_hz)) if paradigm == "SSVEP" else 16
        self.timer.start(interval)
        QTimer.singleShot(80, lambda: self._place_on_screen(screen) if self.timer.isActive() else None)
        self._emit(
            "start",
            paradigm,
            {
                "software_sync": True,
                "protocol_version": PROTOCOL_VERSION,
                "preset": self.preset_label,
                "seed": 17,
                "timing_status": TIMING_STATUS,
                "display_refresh_hz": self.refresh_hz,
                "ssvep_frequencies": self.ssvep_frequencies if paradigm == "SSVEP" else (),
            },
        )

    def _place_on_screen(self, screen) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.show()
        self.setGeometry(screen.geometry())
        self.raise_()
        self.activateWindow()
        if handle is not None:
            handle.requestActivate()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def stop_protocol(self, reason: str = "completed") -> None:
        if self._audio_player is not None:
            self._audio_player.stop()
        if not self.timer.isActive():
            self.hide()
            return
        self.stop_reason = reason
        final_payload = dict(self._current_payload)
        if self.paradigm == "情绪图片唤醒":
            final_payload.update(self._emotion_payload())
        final_payload.update(self.summary())
        self._emit("stop", self.paradigm, final_payload)
        self.timer.stop()
        self.hide()
        self.stopped.emit()

    def _prepare_protocol(self) -> None:
        if self.paradigm == "N-back 工作记忆":
            self._nback_items = generate_nback_schedule(self.preset)
            self._nback_item_ends = tuple(accumulate(item.duration_sec for item in self._nback_items))
            self._nback_item_index = -1
            self._nback_condition_trials = {"target": 0, "non_target": 0}
            self._nback_condition_correct = {"target": 0, "non_target": 0}
            self._nback_condition_rts = {"target": [], "non_target": []}
            self._nback_omissions = 0
            self._nback_load_condition_trials = self._new_nback_load_condition_counts()
            self._nback_load_condition_correct = self._new_nback_load_condition_counts()
            self._nback_load_condition_rts = self._new_nback_load_condition_rts()
            self._nback_load_false_alarms = {level: 0 for level in NBACK_LEVELS}
            self._nback_load_omissions = {level: 0 for level in NBACK_LEVELS}
            self._reset_nback_block_stats()
            self._nback_last_completed_block = -1
        elif self.paradigm == "Stroop 色词冲突":
            self._stroop_practice = generate_stroop_trials(12, seed=11)
            self._stroop_formal = generate_stroop_trials(self.preset.stroop_trials, seed=17)
            self._stroop_item_index = -1
            self._stroop_condition_trials = {"congruent": 0, "incongruent": 0}
            self._stroop_condition_correct = {"congruent": 0, "incongruent": 0}
            self._stroop_condition_rts = {"congruent": [], "incongruent": []}
        elif self.paradigm == "听觉 Oddball":
            practice = generate_oddball_sequence(10, seed=11)
            formal = generate_oddball_sequence(self.preset.oddball_trials, seed=17)
            self._oddball_sequence = practice + formal
            self._oddball_soa = generate_oddball_soa(len(self._oddball_sequence), seed=17)
        elif self.paradigm == "情绪图片唤醒":
            manifest = load_emotion_manifest()
            self._emotion_images = select_emotion_images(
                manifest, per_category=self.preset.emotion_per_category, seed=17
            )
            self._emotion_index = -1
            self._emotion_image = None
            self._emotion_pixmap = QPixmap()
            self._emotion_phase = "warning"
            self._emotion_phase_started_at = self.started_at
            self._emotion_warning_confirmed = False

    @staticmethod
    def _new_nback_load_condition_counts() -> dict[int, dict[str, int]]:
        return {level: {"target": 0, "non_target": 0} for level in NBACK_LEVELS}

    @staticmethod
    def _new_nback_load_condition_rts() -> dict[int, dict[str, list[float]]]:
        return {level: {"target": [], "non_target": []} for level in NBACK_LEVELS}

    def _reset_nback_block_stats(self) -> None:
        self._nback_block_condition_trials = {"target": 0, "non_target": 0}
        self._nback_block_condition_correct = {"target": 0, "non_target": 0}
        self._nback_block_condition_rts = {"target": [], "non_target": []}
        self._nback_block_false_alarms = 0
        self._nback_block_omissions = 0

    def summary(self) -> dict[str, float | int | None]:
        accuracy = (
            self.hits / self.targets
            if self.targets
            and self.paradigm in {"视觉图像识别", "注意力", "N-back 工作记忆", "听觉 Oddball"}
            else None
        )
        result: dict[str, float | int | None] = {
            "trials": self.trials,
            "targets": self.targets,
            "hits": self.hits,
            "responses": self.responses,
            "behavior_hit_rate": accuracy,
            "false_alarms": self._false_alarms,
            "missed_frames_estimate": self.missed_frames,
            "median_response_time_ms": median(self._response_times_ms) if self._response_times_ms else None,
        }
        if self.paradigm in {"N-back 工作记忆", "听觉 Oddball"}:
            non_targets = max(0, self.trials - self.targets)
            result.update(
                signal_detection_metrics(
                    targets=self.targets,
                    hits=self.hits,
                    non_targets=non_targets,
                    false_alarms=self._false_alarms,
                )
            )
        if self.paradigm == "N-back 工作记忆":
            result.update(self._nback_summary())
        if self.paradigm == "听觉 Oddball":
            result["misses"] = max(0, self.targets - self.hits)
            result["miss_rate"] = (
                max(0, self.targets - self.hits) / self.targets if self.targets else 0.0
            )
        if self.paradigm == "Stroop 色词冲突":
            result.update(self._stroop_summary())
        return result

    def _nback_summary(self) -> dict[str, float | int | None]:
        target_trials = self._nback_condition_trials["target"]
        non_target_trials = self._nback_condition_trials["non_target"]
        target_correct = self._nback_condition_correct["target"]
        non_target_correct = self._nback_condition_correct["non_target"]
        target_rts = self._nback_condition_rts["target"]
        non_target_rts = self._nback_condition_rts["non_target"]
        total_correct = target_correct + non_target_correct
        result: dict[str, float | int | None] = {
            "behavior_accuracy": total_correct / self.trials if self.trials else 0.0,
            "balanced_accuracy": balanced_accuracy(
                first_correct=target_correct,
                first_total=target_trials,
                second_correct=non_target_correct,
                second_total=non_target_trials,
            ),
            "match_accuracy": target_correct / target_trials if target_trials else 0.0,
            "nonmatch_accuracy": non_target_correct / non_target_trials if non_target_trials else 0.0,
            "match_median_response_time_ms": median(target_rts) if target_rts else None,
            "nonmatch_median_response_time_ms": median(non_target_rts) if non_target_rts else None,
            "omissions": self._nback_omissions,
        }
        for level in NBACK_LEVELS:
            level_trials = self._nback_load_condition_trials[level]
            level_correct = self._nback_load_condition_correct[level]
            level_rts = self._nback_load_condition_rts[level]
            target_trials = level_trials["target"]
            non_target_trials = level_trials["non_target"]
            target_correct = level_correct["target"]
            non_target_correct = level_correct["non_target"]
            trial_count = target_trials + non_target_trials
            prefix = f"nback_{level}_"
            result.update(
                {
                    f"{prefix}trials": trial_count,
                    f"{prefix}behavior_accuracy": (
                        (target_correct + non_target_correct) / trial_count if trial_count else 0.0
                    ),
                    f"{prefix}balanced_accuracy": balanced_accuracy(
                        first_correct=target_correct,
                        first_total=target_trials,
                        second_correct=non_target_correct,
                        second_total=non_target_trials,
                    ),
                    f"{prefix}match_accuracy": (
                        target_correct / target_trials if target_trials else 0.0
                    ),
                    f"{prefix}nonmatch_accuracy": (
                        non_target_correct / non_target_trials if non_target_trials else 0.0
                    ),
                    f"{prefix}match_median_response_time_ms": (
                        median(level_rts["target"]) if level_rts["target"] else None
                    ),
                    f"{prefix}nonmatch_median_response_time_ms": (
                        median(level_rts["non_target"]) if level_rts["non_target"] else None
                    ),
                    f"{prefix}omissions": self._nback_load_omissions[level],
                    **{
                        f"{prefix}{key}": value
                        for key, value in signal_detection_metrics(
                            targets=target_trials,
                            hits=target_correct,
                            non_targets=non_target_trials,
                            false_alarms=self._nback_load_false_alarms[level],
                        ).items()
                    },
                }
            )
        return result

    def _stroop_summary(self) -> dict[str, float | int | None]:
        total_correct = sum(self._stroop_condition_correct.values())
        congruent_rts = self._stroop_condition_rts["congruent"]
        incongruent_rts = self._stroop_condition_rts["incongruent"]
        congruent_trials = self._stroop_condition_trials["congruent"]
        incongruent_trials = self._stroop_condition_trials["incongruent"]
        congruent_accuracy = (
            self._stroop_condition_correct["congruent"] / congruent_trials if congruent_trials else 0.0
        )
        incongruent_accuracy = (
            self._stroop_condition_correct["incongruent"] / incongruent_trials if incongruent_trials else 0.0
        )
        return {
            "behavior_accuracy": total_correct / self.trials if self.trials else 0.0,
            "balanced_accuracy": (congruent_accuracy + incongruent_accuracy) / 2.0,
            "congruent_accuracy": congruent_accuracy,
            "incongruent_accuracy": incongruent_accuracy,
            "stroop_accuracy_cost": congruent_accuracy - incongruent_accuracy,
            "congruent_median_response_time_ms": median(congruent_rts) if congruent_rts else None,
            "incongruent_median_response_time_ms": median(incongruent_rts) if incongruent_rts else None,
            "stroop_interference_ms": median(incongruent_rts) - median(congruent_rts)
            if congruent_rts and incongruent_rts
            else 0.0,
        }

    def _tick(self) -> None:
        now = time.monotonic()
        expected = 1.0 / self.refresh_hz if self.paradigm == "SSVEP" else 0.016
        gap = now - self._last_tick
        self._last_tick = now
        elapsed = now - self.started_at
        if self.paradigm == "SSVEP":
            expected_frame = int(elapsed * self.refresh_hz)
            if expected_frame > self.frame_index + 1:
                self.missed_frames += expected_frame - self.frame_index - 1
            self.frame_index = expected_frame
        else:
            if gap > expected * 1.8:
                self.missed_frames += max(1, round(gap / expected) - 1)
            self.frame_index += 1
        if self.paradigm == "SSVEP":
            self._update_ssvep(elapsed)
        elif self.paradigm == "运动想象":
            self._update_motor_imagery(elapsed)
        elif self.paradigm == "视觉图像识别":
            self._update_rsvp(now)
        elif self.paradigm == "注意力":
            self._update_attention(elapsed, now)
        elif self.paradigm == "听觉 ASSR":
            self._update_assr(elapsed)
        elif self.paradigm == "听觉 Oddball":
            self._update_oddball(now)
        elif self.paradigm == "静息睁眼/闭眼":
            self._update_resting(elapsed)
        elif self.paradigm == "N-back 工作记忆":
            self._update_nback(elapsed, now)
        elif self.paradigm == "Stroop 色词冲突":
            self._update_stroop(elapsed, now)
        elif self.paradigm == "情绪图片唤醒":
            self._update_emotion_images(now)
        else:
            self._update_emotion(elapsed)
        self.update()

    def _update_ssvep(self, elapsed: float) -> None:
        trial_duration = 9.0
        trial = int(elapsed // trial_duration)
        within = elapsed % trial_duration
        self._ssvep_target_index = trial % len(self.ssvep_frequencies)
        target = self.ssvep_frequencies[self._ssvep_target_index]
        if trial != self._trial_index:
            self._trial_index = trial
            self.trials += 1
            self.targets += 1
        payload = {"trial": trial, "target_frequency": target, "ssvep_frequencies": self.ssvep_frequencies}
        if within < 2.0:
            self._set_phase("cue", f"注视 {target:g} Hz", payload)
        elif within < 7.0:
            self._set_phase("flicker", f"目标 {target:g} Hz", payload)
        else:
            self._set_phase("rest", "休息", payload)

    def _update_motor_imagery(self, elapsed: float) -> None:
        classes = ("左手", "右手", "静息")
        trial_duration = 9.0
        trial = int(elapsed // trial_duration)
        within = elapsed % trial_duration
        label = classes[trial % len(classes)]
        if within < 2.0:
            phase = "fixation"
        elif within < 3.0:
            phase = "cue"
        elif within < 7.0:
            phase = "imagery"
        else:
            phase = "rest"
        if trial != self._trial_index:
            self._trial_index = trial
            self.trials += 1
        self._set_phase(phase, label, {"trial": trial})

    def _update_rsvp(self, now: float) -> None:
        if now - self._last_item_at < 0.25:
            return
        self._last_item_at = now
        self.current_target = self._rng.random() < 0.2
        self._responded_to_item = False
        if self.current_target:
            self.current_symbol = "★"
            self.targets += 1
        else:
            self.current_symbol = self._rng.choice(tuple("ABCDEFGH23456789") + ("●", "▲", "■"))
        self.trials += 1
        self._emit(
            "stimulus",
            self.current_symbol,
            {"trial": self.trials, "target_present": self.current_target, "image_category": self._symbol_category()},
        )

    def _update_attention(self, elapsed: float, now: float) -> None:
        cycle = elapsed % 38.0
        if cycle < 8.0:
            self._set_phase("rest", "放松并注视中央")
            return
        self._set_phase("mental_math", "连续心算")
        if now - self._last_problem_at >= 5.0 or not self._math_problem:
            self._last_problem_at = now
            left = self._rng.randint(12, 49)
            right = self._rng.randint(3, 19)
            operation = self._rng.choice(("+", "-"))
            self._math_answer = left + right if operation == "+" else left - right
            self._math_problem = f"{left} {operation} {right} = ?"
            self._typed_answer = ""
            self.trials += 1
            self.targets += 1
            self._emit("problem", self._math_problem, {"answer": self._math_answer, "trial": self.trials})

    def _update_emotion(self, elapsed: float) -> None:
        prompts = (
            ("正向", "想象一次成功完成重要目标的经历", QColor("#14532d")),
            ("负向", "想象一次计划受阻、令人失望的经历", QColor("#7f1d1d")),
            ("中性", "想象整理桌面物品的过程", QColor("#334155")),
        )
        trial = int(elapsed // 8.0)
        category, prompt, _color = prompts[trial % len(prompts)]
        self._emotion_category = category
        self._emotion_prompt = prompt
        if trial != self._trial_index:
            self._trial_index = trial
            self.trials += 1
            self._emit("emotion", category, {"prompt": prompt, "trial": trial})
        self._set_phase("emotion_imagery", category)

    def _update_resting(self, elapsed: float) -> None:
        duration = float(self.preset.rest_duration_sec)
        if elapsed < 3.0:
            self._set_phase("countdown", f"{max(1, 3 - int(elapsed))}", {"eye_state": "准备"})
            return
        offset = elapsed - 3.0
        stage_count = self.preset.rest_repetitions * 2
        for stage_index in range(stage_count):
            eye_state = "睁眼" if stage_index % 2 == 0 else "闭眼"
            phase = "eyes_open" if eye_state == "睁眼" else "eyes_closed"
            label = "睁眼注视" if eye_state == "睁眼" else "闭眼放松"
            if offset < duration:
                self.trials = max(self.trials, stage_index + 1)
                self._set_phase(
                    phase,
                    label,
                    {
                        "eye_state": eye_state,
                        "planned_duration_s": duration,
                        "formal_trial_index": stage_index,
                        "repetition": stage_index // 2 + 1,
                    },
                )
                return
            offset -= duration
            if stage_index < stage_count - 1:
                next_state = "闭眼" if eye_state == "睁眼" else "睁眼"
                if offset < 10.0:
                    self._set_phase(
                        "transition",
                        f"即将{next_state}",
                        {"eye_state": "过渡", "planned_duration_s": 10.0},
                    )
                    return
                offset -= 10.0
        self.stop_protocol()

    def _update_nback(self, elapsed: float, now: float) -> None:
        if elapsed < 10.0:
            self._set_phase(
                "nback_baseline",
                "静息基线",
                {"is_practice": True, "planned_duration_s": 10.0, "formal_trial_index": -1},
            )
            return
        schedule_elapsed = elapsed - 10.0
        item_index = bisect_right(self._nback_item_ends, schedule_elapsed)
        if item_index >= len(self._nback_items):
            self._finalize_nback_trial()
            if self._nback_items:
                self._finish_nback_block(self._nback_items[-1])
            self.stop_protocol()
            return
        item_started_at = 0.0 if item_index == 0 else self._nback_item_ends[item_index - 1]
        item_elapsed = schedule_elapsed - item_started_at
        if item_index != self._nback_item_index:
            self._finalize_nback_trial()
            self._nback_item_index = item_index
            item = self._nback_items[item_index]
            self.current_symbol = item.label
            self.current_target = bool(item.kind == "trial" and item.trial and item.trial.is_target)
            self._responded_to_item = False
            self._current_started_at = now - item_elapsed
            self._feedback_text = ""
            self._current_payload = self._nback_item_payload(item)
            if item.kind == "rule" and not item.is_practice:
                self._reset_nback_block_stats()
                self._emit("nback_block_start", item.label, self._current_payload)
            elif item.kind == "rest":
                self._finish_nback_block(item)
            elif item.kind == "trial" and item.trial is not None:
                trial = item.trial
                condition = "target" if trial.is_target else "non_target"
                if not item.is_practice:
                    self.trials += 1
                    self.targets += int(trial.is_target)
                    self._nback_condition_trials[condition] += 1
                    self._nback_load_condition_trials[item.nback_level][condition] += 1
                    self._nback_block_condition_trials[condition] += 1
                self._current_payload.update(
                    {
                        "trial_index": trial.trial_index,
                        "symbol": trial.symbol,
                        "comparison_symbol": trial.comparison_symbol,
                        "is_target": trial.is_target,
                        "target_present": trial.is_target,
                        "condition": condition,
                        "correct_response": "J" if trial.is_target else "F",
                    }
                )
                self._emit("nback_trial", trial.symbol, self._current_payload)
        item = self._nback_items[item_index]
        if item.kind == "rule":
            self._set_phase("nback_rule", item.label, self._current_payload)
        elif item.kind == "context":
            self._set_phase("nback_context", item.label, self._current_payload)
        elif item.kind == "trial" and item.trial is not None:
            self._set_phase("nback_stimulus", item.trial.symbol, self._current_payload)
        elif item.kind == "blank":
            self._set_phase("nback_blank", "", self._current_payload)
        else:
            self._current_payload["remaining_sec"] = max(
                0, math.ceil(item.duration_sec - item_elapsed)
            )
            self._set_phase("nback_block_rest", "休息", self._current_payload)

    @staticmethod
    def _nback_item_payload(item: NBackScheduleItem) -> dict:
        return {
            "is_practice": item.is_practice,
            "nback_level": item.nback_level,
            "block_index": item.block_index,
            "load_block_index": item.load_block_index,
            "formal_trial_index": item.formal_trial_index,
            "target_symbol": item.target_symbol,
            "sequence_seed": item.sequence_seed,
            "planned_duration_s": item.duration_sec,
            "condition": item.kind,
        }

    def _finish_nback_block(self, item: NBackScheduleItem) -> None:
        if item.block_index < 0 or item.block_index <= self._nback_last_completed_block:
            return
        self._nback_last_completed_block = item.block_index
        self._emit(
            "nback_block_end",
            f"{item.nback_level}-back",
            {
                **self._nback_item_payload(item),
                "planned_formal_duration_s": self.preset.nback_trials_per_block * 2.0,
                **self._nback_block_summary(),
            },
        )

    def _nback_block_summary(self) -> dict[str, float | int | None]:
        target_trials = self._nback_block_condition_trials["target"]
        non_target_trials = self._nback_block_condition_trials["non_target"]
        target_correct = self._nback_block_condition_correct["target"]
        non_target_correct = self._nback_block_condition_correct["non_target"]
        trial_count = target_trials + non_target_trials
        return {
            "block_trials": trial_count,
            "block_behavior_accuracy": (
                (target_correct + non_target_correct) / trial_count if trial_count else 0.0
            ),
            "block_balanced_accuracy": balanced_accuracy(
                first_correct=target_correct,
                first_total=target_trials,
                second_correct=non_target_correct,
                second_total=non_target_trials,
            ),
            "block_match_accuracy": target_correct / target_trials if target_trials else 0.0,
            "block_nonmatch_accuracy": (
                non_target_correct / non_target_trials if non_target_trials else 0.0
            ),
            "block_match_median_response_time_ms": (
                median(self._nback_block_condition_rts["target"])
                if self._nback_block_condition_rts["target"]
                else None
            ),
            "block_nonmatch_median_response_time_ms": (
                median(self._nback_block_condition_rts["non_target"])
                if self._nback_block_condition_rts["non_target"]
                else None
            ),
            "block_false_alarms": self._nback_block_false_alarms,
            "block_omissions": self._nback_block_omissions,
            **{
                f"block_{key}": value
                for key, value in signal_detection_metrics(
                    targets=target_trials,
                    hits=target_correct,
                    non_targets=non_target_trials,
                    false_alarms=self._nback_block_false_alarms,
                ).items()
            },
        }

    def _finalize_nback_trial(self) -> None:
        if self._responded_to_item or "is_target" not in self._current_payload:
            return
        self._responded_to_item = True
        practice = bool(self._current_payload.get("is_practice", False))
        if practice:
            self._feedback_text = "未作答"
        else:
            self._nback_omissions += 1
            level = int(self._current_payload["nback_level"])
            self._nback_load_omissions[level] += 1
            self._nback_block_omissions += 1
        self._emit("omission", "未作答", {**self._current_payload, "is_correct": False})

    def _update_stroop(self, elapsed: float, now: float) -> None:
        practice_duration = len(self._stroop_practice) * 1.9
        if elapsed < practice_duration:
            practice = True
            trial_index = int(elapsed // 1.9)
            within = elapsed % 1.9
            trial = self._stroop_practice[trial_index]
        elif elapsed < practice_duration + 2.0:
            self.current_symbol = "正式开始"
            self._set_phase("formal_ready", "正式试次即将开始", {"is_practice": False})
            return
        else:
            practice = False
            formal_elapsed = elapsed - practice_duration - 2.0
            trial_index = int(formal_elapsed // 1.5)
            within = formal_elapsed % 1.5
            if trial_index >= len(self._stroop_formal):
                self._finalize_stroop_trial()
                self.stop_protocol()
                return
            trial = self._stroop_formal[trial_index]
        global_index = trial_index if practice else len(self._stroop_practice) + trial_index
        if global_index != self._stroop_item_index:
            self._finalize_stroop_trial()
            self._start_stroop_trial(trial, practice, now)
            self._stroop_item_index = global_index
        if within < 0.3:
            self._set_phase("stroop_fixation", "+", self._current_payload)
        elif within < 1.1:
            if not self._last_phase.startswith("stroop_stimulus"):
                self._current_started_at = now
            self._set_phase("stroop_stimulus", trial.word, self._current_payload)
        elif within < 1.5:
            self._set_phase("stroop_blank", "", self._current_payload)
        else:
            self._finalize_stroop_trial()
            self._set_phase("stroop_feedback", self._feedback_text, self._current_payload)

    def _start_stroop_trial(self, trial: StroopTrial, practice: bool, now: float) -> None:
        self.current_symbol = trial.word
        self._responded_to_item = False
        self._current_started_at = now + 0.3
        self._feedback_text = ""
        if not practice:
            self.trials += 1
            self._stroop_condition_trials[trial.congruency] += 1
        self._current_payload = {
            "trial_index": trial.trial_index,
            "formal_trial_index": trial.trial_index if not practice else -1,
            "is_practice": practice,
            "word_meaning": trial.word,
            "ink_color": trial.ink_color,
            "congruency": trial.congruency,
            "condition": trial.congruency,
            "correct_response": trial.correct_key,
        }

    def _finalize_stroop_trial(self) -> None:
        if self._responded_to_item or "congruency" not in self._current_payload:
            return
        self._responded_to_item = True
        practice = bool(self._current_payload.get("is_practice", False))
        if practice:
            self._feedback_text = "未作答"
        self._emit("omission", "未作答", {**self._current_payload, "is_correct": False})

    def _update_emotion_images(self, now: float) -> None:
        if self._emotion_phase == "warning":
            self._set_phase("emotion_warning", "内容提示｜按 Enter 继续")
            return
        elapsed = now - self._emotion_phase_started_at
        if self._emotion_phase == "baseline":
            if elapsed >= 20.0:
                self._start_next_emotion_trial(now)
            else:
                self._set_phase("emotion_baseline", "中性注视基线", {"planned_duration_s": 20.0})
            return
        if self._emotion_phase == "fixation" and elapsed >= 1.0:
            self._emotion_phase = "image"
            self._emotion_phase_started_at = now
            self._emit("emotion_image", self._emotion_image.fine_category_zh, self._emotion_payload())
        elif self._emotion_phase == "image" and elapsed >= 6.0:
            self._emotion_phase = "blank"
            self._emotion_phase_started_at = now
            self._emit("emotion_trial_complete", "图片呈现完成", self._emotion_payload())
        elif self._emotion_phase == "blank" and elapsed >= 1.0:
            completed = self._emotion_index + 1
            if len(self._emotion_images) == 105 and completed in (35, 70):
                self._emotion_phase = "break"
                self._emotion_phase_started_at = now
                self._emit("emotion_break", f"已完成 {completed}/105", {"completed_trials": completed})
            else:
                self._start_next_emotion_trial(now)
        elif self._emotion_phase == "debrief" and elapsed >= 5.0:
            self.stop_protocol()

    def _start_next_emotion_trial(self, now: float) -> None:
        self._emotion_index += 1
        if self._emotion_index >= len(self._emotion_images):
            self._emotion_phase = "debrief"
            self._emotion_phase_started_at = now
            self._emit("emotion_debrief", "任务结束，请休息并确认状态", self._emotion_payload())
            return
        self._emotion_image = self._emotion_images[self._emotion_index]
        self._emotion_pixmap = QPixmap(str(self._emotion_image.path))
        if self._emotion_pixmap.isNull():
            raise ValueError(f"无法加载情绪图片：{self._emotion_image.path}")
        self._emotion_phase = "fixation"
        self._emotion_phase_started_at = now
        self.trials += 1
        self._emit("emotion_fixation", "+", self._emotion_payload())

    def _emotion_payload(self) -> dict:
        if self._emotion_image is None:
            return {}
        return {
            "trial_index": self._emotion_index,
            "formal_trial_index": self._emotion_index,
            "image_id": self._emotion_image.image_id,
            "image_file": self._emotion_image.file,
            "fine_category": self._emotion_image.fine_category,
            "fine_category_zh": self._emotion_image.fine_category_zh,
            "valence": self._emotion_image.valence,
            "was_skipped": False,
            "condition": self._emotion_image.fine_category,
        }

    def _update_assr(self, elapsed: float) -> None:
        cycle = int(elapsed // 30.0)
        if cycle >= self.preset.assr_cycles:
            self.stop_protocol()
            return
        within = elapsed % 30.0
        if within < 10.0:
            key = "baseline:安静基线"
            if key != self._last_phase and self._audio_player is not None:
                self._audio_player.stop()
            self._set_phase("baseline", "安静基线", {"cycle": cycle, "target_frequency": 40.0})
            return
        key = "stimulation:40 Hz 调幅音"
        if key != self._last_phase:
            if self._audio_player is not None:
                self._audio_player.play_tone(1000.0, 20.0, modulation_hz=40.0)
            self.trials += 1
        self._set_phase(
            "stimulation",
            "40 Hz 调幅音",
            {
                "cycle": cycle,
                "target_frequency": 40.0,
                "carrier_frequency": 1000.0,
                "modulation_depth": 1.0,
            },
        )

    def _update_oddball(self, now: float) -> None:
        if self._oddball_index >= len(self._oddball_sequence):
            self.stop_protocol()
            return
        if now < self._next_tone_at:
            if self._oddball_index == 0:
                self._set_phase("ready", "准备聆听")
            return
        sequence_index = self._oddball_index
        practice = sequence_index < 10
        kind = self._oddball_sequence[sequence_index]
        self._oddball_index += 1
        self._feedback_text = ""
        frequency = 1500.0 if kind == "deviant" else 1000.0
        self.current_target = kind == "deviant"
        self._responded_to_item = False
        if not practice:
            self.trials += 1
            self.targets += int(self.current_target)
        if self._audio_player is not None:
            self._audio_player.play_tone(frequency, 0.1)
        soa = self._oddball_soa[sequence_index]
        self._current_started_at = now
        self._current_payload = {
            "trial_index": sequence_index,
            "formal_trial_index": self.trials - 1 if not practice else -1,
            "is_practice": practice,
            "tone_type": kind,
            "frequency_hz": frequency,
            "tone_frequency": frequency,
            "soa_ms": soa * 1000.0,
            "condition": kind,
            "correct_response": "J" if self.current_target else "None",
            "target_present": self.current_target,
        }
        self._emit(
            kind,
            "偏差音" if self.current_target else "标准音",
            self._current_payload,
        )
        self._last_phase = f"{kind}:{sequence_index}"
        self._next_tone_at = now + soa

    def _set_phase(self, phase: str, label: str, payload: dict | None = None) -> None:
        key = f"{phase}:{label}"
        if key == self._last_phase:
            return
        self._last_phase = key
        self._emit(phase, label, payload or {})

    def _emit(self, phase: str, label: str, payload: dict | None = None) -> None:
        event_payload = {
            "protocol_version": PROTOCOL_VERSION,
            "preset": self.preset_label,
            "seed": 17,
            "timing_status": TIMING_STATUS,
            "is_practice": False,
            **self.summary(),
            **dict(payload or {}),
        }
        self.event_emitted.emit(
            StimulusEvent(
                monotonic_time=time.monotonic(),
                wall_time=time.time(),
                paradigm=self.paradigm,
                phase=phase,
                label=label,
                payload=event_payload,
            )
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.paradigm == "SSVEP":
            self._paint_ssvep(painter)
        elif self.paradigm == "运动想象":
            self._paint_motor_imagery(painter)
        elif self.paradigm == "视觉图像识别":
            self._paint_center(painter, self.current_symbol, "看到 ★ 时按空格", QColor("#020617"))
        elif self.paradigm == "注意力":
            text = self._math_problem if self._last_phase.startswith("mental_math") else "+"
            hint = f"输入答案后回车：{self._typed_answer}" if text != "+" else "放松并注视中央"
            self._paint_center(painter, text, hint, QColor("#020617"))
        elif self.paradigm == "听觉 ASSR":
            phase = self._last_phase.partition(":")[0]
            text = "40 Hz" if phase == "stimulation" else "+"
            hint = "正在播放调幅音｜保持放松" if phase == "stimulation" else "安静基线｜即将播放声音"
            self._paint_center(painter, text, hint, QColor("#0f172a"))
        elif self.paradigm == "听觉 Oddball":
            hit_rate = self.hits / self.targets if self.targets else 0.0
            stage = "练习" if self._oddball_index <= 10 else self.preset_label
            hint = f"听到高音按 J｜{stage}｜正式试次 {self.trials}/{self.preset.oddball_trials}｜命中 {hit_rate:.0%}"
            if self._feedback_text:
                hint += f"｜{self._feedback_text}"
            self._paint_center(painter, "+", hint, QColor("#0f172a"))
        elif self.paradigm == "静息睁眼/闭眼":
            phase = self._last_phase.partition(":")[0]
            if phase == "eyes_closed":
                text, hint = "请闭眼", f"保持放松｜{self.preset.rest_duration_sec} 秒阶段"
            elif phase == "transition":
                text = self._last_phase.partition(":")[2] or "状态切换"
                hint = "10 秒过渡｜调整坐姿并准备切换眼睛状态"
            elif phase == "eyes_open":
                text, hint = "+", f"睁眼注视中央｜{self.preset.rest_duration_sec} 秒阶段"
            else:
                text, hint = self._last_phase.partition(":")[2] or "准备", "减少眨眼和身体活动"
            self._paint_center(painter, text, hint, QColor("#0f172a"))
        elif self.paradigm == "N-back 工作记忆":
            self._paint_nback(painter)
        elif self.paradigm == "Stroop 色词冲突":
            self._paint_stroop(painter)
        elif self.paradigm == "情绪图片唤醒":
            self._paint_emotion_images(painter)
        else:
            colors = {"正向": QColor("#14532d"), "负向": QColor("#7f1d1d"), "中性": QColor("#334155")}
            self._paint_center(painter, self._emotion_prompt, f"当前：{self._emotion_category}｜按 1–9 评价感受强度", colors[self._emotion_category])
        painter.end()

    def _paint_ssvep(self, painter: QPainter) -> None:
        width, height = self.width(), self.height()
        phase = self._last_phase.partition(":")[0]
        if phase == "rest":
            self._paint_center(painter, "+", "休息", QColor("#020617"))
            return
        for index, frequency in enumerate(self.ssvep_frequencies):
            row, column = divmod(index, 2)
            rect = self.rect().adjusted(column * width // 2, row * height // 2, -(1 - column) * width // 2, -(1 - row) * height // 2)
            frames_per_cycle = max(2, round(self.refresh_hz / frequency))
            angle = 2.0 * math.pi * (self.frame_index % frames_per_cycle) / frames_per_cycle
            brightness = 230 if phase == "flicker" and math.sin(angle) >= 0 else 25
            painter.fillRect(rect, QColor(brightness, brightness, brightness))
            painter.setPen(QColor("#020617") if brightness > 100 else QColor("#f8fafc"))
            painter.setFont(QFont("Microsoft YaHei UI", 28, QFont.Weight.Bold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{frequency:g} Hz")
            if phase == "cue" and index == self._ssvep_target_index:
                painter.setPen(QColor("#ef4444"))
                painter.drawRect(rect.adjusted(12, 12, -12, -12))

    def _paint_motor_imagery(self, painter: QPainter) -> None:
        phase, _, label = self._last_phase.partition(":")
        if phase == "fixation":
            text, hint = "+", "准备"
        elif phase == "cue":
            text = {"左手": "←", "右手": "→", "静息": "●"}.get(label, "●")
            hint = f"提示：{label}"
        elif phase == "imagery":
            text, hint = label, "持续进行运动想象，不要实际运动"
        else:
            text, hint = "+", "休息"
        self._paint_center(painter, text, hint, QColor("#020617"))

    def _paint_center(self, painter: QPainter, text: str, hint: str, background: QColor) -> None:
        painter.fillRect(self.rect(), background)
        painter.setPen(QColor("#f8fafc"))
        painter.setFont(QFont("Microsoft YaHei UI", 38, QFont.Weight.Bold))
        painter.drawText(self.rect().adjusted(80, 80, -80, -160), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
        painter.setPen(QColor("#cbd5e1"))
        painter.setFont(QFont("Microsoft YaHei UI", 18))
        painter.drawText(self.rect().adjusted(80, self.height() - 150, -80, -50), Qt.AlignmentFlag.AlignCenter, hint)

    def _paint_nback(self, painter: QPainter) -> None:
        phase = self._last_phase.partition(":")[0]
        if phase == "nback_baseline":
            self._paint_center(painter, "+", "静息基线｜保持注视", QColor("#0f172a"))
            return
        if phase == "nback_rule":
            stage = "练习" if self._current_payload.get("is_practice") else "正式"
            block_index = int(self._current_payload.get("block_index", -1))
            progress = "" if block_index < 0 else f"｜block {block_index + 1}/{self.preset.nback_blocks_per_level * 3}"
            self._paint_center(
                painter,
                self.current_symbol,
                f"目标按 J，非目标按 F｜{stage}{progress}",
                QColor("#0f172a"),
            )
            return
        if phase == "nback_block_rest":
            remaining = int(self._current_payload.get("remaining_sec", 25))
            self._paint_center(
                painter,
                f"休息 {remaining} 秒",
                "请放松，倒计时结束后自动进入下一 block",
                QColor("#0f172a"),
            )
            return
        if phase == "nback_blank":
            self._paint_center(
                painter,
                "",
                f"{int(self._current_payload.get('nback_level', 0))}-back｜目标按 J，非目标按 F",
                QColor("#0f172a"),
            )
            return

        painter.fillRect(self.rect(), QColor("#0f172a"))
        digit_font = QFont("Microsoft YaHei UI", 96, QFont.Weight.Bold)
        digit_font.setPixelSize(max(96, min(180, int(min(self.width(), self.height()) * 0.22))))
        painter.setFont(digit_font)
        painter.setPen(QColor("#f8fafc"))
        digit_rect = self.rect().adjusted(80, 40, -80, -self.height() // 4)
        painter.drawText(digit_rect, Qt.AlignmentFlag.AlignCenter, self.current_symbol)

        if self._current_payload.get("is_practice") and self._feedback_text:
            painter.setFont(QFont("Microsoft YaHei UI", 24, QFont.Weight.Bold))
            painter.setPen(QColor("#22c55e") if self._feedback_text == "正确" else QColor("#f87171"))
            feedback_rect = self.rect().adjusted(80, self.height() // 2 + 50, -80, -self.height() // 4)
            painter.drawText(feedback_rect, Qt.AlignmentFlag.AlignCenter, self._feedback_text)

        painter.setFont(QFont("Microsoft YaHei UI", 18))
        painter.setPen(QColor("#cbd5e1"))
        stage = "练习" if self._current_payload.get("is_practice") else "正式"
        level = int(self._current_payload.get("nback_level", 0))
        block_index = int(self._current_payload.get("block_index", -1))
        block_text = "" if block_index < 0 else f"｜block {block_index + 1}/{self.preset.nback_blocks_per_level * 3}"
        hint = (
            f"{level}-back｜目标按 J，非目标按 F｜{stage}{block_text}"
            f"｜正式试次 {self.trials}/{self.preset.nback_trials}"
        )
        painter.drawText(
            self.rect().adjusted(80, self.height() - 150, -80, -50),
            Qt.AlignmentFlag.AlignCenter,
            hint,
        )

    def _paint_stroop(self, painter: QPainter) -> None:
        phase = self._last_phase.partition(":")[0]
        if phase in {"stroop_fixation", "stroop_blank", "stroop_feedback"}:
            text = "+" if phase == "stroop_fixation" else ""
            hint = f"一致按 J，不一致按 F｜正式试次 {self.trials}/{self.preset.stroop_trials}"
            if phase == "stroop_feedback" and self._feedback_text:
                hint += f"｜{self._feedback_text}"
            self._paint_center(
                painter,
                text,
                hint,
                QColor("#0f172a"),
            )
            return
        if phase == "formal_ready":
            self._paint_center(painter, "正式开始", "文字与字体颜色一致按 J，不一致按 F", QColor("#0f172a"))
            return
        color_map = {"红": QColor("#ef4444"), "绿": QColor("#22c55e"), "蓝": QColor("#3b82f6"), "黄": QColor("#facc15")}
        painter.fillRect(self.rect(), QColor("#0f172a"))
        painter.setPen(color_map.get(str(self._current_payload.get("ink_color", "红")), QColor("#f8fafc")))
        painter.setFont(QFont("Microsoft YaHei UI", 52, QFont.Weight.Bold))
        painter.drawText(self.rect().adjusted(80, 80, -80, -160), Qt.AlignmentFlag.AlignCenter, self.current_symbol)
        painter.setPen(QColor("#cbd5e1"))
        painter.setFont(QFont("Microsoft YaHei UI", 18))
        hint = f"一致按 J，不一致按 F｜正式试次 {self.trials}/{self.preset.stroop_trials}"
        if phase == "stroop_feedback" and self._feedback_text:
            hint += f"｜{self._feedback_text}"
        painter.drawText(self.rect().adjusted(80, self.height() - 150, -80, -50), Qt.AlignmentFlag.AlignCenter, hint)

    def _paint_emotion_images(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor("#0f172a"))
        if self._emotion_phase == "warning":
            self._paint_center(
                painter,
                "内容提示",
                "图片可能包含恐惧、厌恶或悲伤内容。可随时按 Esc 退出，按 S 跳过当前图片。按 Enter 继续。",
                QColor("#451a03"),
            )
            return
        if self._emotion_phase == "baseline":
            self._paint_center(painter, "+", "20 秒中性注视基线｜保持放松", QColor("#0f172a"))
            return
        if self._emotion_phase == "fixation":
            self._paint_center(
                painter,
                "+",
                f"图片 {self.trials}/{len(self._emotion_images)}｜S 可跳过｜Esc 可退出",
                QColor("#0f172a"),
            )
            return
        if self._emotion_phase == "image" and not self._emotion_pixmap.isNull():
            available = self.rect().adjusted(80, 60, -80, -120)
            scaled = self._emotion_pixmap.scaled(
                available.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            x = available.x() + (available.width() - scaled.width()) // 2
            y = available.y() + (available.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.setPen(QColor("#cbd5e1"))
            painter.setFont(QFont("Microsoft YaHei UI", 16))
            painter.drawText(
                self.rect().adjusted(80, self.height() - 90, -80, -30),
                Qt.AlignmentFlag.AlignCenter,
                f"图片 {self.trials}/{len(self._emotion_images)}｜S 跳过｜Esc 退出",
            )
            return
        if self._emotion_phase == "break":
            completed = self._emotion_index + 1
            self._paint_center(painter, "休息", f"已完成 {completed}/105｜准备好后按 Enter 继续", QColor("#0f172a"))
            return
        if self._emotion_phase == "debrief":
            self._paint_center(painter, "任务结束", "请休息并确认当前状态｜窗口将自动关闭", QColor("#14532d"))
            return
        self._paint_center(painter, "", "准备下一张图片", QColor("#0f172a"))

    def _symbol_category(self) -> str:
        if self.current_symbol.isalpha():
            return "letter"
        if self.current_symbol.isdigit():
            return "number"
        return "shape"

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.stop_protocol("escape")
            return
        if self.paradigm == "视觉图像识别" and event.key() == Qt.Key.Key_Space:
            if self._responded_to_item:
                return
            self._responded_to_item = True
            self.responses += 1
            if self.current_target:
                self.hits += 1
            self._emit(
                "response",
                "seen",
                {
                    "target_present": self.current_target,
                    "seen_reported": True,
                    "hit": self.current_target,
                    "image_category": self._symbol_category(),
                },
            )
            return
        if self.paradigm == "注意力":
            if event.text().isdigit():
                self._typed_answer += event.text()
            elif event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
                self._typed_answer = self._typed_answer[:-1]
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._typed_answer:
                correct = int(self._typed_answer) == self._math_answer
                self.responses += 1
                self.hits += int(correct)
                self._emit("response", self._typed_answer, {"correct": correct, "answer": self._math_answer})
                self._last_problem_at = 0.0
                self._math_problem = ""
                self._typed_answer = ""
        elif self.paradigm == "N-back 工作记忆" and event.text().upper() in {"J", "F"}:
            self._handle_nback_response(event.text().upper())
        elif self.paradigm == "Stroop 色词冲突" and event.text().upper() in set(STROOP_RESPONSE_KEYS.values()):
            self._handle_stroop_response(event.text().upper())
        elif self.paradigm == "听觉 Oddball" and event.text().upper() == "J":
            if self._responded_to_item or self._oddball_index == 0:
                return
            self._responded_to_item = True
            practice = bool(self._current_payload.get("is_practice", False))
            response_time_ms = max(0.0, (time.monotonic() - self._current_started_at) * 1000.0)
            if not practice:
                self.responses += 1
                if self.current_target:
                    self.hits += 1
                    self._response_times_ms.append(response_time_ms)
                else:
                    self._false_alarms += 1
            else:
                self._feedback_text = "正确" if self.current_target else "这次是标准音"
            self._emit(
                "response",
                "命中" if self.current_target else "误报",
                {
                    **self._current_payload,
                    "actual_response": "J",
                    "is_correct": self.current_target,
                    "response_time_ms": response_time_ms,
                },
            )
        elif self.paradigm == "情绪图片唤醒":
            self._handle_emotion_key(event)
        elif self.paradigm == "情绪分类" and event.text() in tuple("123456789"):
            self.responses += 1
            self._emit("rating", event.text(), {"category": self._emotion_category})
        self.update()

    def _handle_nback_response(self, key: str) -> None:
        if self._responded_to_item or "is_target" not in self._current_payload:
            return
        response_time_ms = max(0.0, (time.monotonic() - self._current_started_at) * 1000.0)
        if not nback_response_is_open(response_time_ms):
            return
        self._responded_to_item = True
        practice = bool(self._current_payload.get("is_practice", False))
        correct = key == self._current_payload.get("correct_response")
        condition = str(self._current_payload["condition"])
        if not practice:
            self.responses += 1
            if self.current_target and key == "J":
                self.hits += 1
            if not self.current_target and key == "J":
                self._false_alarms += 1
                self._nback_load_false_alarms[int(self._current_payload["nback_level"])] += 1
                self._nback_block_false_alarms += 1
            if correct:
                self._nback_condition_correct[condition] += 1
                self._nback_condition_rts[condition].append(response_time_ms)
                level = int(self._current_payload["nback_level"])
                self._nback_load_condition_correct[level][condition] += 1
                self._nback_load_condition_rts[level][condition].append(response_time_ms)
                self._nback_block_condition_correct[condition] += 1
                self._nback_block_condition_rts[condition].append(response_time_ms)
                self._response_times_ms.append(response_time_ms)
        else:
            self._feedback_text = "正确" if correct else f"正确键：{self._current_payload['correct_response']}"
        self._emit(
            "response",
            "正确" if correct else "错误",
            {
                **self._current_payload,
                "actual_response": key,
                "is_correct": correct,
                "response_time_ms": response_time_ms,
            },
        )

    def _handle_stroop_response(self, key: str) -> None:
        if self._responded_to_item or not self._last_phase.startswith(("stroop_stimulus", "stroop_blank")):
            return
        now = time.monotonic()
        if now < self._current_started_at:
            return
        self._responded_to_item = True
        response_time_ms = (now - self._current_started_at) * 1000.0
        correct = key == self._current_payload.get("correct_response")
        practice = bool(self._current_payload.get("is_practice", False))
        condition = str(self._current_payload["congruency"])
        if not practice:
            self.responses += 1
            self.hits += int(correct)
            if correct:
                self._response_times_ms.append(response_time_ms)
                self._stroop_condition_correct[condition] += 1
                self._stroop_condition_rts[condition].append(response_time_ms)
        else:
            self._feedback_text = "正确" if correct else f"正确键：{self._current_payload['correct_response']}"
        self._emit(
            "response",
            "正确" if correct else "错误",
            {
                **self._current_payload,
                "actual_response": key,
                "is_correct": correct,
                "response_time_ms": response_time_ms,
            },
        )

    def _handle_emotion_key(self, event: QKeyEvent) -> None:
        now = time.monotonic()
        if self._emotion_phase == "warning" and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._emotion_warning_confirmed = True
            self._emotion_phase = "baseline"
            self._emotion_phase_started_at = now
            self._emit("emotion_baseline", "中性注视基线", {"planned_duration_s": 20.0})
            return
        if self._emotion_phase == "break" and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._start_next_emotion_trial(now)
            return
        if event.text().upper() == "S" and self._emotion_phase in {"fixation", "image"}:
            payload = {**self._emotion_payload(), "was_skipped": True}
            self._emotion_phase = "blank"
            self._emotion_phase_started_at = now
            self._emit("emotion_skip", "已跳过当前图片", payload)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.stop_protocol("window_closed")
        event.accept()
