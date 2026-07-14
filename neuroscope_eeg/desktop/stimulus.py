from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QKeyEvent, QPaintEvent, QPainter
from PySide6.QtWidgets import QWidget

from neuroscope_eeg.desktop.protocols import StimulusEvent, frame_locked_frequencies


class StimulusWindow(QWidget):
    event_emitted = Signal(object)
    stopped = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NeuroScope 刺激呈现")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.paradigm = "SSVEP"
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
        self._ssvep_target_index = 0
        self.trials = 0
        self.targets = 0
        self.hits = 0
        self.responses = 0
        self.missed_frames = 0

    def start_protocol(self, paradigm: str, screen) -> None:
        self.paradigm = paradigm
        self.refresh_hz = max(30.0, float(screen.refreshRate()))
        self.ssvep_frequencies = frame_locked_frequencies(self.refresh_hz)
        self.started_at = time.monotonic()
        self.frame_index = 0
        self._last_tick = self.started_at
        self._last_phase = ""
        self._trial_index = -1
        self._last_item_at = 0.0
        self._last_problem_at = 0.0
        self._ssvep_target_index = 0
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

    def stop_protocol(self) -> None:
        if not self.timer.isActive():
            self.hide()
            return
        self._emit("stop", self.paradigm, self.summary())
        self.timer.stop()
        self.hide()
        self.stopped.emit()

    def summary(self) -> dict[str, float | int | None]:
        accuracy = self.hits / self.targets if self.targets and self.paradigm in {"视觉图像识别", "注意力"} else None
        return {
            "trials": self.trials,
            "targets": self.targets,
            "hits": self.hits,
            "responses": self.responses,
            "behavior_hit_rate": accuracy,
            "missed_frames_estimate": self.missed_frames,
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

    def _set_phase(self, phase: str, label: str, payload: dict | None = None) -> None:
        key = f"{phase}:{label}"
        if key == self._last_phase:
            return
        self._last_phase = key
        self._emit(phase, label, payload or {})

    def _emit(self, phase: str, label: str, payload: dict | None = None) -> None:
        self.event_emitted.emit(
            StimulusEvent(
                monotonic_time=time.monotonic(),
                wall_time=time.time(),
                paradigm=self.paradigm,
                phase=phase,
                label=label,
                payload=dict(payload or {}),
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

    def _symbol_category(self) -> str:
        if self.current_symbol.isalpha():
            return "letter"
        if self.current_symbol.isdigit():
            return "number"
        return "shape"

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.stop_protocol()
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
        elif self.paradigm == "情绪分类" and event.text() in tuple("123456789"):
            self.responses += 1
            self._emit("rating", event.text(), {"category": self._emotion_category})
        self.update()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.stop_protocol()
        event.accept()
