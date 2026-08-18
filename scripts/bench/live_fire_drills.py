#!/usr/bin/env python3
"""Live-fire bench drills - Phases 4, 5, 6. Runs on the board (the bench
page) or from a LAN host, against grblHAL over TCP (port 23) and
forgectrl over HTTP (:8080); the machine is GF_HOST, default 127.0.0.1.
LIVE LASER: the operator must be armed with eye protection, a fire
watch, an extinguisher, and the exhaust running. Every drill waits for
the operator to press the physical arm button before the machine fires;
nothing here defeats that gate.

Usage: live_fire_drills.py <drill> [arg] [F]  (ircut/pthresh take S,
       dladder takes the base period in machine ticks)

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
    model = conf_get('laser_power_model')
    if model != 'density':
        print('PRECONDITION FAILED: laser_power_model is %r, need "density".'
              % (model,))
        print('Set it in %s and re-run. The model is read at each arm, so' % CONF)
        print('this key needs no controller restart.')
        return 2
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
