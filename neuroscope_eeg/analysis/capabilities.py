"""Conservative gates for interpreting physiological effects across devices."""


def analysis_block_reason(metadata, paradigm):
    if metadata.source_type == "emotiv_external":
        return "EMOTIV 由 EmotivPRO 录制；关联 EDF 后再离线分析"
    if metadata.source_type not in {"simulated", "simulator", "replay", "npz_replay"} and not metadata.extra.get("profile_confirmed"):
        return "请先确认设备配置中的物理单位、电极位置与参考方式"
    eeg = [i for i, t in enumerate(metadata.channel_types) if t == "eeg"]
    if not eeg or any(metadata.channel_units[i] not in {"uV", "µV", "μV"} for i in eeg):
        return "分析要求已确认的微伏 EEG；原始单位仍如实保存"
    names = {metadata.channel_names[i].upper() for i in eeg}
    if paradigm == "运动想象" and not {"C3", "C4"} <= names:
        return "运动想象分析需要已确认的 C3、C4 电极；刺激与原始记录仍可运行"
    if paradigm == "SSVEP" and not names.intersection({"O1", "O2", "OZ", "POZ", "PO3", "PO4"}):
        return "SSVEP 分析需要已确认的枕区电极；刺激与原始记录仍可运行"
    if paradigm == "听觉 ASSR" and metadata.sfreq <= 100:
        return "采样率不足以可靠分析当前 ASSR 频率"
    return ""
