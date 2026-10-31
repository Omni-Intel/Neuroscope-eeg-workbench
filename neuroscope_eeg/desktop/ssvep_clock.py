"""Passive swap diagnostics. Never block or terminate an experiment."""
import math


class SSVEPFrameClock:
    scheduler = 'frame_swapped_v1'

    def __init__(self, refresh_hz):
        if not math.isfinite(refresh_hz) or refresh_hz < 30:
            raise ValueError('无法取得有效的显示刷新率')
        self.refresh_hz = refresh_hz
        self.period = 1 / refresh_hz
        self.previous = None
        self.frames = 0
        self.trials = {}
        self.recovery_requests = 0

    def observe(self, now, context, frame):
        """Call once per newly painted swap; account for the last flicker frame too."""
        previous = self.previous
        self.previous = (now, context, frame)
        self.frames += 1
        if previous is not None:
            dt = now - previous[0]
            if previous[1][1] == 'flicker':
                key = (previous[1][0], previous[1][2])
                row = self.trials[key]
                row['intervals'] += 1
                row['elapsed_sec'] += dt
                row['max_interval_ms'] = max(row['max_interval_ms'], dt * 1000)
                if frame != previous[2] + 1:
                    row['frame_sequence_anomalies'] += 1
                if not .5 * self.period <= dt <= 1.5 * self.period:
                    row['abnormal_intervals'] += 1
                    row['estimated_skipped_slots'] += max(0, round(dt / self.period) - 1)
                if context != previous[1]:
                    row['complete'] = True
        if context[1] == 'flicker':
            key = (context[0], context[2])
            if key not in self.trials:
                self.trials[key] = dict(segment=context[0], trial=context[2], frames=0,
                    intervals=0, elapsed_sec=0., max_interval_ms=0., abnormal_intervals=0,
                    estimated_skipped_slots=0, frame_sequence_anomalies=0, complete=False)
            self.trials[key]['frames'] += 1

    def snapshot(self):
        trials = []
        for row in self.trials.values():
            rate = row['intervals']/row['elapsed_sec'] if row['elapsed_sec'] > 0 else None
            trials.append(dict(row, observed_rate_hz=rate,
                               rate_mismatch=bool(rate is not None and row['elapsed_sec'] >= .5
                                                  and abs(rate/self.refresh_hz - 1) > .02)))
        return dict(scheduler=self.scheduler, nominal_refresh_hz=self.refresh_hz,
                    swap_interval_requested=1, physical_onset_verified=False,
                    anomaly_action='record_only', phase_clock='perf_counter',
                    interval_limits_frames=[.5, 1.5],
                    rate_tolerance_fraction=.02,
                    frames=self.frames, recovery_requests=self.recovery_requests,
                    trials=trials)
