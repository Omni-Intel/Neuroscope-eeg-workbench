"""Report only timing evidence actually saved by this recording."""


def write_timing_section(layout, report, shown):
    write_brainco_trigger_section(layout, report)
    protocol = report['protocol']
    timing = protocol.get('display_timing')
    clock = (timing or {}).get('ssvep_frame_clock')
    if clock:
        trials = clock.get('trials', [])
        anomalies = sum(r['abnormal_intervals'] for r in trials)
        mismatches = sum(bool(r.get('rate_mismatch')) for r in trials)
        layout.paragraph(f"SSVEP 由 Qt 画面交换推进，闪烁相位使用高精度时钟。"
                         f"闪烁期间异常间隔 {anomalies} 次，刷新恢复请求 {clock['recovery_requests']} 次。"
                         f"交换速率偏离系统刷新率超过 2% 的闪烁段 {mismatches} 段（统计至少 0.5 秒）。"
                         "异常仅记录，未据此自动中止实验；如存在异常，需结合逐试次显示时序评估数据。",
                         'SSVEP 刷新调度')
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
        [('刷新看门定时器' if clock else '定时回调') if r['stream']=='timer' else 'Qt 画面交换', r['callbacks'], shown(r['mean_interval_ms']),
         shown(r['max_interval_ms']), r['long_intervals']] for r in rows], [1.6,.8,1.4,1.4,1.3], compact=True)
    layout.paragraph('采用 perf_counter 高精度时钟；仅统计同一试次、同一阶段内的相邻回调。'
                     '长间隔指超过预期间隔的 1.5 倍；定时回调参照设定周期，画面交换参照系统刷新率。'
                     'Qt 画面交换回调不是屏幕光电测量，不能单凭此表确认物理闪烁频率或丢帧。')
    if report['run']['paradigm'] == 'SSVEP' and any(r['long_intervals'] for r in rows):
        layout.paragraph('正式闪烁期间记录到调度长间隔，建议检查显示负载与刷新设置，并复测刺激时序；任务数值需结合这一限制解释。')


def write_brainco_trigger_section(layout, report):
    brainco = report['protocol'].get('brainco_triggers')
    if brainco is None:
        return
    sync = brainco['startup_sync']
    states = {'unrecorded': '旧记录未保存开启状态', 'not_requested': '尚未请求',
              'disabled': '未启用', 'requesting': '等待确认', 'unsupported': 'SDK 不支持',
              'unconfirmed': '未获确认', 'rejected': '请求被拒绝', 'acknowledged': '已确认开启上报'}
    layout.paragraph(f"BrainCo Trigger：{states.get(sync.get('state'), '状态未知')}；本段保存 {brainco['received_events']} 条触发记录。"
                     + brainco['note'] + (f" 开启错误：{sync['error']}" if sync.get('error') else ''), '同步说明')
