#!/usr/bin/env python3
"""Live-fire bench drills - Phases 4, 5, 6. Runs from a LAN host against
grblHAL over TCP (argv[1] or GF_HOST, port 23) and forgectrl over HTTP
(:8080). LIVE LASER: the operator must be armed with eye protection, a
fire watch, an extinguisher, and the exhaust running. Every drill waits
for the operator to press the physical arm button before the machine
fires; nothing here defeats that gate.

Drills (pass a name):
  witness   Phase 5 A-1/A-2/A-5: a short vector mark at S400. Samples
            forgectrl /status (emission_samples, lid_ir[], hv_current)
            and /cool/status (armed, fire_watch) at ~8 Hz through the
            job. PASS: emission_samples goes nonzero during the fire
            window and returns to 0; lid_ir peak recorded per channel
            vs the ambient baseline; hv_current range logged. Also
            asserts X-3: armed drops at Idle with the job close, not at
            +60 s.
  hold      Phase 4 G-10: arm + start a longer job, feed-hold mid-run,
            then hold. PASS: the disarm grace counts down in Hold and
            the window closes (armed -> false) without the job resuming.
  faultpos  Phase 6 G-2/G-3: after a run that was stopped by an
            underrun (position no longer trusted), a subsequent armed
            job must refuse to cut at the stale origin - the sender
            alarms and re-home is required. Reads homed via /status.

The G-4 arm-refuses-when-a-fire-gate-is-active drill is operator-manual
(kill the pump during the button wait); this harness prints the cue.
"""
import json
import os
import socket
import sys
import time
import urllib.request

HOST = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('GF_HOST')
if not HOST:
    raise SystemExit('usage: live_fire_drills.py <drill> [host]  (or set GF_HOST)')
PORT = 23
BASE = 'http://%s:8080' % HOST

# Ambient lid-IR baseline (2026-08-14, lid closed, idle): per-channel means.
IR_BASELINE = [37.3, 36.3, 39.5, 40.0]


def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=4) as r:
        return json.load(r)


class Grbl:
    def __init__(self, host, port):
        self.s = socket.create_connection((host, port), timeout=5)
        self.s.settimeout(0.2)
        self.buf = b''
        time.sleep(0.5)
        self.drain()

    def drain(self):
        try:
            while True:
                d = self.s.recv(4096)
                if not d:
                    break
                self.buf += d
        except socket.timeout:
            pass
        out, self.buf = self.buf, b''
        return out.decode('ascii', 'replace')

    def cmd(self, line, timeout=5.0):
        self.s.sendall(line.encode() + b'\n')
        deadline = time.time() + timeout
        text = ''
        while time.time() < deadline:
            text += self.drain()
            if 'ok' in text or 'error' in text or 'ALARM' in text:
                return text.strip()
            time.sleep(0.02)
        return '(timeout) ' + text.strip()

    def status(self):
        self.s.sendall(b'?')
        t = time.time() + 1.0
        text = ''
        while time.time() < t:
            text += self.drain()
            if '>' in text:
                break
            time.sleep(0.02)
        if '<' in text and '>' in text:
            return text[text.rfind('<'):text.rfind('>') + 1]
        return ''

    def state(self):
        st = self.status()
        return st[1:].split('|')[0] if st else ''

    def rt(self, ch):
        self.s.sendall(ch)

    def wait_state(self, want, timeout=60.0, poll=0.1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.state()
            if s.startswith(want):
                return s
            time.sleep(poll)
        return self.state()


def sample_forgectrl():
    """One combined /status + /cool/status sample, or None on error."""
    try:
        st = get_json('/status')
        cs = get_json('/cool/status')
    except Exception:
        return None
    return {
        't': time.time(),
        'kstate': st.get('state'),
        'emission': st.get('laser', {}).get('emission_samples'),
        'pgood': st.get('laser', {}).get('pgood_samples'),
        'faults': st.get('faults'),
        'hv': st.get('hv_current_raw'),
        'ir': st.get('lid_ir'),
        'armed': cs.get('armed'),
        'fire_watch': cs.get('fire_watch'),
        'verdict': cs.get('verdict'),
        'phase': cs.get('phase'),
        'reason': cs.get('reason'),
    }


def arm_cue():
    print('\n>>> OPERATOR: eye protection on, exhaust running, fire watch,')
    print('>>> extinguisher in reach, scrap under the head with room to move.')
    print('>>> The job is starting. The white button will light and the')
    print('>>> stream will BLOCK until you press the physical arm button.')
    print('>>> The machine fires only after your press.\n')


def run_and_sample(g, gcode_lines, sample_hz=8, overall_timeout=200):
    """Stream gcode; sample forgectrl through the whole arm -> fire ->
    disarm lifecycle. The arm phase (fan run + flow interrogation) plus
    the operator button wait present grblHAL as Idle, so completion must
    NOT trigger on an early Idle. Complete on one of:
      - real fire captured: emission was seen > 0, then grbl Idle > 3 s;
      - no-fire disarm: armed went True then False, grbl Idle, > 15 s in;
      - overall timeout.
    """
    samples = []
    period = 1.0 / sample_hz
    s0 = sample_forgectrl()
    if s0:
        samples.append(s0)
    for ln in gcode_lines:
        g.s.sendall(ln.encode() + b'\n')
    t_start = time.time()
    next_t = t_start
    seen_emission = False
    seen_armed = False
    disarmed_now = False
    idle_since = None
    while time.time() - t_start < overall_timeout:
        now = time.time()
        if now >= next_t:
            smp = sample_forgectrl()
            if smp:
                samples.append(smp)
                if smp['emission'] and smp['emission'] > 0:
                    seen_emission = True
                if smp['armed']:
                    seen_armed = True
                disarmed_now = seen_armed and not smp['armed']
            next_t = now + period
        st = g.state()
        if st.startswith('Idle'):
            if idle_since is None:
                idle_since = now
            idle_for = now - idle_since
            if seen_emission and idle_for > 3.0:
                break                       # captured the burn
            if disarmed_now and (now - t_start) > 15 and idle_for > 3.0:
                break                       # armed then disarmed, no fire
        else:
            idle_since = None
        time.sleep(0.05)
    return samples


def prepare(g):
    """Guarantee a clean Idle start: clear a latched Door hold (lid was
    opened to inspect) or an Alarm before the run."""
    st = g.status()
    if 'Door' in st or 'Hold' in st:
        g.rt(b'\x18')                       # soft reset clears the hold
        time.sleep(2)
        g.drain()
        st = g.status()
    if 'Alarm' in st:
        print('unlock: %s' % g.cmd('$X'))
        st = g.status()
    return st


def drill_witness(g):
    print('=== Phase 5 witness drill: S400 vector mark ===')
    print('connect: %s' % prepare(g))
    base = sample_forgectrl()
    print('pre-fire: %s' % base)
    arm_cue()
    # A small square outline at S400, motion-only feed so the fire window
    # is unambiguous. Absolute-relative: use G91 so no homing is needed.
    job = [
        'G91', 'G21',           # relative, mm
        'M4',                   # dynamic laser mode, spindle enable
        'S400',
        'G1 X20 F600',
        'G1 Y20 F600',
        'G1 X-20 F600',
        'G1 Y-20 F600',
        'M5',                   # laser off
        'G90',
        'M2',                   # program end: X-3 job-based disarm trigger
    ]
    samples = run_and_sample(g, job)
    # Analysis.
    emis = [s['emission'] for s in samples if s['emission'] is not None]
    peak_emis = max(emis) if emis else 0
    end_emis = emis[-1] if emis else None
    ir_peak = [0, 0, 0, 0]
    hv_vals = []
    for s in samples:
        if s['ir'] and len(s['ir']) == 4:
            for i in range(4):
                ir_peak[i] = max(ir_peak[i], s['ir'][i])
        if s['hv'] is not None:
            hv_vals.append(s['hv'])
    armed_seen = any(s['armed'] for s in samples)
    pgood_vals = [s['pgood'] for s in samples if s['pgood'] is not None]
    print('\n--- results ---')
    print('emission_samples: peak=%s end=%s (PASS if peak>0 and end==0)'
          % (peak_emis, end_emis))
    print('pgood_samples during job: peak=%s (>=128 = power-good)'
          % (max(pgood_vals) if pgood_vals else '-'))
    print('lid_ir peak=%s vs baseline=%s  delta=%s'
          % (ir_peak, IR_BASELINE,
             [round(ir_peak[i] - IR_BASELINE[i], 1) for i in range(4)]))
    print('hv_current range: %s..%s' % (min(hv_vals) if hv_vals else '-',
                                        max(hv_vals) if hv_vals else '-'))
    print('armed observed during job: %s' % armed_seen)
    # X-3: measure time-to-disarm after the job completes at Idle. The
    # job-based window (Phase 4) should disarm promptly at Idle entry,
    # not wait out the ~60 s laser_disarm_s grace.
    t0 = time.time()
    disarm_dt = None
    while time.time() - t0 < 75:
        s = sample_forgectrl()
        if s and not s['armed']:
            disarm_dt = time.time() - t0
            break
        time.sleep(1)
    print('X-3 time-to-disarm after Idle: %s s (job-based PASS if prompt, '
          'not ~60 s grace)'
          % (round(disarm_dt, 1) if disarm_dt is not None else '>75 (REVIEW)'))
    ok = peak_emis > 0 and end_emis == 0
    print('WITNESS emission %s' % ('PASS' if ok else 'REVIEW - see values above'))
    # Emit the recommended cool_fire_ir_delta floor.
    worst = max(ir_peak[i] - IR_BASELINE[i] for i in range(4))
    print('suggest cool_fire_ir_delta >= max(15, %.0f) once several jobs '
          'confirm the peak delta' % (2 * worst if worst > 0 else 15))
    return samples


def drill_hold(g):
    print('=== Phase 4 G-10 drill: disarm grace counts down in Hold ===')
    print('connect: %s' % prepare(g))
    arm_cue()
    # +X move at F300 (~5 mm/s). Held after ~2 s of motion (~10 mm),
    # so ~30 mm of +X clearance is plenty.
    job = ['G91', 'G21', 'M4', 'S400', 'G1 X40 F300']
    for ln in job:
        g.s.sendall(ln.encode() + b'\n')
    print('armed; waiting for motion to start (arm + your button press)...')
    st = g.wait_state('Run', 180)           # arming + button wait, then motion
    if not st.startswith('Run'):
        print('FAIL: motion never started (state=%s) - arm refused or no press'
              % st)
        g.cmd('M5', timeout=1)
        g.rt(b'\x18')
        return
    print('moving under laser: %s; feed-hold in 2 s' % st)
    time.sleep(2)
    g.rt(b'!')                      # feed hold mid-move
    st = g.wait_state('Hold', 5)
    print('feed-held mid-move: %s' % st)
    print('watching the disarm grace count down IN HOLD (not resuming)...')
    t0 = time.time()
    disarmed_at = None
    while time.time() - t0 < 120:
        s = sample_forgectrl()
        held = g.state().startswith('Hold')
        if s and not s['armed']:
            disarmed_at = time.time() - t0
            break
        if not held:
            print('note: left Hold (state=%s) before disarm' % g.state())
        time.sleep(1)
    # Recover: laser off, abort out of hold.
    g.cmd('M5', timeout=1)
    g.rt(b'\x18')                   # soft reset / abort out of hold
    time.sleep(1)
    print('G-10 disarmed in Hold after %s s (PASS if it disarms while held; '
          'the bug left it armed for hours)'
          % (round(disarmed_at, 1) if disarmed_at else 'NOT WITHIN 120 - REVIEW'))
    if 'Alarm' in g.status():
        g.cmd('$X')


def drill_faultpos(g):
    print('=== Phase 6 G-2/G-3 drill: stale origin refused after underrun ===')
    s = get_json('/status')
    print('homed=%s (an underrun should have cleared this)' % s.get('homed'))
    if s.get('homed'):
        print('NOTE: homed is still true - run the SIGSTOP/underrun drill '
              'first, then re-run this to confirm the refusal.')
        return
    print('attempting an armed cut at the stale origin - it must refuse/alarm')
    prepare(g)
    arm_cue()
    r = g.cmd('M4 S400', timeout=2)
    r2 = g.cmd('G1 X10 F300', timeout=3)
    st = g.state()
    print('controller response: %s / %s state=%s' % (r, r2, st))
    print('FAULTPOS %s' % ('PASS (refused/alarm at stale origin)'
          if ('error' in (r + r2).lower() or 'Alarm' in st) else
          'REVIEW - cut was accepted; check G-3 anchor invalidation'))
    g.cmd('M5', timeout=1)


def main():
    drill = sys.argv[1] if len(sys.argv) > 1 else ''
    drills = {'witness': drill_witness, 'hold': drill_hold,
              'faultpos': drill_faultpos}
    if drill not in drills:
        print(__doc__)
        return 2
    g = Grbl(HOST, PORT)
    try:
        drills[drill](g)
    finally:
        # Always leave the laser commanded off.
        try:
            g.cmd('M5', timeout=1)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
