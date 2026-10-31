"""Deterministic Chinese Word report from assessment evidence, without HTML."""
from pathlib import Path

import numpy as np


def device_label(report):
    source = report['device']['source_type']
    return {'simulated': '模拟数据源', 'neuracle': '博睿康 Neuracle', 'brainco': '强脑 BrainCo',
            'omnibci': '公司 OmniBCI', 'emotiv_external': 'EMOTIV 外部录制',
            'lsl': '通用 LSL', 'npz_replay': '数据回放', 'td10_lsl': 'TD10 头带'}.get(source, source)


def report_title(report):
    """One complete title for the cover, document properties and filename."""
    import re

    title = f"{report['run']['participant_id']} {report['run']['paradigm']}脑电信号质量评估报告（{device_label(report)}）"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '－', title).rstrip(' .')


def shown(value, percent=False):
    if value is None:
        return "不可用"
    if isinstance(value, (float, np.floating)):
        return f"{value:.1%}" if percent else f"{value:.3g}"
    return str(value)


def make_figures(report, destination):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    from matplotlib import pyplot as plt
    available = {f.name for f in font_manager.fontManager.ttflist}
    family = next((f for f in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC") if f in available), "DejaVu Sans")
    plt.rcParams.update({"font.family": family, "axes.unicode_minus": False, "font.size": 10})
    destination = Path(destination)
    destination.mkdir(exist_ok=True)
    figures = []
    spectra = report["spectra"]
    for unit in sorted({s["unit"] for s in spectra}):
        fig, ax = plt.subplots(figsize=(7, 3.5), layout="constrained")
        for spectrum in (s for s in spectra if s["unit"] == unit):
            f = np.array(spectrum["frequency"])
            p = np.array(spectrum["psd"])
            mask = (f >= .5) & (f <= 100)
            ax.semilogy(f[mask], np.maximum(p[mask], 1e-20), alpha=.6, linewidth=.8)
        ax.set(xlabel="频率 (Hz)", ylabel=f"功率谱密度 ({unit}²/Hz)", title="全程有效窗口平均 PSD（未陷波，每条曲线为一通道）")
        ax.grid(alpha=.2)
        path = destination / f"psd-{len(figures)+1}.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        figures.append(("全程功率谱", path))
    task = report["task"]
    for index, measurement in enumerate(report["impedance"]):
        measured = [r for r in measurement.get("channels", []) if r.get("value") is not None]
        if measured:
            fig, ax = plt.subplots(figsize=(7, 3), layout="constrained")
            ax.bar([r["channel"] for r in measured], [r["value"] for r in measured], color="#477b9c")
            ax.tick_params(axis="x", labelrotation=60 if len(measured) > 8 else 0, labelsize=8)
            ax.set(ylabel=measurement["unit"], title="阻抗 / 接触状态原始测量值（不设跨品牌合格线）")
            path = destination / f"impedance-{index+1}.png"
            fig.savefig(path, dpi=160)
            plt.close(fig)
            figures.append(("阻抗与接触状态", path))
    if task.get("status") == "available":
        summary = task["all_trials"]
        fig, ax = plt.subplots(figsize=(7, 3.7 if report["run"]["paradigm"] == "SSVEP" else 2.6), layout="constrained")
        matrix = np.array(summary["confusion"])
        normalized = np.array(summary["confusion_row_fraction"], dtype=float)
        ax.imshow(normalized, cmap="Blues", aspect="auto", vmin=0, vmax=1)
        ax.set_xticks(range(matrix.shape[1]), [str(x) for x in summary["prediction_columns"]])
        ax.set_yticks(range(matrix.shape[0]), [str(x) for x in summary["labels"]])
        for (i, j), value in np.ndenumerate(matrix):
            percent = f"{normalized[i, j]:.0%}" if np.isfinite(normalized[i, j]) else "不可用"
            ax.text(j, i, f"{value}\n{percent}", ha="center", va="center", color="white" if normalized[i, j] > .5 else "black", fontsize=9)
        ax.set(xlabel="预测类别 / 未判定原因", ylabel="真实提示条件", title="全部已观察正式计分试次：计数及行百分比")
        path = destination / "task-confusion.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        figures.append(("固定算法混淆矩阵（未观察到的计划试次不进入矩阵）", path))
    curves = task.get("timecourses", [])
    if curves:
        same = all(r.get('clean') for r in curves)
        fig, axes = plt.subplots(1 if same else 2, 2, figsize=(7, 2.8 if same else 4.8), layout="constrained", sharey=True, squeeze=False)
        panels = (("mu", False), ("beta", False)) if same else (("mu", False), ("beta", False), ("mu", True), ("beta", True))
        for ax, (band, screened) in zip(axes.flat, panels):
            selected_curves = [r for r in curves if not screened or r.get("clean")]
            for condition in ("左手", "右手", "静息"):
                for channel, style in (("C3", "-"), ("C4", "--")):
                    times = sorted({r["time_sec"] for r in curves})
                    values = [np.mean([r[channel+"_erd_pct"] for r in selected_curves if r["band"] == band and r["condition"] == condition and r["time_sec"] == t])
                              if any(r["band"] == band and r["condition"] == condition and r["time_sec"] == t for r in selected_curves) else np.nan for t in times]
                    n = len({r["trial"] for r in selected_curves if r["condition"] == condition})
                    line, = ax.plot(times, values, style, label=f"{condition} {channel} n={n}")
                    intervals = []
                    for t in times:
                        samples = np.array([r[channel+"_erd_pct"] for r in selected_curves if r["band"] == band and r["condition"] == condition and r["time_sec"] == t])
                        rng = np.random.default_rng(20261028)
                        intervals.append(np.quantile(rng.choice(samples, (2000, len(samples))).mean(axis=1), [.025, .975]) if len(samples) >= 3 else [np.nan, np.nan])
                    ax.fill_between(times, np.array(intervals)[:, 0], np.array(intervals)[:, 1], color=line.get_color(), alpha=.13)
            ax.axhline(0, color="gray", linewidth=.6)
            label = '可分析与筛查后一致' if same else ('幅值筛查后' if screened else '全部可分析')
            ax.set(title=f"{band} · {label}", xlabel="想象阶段起点后秒数")
            ax.grid(alpha=.2)
            ax.legend(fontsize=7, ncol=2, loc="best")
        for ax in axes[:, 0]:
            ax.set_ylabel("相对基线功率变化 (%)")
        path = destination / "mi-erd.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        figures.append(("运动想象 ERD 时间曲线（负值为功率下降）", path))
    from neuroscope_eeg.reports.response_section import response_figures
    figures.extend(response_figures(report, destination))
    if report['run']['paradigm'] in {'SSVEP', '运动想象'}:
        from neuroscope_eeg.reports.compact_report import compact_figure
        figures.extend(compact_figure(report, destination))
    return figures


def write_word(report, destination, figures):
    if report['run']['paradigm'] in {'SSVEP', '运动想象'}:
        from neuroscope_eeg.reports.compact_report import write_compact
        return write_compact(report, destination, figures, report_title(report), device_label(report), shown)
    return write_detailed_word(report, destination, figures)


def write_detailed_word(report, destination, figures):
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    from neuroscope_eeg.reports.layout import ReportLayout

    layout = ReportLayout()
    doc, paragraph, table, box = layout.doc, layout.paragraph, layout.table, layout.box
    run, device, task = report['run'], report['device'], report['task']
    profile, protocol, integrity = report['profile'], report['protocol'], report['integrity']
    paradigm = run['paradigm']
    simulated = run.get('simulated', False)
    available = task.get('status') == 'available'
    counts = task.get('counts', {})
    selected = task.get('selected_channels', [])
    brand = device_label(report)
    status = {'complete': '正常完成', 'aborted': '提前停止', 'error': '异常结束'}.get(run['recording_status'], '待核对')
    reasons = Counter(r.get('exclusion_reason') or '原因未记录' for r in task.get('trials', []) if not r.get('analyzable'))
    if available:
        finding = f"可计算本次{'频率响应与 SNR' if paradigm == 'SSVEP' else 'μ／β 功率变化与侧化'}；固定算法准确率为 {shown(task['all_trials']['accuracy'], True)}（全部已观察计分试次），须结合响应、保留率及同步证据解读。"
    else:
        finding = '任务指标暂不可用：' + task.get('reason', '尚无分析依据') + '。'
    if simulated:
        finding = '本次为模拟 / 回放流程验证，不代表真实设备性能。' + finding
    sync_methods = task.get('timing_methods', [])
    timing_labels = {'software_cursor_unverified': '样本索引近似对齐，未校准', 'external_alignment': '外部对齐依据'}
    sync = '；'.join(timing_labels.get(m, m) for m in sync_methods) or '尚无可用事件对齐依据'
    if protocol.get('trigger_mode', {}).get('mode') == 'lsl_only':
        sync = 'LSL 软件同步；' + sync
    sync += '；设备接收与物理刺激时刻需独立核对'
    reference = profile.get('eeg_reference') or '采集参考方式未确认'
    preprocessing = '保留采集参考，不追加重参考；全程 4 秒分窗，末尾短窗保留幅值；通用质量分析不做陷波'
    if paradigm == '运动想象':
        preprocessing += '；任务使用 μ / β 频带功率及相对基线变化'
    elif paradigm == 'SSVEP':
        preprocessing += '；任务使用固定三子带 FBCCA，无个体校准'
    generated = report.get('report_generated_at')
    date = datetime.fromisoformat(generated).astimezone(timezone(timedelta(hours=8))).date().isoformat() if generated else '未记录'
    units = '、'.join(dict.fromkeys(device.get('channel_units', []))) or '未确认'
    analysis_channels = '、'.join(selected) or '任务电极尚未确认或本次不执行专项分析'
    title = report_title(report)
    doc.core_properties.title = title
    doc.add_paragraph(title, 'Title')
    subtitle = (f"信号质量、{paradigm}频域反应与固定算法评估" if paradigm in {'SSVEP', '运动想象'}
                else f"信号质量与{paradigm}记录可用性评估")
    doc.add_paragraph(subtitle, 'Subtitle')
    table(['项目', '内容'], [
        ('被试', run['participant_id'] + ('（模拟流程测试编号）' if simulated else '')),
        ('有效任务', paradigm),
        ('采集系统', f"{brand}；{len(device['channel_names'])} 通道；{device['sfreq']:g} Hz；保存单位 {units}"),
        ('分析电极', f"全通道用于通用质量检查；任务分析：{analysis_channels}"),
        ('重参考', f"未追加重参考；{reference}"),
        ('预处理', preprocessing),
        ('事件同步', sync),
        ('分析日期', date + '（北京时间）'),
    ], [1.0833, 5.4167])
    paragraph('本报告描述本次记录的信号特征与任务相关表现，不构成设备总体评级、医疗诊断或被试能力判断。软件事件对齐不等于已验证的物理刺激时刻。', '报告边界')
    paragraph(finding, '结果摘要')
    doc.add_heading('实验完成与数据可用性', 1).paragraph_format.page_break_before = True
    table(['任务', '记录状态', '保存时长 / 秒', '保存样本', '有效样本'], [
        (paradigm, status, shown(integrity.get('duration_sec')), integrity['samples'],
         shown(integrity['samples'] - integrity['invalid_samples']) if integrity.get('invalid_samples') is not None else '不可用'),
    ], [1.5, 1.1, 1.4, 1.25, 1.25])
    paragraph('时长按保存样本数与标称采样率计算，不等于实验计时。完成试次不等于可分析试次；两者在试次表中分别列出。', '可用性说明')
    table(['完整性或同步指标', '结果', '解释'], [
        ('样本序号间断 / 长时间戳间隔', f"{shown(integrity.get('sample_index_gaps'))} / {shown(integrity.get('timestamp_long_intervals'))}", '序号连续不等于已证明无丢包'),
        ('刺激显示估计丢帧', shown(protocol.get('missed_frames_estimate')), '软件对显示帧的估计，不是脑电丢包数'),
        ('硬件发送请求 / 错误', f"{protocol.get('hardware_send_requests', 0)} / {protocol.get('hardware_send_errors', 0)}", '发送请求不等于设备接收'),
        ('设备侧标记', shown(protocol.get('received_hardware_markers')), '不可用表示缺少证据，不表示零接收'),
    ], [2.2, 1.2, 3.1])

    from neuroscope_eeg.reports.timing_section import write_brainco_trigger_section
    write_brainco_trigger_section(layout, report)

    from neuroscope_eeg.reports.protocol_section import write_protocol_section, write_segment_quality_section
    write_protocol_section(layout, report, shown)

    from neuroscope_eeg.reports.response_section import write_retention_section
    if not write_retention_section(layout, report, shown):
        table(['计划正式试次', '实际完成', '可分析', '幅值筛查后保留'], [
            tuple(shown(v) for v in [protocol['planned'], protocol['completed'], counts.get('analyzable'), counts.get('clean')])
        ])
    if reasons:
        table(['不可分析原因', '正式试次数'], list(reasons.items()), [5.3, 1.2])
    paragraph('熟悉试次不参与评分；左右手及静息的任务完成状态来自程序事件，不证明被试实际完成了相应想象。', '计数说明') if paradigm == '运动想象' else paragraph('熟悉试次不参与评分；程序完成状态不等于被试注视或任务执行已被独立验证。', '计数说明')

    doc.add_heading('信号质量与电极接触', 1)
    paragraph('预处理方式见首页。未使用 ICA 或按伪迹类别自动修正数据。', '处理方法')
    paragraph('微伏 EEG 的窗峰峰值 <0.1 μV 标记为平直候选，>300 μV 标记为大幅值候选；这些是工程筛查阈值，不能确认伪迹来源或判定设备合格。缺少已确认硬件量程时不计算削顶。', '筛查定义')
    eligible = [c for c in report['channels'] if c.get('flat_fraction') is not None]
    flagged = [c['channel'] for c in report['channels'] if (c.get('flat_fraction') or 0) > 0 or (c.get('large_amplitude_fraction') or 0) > 0 or c['finite_fraction'] < 1]
    quality = (f"发现 {len(flagged)} 个通道存在幅值或非有限值线索，需结合逐窗结果复核。" if flagged else
               '已执行的幅值筛查未标记平直或大幅值窗口；不排除其他质量问题。') if eligible else '缺少满足微伏单位与 EEG 类型要求的幅值筛查结果。'
    paragraph(quality, '质量解释')
    if not profile.get('power_line_frequency'):
        paragraph('本次未确认工频为 50 Hz 或 60 Hz，因此工频比例显示不可用，不以 0 代替。')
    box('方法限制', '幅值与频谱仅提供质量线索；本版未获得独立眼电、肌电或动作证据，不把高频或漂移直接命名为某类伪迹。')
    write_segment_quality_section(layout, report, shown)
    for label, path in figures:
        if label == '全程功率谱':
            layout.figure(label, path)

    doc.add_heading('阻抗与接触质量', 2)
    if not report['impedance']:
        paragraph('本次为模拟数据，未提供实际阻抗或接触测量，不能评价电极接触。' if simulated else
                  '未关联本次记录的阻抗或接触质量测量，暂不能评价接触状态。')
    for measurement in report['impedance']:
        paragraph(f"来源：{measurement.get('method', '外部导入')}；时间：{measurement.get('measured_at', '未提供')}；阶段：{measurement.get('stage', '未提供')}。仅适用于测量时点。")
        table(['通道', '值', '单位', '标记'], [(r['channel'], shown(r.get('value')), measurement.get('unit', '未确认'), r.get('status', '')) for r in measurement.get('channels', [])])
        if measurement.get('attachment'):
            paragraph('原始测量凭据：' + measurement['attachment'])
    for label, path in figures:
        if label == '阻抗与接触状态':
            layout.figure(label, path)
    if device['source_type'] == 'emotiv_external':
        paragraph('EMOTIV CQ / EQ 等级不等同于 kΩ，不作阻抗单位换算。')

    doc.add_heading(paradigm + '任务响应', 1)
    if not available:
        paragraph('本次不报告任务准确率或 ERD / SNR 数值；不可分析不应解读为设备表现差。具体原因见上表或任务不可用说明。', '结果解释')
    if paradigm == 'SSVEP':
        lo, hi = report['configuration']['ssvep_window_relative_flicker_sec']
        paragraph(f'取闪烁后 {lo:g}–{hi:g} 秒分析频率响应。局部 SNR 按目标频带平均 PSD / 邻近背景中位数的 10×log10 计算，排除其他目标、谐波及已知工频邻域。', '分析方法')
    elif paradigm == '运动想象':
        blo, bhi = report['configuration']['mi_baseline_relative_fixation_sec']
        tlo, thi = report['configuration']['mi_task_relative_imagery_sec']
        paragraph(f'准备阶段 {blo:g}–{bhi:g} 秒作为基线，想象后 {tlo:g}–{thi:g} 秒为任务窗。μ 8–13 Hz、β 13–30 Hz；ERD = 100 × (任务功率 − 基线功率) / 基线功率，负值为功率下降。', '分析方法')
    from neuroscope_eeg.reports.response_section import write_classification_details, write_response_section
    response_images = [(label, path) for label, path in figures if path.name.startswith('response-') or path.name == 'mi-erd.png']
    write_response_section(layout, report, response_images, shown)
    if available:
        write_classification_details(layout, task, shown, paradigm)
        table(['计分范围', 'n', '准确率', '95% 区间', '平衡准确率', 'macro F1'], [
            (label, task[key]['n'], shown(task[key]['accuracy'], True),
             '～'.join(shown(v, True) for v in task[key]['ci95_wilson']) if task[key]['ci95_wilson'] else '不可用',
             shown(task[key]['balanced_accuracy'], True), shown(task[key]['macro_f1']))
            for label, key in [('全部已观察', 'all_trials'), ('可分析', 'analyzable_trials'), ('幅值筛查后', 'clean_trials')]
        ], [1.2, .4, 1, 1.7, 1.1, 1.1])
        for label, path in figures:
            if path.name == 'task-confusion.png':
                layout.figure(label, path)
        if task.get('blocks'):
            table(['分组', '可分析计分试次', '准确率', '平衡准确率'], [
                (b, s['n'], shown(s['accuracy'], True), shown(s['balanced_accuracy'], True)) for b, s in task['blocks'].items()
            ])

    doc.add_heading('最终综合结论', 1)
    table(['问题', '本次结论', '依据与限制'], [
        ('脑电信号能否评价', '仅验证流程' if simulated else '需结合质量证据复核', '模拟信号不能证明设备性能。' if simulated else quality),
        ('任务反应能否评价', '仅作流程观察' if simulated and available else ('可作本次描述' if available else '暂不可评估'), '结合任务响应、试次保留及同步依据解读。' if available else task.get('reason', '任务证据不足')),
        ('电极接触能否评价', '仅限测量时点' if report['impedance'] else '证据不足', '已关联原始测量，按厂商单位解释。' if report['impedance'] else '未获得本次实际测量。'),
        ('能否比较品牌或认知能力', '不能据此下结论', '单次记录、任务执行差异及同步限制，不能支持跨设备总体排名或临床判断。'),
    ], [1.6, 1.25, 3.65])
    box('建议', ('先核对时间推进与事件对齐，再重新进行模拟流程测试；修正前不补造任务指标。' if simulated and not available else
                 '先复核试次排除原因、同步依据与电极配置，再按相同条件复测。') + '增加重复试次只能改善本次估计，不能替代跨被试验证。')

    doc.add_heading('附录 通道指标与数据依据', 1).paragraph_format.page_break_before = True
    paragraph('RMS（均方根）和峰峰值为全程窗口中位数；平直窗、大幅值窗为标记窗口比例。原始单位保留，未知项显示不可用。')
    if report['channels']:
        table(['通道 / 单位', 'RMS', '峰峰值', '工频比例', '平直窗', '大幅值窗'], [
            (f"{c['channel']} / {c['unit']}", shown(c['rms_ac_median']), shown(c['peak_to_peak_median']),
             shown(c['line_fraction_median'], True), shown(c['flat_fraction'], True), shown(c['large_amplitude_fraction'], True)) for c in report['channels']
        ], [1.3, .8, .9, 1.2, 1.1, 1.2], compact=True)
        table(['通道', '非有限样本', '低频比例', '高频比例', '量程触及比例'], [
            (c['channel'], shown(1-c['finite_fraction'], True), shown(c.get('drift_fraction_median'), True),
             shown(c.get('high_frequency_fraction_median'), True), shown(c.get('clipping_fraction_median'), True))
            for c in report['channels']], [1.3, 1.3, 1.3, 1.3, 1.3], compact=True)
        paragraph('低频为 0.5–2 Hz，高频为 30–80 Hz；频谱比例以 0.5–min(100, Nyquist) Hz 为分母。表中为窗口中位数，不是整段污染时间比例；量程未确认时不估计触及比例。')
    else:
        paragraph('尚无可读取的脑电数据；外部录制需关联对应 EDF 后再评估。')
    paragraph(f"记录标识：{run['session_id']}；分析版本：{report['analysis_version']}。", '数据追溯')
    paragraph('assessment.json 保存配置、输入哈希、运行库版本和不可用原因；channels.csv 为通道指标，windows.csv 为逐窗指标，trials.csv 为试次及排除原因，timecourses.csv 为 ERD 曲线；新协议另含 phases.csv 实际阶段时间和 segment_channels.csv 分段通道质量。原始数据保持不变，每次报告独立留存。')
    paragraph('新增 trial_responses.csv、response_summary.csv、block_response.csv 保存逐试次、条件及分组响应；condition_spectra.csv、time_frequency.csv 保存频谱与时频数组；trial_retention.csv、baseline_windows.csv、baseline_comparison.csv、harmonic_overlaps.csv、classification.csv 保存分母、基线、共享谐波和分类依据。补充计算错误单列 response_errors.csv。')
    paragraph('工频比例依赖已确认的工频配置；削顶依赖已确认的硬件量程。高频比例不能单独确认肌电，软件同步不能证明物理时序准确。本报告不是 BIDS 校验或平台质量评分。')
    doc.save(str(destination))
