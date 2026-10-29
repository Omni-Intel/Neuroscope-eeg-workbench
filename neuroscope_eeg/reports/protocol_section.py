"""Compact protocol evidence section, using this run's settings and measured intervals."""
import math

import numpy as np

from neuroscope_eeg.analysis.protocol_segments import PHASE_LABELS
from neuroscope_eeg.protocol_config import AssessmentProtocol


def write_protocol_section(layout, report, shown):
    settings = report["protocol"].get("settings")
    if not settings:
        if report["protocol"].get("settings_error"):
            layout.paragraph(report["protocol"]["settings_error"], "实验参数不可用")
        return
    doc, paragraph, table = layout.doc, layout.paragraph, layout.table
    doc.add_heading("本次实验流程与参数", 2)
    conditions = AssessmentProtocol.from_dict(settings).conditions
    block_note = (f"组间至少休息 {settings['block_rest_sec']:g} 秒，再按空格继续。"
                  if settings['total_trials'] > settings['block_trials'] else '本次仅一组，无组间休息。')
    table(["正式总试次", "每组最多", "计划组数", "练习总试次"], [[
        settings["total_trials"], settings["block_trials"], math.ceil(settings["total_trials"] / settings["block_trials"]),
        conditions * settings["practice_per_condition"]]])
    paragraph(f"说明与指导 → 练习 → 睁眼静息 {settings['eyes_open_sec']:g} 秒 → 闭眼准备 {settings['close_prepare_sec']:g} 秒 → "
              f"闭眼静息 {settings['eyes_closed_sec']:g} 秒 → 睁眼恢复 {settings['open_recovery_sec']:g} 秒 → 正式分组。"
              + block_note + "条件按固定等量轮换；每次范式独立采集静息。")
    plan = AssessmentProtocol.from_dict(settings)
    rows = report.get("phase_intervals", [])
    evidence = []
    for phase, duration in plan.phases:
        observed = [r["actual_sec"] for r in rows if r["phase"] == phase and r["segment"] == "formal" and r["completed"]]
        label = '中央注视准备' if phase == 'fixation' and plan.single_target else PHASE_LABELS[phase]
        evidence.append([label, shown(duration), len(observed),
                         f"{min(observed):.2f}–{max(observed):.2f}" if observed else "不可用"])
    table(["单试次阶段", "计划 / 秒", "完整阶段数", "实测范围 / 秒"], evidence, [1.7, 1.2, 1.2, 2.4])
    paragraph("实测范围来自事件对齐，包含显示调度误差，不等于已验证的物理刺激时长。等待时间另行记录；中止时未结束的阶段不列入范围。"
              "练习与静息不参与任务评分，独立静息用于信号质量观察。"
              + ("四条件 MI 仅采集，响应分析与分类待接入。" if plan.mi_collection else
                 "运动想象 ERD 仍使用各试次的提示前基线。" if settings['paradigm'] == '运动想象' else ""))
    if plan.single_target or plan.eight_target:
        display = report['run'].get('protocol_start_payload', {}).get('ssvep_display') or {}
        paragraph('八个等大方块位于九宫格外围，中央为提示区；八个目标同时闪烁，每组按 8–15 Hz 升序循环。固定 FBCCA 识别被提示注视的目标。' if plan.eight_target else '四个等大三角靶贴近屏幕上、右、下、左四边；仅提示目标闪烁，其余保持暗态。每组按频率从小到大循环。'
                  '固定算法结果描述不同单目标刺激频率的可辨识程度，不代表四靶同时闪烁的注视选择能力。')
        frequencies = display.get('frequencies_hz') or report['run'].get('protocol_start_payload', {}).get('ssvep_frequencies', [])
        rectangles = display.get('target_rects_logical_px', [])
        table(['显示条件', '本次记录'], [
            ('位置顺序对应频率' if plan.eight_target else '上／右／下／左频率', ' / '.join(f'{v:g} Hz' for v in frequencies) or '未记录'),
            ('刷新率／屏幕', f"{shown(display.get('refresh_hz_reported'))} Hz / {display.get('screen_name') or '未记录'}"),
            ('方块边长' if plan.eight_target else '三角靶外框尺寸', (f"{rectangles[0][2]} 逻辑像素；" if rectangles else '') +
             (f"估算 {display['target_size_cm_estimated']:.2f} cm" if display.get('target_size_cm_estimated') else '物理尺寸未确定')),
            ('屏幕对角线／观看距离', f"{shown(display.get('screen_diagonal_in_entered'))} 英寸 / {shown(display.get('viewing_distance_cm_entered'))} cm"),
        ], [2, 4.5])
        paragraph('未填写屏幕尺寸时，外框取短边的 20%；否则由人工填写的对角线估算。实际外框存入记录。'
                  '固定顺序可能混入时间或疲劳影响，设备间比较需保持相同流程。')
        if plan.eight_target:
            paragraph('频率与逐帧黑白方波参考 Nakanishi 等（2014），doi:10.1371/journal.pone.0099235。'
                      '本程序保留较长刺激、独立静息及升序条件安排，用于记录质量评估，非原论文的高速 BCI 实验复现。')


def write_segment_quality_section(layout, report, shown):
    doc, paragraph, table = layout.doc, layout.paragraph, layout.table
    if report["protocol"].get("segment_quality_error"):
        paragraph(report["protocol"]["segment_quality_error"], "分段质量暂不可用")
    if report.get("segment_quality"):
        doc.add_heading("静息与正式任务的分段质量", 2)
        evidence = []
        for segment in report["segment_quality"]:
            channels = [c for c in segment["channels"] if c["type"] == "eeg" and c["unit"] in {"uV", "µV", "μV"}]
            def across(metric, channels=channels):
                values = [c[metric] for c in channels if c.get(metric) is not None]
                return float(np.median(values)) if values else None
            evidence.append([segment["label"] + ("（未完整）" if not segment["completed"] else ""),
                             shown(segment["duration_sec"]), shown(segment["valid_fraction"], True),
                             shown(across("rms_ac_median")), shown(across("large_amplitude_fraction"), True)])
        table(["区段", "时长 / 秒", "有效样本", "RMS / μV", "大幅值窗"], evidence, [1.6, 1, 1.1, 1.2, 1.6])
        paragraph("RMS 与大幅值窗比例为已确认微伏 EEG 通道指标的中位数，逐通道值见 segment_channels.csv；不拼接不连续区段。"
                  "本表排除练习、指导与等待。而全程图表仍保留所有记录区段，仅作采集过程检查，不作静息质量或任务指标。")
