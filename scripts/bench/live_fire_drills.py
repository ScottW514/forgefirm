#!/usr/bin/env python3
"""Live-fire bench drills - Phases 4, 5, 6. Runs on the board (the bench
page) or from a LAN host, against grblHAL over TCP (port 23) and
forgectrl over HTTP (:8080); the machine is GF_HOST, default 127.0.0.1.
LIVE LASER: the operator must be armed with eye protection, a fire
watch, an extinguisher, and the exhaust running. Every drill waits for
the operator to press the physical arm button before the machine fires;
nothing here defeats that gate.

Usage: live_fire_drills.py <drill> [arg] [F]  (ircut/pthresh take S,
       dladder takes the base period in machine ticks, pcurve takes
       F, the line length and an optional rung list)

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
  ircut     Lid-IR fire characterization at cutting power: a 30 mm
            square at S<power> (default 1000 = full) and F<feed>
            (default 300) on scrap, sampled like `witness`. Prints the
            per-channel peak delta over the ambient baseline and the
            engine's own "run telemetry" line is the record. Run it
            >= 3 times on representative material; the highest peak
            delta sizes cool_fire_ir_delta.
              ircut [S] [F]             e.g. ircut 1000 300
  pthresh   Laser power-threshold ladder: one line per power level on
            scrap, climbing from 2 % to 30 % of full, at constant power
            (M3) so nothing scales the duty with velocity. The ladder
            separates two thresholds that are far apart: the discharge
            strikes at a duty well below the one the tube lases at, and
            the rungs between them show only a spot at the line start
            (the strike transient) with a dark line after it. The
            lowest rung that leaves a CONTINUOUS mark is the lasing
            threshold, and because $35 is a percent of full duty and
            the rungs are percents of $30 with $31 = 0, that rung's
            percent IS the $35 value. Requires $35 = 0 for the run: a
            floor already in place lifts every rung and hides both
            thresholds.
              pthresh [Smax] [F]        e.g. pthresh 1000 300
  dladder   Density ladder for the FIRE-bit dose model: one line per
            dose level on scrap, 5 % to 100 %, at constant power (M3)
            so nothing scales the dose with velocity. Under this model
            the duty is pinned at full and the level is carried by how
            many ticks of each base period fire, so a rung's burst is
            density x period - and the base period is the parameter the
            host cannot choose for you. Run it at 20, then 40, then 10
            on the same material: 20 ticks is 710 us, the factory's
            ~1.43 kHz, and 40 and 10 bracket it. Two questions the
            material answers: does mark depth track density linearly,
            and how short a burst still marks. Requires
            laser_power_model = density; reads $30/$31/$35/$36 and
            reports the mapping, so a run with a density floor set shows
            what a shipped machine would actually emit. Sets
            laser_pulse_ticks itself when run on the board.
              dladder [period] [F]      e.g. dladder 20 300
  pcurve    Laser performance-curve ladder, both instruments: one line
            per level at constant feed (default F600, 10 mm/s, 100 mm),
            M3 constant power, the laser off between rungs and a
            mid-ladder rung repeated at the end as the drift witness. Reads
            the HV current and the head thermopile (a scatter detector
            in the beam path upstream of the final mirror, so it sees
            the beam, not the material) straight from sysfs at ~25 Hz
            while the machine runs, brackets each rung on the
            controller's Run/Idle states, and reports per rung the
            current (mean, spread, max, CLIPPED at 1023), the thermopile
            delta over its laser-off baseline with its in-line drift,
            the digital flag's duty and the coolant temperature; then
            the normalized curve, a monotonicity check, a straight-line
            fit with its x-intercept as the measured threshold, and the
            repeat-rung comparison. Rungs follow laser_power_model:
            analog 16..100 % of duty (dense at the knee), density
            1..100 %; a comma list overrides. Records the actual level
            each S lands on from $30/$31/$35/$36; measuring the curve
            itself wants $35 = 0. JSON record (with the raw trace) in
            FORGETEST_BENCH_DATA, else /tmp. Runs on the board for the
            thermopile; from a host it falls back to /status (current
            only, no curve). Reaches FULL power for 10 s per line.
              pcurve [F] [len] [pcts]   e.g. pcurve 600 100 16,20,30,50,100
  m5dark    The rapids after an M5 ship dark: one 20 mm line at M3 S400,
            M5, a dwell, a rapid back over the line, a dwell, a rapid
            forward, a dwell, M2. Samples sysfs at 25 Hz (board only):
            PASS when the current shows exactly one discharge segment,
            reads dark after the M5, and laser_on_sampled never goes
            nonzero again after its first zero past the line. Prints the
            9 s after the line at 40 ms steps. The catalog's
            laser.m5-rapid-dark is its port.
  expstop   Armed kill on the EXPECTED-stop path: start a mark job,
            then mid-burn POST /controller/stop (the supervisor stops
            the controller: SIGTERM, reap, exit safing). PASS: emission
            drops to 0 within a few samples of the stop and stays 0,
            the kernel is not running, and POST /controller/start
            is a SEPARATE step (`ctrlstart`, run after the operator has
            judged the stop). Needs the panel token: GF_TOKEN, or
            /data/forgefirm/panel.token when running on the board.
  ctrlstart POST /controller/start after an expstop; no motion, no laser.

The G-4 arm-refuses-when-a-fire-gate-is-active drill is operator-manual
(kill the pump during the button wait); this harness prints the cue.
"""
import json
import os
import socket
import sys
import time
import urllib.request

HOST = os.environ.get('GF_HOST') or '127.0.0.1'
PORT = 23
BASE = 'http://%s:8080' % HOST


def panel_token():
    tok = os.environ.get('GF_TOKEN', '')
    if tok:
        return tok
    try:
        with open('/data/forgefirm/panel.token') as f:
            return f.read().strip()
    except OSError:
        return ''

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


def drill_ircut(g):
    power = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    feed = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    print('=== lid-IR characterization: S%d F%d 30 mm square ===' % (power, feed))
    print('connect: %s' % prepare(g))
    base = sample_forgectrl()
    print('pre-fire: %s' % base)
    arm_cue()
    job = [
        'G91', 'G21', 'M4', 'S%d' % power,
        'G1 X30 F%d' % feed, 'G1 Y30 F%d' % feed,
        'G1 X-30 F%d' % feed, 'G1 Y-30 F%d' % feed,
        'M5', 'G90', 'M2',
    ]
    samples = run_and_sample(g, job, overall_timeout=400)
    ir_peak = [0, 0, 0, 0]
    ir_min = [10 ** 6] * 4
    hv_vals = []
    emis = []
    fw = set()
    for s in samples:
        if s['ir'] and len(s['ir']) == 4:
            for i in range(4):
                ir_peak[i] = max(ir_peak[i], s['ir'][i])
                ir_min[i] = min(ir_min[i], s['ir'][i])
        if s['hv'] is not None:
            hv_vals.append(s['hv'])
        if s['emission'] is not None:
            emis.append(s['emission'])
        if s['fire_watch']:
            fw.add(s['fire_watch'])
    print('\n--- results ---')
    print('samples: %d  emission peak=%s  fire_watch states=%s'
          % (len(samples), max(emis) if emis else '-', sorted(fw)))
    delta = [round(ir_peak[i] - IR_BASELINE[i], 1) for i in range(4)]
    print('lid_ir min=%s peak=%s baseline=%s  peak delta=%s'
          % (ir_min, ir_peak, IR_BASELINE, delta))
    print('hv_current range: %s..%s' % (min(hv_vals) if hv_vals else '-',
                                        max(hv_vals) if hv_vals else '-'))
    worst = max(delta)
    print('worst peak delta this job: %s counts -> cool_fire_ir_delta must sit '
          'above the worst across ALL jobs (>= 2x it, never < 15)' % worst)
    print('the engine logged its own "run telemetry: lid IR ..." line for this job')
    return samples


# Power ladder for `pthresh`, in percent of full duty. The spacing is fine
# at the bottom because that is where the tube stops striking.
PTHRESH_PCT = (2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 25, 30)
PTHRESH_LEN = 25.0                      # mm of burn per rung
PTHRESH_PITCH = 3.0                     # mm between rungs


def drill_pthresh(g):
    smax = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    feed = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    levels = [(p, max(1, int(round(smax * p / 100.0)))) for p in PTHRESH_PCT]
    print('=== laser power threshold ladder: %d rungs, F%d, %g mm each ==='
          % (len(levels), feed, PTHRESH_LEN))
    print('constant power (M3): the commanded duty is the tested duty.')
    print('PRECONDITION: $35 must be 0 for this run. A floor already in')
    print('place lifts every rung and the threshold cannot be read.')
    print('rungs (drawn in order, alternating direction, +Y between):')
    for i, (pct, s) in enumerate(levels):
        print('  %2d: %2d%% -> S%d' % (i + 1, pct, s))
    print('connect: %s' % prepare(g))
    base = sample_forgectrl()
    print('pre-fire: %s' % base)
    arm_cue()
    print('>>> This ladder reaches %d%% of full power - use scrap you are'
          % PTHRESH_PCT[-1])
    print('>>> willing to cut through.\n')
    job = ['G91', 'G21', 'M3']
    for i, (_pct, s) in enumerate(levels):
        job.append('S%d' % s)
        job.append('G1 X%g F%d' % (PTHRESH_LEN if i % 2 == 0 else -PTHRESH_LEN,
                                   feed))
        job.append('G0 Y%g' % PTHRESH_PITCH)
    job += ['M5', 'G90', 'M2']
    samples = run_and_sample(g, job, overall_timeout=600)
    hv_vals = [s['hv'] for s in samples if s['hv'] is not None]
    emis = [s['emission'] for s in samples if s['emission'] is not None]
    print('\n--- results ---')
    print('samples: %d  emission peak=%s' % (len(samples),
                                             max(emis) if emis else '-'))
    print('hv_current range: %s..%s' % (min(hv_vals) if hv_vals else '-',
                                        max(hv_vals) if hv_vals else '-'))
    if samples:
        t0 = samples[0]['t']
        print('hv_current trace (t s : raw) - the discharge current is the')
        print('electrical witness of striking, and it lifts off baseline')
        print('well below the rung that marks. Read it for the rung')
        print('boundaries: the laser-off G0 between rungs reads 0, so the')
        print('runs of nonzero current count the rungs that struck at all.')
        line = []
        for s in samples:
            if s['hv'] is None:
                continue
            line.append('%5.1f:%s' % (s['t'] - t0, s['hv']))
            if len(line) == 8:
                print('  ' + '  '.join(line))
                line = []
        if line:
            print('  ' + '  '.join(line))
    print('\nRead the material: count rungs from the FIRST one drawn. The')
    print('lowest rung carrying a CONTINUOUS mark is the lasing threshold;')
    print('set $35 to that rung\'s percent. A rung showing only a spot at')
    print('the start of its line struck but did not sustain - it is below')
    print('the threshold, not at it. Note the emission counter proves the')
    print('safety chain asserted LASER_ON, not that the tube lased - only')
    print('the mark and the discharge current say that.')
    return samples


# --- density ladder -------------------------------------------------------

# Dose levels in percent of full, weighted to the bottom: with a density
# floor set, what matters is whether the lowest levels a user can dial in
# still mark, not how the top half behaves.
DLADDER_PCT = (1, 2, 5, 10, 20, 40, 70, 100)
DLADDER_LEN = 25.0                      # mm of burn per rung
DLADDER_PITCH = 3.0                     # mm between rungs
STREAM_RATE_HZ = 28160                  # machine tick (GFSINK_RATE default)
PWM_PERIOD = 127                        # 7-bit power byte against PWMSAR
CONF = os.environ.get('GFHOME_CONF') or '/data/forgefirm.conf'
PULSE_MIN_KEY = 'laser_pulse_min_ticks'
PULSE_MIN_DEFAULT = 3                   # glowforge_laser.c PULSE_MIN_TICKS_DEFAULT


def conf_get(key):
    """One key from the shared machine config, or None."""
    try:
        with open(CONF) as f:
            for line in f:
                head = line.split('#', 1)[0]
                if '=' in head:
                    k, v = head.split('=', 1)
                    if k.strip() == key:
                        return v.strip()
    except OSError:
        return None
    return None


def conf_set(key, val):
    """Set one key, preserving every other line. False when the config is
    not ours to write - running from a LAN host, say."""
    try:
        with open(CONF) as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    out, done = [], False
    for line in lines:
        head = line.split('#', 1)[0]
        if '=' in head and head.split('=', 1)[0].strip() == key:
            if done:
                continue
            out.append('%s = %s' % (key, val))
            done = True
        else:
            out.append(line)
    if not done:
        out.append('%s = %s' % (key, val))
    try:
        mode = os.stat(CONF).st_mode & 0o777
        with open(CONF + '.tmp', 'w') as f:
            f.write('\n'.join(out) + '\n')
        os.chmod(CONF + '.tmp', mode)
        os.replace(CONF + '.tmp', CONF)
    except OSError:
        return False
    return True


def grbl_setting(g, key):
    """One $-setting as a float, read from the controller."""
    for line in g.cmd('$$', timeout=8.0).splitlines():
        line = line.strip()
        if line.startswith(key + '='):
            try:
                return float(line.split('=', 1)[1])
            except ValueError:
                return None
    return None


def drill_dladder(g):
    period = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    feed = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    if period < 1:
        print('period must be at least 1 machine tick')
        return 2

    print('=== density ladder: %d rungs, base period %d ticks, F%d, %g mm each ==='
          % (len(DLADDER_PCT), period, feed, DLADDER_LEN))

    # Preconditions. The model is read at each arm, so it must already be
    # selected; the floor must be gone, or every rung is lifted off the
    # bottom of the range this drill exists to explore.
    # Density is the shipped default, so an absent key selects it; only an
    # explicit analog selection is a refusal.
    model = conf_get('laser_power_model') or 'density'
    if model != 'density':
        print('PRECONDITION FAILED: laser_power_model is %r, need "density"'
              % (model,))
        print('(or the key absent, which selects it). The model is read at')
        print('each arm, so this key needs no controller restart.')
        return 2
    print('dose model: density (%s)'
          % ('set in ' + CONF if conf_get('laser_power_model') else 'driver default'))
    # The core maps S onto the level this model renders as density, and
    # $35/$36 are its floor and ceiling. Read them rather than assuming:
    # with a floor set, the ladder is testing the shipping mapping, and
    # every rung sits higher than its commanded percent.
    floor = grbl_setting(g, '$35')
    ceil = grbl_setting(g, '$36')
    rpm_max = grbl_setting(g, '$30')
    rpm_min = grbl_setting(g, '$31')
    if None in (floor, ceil, rpm_max, rpm_min) or rpm_max <= rpm_min:
        print('PRECONDITION FAILED: cannot read $30/$31/$35/$36 (%s/%s/%s/%s)'
              % (rpm_max, rpm_min, floor, ceil))
        return 2
    min_value = int(PWM_PERIOD * floor / 100.0)
    max_value = int(PWM_PERIOD * ceil / 100.0)
    gradient = (max_value - min_value) / (rpm_max - rpm_min)
    print('mapping: $30=%g $31=%g $35=%g $36=%g -> density %.1f%%..%.1f%%'
          % (rpm_max, rpm_min, floor, ceil,
             100.0 * min_value / PWM_PERIOD, 100.0 * max_value / PWM_PERIOD))
    if floor > 0.0:
        print('a floor is set, so the rungs below it all land on it - that is')
        print('the shipping mapping, not the raw range.')
    if conf_set('laser_pulse_ticks', str(period)):
        print('laser_pulse_ticks = %d (written to %s)' % (period, CONF))
    else:
        have = conf_get('laser_pulse_ticks')
        if have != str(period):
            print('PRECONDITION FAILED: cannot write %s from here, and' % CONF)
            print('laser_pulse_ticks is %r, not %d. Set it on the board.'
                  % (have, period))
            return 2
        print('laser_pulse_ticks already %d' % period)

    # What each rung actually emits. The on-count is dithered between
    # adjacent integers, so the burst below is the mean.
    min_ticks = int(conf_get(PULSE_MIN_KEY) or PULSE_MIN_DEFAULT)
    if min_ticks < 1:
        min_ticks = 1
    print('period %d ticks = %.0f us at %d Hz -> %.0f Hz pulse rate'
          % (period, period * 1e6 / STREAM_RATE_HZ, STREAM_RATE_HZ,
             STREAM_RATE_HZ / float(period)))
    print('minimum pulse %d ticks = %.0f us (%s): below it the model skips'
          % (min_ticks, min_ticks * 1e6 / STREAM_RATE_HZ,
             PULSE_MIN_KEY if conf_get(PULSE_MIN_KEY) else 'driver default'))
    print('periods and carries the debt, so the pulse never falls under it.')
    print('rungs (drawn in order, alternating direction, +Y between):')
    levels = []
    for pct in DLADDER_PCT:
        sval = int(round(rpm_max * pct / 100.0))
        level = int((sval - rpm_min) * gradient) + min_value
        level = min(level, max_value)
        dens = level / float(PWM_PERIOD)
        on = dens * period
        levels.append((pct, sval, dens))
        # The on-count is a whole number of ticks, dithered between the
        # two nearest, so quote the pulse the tube actually sees. Below
        # one tick per period the pulse stays one tick and periods are
        # skipped instead - that is the short end this drill is for.
        lo = int(on)
        tick_us = 1e6 / STREAM_RATE_HZ
        if on < min_ticks:
            # Below the minimum the model skips periods and carries the
            # debt, so the pulse holds at the minimum and the rate drops.
            burst = '%d ticks (%.0f us) every %.1f periods (%.0f Hz)' % (
                min_ticks, min_ticks * tick_us, min_ticks / on,
                STREAM_RATE_HZ / float(period) * on / min_ticks)
        elif on == lo:
            burst = '%d ticks (%.0f us)' % (lo, lo * tick_us)
        else:
            burst = '%d-%d ticks (%.0f-%.0f us)' % (lo, lo + 1, lo * tick_us,
                                                    (lo + 1) * tick_us)
        print('  %3d%% -> S%-4d  density %.4f  %5.2f on-ticks  pulse %s'
              % (pct, sval, dens, on, burst))
    print('connect: %s' % prepare(g))
    base = sample_forgectrl()
    print('pre-fire: %s' % base)
    arm_cue()
    print('>>> This ladder reaches FULL dose - use scrap you are willing')
    print('>>> to cut through.\n')

    job = ['G91', 'G21', 'M3']
    for i, (_pct, sval, _d) in enumerate(levels):
        job.append('S%d' % sval)
        job.append('G1 X%g F%d' % (DLADDER_LEN if i % 2 == 0 else -DLADDER_LEN,
                                   feed))
        job.append('G0 Y%g' % DLADDER_PITCH)
    job += ['M5', 'G90', 'M2']
    samples = run_and_sample(g, job, overall_timeout=600)

    emis = [s['emission'] for s in samples if s['emission'] is not None]
    hv_vals = [s['hv'] for s in samples if s['hv'] is not None]
    print('\n--- results ---')
    print('samples: %d  emission peak=%s' % (len(samples),
                                             max(emis) if emis else '-'))
    print('hv_current range: %s..%s' % (min(hv_vals) if hv_vals else '-',
                                        max(hv_vals) if hv_vals else '-'))
    if samples:
        t0 = samples[0]['t']
        print('hv_current trace (t s : raw) - the laser-off G0 between rungs')
        print('reads 0, so the runs of nonzero current count the rungs that')
        print('struck, and their level tracks the dose of each:')
        line = []
        for smp in samples:
            if smp['hv'] is None:
                continue
            line.append('%5.1f:%s' % (smp['t'] - t0, smp['hv']))
            if len(line) == 8:
                print('  ' + '  '.join(line))
                line = []
        if line:
            print('  ' + '  '.join(line))
    print('Check the controller said "laser armed (density)" - a plain')
    print('"laser armed" means the analog path ran and this is a duty')
    print('ladder, not a density one.')
    print('\nRead the material: count rungs from the FIRST one drawn.')
    print('Two readings, and the second is the one only the bench can give:')
    print(' 1. LINEARITY - does depth/darkness track the density column')
    print('    above, or does the low end mark harder than its share? Every')
    print('    burst restarts the discharge, so each carries the strike')
    print('    transient, and dose per burst need not scale with its length.')
    print(' 2. THE SHORT END - the lowest rung that still marks cleanly. Its')
    print('    burst length in us is the number to keep; a rung that stops')
    print('    marking sets the floor this base period can reach.')
    print('The base period does not decide the low end: below the minimum')
    print('the pulse interval is min_ticks x tick / density, which the')
    print('period cancels out of. What sets the bottom is the density')
    print('floor ($35), so a rung that fails is telling you to raise it.')
    return samples


# --- performance curve ladder ---------------------------------------------

# One line per level at constant feed, two instruments read through each:
# the HV current (the supply's curve under analog; presence only under
# density, where every pulse is full current) and the head thermopile, a
# scatter detector in the beam path upstream of the final mirror, so it
# reads the beam and not the material. Rungs are percents of full. The
# analog list is dense at the knee where the tube starts to lase; the
# density list is weighted to the bottom, where the per-pulse strike
# deficit lives.
PCURVE_ANALOG_PCT = (16, 18, 20, 23, 26, 30, 35, 42, 50, 60, 72, 85, 100)
PCURVE_DENSITY_PCT = (1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 80, 100)
PCURVE_FEED = 600                       # mm/min: 10 mm/s
PCURVE_LEN = 100.0                      # mm of burn per rung
PCURVE_PITCH = 3.0                      # mm between rungs (+X)
PCURVE_GAP_S = 4.0                      # laser-off settle before each rung
PCURVE_GAP_SKIP_S = 1.5                 # of which the first part still decays
PCURVE_SAMPLE_HZ = 25                   # sysfs sampler target rate
PCURVE_TRIM_HEAD_S = 1.0                # dropped from the start of each line
PCURVE_TRIM_TAIL_S = 0.5                # dropped from its end
SYSFS = '/sys/glowforge'
HV_FULL_SCALE = 1023                    # the PIC ADC's top count
# (key, sysfs attribute) per sampled channel.
PCURVE_CHANNELS = (
    ('hv', 'pic/hv_current'),
    ('tp', 'head/beam_detect_analog'),
    ('tpd', 'head/beam_detect_digital'),
    ('lon', 'cnc/laser_on_sampled'),
    ('wt1', 'pic/water_temp_1'),
    ('wt2', 'pic/water_temp_2'),
    ('pt', 'pic/pwr_temp'),
)


class Sampler:
    """Reads the pcurve channels in a thread. On the board they come
    straight from sysfs, each read a live bus transaction, so the achieved
    rate is whatever the PIC (SPI) and head (I2C) buses allow and it is
    reported rather than assumed. From a host the only source is
    forgectrl's /status at ~8 Hz, which carries the current and nothing
    the thermopile needs."""

    def __init__(self, hz):
        import threading
        self.local = os.path.isdir(SYSFS)
        self.period = 1.0 / (hz if self.local else 8)
        self.samples = []
        self.errors = 0
        self._stop = threading.Event()
        self._thr = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thr.start()

    def stop(self):
        self._stop.set()
        self._thr.join(timeout=3)

    def _read_sysfs(self):
        smp = {'t': time.time()}
        for key, attr in PCURVE_CHANNELS:
            try:
                with open(os.path.join(SYSFS, attr)) as f:
                    smp[key] = int(f.read().strip())
            except (OSError, ValueError):
                smp[key] = None
                self.errors += 1
        return smp

    def _read_status(self):
        st = sample_forgectrl()
        smp = dict((key, None) for key, _attr in PCURVE_CHANNELS)
        smp['t'] = time.time()
        if st is None:
            self.errors += 1
            return smp
        smp['hv'] = st['hv']
        smp['lon'] = st['emission']
        return smp

    def _run(self):
        read = self._read_sysfs if self.local else self._read_status
        next_t = time.time()
        while not self._stop.is_set():
            self.samples.append(read())
            next_t += self.period
            delay = next_t - time.time()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.time()

    def rate(self):
        if len(self.samples) < 2:
            return 0.0
        span = self.samples[-1]['t'] - self.samples[0]['t']
        return (len(self.samples) - 1) / span if span > 0 else 0.0


def _stats(vals):
    n = len(vals)
    if not n:
        return {'n': 0, 'mean': None, 'sd': None, 'min': None, 'max': None}
    mean = sum(vals) / float(n)
    var = sum((v - mean) ** 2 for v in vals) / float(n)
    return {'n': n, 'mean': mean, 'sd': var ** 0.5, 'min': min(vals),
            'max': max(vals)}


def _window(samples, t0, t1, key):
    return [s[key] for s in samples
            if t0 <= s['t'] < t1 and s.get(key) is not None]


def _linfit(xs, ys):
    """Least squares y = a + b x; (a, b, r2), or None below two points."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / float(n)
    my = sum(ys) / float(n)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return a, b, r2


def _degc(raw):
    """The factory coolant conversion when gfbench is importable (on the
    board, or with GF_HOST set), else None and the raw count is quoted.
    The helper lives beside this file in the repo and under the bench
    directory on the dev image; a copy staged elsewhere still finds it."""
    for d in (os.path.dirname(os.path.abspath(__file__)),
              '/usr/share/forgetest/bench'):
        if d not in sys.path:
            sys.path.append(d)
    try:
        from gfbench import degc
    except (ImportError, SystemExit):
        return None
    return degc(raw)


def pcurve_levels(g, pcts):
    """(pct, S, level) per rung: the level is what the core maps S onto
    with the settings in force, as a fraction of full (duty/127 under
    analog, density under density). None when a setting cannot be read."""
    floor = grbl_setting(g, '$35')
    ceil = grbl_setting(g, '$36')
    rpm_max = grbl_setting(g, '$30')
    rpm_min = grbl_setting(g, '$31')
    if None in (floor, ceil, rpm_max, rpm_min) or rpm_max <= rpm_min:
        return None, (rpm_max, rpm_min, floor, ceil)
    min_value = int(PWM_PERIOD * floor / 100.0)
    max_value = int(PWM_PERIOD * ceil / 100.0)
    gradient = (max_value - min_value) / (rpm_max - rpm_min)
    levels = []
    for pct in pcts:
        sval = int(round(rpm_max * pct / 100.0))
        if sval <= rpm_min:
            level = 0
        else:
            level = min(int((sval - rpm_min) * gradient) + min_value, max_value)
        levels.append((pct, sval, level / float(PWM_PERIOD)))
    return levels, (rpm_max, rpm_min, floor, ceil)


def pcurve_analyze(samples, rungs, head_trim=PCURVE_TRIM_HEAD_S,
                   tail_trim=PCURVE_TRIM_TAIL_S):
    """Per-rung statistics over the trimmed steady window of each line,
    then the curve: normalized thermopile delta against level, a
    monotonicity count, straight-line fits with their x-intercepts, and
    the repeat-rung comparison. Pure: takes the raw trace and the rung
    brackets, returns a dict, so it can be checked without a machine."""
    rows = []
    for r in rungs:
        t0, t1 = r['t_run0'] + head_trim, r['t_run1'] - tail_trim
        if t1 - t0 < 1.0:
            t0, t1 = r['t_run0'], r['t_run1']
        hv = _stats(_window(samples, t0, t1, 'hv'))
        tp = _stats(_window(samples, t0, t1, 'tp'))
        # The thermopile falls back to baseline within about a second of a
        # line ending (measured 2026-08-25), so the first part of the gap
        # still carries the previous rung's tail; the baseline is the rest.
        base = _stats(_window(samples, r['t_gap0'] + PCURVE_GAP_SKIP_S,
                              r['t_m3'], 'tp'))
        first = _stats(_window(samples, t0, min(t0 + 2.0, t1), 'tp'))
        last = _stats(_window(samples, max(t1 - 2.0, t0), t1, 'tp'))
        tpd = _window(samples, t0, t1, 'tpd')
        # laser_on_sampled is a once-per-second window count, so the
        # last window of a line lands after Idle: look one second past.
        lon = _window(samples, r['t_run0'], r['t_run1'] + 1.0, 'lon')
        # Coolant from the UPSTREAM sensor: water_temp_1 sits downstream of
        # the flow-check heater and swings with it during a run.
        wt1 = _stats(_window(samples, r['t_gap0'], r['t_m3'], 'wt2'))
        pt = _stats(_window(samples, r['t_gap0'], r['t_m3'], 'pt'))
        delta = (tp['mean'] - base['mean']
                 if tp['mean'] is not None and base['mean'] is not None
                 else None)
        drift = (last['mean'] - first['mean']
                 if last['mean'] is not None and first['mean'] is not None
                 else None)
        rows.append({
            'rung': r['rung'], 'repeat': r.get('repeat', False),
            'pct': r['pct'], 's': r['s'], 'level': r['level'],
            'seconds': round(r['t_run1'] - r['t_run0'], 2),
            'hv_n': hv['n'], 'hv_mean': hv['mean'], 'hv_sd': hv['sd'],
            'hv_max': hv['max'],
            'hv_clipped': hv['max'] is not None and hv['max'] >= HV_FULL_SCALE,
            'tp_n': tp['n'], 'tp_mean': tp['mean'], 'tp_sd': tp['sd'],
            'tp_base': base['mean'], 'tp_base_sd': base['sd'],
            'tp_delta': delta, 'tp_drift': drift,
            'tpd_duty': (sum(1 for v in tpd if v) / float(len(tpd))
                         if tpd else None),
            'lon_max': max(lon) if lon else None,
            'fired': bool(lon) and max(lon) > 0,
            'coolant_raw': wt1['mean'],
            'coolant_c': _degc(wt1['mean']) if wt1['mean'] is not None else None,
            'supply_raw': pt['mean'],
        })
    primary = [row for row in rows if not row['repeat']]
    primary.sort(key=lambda row: row['level'])
    fired = [row for row in primary if row['fired']]
    curve = {'rows': len(rows), 'fired': len(fired)}
    # Normalize the thermopile delta to the top of the ladder.
    deltas = [row['tp_delta'] for row in fired if row['tp_delta'] is not None]
    top = max(deltas) if deltas else None
    for row in rows:
        row['tp_norm'] = (row['tp_delta'] / top
                          if top and row['tp_delta'] is not None else None)
    # Monotonicity: decreases of the delta with rising level, beyond noise.
    dec = 0
    prev = None
    for row in fired:
        if row['tp_delta'] is None:
            continue
        if prev is not None and row['tp_delta'] < prev['tp_delta'] - 2.0 * (row['tp_sd'] or 0):
            dec += 1
        prev = row
    curve['tp_decreases'] = dec
    dec = 0
    prev = None
    for row in fired:
        if row['hv_mean'] is None or row['hv_clipped']:
            continue
        if prev is not None and row['hv_mean'] < prev['hv_mean'] - 2.0 * (row['hv_sd'] or 0):
            dec += 1
        prev = row
    curve['hv_decreases'] = dec
    # Signal rungs: delta clear of the baseline noise, for the fits.
    sig = [row for row in fired if row['tp_delta'] is not None
           and row['tp_delta'] > 3.0 * (row['tp_base_sd'] or 0)]
    fit = _linfit([row['level'] for row in sig], [row['tp_delta'] for row in sig])
    if fit:
        a, b, r2 = fit
        curve['tp_fit'] = {'points': len(sig), 'intercept': a, 'slope': b,
                           'r2': r2,
                           'x_intercept': (-a / b) if b else None}
    unclipped = [row for row in fired if row['hv_mean'] is not None
                 and not row['hv_clipped']]
    fit = _linfit([row['level'] for row in unclipped],
                  [row['hv_mean'] for row in unclipped])
    if fit:
        a, b, r2 = fit
        curve['hv_fit'] = {'points': len(unclipped), 'intercept': a,
                           'slope': b, 'r2': r2,
                           'x_intercept': (-a / b) if b else None}
    curve['hv_clipped_rungs'] = [row['rung'] for row in rows if row['hv_clipped']]
    reps = [row for row in rows if row['repeat']]
    firsts = [row for row in rows if not row['repeat'] and reps
              and row['rung'] == reps[-1]['rung']]
    if reps and firsts:
        first, again = firsts[0], reps[-1]
        rep = {'rung': first['rung']}
        if first['tp_delta'] is not None and again['tp_delta'] is not None:
            rep['tp_delta_first'] = first['tp_delta']
            rep['tp_delta_again'] = again['tp_delta']
            rep['tp_delta_change'] = again['tp_delta'] - first['tp_delta']
            rep['tp_delta_change_pct'] = (100.0 * rep['tp_delta_change'] / first['tp_delta']
                                          if first['tp_delta'] else None)
        if first['hv_mean'] is not None and again['hv_mean'] is not None:
            rep['hv_change'] = again['hv_mean'] - first['hv_mean']
        bases = [row['tp_base'] for row in rows if row['tp_base'] is not None]
        if len(bases) >= 2:
            rep['baseline_walk'] = bases[-1] - bases[0]
        curve['repeat'] = rep
    return {'rungs': rows, 'curve': curve}


def _fmt(v, prec=1):
    if v is None:
        return '-'
    if isinstance(v, float):
        return '%.*f' % (prec, v)
    return str(v)


def pcurve_report(res, model):
    rows, curve = res['rungs'], res['curve']
    print('\n--- per rung (steady window, first %gs and last %gs of each line dropped) ---'
          % (PCURVE_TRIM_HEAD_S, PCURVE_TRIM_TAIL_S))
    unit = 'density' if model == 'density' else 'duty'
    print('  rung  %%    S     %-8s  hv mean  sd    max    | tp delta   sd    base    drift  norm  | dig  lon  cool'
          % unit)
    for row in rows:
        tag = '%2d%s' % (row['rung'], 'r' if row['repeat'] else ' ')
        print('  %s  %3d  %4d  %6.2f%%   %7s %5s %5s%s | %8s %5s %7s %6s %5s | %4s %4s %s'
              % (tag, row['pct'], row['s'], 100.0 * row['level'],
                 _fmt(row['hv_mean']), _fmt(row['hv_sd']), _fmt(row['hv_max'], 0),
                 '!' if row['hv_clipped'] else ' ',
                 _fmt(row['tp_delta']), _fmt(row['tp_sd']), _fmt(row['tp_base']),
                 _fmt(row['tp_drift']), _fmt(row['tp_norm'], 3),
                 _fmt(row['tpd_duty'], 2), _fmt(row['lon_max'], 0),
                 _fmt(row['coolant_c']) if row['coolant_c'] is not None
                 else _fmt(row['coolant_raw'], 0) + 'raw'))
    print('  (! = hv_current touched %d: the ADC is clipped there and the'
          % HV_FULL_SCALE)
    print('   current column is no longer a measurement on that rung)')
    print('\n--- curve ---')
    print('rungs fired (laser_on_sampled > 0): %d of %d' % (curve['fired'], curve['rows']))
    print('thermopile delta decreases with rising level (beyond 2 sd): %s'
          % curve['tp_decreases'])
    print('hv_current decreases with rising level (beyond 2 sd, unclipped): %s'
          % curve['hv_decreases'])
    if curve.get('hv_clipped_rungs'):
        print('hv_current CLIPPED on rungs %s' % curve['hv_clipped_rungs'])
    for name, key in (('thermopile', 'tp_fit'), ('hv_current', 'hv_fit')):
        f = curve.get(key)
        if not f:
            print('%s fit: not enough signal rungs' % name)
            continue
        print('%s vs level: %d points, slope %.1f per 100%%, r2 %.3f, '
              'x-intercept %s%% (the measured threshold if the fit holds)'
              % (name, f['points'], f['slope'], f['r2'],
                 _fmt(100.0 * f['x_intercept']) if f['x_intercept'] is not None else '-'))
    rep = curve.get('repeat')
    if rep:
        print('repeat of rung %d: thermopile delta %s -> %s (%s, %s%%), '
              'hv %s; baseline walked %s over the ladder'
              % (rep['rung'], _fmt(rep.get('tp_delta_first')),
                 _fmt(rep.get('tp_delta_again')), _fmt(rep.get('tp_delta_change')),
                 _fmt(rep.get('tp_delta_change_pct')), _fmt(rep.get('hv_change')),
                 _fmt(rep.get('baseline_walk'))))


def drill_pcurve(g):
    feed = int(sys.argv[2]) if len(sys.argv) > 2 else PCURVE_FEED
    length = float(sys.argv[3]) if len(sys.argv) > 3 else PCURVE_LEN
    model = conf_get('laser_power_model') or 'density'
    if len(sys.argv) > 4:
        pcts = tuple(int(x) for x in sys.argv[4].split(',') if x.strip())
    else:
        pcts = PCURVE_DENSITY_PCT if model == 'density' else PCURVE_ANALOG_PCT
    if not pcts or min(pcts) < 1 or max(pcts) > 100:
        print('rungs must be percents in 1..100')
        return 2
    print('=== laser performance curve: %s model, %d rungs + repeat, F%d, %g mm each ==='
          % (model, len(pcts), feed, length))
    print('constant power (M3): the commanded level is the tested level.')
    levels, (rpm_max, rpm_min, floor, ceil) = pcurve_levels(g, pcts)
    if levels is None:
        print('PRECONDITION FAILED: cannot read $30/$31/$35/$36 (%s/%s/%s/%s)'
              % (rpm_max, rpm_min, floor, ceil))
        return 2
    print('mapping: $30=%g $31=%g $35=%g $36=%g' % (rpm_max, rpm_min, floor, ceil))
    if floor > 0.0:
        print('a floor is set, so the low rungs land on it: this run records')
        print('the shipping mapping. To measure the curve itself set $35=0')
        print('and restart the controller first.')
    unit = 'density' if model == 'density' else 'duty'
    # The drift witness is a mid-ladder rung drawn again at the end: it
    # has real signal (the bottom rung sits at the threshold and reads
    # nothing twice) and it is not full power, so it adds little heat.
    witness = len(levels) // 2
    print('rungs (each a +X line from the block\'s X0, stepping +Y %g mm; rung'
          % PCURVE_PITCH)
    print('%d is drawn again at the end, running -X, as the drift witness;'
          % (witness + 1))
    print('the next run\'s block starts %g mm further along X):' % length)
    for i, (pct, sval, level) in enumerate(levels):
        print('  %2d: %3d%% -> S%-4d  %s %.2f%%' % (i + 1, pct, sval, unit, 100.0 * level))
    sampler = Sampler(PCURVE_SAMPLE_HZ)
    if sampler.local:
        print('sampling sysfs on the board at a target %d Hz: %s'
              % (PCURVE_SAMPLE_HZ, ' '.join(attr for _k, attr in PCURVE_CHANNELS)))
    else:
        print('NOT on the board: sampling forgectrl /status at ~8 Hz instead.')
        print('That carries the current and the emission witness only; the')
        print('thermopile is not in /status, so this run yields no curve.')
    print('connect: %s' % prepare(g))
    print('pre-fire: %s' % sample_forgectrl())
    arm_cue()
    print('>>> This ladder reaches FULL power for %.0f s per line. Use'
          % (length / feed * 60.0))
    print('>>> something you are willing to cut through and that will not')
    print('>>> flame: scrap tile, firebrick, thick draftboard on a')
    print('>>> sacrificial layer. The thermopile is in the head, so the')
    print('>>> material is not part of the measurement.\n')
    print('G91/G21: %s / %s' % (g.cmd('G91'), g.cmd('G21')))
    order = list(range(len(levels))) + [witness]
    line_s = length / feed * 60.0
    sampler.start()
    rungs = []
    aborted = None
    try:
        for n, idx in enumerate(order):
            pct, sval, level = levels[idx]
            repeat = n == len(order) - 1
            # Every line runs +X from the block's X0 at one Y and the rungs
            # step +Y, so a run occupies a block `length` wide by
            # PCURVE_PITCH x rungs tall and the next run's block starts
            # `length` further along X. The drift witness runs the other
            # way, from the far end back to X0: a swing that reverses with
            # direction is head position along the gantry; one that repeats
            # is time.
            if repeat:
                g.s.sendall(('G0 X%g\n' % length).encode())
                g.wait_state('Idle', 30)
            t_gap0 = time.time()
            time.sleep(PCURVE_GAP_S)             # laser off: the baseline
            t_m3 = time.time()
            job = ['M3 S%d' % sval,
                   'G1 X%g F%d' % (-length if repeat else length, feed),
                   'M5']
            for ln in job:
                g.s.sendall(ln.encode() + b'\n')
            st = g.wait_state('Run', 240 if n == 0 else 60)
            if not st.startswith('Run'):
                aborted = ('rung %d never ran (state=%s): arm refused, no '
                           'press, or the controller alarmed' % (idx + 1, st))
                break
            t_run0 = time.time()
            st = g.wait_state('Idle', line_s + 30.0, poll=0.05)
            t_run1 = time.time()
            if not st.startswith('Idle'):
                aborted = 'rung %d did not finish (state=%s)' % (idx + 1, st)
                break
            if t_run1 - t_run0 < line_s - 1.5:
                # A line that ended early was cancelled by the operator or
                # the controller, and a cancel may have moved the head
                # (the controller returns to machine zero). From here every
                # relative move is aimed from a position this drill no
                # longer knows, so send nothing more.
                aborted = ('rung %d ran %.1f s of %.1f: cancelled; no further '
                           'moves sent' % (idx + 1, t_run1 - t_run0, line_s))
                break
            rungs.append({'rung': idx + 1, 'repeat': repeat, 'pct': pct,
                          's': sval, 'level': level, 't_gap0': t_gap0,
                          't_m3': t_m3, 't_run0': t_run0, 't_run1': t_run1})
            print('  rung %2d%s: S%-4d ran %.1f s' % (idx + 1, 'r' if repeat else ' ',
                                                    sval, t_run1 - t_run0))
            back = '' if repeat else 'G0 X%g\n' % -length
            g.s.sendall((back + 'G0 Y%g\n' % PCURVE_PITCH).encode())
            g.wait_state('Idle', 30)
    finally:
        try:
            g.cmd('M5', timeout=1)
        except Exception:
            pass
        if aborted:
            g.rt(b'\x18')                   # abort out of whatever it is in
        else:
            g.s.sendall(b'G90\nM2\n')       # program end closes the window
        time.sleep(1.5)
        sampler.stop()
    if aborted:
        print('ABORTED: %s' % aborted)
    print('\nsampler: %d samples, %.1f Hz achieved, %d read errors'
          % (len(sampler.samples), sampler.rate(), sampler.errors))
    if not rungs:
        return 1
    res = pcurve_analyze(sampler.samples, rungs)
    pcurve_report(res, model)
    record = {
        'drill': 'pcurve', 'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'model': model, 'feed': feed, 'length_mm': length,
        'gap_s': PCURVE_GAP_S, 'pitch_mm': PCURVE_PITCH,
        'settings': {'$30': rpm_max, '$31': rpm_min, '$35': floor, '$36': ceil},
        'sampler': {'local': sampler.local, 'hz': sampler.rate(),
                    'samples': len(sampler.samples), 'errors': sampler.errors},
        'aborted': aborted, 'rungs': res['rungs'], 'curve': res['curve'],
        'trace': sampler.samples,
    }
    ddir = os.environ.get('FORGETEST_BENCH_DATA') or ('/tmp' if sampler.local else os.getcwd())
    path = os.path.join(ddir, 'pcurve_%s_%s.json' % (model, time.strftime('%Y%m%d-%H%M%S')))
    try:
        with open(path, 'w') as f:
            json.dump(record, f, indent=1)
        print('record: %s' % path)
    except OSError as e:
        print('record not written: %s' % e)
    print('\nRead it in this order. First the instrument: the thermopile')
    print('delta must rise with the level on every rung that fired, settle')
    print('inside the line (small drift), return to its baseline between')
    print('rungs, and the repeat rung must agree with its first run. Any')
    print('miss there is a fact about the sensor, not the tube. Then the')
    print('curve: under analog the current column is the supply and the')
    print('thermopile is the tube; under density the current is only a')
    print('presence witness and the thermopile is the whole story. A knee')
    print('where the delta stops rising before 100%% is the ceiling S1000')
    print('should map to. The material remains the witness that it lased.')
    return res


# --- the rapids after an M5 ship dark ----------------------------------------

# One constant-power line, M5, then two rapids over it with dwells between,
# the shape every ladder above uses between rungs. M5 executes with the
# planner drained and the kernel run over, and the core issues no
# per-segment laser update for moves made with the spindle off, so only the
# stream's wanted fire state decides whether those rapids fire.
# S1000 is a certain strike and, under the density model, the worst case
# for the bug: full duty pinned, so a rapid that inherited fire would run
# at full power.
M5DARK_JOB = ['G91', 'G21', 'M3', 'S400',
              'G1 X20 F600',
              'M5', 'G4 P2.5',
              'G0 X-20', 'G4 P2.5',
              'G0 X20', 'G4 P2.5',
              'G90', 'M2']
HV_DARK_MAX = 20                        # hv_current reads 0 with the tube off


def drill_m5dark(g):
    print('=== the rapids after an M5 ship dark: M3 S400, 20 mm line, M5, two rapids ===')
    sampler = Sampler(PCURVE_SAMPLE_HZ)
    if not sampler.local:
        print('run this on the board: the witnesses are sysfs at 25 Hz')
        return 2
    print('connect: %s' % prepare(g))
    print('pre-fire: %s' % sample_forgectrl())
    arm_cue()
    print('>>> 20 mm of free +X travel at the head. One 20 mm line at S400,')
    print('>>> then the head rapids back over it and forward again, dark.\n')
    sampler.start()
    for ln in M5DARK_JOB:
        g.s.sendall(ln.encode() + b'\n')
    st = g.wait_state('Run', 240)
    if not st.startswith('Run'):
        print('FAIL: the job never ran (state=%s)' % st)
        g.rt(b'\x18')
        sampler.stop()
        return 1
    # The controller reports Idle inside a G4 dwell, so Idle is no sign the
    # job is over; the armed window closing at M2 is.
    t0 = time.time()
    seen_armed = False
    while time.time() - t0 < 90:
        smp = sample_forgectrl()
        if smp and smp['armed']:
            seen_armed = True
        elif smp and seen_armed and not smp['armed']:
            break
        time.sleep(0.2)
    time.sleep(1.5)
    sampler.stop()
    tr = sampler.samples
    # Discharge segments from the current, 1 s hysteresis: the line is one;
    # a rapid that fired is another.
    segs, cur = [], None
    for s in tr:
        on = s['hv'] is not None and s['hv'] > 30
        if on and cur is None:
            cur = [s['t'], s['t']]
        elif on:
            cur[1] = s['t']
        elif cur is not None and s['t'] - cur[1] > 1.0:
            segs.append(cur)
            cur = None
    if cur:
        segs.append(cur)
    print('\n--- results (%d samples, %.1f Hz) ---' % (len(tr), sampler.rate()))
    if not segs:
        print('FAIL: no discharge seen at all (arm refused, no press, or no fire)')
        return 1
    t_end = segs[0][1]
    base = _stats(_window(tr, segs[0][0] - 2.0, segs[0][0] - 0.2, 'tp'))['mean']
    print('line: %.2f s of discharge; %d discharge segment(s) in the run%s'
          % (t_end - segs[0][0], len(segs),
             '' if len(segs) == 1 else ': the extra ones are rapids that FIRED'))
    hv_after = max((s['hv'] for s in tr if s['t'] > t_end + 0.3 and s['hv'] is not None),
                   default=0)
    lon_after = [s for s in tr if s['t'] > t_end + 0.3 and s.get('lon')]
    # laser_on_sampled lags a window: the first zero past the line is the
    # dark point, and nothing after it may be nonzero.
    zeros = [s['t'] for s in tr if s['t'] > t_end and s.get('lon') == 0]
    relit = [s for s in tr if zeros and s['t'] > zeros[0] and s.get('lon')]
    print('after the M5: hv max %d (dark <= %d); laser_on_sampled nonzero samples %d, '
          'after its first zero %d' % (hv_after, HV_DARK_MAX, len(lon_after), len(relit)))
    print('trace from 0.2 s before the line ended, 40 ms steps (hv / thermopile delta):')
    row = [s for s in tr if t_end - 0.2 <= s['t'] <= t_end + 9.0]
    for i in range(0, len(row), 25):
        chunk = row[i:i + 25]
        print('  +%4.1fs hv: %s' % (chunk[0]['t'] - t_end, ' '.join('%d' % (s['hv'] or 0) for s in chunk)))
        print('         tp: %s' % ' '.join('%d' % ((s['tp'] or 0) - (base or 0)) for s in chunk))
    covered = tr[-1]['t'] - t_end
    if covered < 7.0:
        print('M5DARK INCONCLUSIVE: the trace ends %.1f s after the line, before '
              'the rapids (the job runs ~8 s past the M5)' % covered)
        return 1
    ok = len(segs) == 1 and hv_after <= HV_DARK_MAX and not relit
    print('M5DARK %s' % ('PASS: the rapids after the M5 shipped dark (%.1f s sampled past the line)'
                         % covered if ok else 'FAIL: the laser fired after the M5'))
    return 0 if ok else 1


def post_ctrl(action):
    # http.client preserves the header-name case exactly as given.
    import http.client
    tok = panel_token()
    c = http.client.HTTPConnection(HOST, 8080, timeout=8)
    c.putrequest('POST', '/controller/' + action)
    c.putheader('X-ForgeFIRM-Token', tok)
    c.putheader('Content-Length', '0')
    c.endheaders()
    r = c.getresponse()
    body = r.read().decode()
    c.close()
    return r.status, body


def drill_expstop(g):
    print('=== armed kill on the expected-stop path (POST /controller/stop) ===')
    if not panel_token():
        raise SystemExit('set GF_TOKEN to the panel token first (or run on the board)')
    print('connect: %s' % prepare(g))
    arm_cue()
    job = ['G91', 'G21', 'M4', 'S400',
           'G1 X40 F200', 'G1 Y40 F200', 'G1 X-40 F200', 'G1 Y-40 F200',
           'M5', 'G90', 'M2']
    for ln in job:
        g.s.sendall(ln.encode() + b'\n')
    # Wait for the burn to be under way (emission > 0), then stop.
    t0 = time.time()
    seen = False
    while time.time() - t0 < 240:
        smp = sample_forgectrl()
        if smp and smp['emission'] and smp['emission'] > 0:
            seen = True
            break
        time.sleep(0.15)
    if not seen:
        print('no emission seen within the wait - operator did not arm? ABORT')
        return []
    print('emission live (%s) - stopping the controller NOW' % smp['emission'])
    t_stop = time.time()
    code, body = post_ctrl('stop')
    print('POST /controller/stop -> %s %s (%.2f s)' % (code, body.strip(), time.time() - t_stop))
    trail = []
    for _ in range(40):                     # ~5 s at 8 Hz
        smp = sample_forgectrl()
        if smp:
            trail.append((round(time.time() - t_stop, 2), smp['emission'], smp['kstate'], smp['armed']))
        time.sleep(0.12)
    print('post-stop trail (t, emission_samples, kstate, armed):')
    for t in trail:
        print('  %s' % (t,))
    zero_at = next((t for t, e, _, _ in trail if e == 0), None)
    tail_zero = all(e == 0 for _, e, _, _ in trail[-16:])
    not_running = all(k != 'running' for _, _, k, _ in trail[-16:])
    print('emission first 0 at +%s s; last 2 s all zero: %s; kernel not running: %s'
          % (zero_at, tail_zero, not_running))
    try:
        mode = get_json('/mode')
    except Exception as e:
        mode = str(e)
    print('/mode after stop: %s' % mode)
    ok = zero_at is not None and zero_at < 2.5 and tail_zero and not_running
    print('EXPSTOP %s' % ('PASS' if ok else 'REVIEW'))
    print('the controller is left STOPPED (supervision held); resume it with '
          'the ctrlstart step once the operator has judged the stop')
    return trail


def drill_ctrlstart(g):
    """Resume supervision after expstop: POST /controller/start, then
    report /mode. No motion, no laser."""
    code, body = post_ctrl('start')
    print('POST /controller/start -> %s %s' % (code, body.strip()))
    time.sleep(6)
    try:
        print('/mode after start: %s' % get_json('/mode'))
    except Exception as e:
        print('/mode after start: %s' % e)
    return []


def main():
    drill = sys.argv[1] if len(sys.argv) > 1 else ''
    drills = {'witness': drill_witness, 'hold': drill_hold,
              'faultpos': drill_faultpos, 'ircut': drill_ircut,
              'pthresh': drill_pthresh, 'dladder': drill_dladder,
              'pcurve': drill_pcurve, 'm5dark': drill_m5dark,
              'expstop': drill_expstop, 'ctrlstart': drill_ctrlstart}
    if drill not in drills:
        print(__doc__)
        return 2
    if drill == 'ctrlstart':
        drills[drill](None)
        return 0
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
