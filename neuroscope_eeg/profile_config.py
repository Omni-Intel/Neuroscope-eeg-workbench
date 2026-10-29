"""Strict user-supplied device/analysis configuration (not SDK metadata)."""
import math

FIELDS = {"confirmed", "device_id", "manufacturer", "model", "channel_names", "channel_types", "channel_units",
          "eeg_reference", "software_filters", "power_line_frequency", "edf_timezone", "adc_rails_uv",
          "physical_min", "physical_max", "range_evidence", "session_id", "source_id"}


def validate_profile(p):
    if not isinstance(p, dict):
        raise ValueError("设备配置必须是对象")  # noqa: TRY004 - public configuration boundary
    unknown = set(p) - FIELDS
    if unknown:
        raise ValueError("未知设备配置字段：" + ", ".join(sorted(unknown)))
    if "confirmed" in p and type(p["confirmed"]) is not bool:
        raise ValueError("confirmed 必须是布尔值")
    for name in FIELDS - {"confirmed", "channel_names", "channel_types", "channel_units", "software_filters",
                          "power_line_frequency", "physical_min", "physical_max", "adc_rails_uv"}:
        if name in p and (not isinstance(p[name], str) or not p[name].strip()):
            raise ValueError(name + " 必须是非空字符串")
    for name in ("channel_names", "channel_types", "channel_units"):
        if name in p and (not isinstance(p[name], list) or not p[name] or any(not isinstance(v, str) or not v.strip() for v in p[name])):
            raise ValueError(name + " 必须是非空字符串列表")
    if "power_line_frequency" in p and p["power_line_frequency"] != "n/a" and (type(p["power_line_frequency"]) not in (int, float) or p["power_line_frequency"] not in (50, 60)):
        raise ValueError("power_line_frequency 必须为 50、60 或 n/a")
    if "software_filters" in p and not isinstance(p["software_filters"], (str, dict)):
        raise ValueError("software_filters 必须为字符串或对象")
    if "adc_rails_uv" in p and not isinstance(p["adc_rails_uv"], dict):
        raise ValueError("adc_rails_uv 必须按通道提供对象")
    for channel, rails in p.get("adc_rails_uv", {}).items():
        if not isinstance(channel, str) or not isinstance(rails, list) or len(rails) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in rails) or rails[0] >= rails[1]:
            raise ValueError("adc_rails_uv 须按通道提供有效上下限")
    if ("physical_min" in p) != ("physical_max" in p):
        raise ValueError("physical_min / physical_max 须成对提供")
    if "physical_min" in p:
        lo, hi = p["physical_min"], p["physical_max"]
        if not isinstance(lo, list) or not isinstance(hi, list) or not lo or len(lo) != len(hi):
            raise ValueError("量程须按存储通道顺序提供等长列表")
        if any(type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a) or not math.isfinite(b) or a >= b for a, b in zip(lo, hi)):
            raise ValueError("量程须为有限数值且最小值小于最大值")
        if not p.get("range_evidence"):
            raise ValueError("须提供量程来源 range_evidence")
    return dict(p)
