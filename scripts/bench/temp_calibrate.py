#!/usr/bin/env python3
"""Coolant temperature spot-check helper (runs on Windows, reads the
board over ssh).

The raw->Celsius conversion in UAPI.md is the factory B-equation (10k
B3380 NTC in a 10k divider behind a 1.3x gain stage, 10-bit ADC). This
tool collects reference points - a measured real temperature paired with
the machine's raw ADC readings - and fits a per-machine line to
cross-check that curve against a thermometer.

Usage:
  temp_calibrate.py watch                 live raw + current-formula C
  temp_calibrate.py point <measured_C>    record a calibration point
  temp_calibrate.py fit                   fit and print the calibration

Points accumulate in temp_calibration.json next to this script. Take at
least two points as far apart in temperature as practical (e.g. cold
machine in the morning, and warm after a fan-off soak with the flow
heater on).
"""
import json
import math
import os
import shlex
import subprocess
import sys
import time

HOST = os.environ.get('GF_HOST')
if not HOST:
    raise SystemExit('set GF_HOST to the machine IP address')
# ssh client used to reach the board; override for a wrapper, e.g.
# GF_SSH='wsl -d <distro> -- ssh'.
SSH = shlex.split(os.environ.get('GF_SSH', 'ssh'))
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_calibration.json')


def uapi_c(raw):
    """The UAPI.md factory conversion (B-equation NTC behind divider + gain)."""
    adc_f = 1024.0 * 1.3
    if raw <= 0 or raw >= adc_f:
        return float('nan')
    rinf = 10000.0 * math.exp(-3380.0 / 298.15)
    r = 10000.0 / (adc_f / raw - 1.0)
    return 3380.0 / math.log(r / rinf) - 273.15


def board(cmd):
    r = subprocess.run(SSH + ['-o', 'PreferredAuthentications=none',
                              'root@' + HOST, cmd],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


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
        print('raw1(down) raw2(up)   uapi-C down/up   (ctrl-C to stop)')
        while True:
            r1, r2 = raws(1, 0)
            print('  %6.1f   %6.1f      %.2f / %.2f'
                  % (r1, r2, uapi_c(r1), uapi_c(r2)))
            time.sleep(2)

    elif mode == 'point':
        measured = float(sys.argv[2])
        note = sys.argv[3] if len(sys.argv) > 3 else ''
        print('sampling raws (10 s)...')
        r1, r2 = raws()
        data = load()
        data['points'].append({'measured_c': measured, 'raw1': r1, 'raw2': r2,
                               'note': note, 'when': time.strftime('%Y-%m-%d %H:%M:%S')})
        save(data)
        print('recorded: measured %.2f C  raw1=%.1f raw2=%.1f  (%d points total)'
              % (measured, r1, r2, len(data['points'])))

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
