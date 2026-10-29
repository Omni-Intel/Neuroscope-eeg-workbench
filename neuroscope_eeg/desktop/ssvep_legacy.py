"""Dog's four edge triangles, adapted to the existing four-frequency assessment.

Layout, colors, fixation dots and cue drawing follow D:/dog/neuroscope_eeg/
desktop/stimulus.py (compute_ssvep_layout and _paint_ssvep). No runtime dependency
on that repository; robot mode-switch target and robot controls are excluded.
"""
import math

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFont, QPen, QPolygon

POSITIONS = ('上', '右', '下', '左')
BORDER_COLORS = ('#22c55e', '#ef4444', '#38bdf8', '#eab308')


def target_layout(width, height, diagonal_in=0, target_cm=6):
    """Logical pixels; physical dimensions are operator supplied, never guessed."""
    short = min(width, height)
    pixels_per_cm = math.hypot(width, height) / (diagonal_in * 2.54) if diagonal_in > 0 else None
    requested = min(target_cm * pixels_per_cm, short - 32) if pixels_per_cm else short / 5
    side = max(2, round(requested))
    cx, cy = width // 2, height // 2
    ring_v = max(0, round(cy - requested / 2 - 16))
    ring_h = max(0, round(cx - requested / 2 - 16))
    centers = ((cx, cy-ring_v), (cx+ring_h, cy), (cx, cy+ring_v), (cx-ring_h, cy))
    half = side // 2
    rects = [(x-half, y-half, 2*half, 2*half) for x,y in centers]
    return rects, (2*half / pixels_per_cm if pixels_per_cm else None)


def target_polygons(rects):
    polygons = []
    for position, (x,y,w,h) in zip(POSITIONS, rects):
        cx,cy = x+w//2,y+h//2
        polygons.append({'上': [(cx,y),(x,y+h),(x+w,y+h)],
                         '右': [(x+w,cy),(x,y),(x,y+h)],
                         '下': [(cx,y+h),(x,y),(x+w,y)],
                         '左': [(x,cy),(x+w,y),(x+w,y+h)]}[position])
    return polygons


def display_metadata(window, plan, screen):
    width, height = window.width(), window.height()
    rects, actual_cm = target_layout(width, height, plan.screen_diagonal_in, plan.target_size_cm)
    return {
        'mode': 'single_target', 'layout': 'dog_edge_triangles_v1',
        'frequency_order': 'ascending_cyclic', 'position_order': list(POSITIONS),
        'frequencies_hz': list(window.ssvep_frequencies),
        'screen_name': screen.name(), 'refresh_hz_reported': window.refresh_hz,
        'viewport_logical_px': [width, height], 'device_pixel_ratio': window.devicePixelRatioF(),
        'screen_diagonal_in_entered': plan.screen_diagonal_in or None,
        'viewing_distance_cm_entered': plan.viewing_distance_cm or None,
        'target_size_cm_requested': plan.target_size_cm,
        'target_size_cm_estimated': actual_cm,
        'size_basis': 'operator_screen_diagonal' if actual_cm is not None else '20_percent_short_side',
        'target_rects_logical_px': [list(r) for r in rects],
        'target_rects_device_px': [[round(v*window.devicePixelRatioF()) for v in r] for r in rects],
        'target_vertices_logical_px': target_polygons(rects),
        'border_colors': list(BORDER_COLORS), 'edge_padding_logical_px': 16,
        'layout_reference': 'dog/neuroscope_eeg/desktop/stimulus.py:compute_ssvep_layout,_paint_ssvep',
        'size_clamped': plan.screen_diagonal_in > 0 and actual_cm < plan.target_size_cm - .05,
        'luminance_levels_rgb': {'peak': 255, 'trough': 0, 'inactive': 30},
        'timing_validation': 'software_frame_events_only_not_photodiode_verified',
    }


def target_levels(phase, target_index, frame, refresh_hz, frequencies):
    levels = [30] * len(frequencies)
    if phase == 'cue':
        levels[target_index] = 100
    elif phase == 'prep':
        levels[target_index] = 170
    elif phase == 'flicker':
        period = max(2, round(refresh_hz / frequencies[target_index]))
        levels[target_index] = 255 if (frame % period) < period / 2 else 0
    return levels


def paint_single_target(window, painter):
    plan = window._guided.plan
    phase = window._guided.step.phase
    painter.fillRect(window.rect(), QColor('#020617'))
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    if phase == 'rest':
        painter.setPen(QColor('#f8fafc'))
        painter.setFont(QFont('Microsoft YaHei UI', 34, QFont.Weight.Bold))
        painter.drawText(window.rect().adjusted(80,80,-80,-80), Qt.AlignmentFlag.AlignCenter, '休息 · 可以眨眼')
        elapsed = max(0,window._presentation_time()-window._guided.presented_at) if window._guided.presented_at is not None else 0
        painter.setPen(QColor('#64748b'))
        painter.setFont(QFont('Microsoft YaHei UI',22))
        painter.drawText(window.rect().adjusted(80,window.height()-160,-80,-60), Qt.AlignmentFlag.AlignCenter,
                         f'{math.ceil(max(0,plan.rest_sec-elapsed))} 秒')
        return
    rects, _ = target_layout(window.width(), window.height(), plan.screen_diagonal_in, plan.target_size_cm)
    levels = target_levels(phase, window._ssvep_target_index,
                           window.frame_index - window._ssvep_flicker_frame,
                           window.refresh_hz, window.ssvep_frequencies)
    for index, (box, vertices, level) in enumerate(zip(rects, target_polygons(rects), levels)):
        poly = QPolygon([QPoint(x,y) for x,y in vertices])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(level,level,level))
        painter.drawPolygon(poly)
        highlighted = index == window._ssvep_target_index and phase in {'cue', 'prep'}
        painter.setPen(QPen(QColor(BORDER_COLORS[index]), 6 if highlighted else 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(poly)
        x,y,w,h = box
        painter.setPen(QPen(QColor('#0f172a'),2))
        painter.setBrush(QColor(BORDER_COLORS[index]))
        painter.drawEllipse(QPoint(x+w//2,y+h//2),6,6)
    cx,cy = window.width()//2, window.height()//2
    if phase in {'fixation', 'cue', 'prep'}:
        size = 12 if phase == 'prep' else 18
        painter.setPen(QPen(QColor('#94a3b8' if phase == 'prep' else '#f8fafc'),3))
        painter.drawLine(QPoint(cx-size,cy),QPoint(cx+size,cy))
        painter.drawLine(QPoint(cx,cy-size),QPoint(cx,cy+size))
        if phase in {'cue','prep'}:
            x,y,w,h = rects[window._ssvep_target_index]
            paint_arrow(painter,cx,cy,x+w//2,y+h//2,'#94a3b8' if phase == 'prep' else '#ef4444')
        hint = {'fixation': '深呼吸 · 准备', 'cue': '跟随箭头注视目标',
                'prep': '盯住边框加粗的三角形 · 只有它会闪 · 其余保持暗'}[phase]
        painter.setPen(QColor('#94a3b8'))
        painter.setFont(QFont('Microsoft YaHei UI',16))
        painter.drawText(window.rect().adjusted(0,cy+50,0,-(cy-110)), Qt.AlignmentFlag.AlignCenter,hint)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#1a1a2e'))
        painter.drawEllipse(QPoint(cx,cy),10,10)


def paint_arrow(painter,cx,cy,tx,ty,color):
    dx,dy = tx-cx,ty-cy
    length = math.hypot(dx,dy)
    if length < 1:
        return
    ux,uy = dx/length,dy/length
    sx,sy = cx+ux*70,cy+uy*70
    ex,ey = cx+dx*.55,cy+dy*.55
    painter.setPen(QPen(QColor(color),10))
    painter.drawLine(QPoint(int(sx),int(sy)),QPoint(int(ex),int(ey)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(QPolygon([QPoint(int(ex+ux*30),int(ey+uy*30)),
                                  QPoint(int(ex-uy*18),int(ey+ux*18)),
                                  QPoint(int(ex+uy*18),int(ey-ux*18))]))
