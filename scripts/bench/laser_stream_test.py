#!/usr/bin/env python3
"""Host-side verification of the laser pulse-stream emission.

Runs the native grblHAL_glowforge binary in null-sink mode with
GFSINK_DUMP capturing the shipped byte stream, drives small laser jobs
over TCP, then checks the dumps against the kernel feeder contract:

  1. a power byte (bit 7) leads the stream, before any tick byte
  2. no two consecutive power bytes (the SDMA script drops the second)
  3. the first FIRE bit (0x10) comes after a nonzero power byte
  4. power values match the S words through the core's mapping, floor
     included ($30=1000, $31=0, $35 = the board's floor), and no duty
     under FIRE falls below that floor
  5. FIRE only spans the cutting moves: none before the job, none during
     the G0 return, none at the tail
  6. step accounting survives the insertions: X returns to net zero and
     peaks at the programmed 10 mm
  7. termination: every stream ends with FIRE clear, including an M3
     (constant-power) job whose core never issues a laser-off update -
     the stream must never lean on the kernel's end-of-data backstop
  8. no FIRE bit ever rides a zero-step gap: a stepless run of stream
     bytes carrying FIRE longer than any legitimate between-step
     interval is a stationary dwell burn
  9. rules 7-8 hold across rapid cycle stop/start churn (planner-starve
     shaped jobs), where the FIRE state of the previous cycle must not
     leak into the idle-gap pad bytes
 10. a power ladder fires every rung at the duty commanded for it: no
     FIRE tick rides a duty that was never commanded (a run start resets
     the hardware duty to ~100 %, so a fire bit reaching the stream
     ahead of the rung's power byte would burn at full power), and the
     fire ticks divide evenly across the rungs, which is what fails if a
     rung's opening ticks carry the previous rung's duty

Usage: laser_stream_test.py [path-to-binary]   (default ./build-native/grblHAL_glowforge)
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

BIN = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build-native/grblHAL_glowforge")
PORT = 2399
STEPS_PER_MM = 53.333

# The S -> duty mapping the board defaults produce: $30 = 1000, $31 = 0,
# and a $35 floor (boards/glowforge.h DEFAULT_SPINDLE_PWM_MIN_VALUE)
# against the hardware's 127-count period. Changing the board's floor
# changes every expectation below, which is why it is mirrored here
# rather than inferred from the stream.
PWM_PERIOD = 127
PWM_MIN_PCT = 16.0
PWM_MIN = int(PWM_PERIOD * PWM_MIN_PCT / 100.0)
RPM_MAX = 1000.0


def duty_for(s):
    """Duty the core computes for an S word, floor included."""
    return int(s * (PWM_PERIOD - PWM_MIN) / RPM_MAX) + PWM_MIN

# Longest stepless run allowed to carry FIRE, in machine ticks. The
# slowest legitimate between-step interval in these jobs is the first
# step of an accel-from-rest: sqrt(2 * (1/53.333 mm) / 700 mm/s^2)
# = 7.3 ms = ~206 ticks at 28160 Hz. 500 gives >2x margin while staying
# far below any idle-gap pad run.
FIRE_GAP_LIMIT_TICKS = 500

WAIT_IDLE = ("wait_idle",)

# Session A: the original M4 dynamic-power job (rules 1-6).
JOB_M4 = [
    "M4 S0",
    "G1 X5 F600 S500",
    "G1 X10 S1000",
    "G0 X0",
    "M5",
]

# Session B: M3 constant power to the end of the stream. The core never
# issues a laser-off update for M3, so the stream engine itself must
# terminate the cycle dark (rule 7).
JOB_M3_TERM = [
    "M3 S1000",
    "G1 X5 F600",
    WAIT_IDLE,
    ("sleep", 1.0),
    "M5",
]

# Session C: rapid cycle churn - many tiny laser moves sent one at a
# time with small gaps, so cycles stop and restart the way a planner
# starve produces them (rules 8-9).
JOB_CHURN = []
for _ in range(30):
    JOB_CHURN.append("G1 X0.2 F600 S800")
    JOB_CHURN.append(("sleep", 0.02))
    JOB_CHURN.append("G1 X0 S800")
    JOB_CHURN.append(("sleep", 0.02))
JOB_CHURN.insert(0, "M4 S0")
JOB_CHURN.append("M5")

# Session D: a power ladder in the shape the bench threshold drill uses -
# constant power (M3) so the commanded duty is the tested duty, rungs
# ascending, a dark G0 between them. Full power is deliberately absent
# from the ladder, so duty 127 under FIRE can only be a leak.
LADDER_S = (20, 30, 60, 120, 200, 300)
LADDER_DUTY = tuple(duty_for(s) for s in LADDER_S)
LADDER_MM = 5.0
JOB_LADDER = ["G91", "G21", "M3"]
for _i, _s in enumerate(LADDER_S):
    JOB_LADDER.append("S%d" % _s)
    JOB_LADDER.append("G1 X%g F300" % (LADDER_MM if _i % 2 == 0 else -LADDER_MM))
    JOB_LADDER.append("G0 Y1")
JOB_LADDER.append("M5")


def fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def send_line(sock, line, log):
    sock.sendall((line + "\n").encode())
    while True:
        r = read_avail(sock, log, 5.0, until=("ok", "error"))
        if r is None:
            fail("no ok/error for %r" % line)
        if r == "error":
            fail("error response to %r" % line)
        return


def read_avail(sock, log, timeout, until=None):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        sock.settimeout(max(0.05, end - time.time()))
        try:
            data = sock.recv(4096)
        except socket.timeout:
            data = b""
        if data:
            buf += data
            log.append(data.decode(errors="replace"))
            if until:
                for token in until:
                    if re.search(r"^%s\b" % token, buf.decode(errors="replace"), re.M):
                        return token
        elif until is None:
            return None
    return None


def wait_idle(sock, log):
    for _ in range(100):
        sock.sendall(b"?")
        read_avail(sock, log, 0.3)
        if re.search(r"<Idle", "".join(log[-3:])):
            return
        time.sleep(0.2)
    fail("controller never returned to Idle")


def publish_verdicts(path, stop):
    """Publish a fresh, clean cooling verdict every 0.5 s (the arm flow
    refuses without one; freshness window is 2 s). Same-host monotonic
    clock, atomic rename so the reader never sees a torn file."""
    while not stop.is_set():
        body = ('{"ts_mono":%.3f,"fire_ok":true,"hold":false,'
                '"resume_ok":true,"reason":""}'
                % time.clock_gettime(time.CLOCK_MONOTONIC))
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(body)
        os.replace(tmp, path)
        stop.wait(0.5)


def run_session(name, steps):
    """Launch the controller, run the job steps, return the dump bytes."""
    workdir = tempfile.mkdtemp(prefix="laser-test-")
    dump = os.path.join(workdir, "stream.bin")
    verdict = os.path.join(workdir, "cooling.state")
    env = dict(os.environ, GFSINK_DUMP=dump, GF_VERDICT_FILE=verdict,
               FFLOG_STDERR="1")
    env.pop("GFSINK", None)

    stop = threading.Event()
    pub = threading.Thread(target=publish_verdicts, args=(verdict, stop), daemon=True)
    pub.start()

    proc = subprocess.Popen([BIN, "-p", str(PORT)], cwd=workdir, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        sock = None
        for _ in range(50):
            try:
                sock = socket.create_connection(("127.0.0.1", PORT), timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        if sock is None:
            err = b""
            if proc.poll() is not None:
                err = proc.stderr.read() or b""
            fail("[%s] cannot connect to the controller (exit=%s)\n%s"
                 % (name, proc.poll(), err.decode(errors="replace")))

        log = []
        read_avail(sock, log, 0.5)          # banner / hello

        for step in steps:
            if step == WAIT_IDLE:
                wait_idle(sock, log)
            elif isinstance(step, tuple) and step[0] == "sleep":
                time.sleep(step[1])
            else:
                send_line(sock, step, log)

        # Wait for the motion to play out on the wall clock (the shipper
        # is wall-paced), then for the Idle report.
        wait_idle(sock, log)
        time.sleep(1.0)                     # let the shipper drain the tail

        text = "".join(log)
        if "laser armed" not in text:
            fail("[%s] no 'laser armed' message (arming flow did not run)" % name)

        sock.close()
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stop.set()
        pub.join(2)

    data = open(dump, "rb").read()
    if not data:
        fail("[%s] empty stream dump" % name)
    shutil.rmtree(workdir, ignore_errors=True)
    return data


def tick_bytes(data):
    """The stream with power bytes stripped (tick bytes only)."""
    return bytes(b for b in data if not b & 0x80)


def check_fire_gaps(name, data):
    """Rule 8: no stepless run carrying FIRE longer than the limit."""
    run = 0
    worst = 0
    for tick, b in enumerate(tick_bytes(data)):
        if b & 0x10 and not b & 0x25:       # FIRE, no X/Y/Z step
            run += 1
            worst = max(worst, run)
            if run >= FIRE_GAP_LIMIT_TICKS:
                fail("[%s] FIRE carried across a %d-tick zero-step gap "
                     "ending at tick %d (stationary dwell burn)"
                     % (name, run, tick))
        else:
            run = 0
    return worst


def check_termination(name, data):
    """Rule 7: the stream's final tick byte must carry FIRE clear."""
    ticks = tick_bytes(data)
    if not ticks:
        fail("[%s] no tick bytes in the stream" % name)
    if ticks[-1] & 0x10:
        fail("[%s] stream ends with FIRE set (0x%02x) - termination "
             "rule violated, relies on the end-of-data backstop"
             % (name, ticks[-1]))


def check_m4_job(data):
    """Rules 1-6 on the original M4 job."""
    if not data[0] & 0x80:
        fail("stream does not lead with a power byte (first byte 0x%02x)" % data[0])

    prev_power = False
    cur_power = 0
    fire_ticks = []                 # (tick_index, power_at_that_tick)
    x_pos = 0
    x_min = x_max = 0
    tick = 0
    first_fire_power = None
    for b in data:
        if b & 0x80:
            if prev_power:
                fail("consecutive power bytes at tick %d" % tick)
            prev_power = True
            cur_power = b & 0x7F
            continue
        prev_power = False
        if b & 0x10:
            if first_fire_power is None:
                first_fire_power = cur_power
            fire_ticks.append((tick, cur_power))
        if b & 0x01:
            x_pos += -1 if b & 0x02 else 1
            x_min = min(x_min, x_pos)
            x_max = max(x_max, x_pos)
        if b & 0x24:
            fail("unexpected Y/Z step at tick %d (byte 0x%02x)" % (tick, b))
        tick += 1

    if not fire_ticks:
        fail("no FIRE bits in the stream")
    if first_fire_power == 0:
        fail("first FIRE bit rides duty 0 (power-before-fire violated)")

    powers = sorted(set(p for _, p in fire_ticks))
    if powers[-1] != PWM_PERIOD:
        fail("S1000 did not reach duty %d (max %d)" % (PWM_PERIOD, powers[-1]))
    want = duty_for(500)
    if not any(abs(p - want) <= 2 for p in powers):
        fail("S500 plateau (~%d) not seen (powers %s)" % (want, powers[:20]))
    if powers[0] < PWM_MIN:
        fail("duty %d under FIRE is below the $35 floor of %d: M4's ramp is "
             "commanding power the tube cannot lase at" % (powers[0], PWM_MIN))

    expect_peak = round(10 * STEPS_PER_MM)
    if abs(x_max - expect_peak) > 2:
        fail("X peak %d steps, expected ~%d" % (x_max, expect_peak))
    if x_pos != 0:
        fail("X net %d steps after return to 0" % x_pos)
    if x_min < 0:
        fail("X went negative (min %d)" % x_min)

    last_fire = fire_ticks[-1][0]
    tail_steps = 0
    tick = 0
    for b in data:
        if b & 0x80:
            continue
        if tick > last_fire and b & 0x01:
            tail_steps += 1
        tick += 1
    if tail_steps < 400:
        fail("only %d fire-free steps after the last FIRE bit - G0 return not dark" % tail_steps)

    return fire_ticks, powers, x_max, tail_steps


def check_power_ladder(name, data, expect):
    """Rule 10: every FIRE tick rides the duty commanded for its rung."""
    cur = None
    order = []                      # duties in the order they carry FIRE
    counts = {}
    for b in data:
        if b & 0x80:
            cur = b & 0x7F
            continue
        if b & 0x10:
            if cur is None:
                fail("[%s] FIRE bit ahead of any power byte" % name)
            counts[cur] = counts.get(cur, 0) + 1
            if not order or order[-1] != cur:
                order.append(cur)

    stray = sorted(d for d in counts if d not in expect)
    if stray:
        fail("[%s] FIRE rode uncommanded duty %s (commanded %s): power the "
             "job never asked for is uncommanded energy"
             % (name, stray, list(expect)))
    if order != list(expect):
        fail("[%s] duty sequence under FIRE was %s, expected %s"
             % (name, order, list(expect)))

    # Equal-length rungs at one feed burn equal numbers of fire ticks.
    # A rung whose opening ticks carry the previous rung's duty shows up
    # here as a surplus on one duty and a deficit on the next.
    lo, hi = min(counts.values()), max(counts.values())
    if hi > lo * 1.05:
        fail("[%s] fire ticks per rung uneven (%d..%d, %s): a rung is "
             "firing at its neighbor's duty" % (name, lo, hi, counts))
    return counts


def count_fire(data):
    return sum(1 for b in tick_bytes(data) if b & 0x10)


def main():
    # --- session A: M4 dynamic power, rules 1-6 + 7-8 -------------------
    data = run_session("m4", JOB_M4)
    fire_ticks, powers, x_max, tail_steps = check_m4_job(data)
    check_termination("m4", data)
    gap_a = check_fire_gaps("m4", data)
    print("PASS [m4]: %d bytes, %d power bytes, %d fire ticks, powers %s, "
          "X peak %d steps net 0, %d dark return steps, max fire gap %d"
          % (len(data), sum(1 for b in data if b & 0x80), len(fire_ticks),
             powers, x_max, tail_steps, gap_a))

    # --- session B: M3 constant power to stream end, rule 7 -------------
    data = run_session("m3-term", JOB_M3_TERM)
    if not count_fire(data):
        fail("[m3-term] no FIRE bits in the stream")
    check_termination("m3-term", data)
    gap_b = check_fire_gaps("m3-term", data)
    print("PASS [m3-term]: %d bytes, %d fire ticks end dark, max fire gap %d"
          % (len(data), count_fire(data), gap_b))

    # --- session C: cycle churn, rules 8-9 ------------------------------
    data = run_session("churn", JOB_CHURN)
    if not count_fire(data):
        fail("[churn] no FIRE bits in the stream")
    check_termination("churn", data)
    gap_c = check_fire_gaps("churn", data)
    print("PASS [churn]: %d bytes, %d fire ticks, max fire gap %d"
          % (len(data), count_fire(data), gap_c))

    # --- session D: power ladder, rule 10 -------------------------------
    data = run_session("ladder", JOB_LADDER)
    counts = check_power_ladder("ladder", data, LADDER_DUTY)
    check_termination("ladder", data)
    gap_d = check_fire_gaps("ladder", data)
    print("PASS [ladder]: %d bytes, duties %s fire ticks %s, max fire gap %d"
          % (len(data), list(LADDER_DUTY),
             [counts[d] for d in LADDER_DUTY], gap_d))

    print("PASS: all stream emission rules hold")


if __name__ == "__main__":
    main()
