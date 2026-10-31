"""Guided screens layered around the existing fullscreen task renderers."""
import math

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont


class GuidedPresentation:
    def _enter_guided_step(self, previous=None):
        flow = self._guided
        step = flow.step
        if previous is not None:
            if previous.phase in {"baseline_eyes_open", "baseline_eyes_closed"}:
                self._emit(previous.phase + "_end", previous.label + "结束", {"segment": "baseline"})
            if previous.phase == "rest" and "trial" in previous.payload:
                self._emit("trial_complete", "试次完成", {**self._current_payload})
        payload = {"guided_step": flow.index, "segment": "baseline" if step.phase.startswith("baseline_") else "instruction",
                   "planned_duration_s": step.duration, **step.payload}
        label = step.label
        if "trial" in payload:
            if self.paradigm == "SSVEP":
                self._ssvep_target_index = payload["condition_index"]
                target = self.ssvep_frequencies[self._ssvep_target_index]
                payload.update(target_frequency=target, ssvep_frequencies=self.ssvep_frequencies)
                if flow.plan.single_target or flow.plan.eight_target:
                    from neuroscope_eeg.desktop.ssvep_presentation import POSITIONS
                    if flow.plan.single_target:
                        from neuroscope_eeg.desktop.ssvep_legacy import POSITIONS
                    payload.update(stimulus_mode=flow.plan.stimulus_mode, target_position=POSITIONS[self._ssvep_target_index],
                                   condition_order='ascending_frequency_cyclic')
                    if step.phase == 'flicker':
                        self._ssvep_flicker_frame = self.frame_index
                label = f"目标 {target:g} Hz" if step.phase != "rest" else "休息"
            else:
                label = flow.plan.mi_labels[payload["condition_index"]]
                payload["condition"] = label
            if payload["trial"] != self._trial_index:
                self._trial_index = payload["trial"]
                self.trials += 1
                if self.paradigm == "SSVEP":
                    self.targets += 1
        self._current_payload = payload
        self._last_phase = f"{step.phase}:{label}"
        self._emit(step.phase, label, payload)
        self.update()

    def _advance_guided(self):
        previous = self._guided.step
        if self._guided.advance():
            self._enter_guided_step(previous)

    def _tick_guided(self, now):
        if self._guided.ready(now):
            self._advance_guided()

    def _ack_guided_frame(self, now, pending):
        if self._guided is None or not self.timer.isActive():
            return
        for event in pending:
            if event.phase == "trial_complete" and not event.payload.get("is_practice"):
                self._completed_formal.add(event.payload["formal_trial_index"])
        if not any(e.payload.get("guided_step") == self._guided.index and e.phase == self._guided.step.phase for e in pending):
            return
        self._guided.acknowledge_frame(now)

    def _guided_space(self, event):
        if event.isAutoRepeat() or self._space_down:
            return
        self._space_down = True
        flow = self._guided
        if flow is None or flow.presented_at is None or self._presentation_time() - flow.presented_at < .25:
            return
        if self._guided_ended:
            self.hide()
        elif flow.step.duration is None and self.timer.isActive():
            self._emit("instruction_advance", "空格继续", {"from_phase": flow.step.phase, "segment": "instruction"})
            self._advance_guided()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
        super().keyReleaseEvent(event)

    def _paint_guided_screen(self, painter):
        step = self._guided.step
        if "trial" in step.payload:
            return False
        painter.fillRect(self.rect(), QColor("#020617"))
        painter.setPen(QColor("#f8fafc"))
        if step.phase == "baseline_eyes_open":
            painter.setFont(QFont("Microsoft YaHei UI", 40))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "+")
            return True
        width, height = self.width(), self.height()
        margin = max(32, width // 10)
        content_width = width - margin * 2
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(max(24, min(40, height // 17)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#7dd3fc"))
        painter.drawText(QRect(margin, height // 7, content_width, height // 8), Qt.AlignmentFlag.AlignCenter, step.label)
        font.setBold(False)
        font.setPixelSize(max(16, min(27, height // 28)))
        painter.setFont(font)
        painter.setPen(QColor("#e2e8f0"))
        body = step.body
        if step.duration is not None:
            elapsed = max(0, self._presentation_time() - self._guided.presented_at) if self._guided.presented_at is not None else 0
            remaining = math.ceil(max(0, step.duration - elapsed))
            body += f"\n\n{remaining} 秒"
        painter.drawText(QRect(margin, height * 2 // 7, content_width, height // 2),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, body)
        font.setPixelSize(max(14, min(21, height // 36)))
        painter.setFont(font)
        painter.setPen(QColor("#94a3b8"))
        hint = "按空格继续  ·  Esc 停止" if step.duration is None else "本阶段自动计时  ·  Esc 停止"
        if self._guided_ended:
            hint = "按空格返回主控台"
        painter.drawText(QRect(margin, height * 6 // 7, content_width, height // 12), Qt.AlignmentFlag.AlignCenter, hint)
        return True
