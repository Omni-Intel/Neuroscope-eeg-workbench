"""Derive export metadata from verified Omni 0.2.0 acquisition metadata.

Export readiness is deliberately independent of scalp-montage confirmation.
"""
import math


def delivery_profile(device, profile):
    p = dict(profile)
    p.pop('delivery_confirmed', None)
    extra = device.get('extra', {})
    if device.get('source_type') != 'omnibci':
        return p
    config = extra.get('frontend_config', {})
    model = extra.get('device_model')
    count = {'stm32': 32, 'esp32': 8}.get(model)
    gains = config.get('gains', []) if isinstance(config, dict) else []
    if (extra.get('sdk_version') != '0.2.0' or extra.get('native_sdk_version') != '0.2.0'
            or not isinstance(config, dict) or config.get('verified') is not True or not count
            or not isinstance(gains, (list, tuple)) or len(gains) != count
            or len(device.get('channel_names', [])) != count
            or list(device.get('channel_units', [])) != ['uV'] * count
            or any(type(g) is not int or g not in (1, 2, 4, 6, 8, 12, 24) for g in gains)):
        return p  # Unknown contracts still require an explicit export profile.
    defaults = {'manufacturer': 'Omni-Intel', 'model': f'OmniBCI {model.upper()} {count}CH',
                'eeg_reference': 'n/a', 'software_filters': 'n/a', 'power_line_frequency': 'n/a'}
    missing = [name for name in ('eeg_reference', 'power_line_frequency') if p.get(name, 'n/a') == 'n/a']
    for key, value in defaults.items():
        p.setdefault(key, value)
    if 'physical_min' not in p and 'physical_max' not in p:
        # SDK lib.rs: 4.5 V / gain / (2**23-1), signed 24-bit counts.
        # Round outward to integer uV (including float32 rounding), fits EDF's 8-byte fields.
        limits = [math.ceil(4_500_000 / g * (2**23 / (2**23-1))) + 1 for g in gains]
        p['physical_min'], p['physical_max'] = [-v for v in limits], limits
        p['range_evidence'] = ('OmniBCI SDK 0.2.0 nominal ADC conversion: VREF=4.5 V, '
            'signed 24-bit counts, verified per-channel gains; outward integer-uV bounds. '
            'Not a hardware calibration. SDK revision: ' + str(extra.get('sdk_revision', 'not recorded')))
    p['delivery_confirmed'] = True
    p['unrecorded_export_fields'] = missing
    p['export_metadata_note'] = ('n/a reference/mains means not recorded, not verified absent. '
        'No NeuroScope software filtering is applied to stored samples. '
        'SDK hardware settings are in the native device.json; scalp montage is not inferred.')
    return p
