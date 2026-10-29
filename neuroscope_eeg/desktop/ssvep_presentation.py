"""Eight simultaneous frequency-coded squares around a central cue area."""
import math

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPen

from . import ssvep_legacy

POSITIONS = ('左上', '上', '右上', '左', '右', '左下', '下', '右下')
FREQUENCIES = tuple(float(f) for f in range(8, 16))


def target_layout(width, height, diagonal_in=0, target_cm=6):
    ppcm = math.hypot(width, height)/(diagonal_in*2.54) if diagonal_in > 0 else None
    side = max(2, round(min(target_cm*ppcm if ppcm else min(width,height)*.2, min(width,height)*.25)))
    boxes = [(round(width*x-side/2), round(height*y-side/2), side, side)
             for x,y in ((.2,.2),(.5,.2),(.8,.2),(.2,.5),(.8,.5),(.2,.8),(.5,.8),(.8,.8))]
    return boxes, side/ppcm if ppcm else None


def target_levels(phase, target_index, frame, refresh_hz, frequencies=FREQUENCIES):
    if phase == 'flicker':
        # Nakanishi et al. 2014, Eq. 1: sampled 50% duty square wave.
        # Fractional cycle lengths must not be rounded to a fixed frame period.
        return [255 if (frame*f/refresh_hz) % 1 < .5 else 0 for f in frequencies]
    return [170 if i == target_index and phase in {'cue','prep'} else 30 for i in range(len(frequencies))]


def display_metadata(window, plan, screen):
    if not plan.eight_target:
        return ssvep_legacy.display_metadata(window, plan, screen)
    boxes, cm = target_layout(window.width(), window.height(), plan.screen_diagonal_in, plan.target_size_cm)
    return {'mode': 'simultaneous_eight', 'layout': 'eight_square_grid_v3',
                'frequency_order': 'ascending_cyclic', 'position_order': list(POSITIONS),
                'frequencies_hz': list(window.ssvep_frequencies), 'modulation': 'frame_sampled_square_50_percent',
                'frequency_reference': '10.1371/journal.pone.0099235',
                'phase_radians': [0.]*8, 'screen_name': screen.name(), 'refresh_hz_reported': window.refresh_hz,
                'viewport_logical_px': [window.width(),window.height()], 'device_pixel_ratio': window.devicePixelRatioF(),
                'screen_diagonal_in_entered': plan.screen_diagonal_in or None,
                'viewing_distance_cm_entered': plan.viewing_distance_cm or None,
                'target_size_cm_requested': plan.target_size_cm, 'target_size_cm_estimated': cm,
                'target_rects_logical_px': [list(r) for r in boxes],
                'target_rects_device_px': [[round(v*window.devicePixelRatioF()) for v in r] for r in boxes],
                'size_clamped': cm is not None and cm < plan.target_size_cm-.05,
                'luminance_levels_rgb': {'peak':255,'trough':0,'inactive':30},
                'timing_validation': 'software_frame_events_only_not_photodiode_verified'}


def paint_single_target(window, painter):
    if not window._guided.plan.eight_target:
        return ssvep_legacy.paint_single_target(window, painter)
    plan, phase = window._guided.plan, window._guided.step.phase
    painter.fillRect(window.rect(), QColor('#020617'))
    painter.setFont(QFont('Microsoft YaHei UI', 20))
    painter.setPen(QColor('#e2e8f0'))
    if phase == 'rest':
        elapsed = max(0,window._presentation_time()-window._guided.presented_at) if window._guided.presented_at is not None else 0
        painter.drawText(window.rect(), Qt.AlignmentFlag.AlignCenter,
                         f'休息 · 可以眨眼\n{math.ceil(max(0,plan.rest_sec-elapsed))} 秒')
        return
    boxes,_ = target_layout(window.width(),window.height(),plan.screen_diagonal_in,plan.target_size_cm)
    levels = target_levels(phase,window._ssvep_target_index,window.frame_index-window._ssvep_flicker_frame,
                           window.refresh_hz,window.ssvep_frequencies)
    for i,(box,level) in enumerate(zip(boxes,levels)):
        painter.fillRect(QRect(*box),QColor(level,level,level))
        highlighted = i == window._ssvep_target_index and phase in {'cue','prep'}
        painter.setPen(QPen(QColor('#f87171' if highlighted else '#64748b'),5 if highlighted else 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRect(*box))
    painter.setPen(QColor('#e2e8f0'))
    painter.setFont(QFont('Microsoft YaHei UI',18))
    center = QRect(round(window.width()*.36),round(window.height()*.38),round(window.width()*.28),round(window.height()*.24))
    text = ('+\n准备' if phase == 'fixation' else
            f'注视{POSITIONS[window._ssvep_target_index]}方块\n八块同时闪烁' if phase in {'cue','prep'} else '+')
    painter.drawText(center,Qt.AlignmentFlag.AlignCenter,text)
