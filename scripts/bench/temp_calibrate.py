#!/usr/bin/env python3
"""Coolant temperature spot-check helper (runs on the board or from a
host; gfbench: GF_HOST).

The raw->Celsius conversion in UAPI.md is the factory B-equation (10k
B3380 NTC in a 10k divider behind a 1.3x gain stage, 10-bit ADC). This
tool collects reference points - a measured real temperature paired with
the machine's raw ADC readings - and fits a per-machine line to
cross-check that curve against a thermometer.

Usage:
  temp_calibrate.py watch [seconds]            live raw + current-formula C
                                               (default 60 s)
  temp_calibrate.py point <measured_C> [note]  record a calibration point
  temp_calibrate.py fit                        fit and print the calibration

Points accumulate in temp_calibration.json in the bench data directory
(gfbench.data_path: next to this script, or FORGETEST_BENCH_DATA). Take
at least two points as far apart in temperature as practical (e.g. cold
machine in the morning, and warm after a fan-off soak with the flow
heater on).
"""
import json
import os
import sys
import time

from gfbench import board, degc, data_path

STORE = data_path('temp_calibration.json')


def uapi_c(raw):
    """The UAPI.md factory conversion (B-equation NTC behind divider + gain)."""
    return degc(raw)


def raws(samples=5, delay=1.0):
    """Average several readings of both sensors (ADC noise is real)."""
    acc1, acc2, n = 0, 0, 0
    for _ in range(samples):
        out = board('cat /sys/glowforge/pic/water_temp_1 /sys/glowforge/pic/water_temp_2').split()
        if len(out) == 2:
            acc1 += int(out[0]); acc2 += int(out[1]); n += 1
        time.sleep(delay)
    return (acc1 / n, acc2 / n) if n else (None, None)


def load():
    if os.path.exists(STORE):
        with open(STORE) as f:
            return json.load(f)
    return {'points': []}


def save(data):
    with open(STORE, 'w') as f:
        json.dump(data, f, indent=2)


def fit(points, key):
    """Least-squares line: measured_C = slope * raw + offset."""
    xs = [p[key] for p in points]
    ys = [p['measured_c'] for p in points]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None, None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return slope, my - slope * mx


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'watch'

    if mode == 'watch':
        seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
        print('raw1(down) raw2(up)   uapi-C down/up   (%.0f s)' % seconds)
        t0 = time.time()
        while time.time() - t0 < seconds:
            r1, r2 = raws(1, 0)
            if r1 is None:
                print('  (no reading)')
            else:
                print('  %6.1f   %6.1f      %.2f / %.2f'
                      % (r1, r2, uapi_c(r1), uapi_c(r2)), flush=True)
            time.sleep(2)

    elif mode == 'point':
        try:
            measured = float(sys.argv[2])
        except (IndexError, ValueError):
            print('point needs the thermometer reading in C (value)')
            return 2
        note = sys.argv[3] if len(sys.argv) > 3 else ''
        print('sampling raws (10 s)...', flush=True)
        r1, r2 = raws()
        if r1 is None:
            print('no readings from the machine')
            return 1
        data = load()
        data['points'].append({'measured_c': measured, 'raw1': r1, 'raw2': r2,
                               'note': note, 'when': time.strftime('%Y-%m-%d %H:%M:%S')})
        save(data)
        print('recorded: measured %.2f C  raw1=%.1f raw2=%.1f  (%d points total in %s)'
              % (measured, r1, r2, len(data['points']), STORE))

    elif mode == 'fit':
        data = load()
        pts = data['points']
        if len(pts) < 2:
            print('need at least 2 points (have %d)' % len(pts))
            return 1
        print('points:')
        for p in pts:
            print('  %6.2f C   raw1=%.1f raw2=%.1f   %s %s'
                  % (p['measured_c'], p['raw1'], p['raw2'], p['when'], p['note']))
        span = max(p['measured_c'] for p in pts) - min(p['measured_c'] for p in pts)
        print('\ntemperature span: %.2f C%s' % (span, '  (WARNING: <3 C span, fit is weak)' if span < 3 else ''))
        for key, label in (('raw1', 'downstream (water_temp_1)'), ('raw2', 'upstream (water_temp_2)')):
            slope, offset = fit(pts, key)
            print('\n%s:' % label)
            print('  fitted:  C = raw * %.6f + %.4f' % (slope, offset))
            for raw in (600, 650, 700, 750, 800):
                print('    raw %3d -> fitted %6.2f C   uapi %6.2f C   diff %+.2f'
                      % (raw, raw * slope + offset, uapi_c(raw),
                         (raw * slope + offset) - uapi_c(raw)))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
