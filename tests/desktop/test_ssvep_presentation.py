from dataclasses import replace

import pytest

from neuroscope_eeg.protocol_config import AssessmentProtocol
from neuroscope_eeg.desktop.protocols import frame_locked_frequencies
from neuroscope_eeg.desktop.ssvep_presentation import target_layout, target_levels, target_polygons, BORDER_COLORS


def test_new_and_legacy_protocols_remain_distinct():
    new = AssessmentProtocol.defaults('SSVEP')
    assert new.minimum_duration_sec == 1250
    assert new.phases == [('fixation',1.5),('cue',1),('prep',1),('flicker',5),('rest',4)]
    assert AssessmentProtocol.from_dict(new.to_dict()) == new
    old = replace(new, ssvep_mode='simultaneous_quadrants_v1', cue_sec=2, rest_sec=2, fixation_sec=2)
    saved = old.to_dict()
    restored = AssessmentProtocol.from_dict(saved)
    assert restored.phases == [('cue',2),('flicker',5),('rest',2)]
    assert restored.to_dict() == saved
    assert restored.for_new_run() == new
    mi = AssessmentProtocol.defaults('运动想象')
    assert mi.minimum_duration_sec == 1124
    assert AssessmentProtocol.from_dict(mi.to_dict()).phases == mi.phases


@pytest.mark.parametrize('width,height', [(1920,1080),(800,600),(1080,1920)])
@pytest.mark.parametrize('diagonal', [0,13,24,32])
def test_triangle_bounds_are_equal_and_inside_screen(width,height,diagonal):
    boxes,cm = target_layout(width,height,diagonal)
    assert len({(w,h) for x,y,w,h in boxes}) == 1
    assert all(w == h and 0 <= x <= width-w and 0 <= y <= height-h for x,y,w,h in boxes)
    assert (cm is None) == (diagonal == 0)
    if diagonal == 24:
        assert cm == pytest.approx(6, abs=.1)


def test_only_cued_target_flickers_with_refresh_derived_period():
    frequencies = tuple(sorted(frame_locked_frequencies(60)))
    assert frequencies == (7.5,10,12,15)
    for target, frequency in enumerate(frequencies):
        frames = [target_levels('flicker',target,f,60,frequencies) for f in range(120)]
        assert {f[target] for f in frames} == {0,255}
        assert all(f[j] == 30 for f in frames for j in range(4) if j != target)
        period = round(60/frequency)
        assert frames[:period] == frames[period:2*period]
        for phase in ('fixation','cue','prep'):
            assert target_levels(phase,target,0,60,frequencies) == target_levels(phase,target,60,60,frequencies)


def test_dog_edge_layout_and_direction_colors():
    boxes,_ = target_layout(1920,1080)
    assert boxes == [(852,16,216,216),(1688,432,216,216),(852,848,216,216),(16,432,216,216)]
    assert target_polygons(boxes) == [
        [(960,16),(852,232),(1068,232)],
        [(1904,540),(1688,432),(1688,648)],
        [(960,1064),(852,848),(1068,848)],
        [(16,540),(232,432),(232,648)],
    ]
    assert BORDER_COLORS == ('#22c55e','#ef4444','#38bdf8','#eab308')
