"""Report only timing evidence actually saved by this recording."""


def write_timing_section(layout, report, shown):
    protocol = report['protocol']
    timing = protocol.get('display_timing')
    if not timing:
        old = protocol.get('missed_frames_estimate')
        layout.paragraph(f"旧版定时回调帧缺口估计为 {shown(old)}；该记录未保存高精度回调与画面交换间隔，"
                         "不能据此确认实际丢帧。旧版 Windows 低精度时钟可能影响此计数及刺激相位；本次刺激时序需另行验证。",
                         '显示时序证据')
        return
    scope = 'formal/flicker' if report['run']['paradigm'] == 'SSVEP' else 'formal/imagery'
    rows = [r for r in timing['rows'] if r['scope'] == scope]
    if not rows:
        layout.paragraph('未获得正式任务阶段的显示间隔，暂不能评价显示调度。')
        return
    layout.table(['正式任务阶段', '回调数', '平均间隔 ms', '最大间隔 ms', '长间隔数'], [
        ['定时回调' if r['stream']=='timer' else 'Qt 画面交换', r['callbacks'], shown(r['mean_interval_ms']),
         shown(r['max_interval_ms']), r['long_intervals']] for r in rows], [1.6,.8,1.4,1.4,1.3], compact=True)
    layout.paragraph('采用 perf_counter 高精度时钟；仅统计同一试次、同一阶段内的相邻回调。'
                     '长间隔指超过预期间隔的 1.5 倍；定时回调参照设定周期，画面交换参照系统刷新率。'
                     'Qt 画面交换回调不是屏幕光电测量，不能单凭此表确认物理闪烁频率或丢帧。')
    if report['run']['paradigm'] == 'SSVEP' and any(r['long_intervals'] for r in rows):
        layout.paragraph('正式闪烁期间记录到调度长间隔，建议检查显示负载与刷新设置，并复测刺激时序；任务数值需结合这一限制解释。')
