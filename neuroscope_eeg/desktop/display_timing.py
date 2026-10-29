"""Bounded timing evidence; Qt buffer swaps are not physical photon measurements."""
import time


class DisplayTiming:
    def __init__(self, refresh_hz, timer_interval_ms):
        self.refresh_hz = refresh_hz
        self.timer_interval_ms = timer_interval_ms
        self.previous = {}
        self.rows = {}

    def observe(self, stream, now, context):
        segment, phase, trial = context
        for scope in ('all', f'{segment}/{phase}'):
            key = (stream, scope)
            row = self.rows.setdefault(key, dict(callbacks=0, intervals=0, elapsed_sec=0., max_interval_ms=0.,
                                                  long_intervals=0, estimated_skipped_slots=0))
            row['callbacks'] += 1
            previous = self.previous.get(key)
            # No intervals across distinct trials or a gap outside this phase.
            if previous and (scope == 'all' or previous[1] == context):
                dt = now - previous[0]
                if dt > 0:
                    expected = self.timer_interval_ms / 1000 if stream == 'timer' else 1 / self.refresh_hz
                    row['intervals'] += 1
                    row['elapsed_sec'] += dt
                    row['max_interval_ms'] = max(row['max_interval_ms'], dt * 1000)
                    if dt > expected * 1.5:
                        row['long_intervals'] += 1
                        row['estimated_skipped_slots'] += max(1, round(dt / expected) - 1)
            self.previous[key] = (now, context)

    def snapshot(self):
        rows = []
        for (stream, scope), row in self.rows.items():
            rows.append(dict(stream=stream, scope=scope, **row,
                             callback_rate_hz=row['intervals']/row['elapsed_sec'] if row['elapsed_sec'] else None,
                             mean_interval_ms=1000*row['elapsed_sec']/row['intervals'] if row['intervals'] else None))
        return dict(version=1, clock='perf_counter', clock_resolution_sec=time.get_clock_info('perf_counter').resolution,
                    nominal_refresh_hz=self.refresh_hz, timer_interval_ms=self.timer_interval_ms,
                    physical_onset_verified=False, interval_boundary_policy='within_same_trial_and_phase', rows=rows)
