#!/usr/bin/env python3
"""Characterize the coolant flow signature using the FACTORY temperature
curve, and recommend flow-fault thresholds.

The loop heater sits between the two water sensors; flowing coolant
carries its heat away, so downstream-minus-upstream settles at a small
stable delta. Stopping the pump lets that heat pool, and the delta
climbs. This measures both signatures and prints the separation.

Phases: baseline (heater off) -> flow (heater on, pump on) -> no-flow
(pump off) -> recovery (pump on). Restores heater off / pump on.

Run with the controller stopped, or accept that it will fight you: the
driver only writes the heater on M8/M9 transitions, so an idle driver
leaves this alone.
"""
import math
import os
import subprocess
import sys
import time

HOST = os.environ.get('GF_HOST')
if not HOST:
    raise SystemExit('set GF_HOST to the machine IP address')

# Factory B-equation conversion (see kernel-module-glowforge/UAPI.md).
F = 1024.0 * 1.3
RD = 10000.0
BETA = 3380.0
RINF = 10000.0 * math.exp(-3380.0 / 298.15)


def degc(raw):
    if raw <= 0 or raw >= F:
        return float('nan')
    r = RD / (F / raw - 1.0)
    return BETA / math.log(r / RINF) - 273.15


def board(cmd):
    r = subprocess.run(['wsl', '-d', 'forge-yocto', '--', 'ssh',
                        '-o', 'PreferredAuthentications=none',
                        'root@' + HOST, cmd],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def sample():
    out = board('cat /sys/glowforge/pic/water_temp_1 /sys/glowforge/pic/water_temp_2').split()
    if len(out) != 2:
        return None
    d, u = degc(int(out[0])), degc(int(out[1]))
    return d, u, d - u


DOWN_ABORT_C = 45.0   # never cook the loop while characterizing


def phase(tag, seconds, interval=10, settle=0):
    """Log a phase; return the deltas after the settle period."""
    t0 = time.time()
    keep = []
    while time.time() - t0 < seconds:
        s = sample()
        if s:
            el = time.time() - t0
            print('  %-7s t=%3.0fs  down=%5.2f  up=%5.2f  dT=%+5.2f'
                  % (tag, el, s[0], s[1], s[2]), flush=True)
            if el >= settle:
                keep.append(s[2])
            if s[0] >= DOWN_ABORT_C:
                print('  ABORT: downstream %.1f C >= %.1f C safety limit'
                      % (s[0], DOWN_ABORT_C), flush=True)
                board('echo 1 > /sys/glowforge/thermal/water_pump_on; '
                      'echo 0 > /sys/glowforge/thermal/heater_pwm')
                break
        time.sleep(interval)
    return keep


def stats(name, ds):
    if not ds:
        print('%s: no samples' % name)
        return None, None
    print('%s: n=%d  min=%+.2f  max=%+.2f  mean=%+.2f'
          % (name, len(ds), min(ds), max(ds), sum(ds) / len(ds)))
    return min(ds), max(ds)


heater_pct = int(sys.argv[1]) if len(sys.argv) > 1 else 10
heater_pwm = str(int(65535 * heater_pct / 100))

print('=== baseline: heater off, pump on (60 s)')
board('echo 1 > /sys/glowforge/thermal/water_pump_on; echo 0 > /sys/glowforge/thermal/heater_pwm')
base = phase('base', 60, 10, 30)
stats('baseline dT', base)

print('=== flow: heater %d%%, pump on (240 s; first 60 s ignored while dT establishes)' % heater_pct)
board('echo ' + heater_pwm + ' > /sys/glowforge/thermal/heater_pwm')
flow = phase('flow', 240, 10, 60)
fmin, fmax = stats('flow dT', flow)

print('=== no-flow: pump OFF, heater still on (150 s; first 20 s ignored)')
board('echo 0 > /sys/glowforge/thermal/water_pump_on')
noflow = phase('noflow', 150, 10, 20)
nmin, nmax = stats('no-flow dT', noflow)

print('=== recovery: pump on, heater off (90 s)')
board('echo 1 > /sys/glowforge/thermal/water_pump_on; echo 0 > /sys/glowforge/thermal/heater_pwm')
phase('recov', 90, 15)

print()
if fmax is not None and nmin is not None:
    print('flow band:    up to %+.2f C' % fmax)
    print('no-flow band: from %+.2f C' % nmin)
    if nmin > fmax:
        fault = (fmax + nmin) / 2.0
        print('separation:   %.2f C  -> suggested fault threshold %.2f C, re-arm %.2f C'
              % (nmin - fmax, fault, fault - 0.4))
    else:
        print('BANDS OVERLAP - flow detection unreliable at %d%% heater; try a higher duty'
              % heater_pct)
print('restored: pump on, heater off')
