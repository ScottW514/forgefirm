#!/usr/bin/env python3
"""Validate the flow check at a WARM loop baseline - the condition a
real job actually presents.

Every design-matrix run started near ambient (21-23 C). During a cut the
loop sits warmer, where heat loss to ambient is larger, which shrinks
the measured rise in BOTH the flow and no-flow cases and could compress
the margin the threshold depends on. This warms the loop with its own
heater (which plateaus near 28-29 C - the most it can reach unaided),
then runs the real check at 40% / 50 s with the cut-profile fans, and
alternates flow / no-flow so both cases see the same conditions.

Usage: flow_warm_validate.py [cycles_per_case]   (default 3)
"""
import json
import math
import os
import shlex
import statistics
import subprocess
import sys
import time

HOST = os.environ.get('GF_HOST')
if not HOST:
    raise SystemExit('set GF_HOST to the machine IP address')
# ssh client used to reach the board; override for a wrapper, e.g.
# GF_SSH='wsl -d <distro> -- ssh'.
SSH = shlex.split(os.environ.get('GF_SSH', 'ssh'))
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'flow_warm_results.json')

F = 1024.0 * 1.3
RD, BETA = 10000.0, 3380.0
RINF = 10000.0 * math.exp(-3380.0 / 298.15)

DUTY = 40
CHECK_S = 50
THRESHOLD = 13.7
WARM_TARGET_C = 25.5        # what a ~19-20 C room permits at 50% duty
WARM_MAX_S = 780
ABORT_C = 48.0

FANS_RUN = ('echo 65535 > /sys/glowforge/thermal/exhaust_pwm; '
            'echo 43278 > /sys/glowforge/thermal/intake_pwm')
FANS_OFF = ('echo 0 > /sys/glowforge/thermal/exhaust_pwm; '
            'echo 0 > /sys/glowforge/thermal/intake_pwm')


def degc(raw):
    raw = float(raw)
    if raw <= 1.0 or raw >= F:
        return float('nan')
    r = RD / (F / raw - 1.0)
    return BETA / math.log(r / RINF) - 273.15


def board(cmd, timeout=120):
    r = subprocess.run(SSH + ['-o', 'PreferredAuthentications=none',
                              'root@' + HOST, cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout


_last_good = (22.0, 22.0)


def temps():
    """Sanity-guarded read. A single glitched sysfs value used to map to
    ~109 C and trip the safety abort, silently ending the warm phase
    after one iteration - which wasted two whole validation runs."""
    global _last_good
    o = board('cat /sys/glowforge/pic/water_temp_1 /sys/glowforge/pic/water_temp_2').split()
    if len(o) != 2:
        return _last_good
    d, u = degc(o[0]), degc(o[1])
    if any(x != x or x < 5.0 or x > 60.0 for x in (d, u)):
        return _last_good
    _last_good = (d, u)
    return d, u


def heater(pct):
    board('echo %d > /sys/glowforge/thermal/heater_pwm' % int(65535 * pct / 100))


def pump(on):
    board('echo %d > /sys/glowforge/thermal/water_pump_on' % (1 if on else 0))


def warm_to(target, log):
    """Warm with the loop heater, pump circulating, fans off."""
    pump(True)
    board(FANS_OFF)
    # 50% is the practical ceiling: the downstream sensor sits AT the
    # heater element, so 100% drives it past 50 C within 30 s while the
    # bulk has barely moved. At 50% it plateaus near 41 C, leaving the
    # bulk free to climb for as long as we let it.
    heater(50)
    t0 = time.time()
    # Plateau detection compares against the reading two minutes back:
    # with the pump circulating, the bulk climbs only ~0.5-0.8 C/min, so
    # a per-sample threshold mistakes normal warming for a plateau (it
    # did exactly that on the first attempt and the whole run executed
    # at ambient).
    hist = []
    while time.time() - t0 < WARM_MAX_S:
        d, u = temps()
        el = (time.time() - t0) / 60
        if u >= target:
            log('    warm target reached: up=%.2f at %.1f min' % (u, el))
            break
        if d >= ABORT_C:
            log('    warm abort: downstream %.2f at %.1f min' % (d, el))
            break
        hist.append(u)
        if len(hist) % 4 == 0:
            log('      warming: %.1f min  down=%.2f  up=%.2f' % (el, d, u))
        if len(hist) > 8 and u - hist[-9] < 0.3:
            log('    (warming plateaued at %.2f C after %.1f min)' % (u, el))
            break
        time.sleep(15)
    heater(0)
    pump(True)
    time.sleep(45)          # mix so the bulk is uniform before measuring
    d, u = temps()
    log('    warmed to down=%.2f up=%.2f in %.1f min' % (d, u, (time.time() - t0) / 60))
    return u


def check(flow, log):
    """The real check: fans at cut profile, 40% heater, 50 s."""
    board(FANS_RUN)
    pump(flow)
    time.sleep(3)
    d0, u0 = temps()
    heater(DUTY)
    raw = board('python3 /usr/share/forgetest/bench/flow_sampler.py %d 1.0' % CHECK_S, timeout=CHECK_S + 60)
    heater(0)
    pump(True)

    series = []
    for line in raw.strip().splitlines():
        try:
            el, r1, r2 = line.split(',')
            series.append((float(el), degc(r1), degc(r2)))
        except ValueError:
            continue
    if not series:
        return None
    el, d, u = series[-1]
    return {'flow': flow, 'base_up': u0, 'base_down': d0, 'down_rise': d - d0,
            'up_rise': u - u0, 'peak_down': max(s[1] for s in series), 't': el}


def main():
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    logf = open(os.path.join(HERE, 'flow_warm_log.txt'), 'a')

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + '\n')
        logf.flush()

    log('=== warm-baseline validation %s  duty=%d%% window=%ds threshold=%.1f'
        % (time.strftime('%Y-%m-%d %H:%M:%S'), DUTY, CHECK_S, THRESHOLD))
    board('pkill -x grblHAL_glowfor; sleep 1; true')

    runs = []
    try:
        for c in range(cycles):
            for flow in (True, False):
                log('  cycle %d/%d  %s' % (c + 1, cycles, 'FLOW' if flow else 'NO-FLOW'))
                warm_to(WARM_TARGET_C, log)
                r = check(flow, log)
                if r:
                    r['cycle'] = c
                    runs.append(r)
                    verdict = 'FAULT' if r['down_rise'] > THRESHOLD else 'ok'
                    correct = (verdict == 'FAULT') == (not flow)
                    log('    base_up=%.2f  down_rise=%.2f  -> %-5s  %s  (peak down %.1f C)'
                        % (r['base_up'], r['down_rise'], verdict,
                           'CORRECT' if correct else '*** WRONG ***', r['peak_down']))
                    json.dump(runs, open(RESULTS, 'w'), indent=1)
    finally:
        heater(0)
        pump(True)
        board(FANS_OFF)

    fv = [r['down_rise'] for r in runs if r['flow']]
    nv = [r['down_rise'] for r in runs if not r['flow']]
    log('')
    log('=== warm-baseline results (baselines %.1f - %.1f C)'
        % (min(r['base_up'] for r in runs), max(r['base_up'] for r in runs)))
    if len(fv) >= 2 and len(nv) >= 2:
        log('  flow    n=%d  mean %.2f  sd %.2f  max %.2f' % (len(fv), statistics.mean(fv), statistics.stdev(fv), max(fv)))
        log('  no-flow n=%d  mean %.2f  sd %.2f  min %.2f' % (len(nv), statistics.mean(nv), statistics.stdev(nv), min(nv)))
        log('  worst-case margin: %+.2f C   threshold %.1f sits %+.2f above flow max, %+.2f below no-flow min'
            % (min(nv) - max(fv), THRESHOLD, THRESHOLD - max(fv), min(nv) - THRESHOLD))
    wrong = [r for r in runs if ((r['down_rise'] > THRESHOLD) != (not r['flow']))]
    log('  misclassified: %d of %d' % (len(wrong), len(runs)))

    board('cd /data && GFSINK=/dev/glowforge nohup grblHAL_glowforge -p 23 '
          '-e /data/EEPROM-glowforge.DAT > /data/glowforge.log 2>&1 & sleep 2; true')
    log('controller restarted')
    logf.close()


if __name__ == '__main__':
    sys.exit(main())
