"""motion.* - the motion controller under grblHAL: dry motion, no emission.

Ported from `scripts/bench/pacing_test.py` (protocol-loop pacing) and
`scripts/bench/bench_m2.py` (motion-quality bench). Every move is relative
and round-trip; the laser stays latched (the tests never touch it); the
suite is the only Grbl client while a test runs.
"""
import os
import time

from ..catalog import test
from .. import hw
from ..runner import Failed

_MOTION_COVERS = [("grblhal-glowforge", "src/**"), ("kernel-module-glowforge", "**"),
                  ("forgectrl", "src/super.*"), ("forgectrl", "src/liveness.*")]


def controller_pid():
    pids = hw.pidof("grblHAL_glowfor")
    if not pids:
        raise Failed("controller process not found (grblHAL_glowforge)")
    return pids[0]


def cpu_ticks(pid):
    with open("/proc/%d/stat" % pid) as f:
        s = f.read().split()
    return int(s[13]) + int(s[14])          # utime + stime (all threads)


def cpu_percent(ctx, pid, window):
    import os
    hz = os.sysconf("SC_CLK_TCK")
    a = cpu_ticks(pid)
    ctx.sleep(window)
    b = cpu_ticks(pid)
    return 100.0 * (b - a) / (hz * window)


def wait_state(ctx, g, prefix, timeout):
    end = time.time() + timeout
    while time.time() < end:
        ctx.checkpoint()
        st = g.status_report()
        if st["state"].startswith(prefix):
            return st
        time.sleep(0.1)
    return None


def wait_state_text(ctx, g, prefix, timeout):
    """wait_state, keeping everything the controller said while polling.
    The driver reports a press with a [MSG:] line the moment it acts on it -
    inside the poll window - so a test that wants both the state and the
    message has to collect them together."""
    end = time.time() + timeout
    text = ""
    while time.time() < end:
        ctx.checkpoint()
        st = g.status_report()
        text += g.drain()
        if st["state"].startswith(prefix):
            return st, text
        time.sleep(0.1)
    return None, text + g.drain()


def wait_left_state(ctx, g, prefix, timeout):
    """The first report whose state is no longer `prefix`, with the text.
    Leaving a state is what proves a command was acted on; catching the
    state it moves INTO is a race whenever the remaining work is short."""
    end = time.time() + timeout
    text = ""
    while time.time() < end:
        ctx.checkpoint()
        st = g.status_report()
        text += g.drain()
        if not st["state"].startswith(prefix):
            return st, text
        time.sleep(0.1)
    return None, text + g.drain()


def wait_idle(ctx, g, timeout=30.0, poll=0.05, grace=0.3):
    """Poll until Idle; returns (peak_feed_mm_min, states_seen, final_report).
    An Idle report inside the first `grace` seconds counts only once a
    non-Idle state was seen: a move just commanded may not have started."""
    peak = 0.0
    states = []
    t0 = time.time()
    deadline = t0 + timeout
    st = None
    while time.time() < deadline:
        ctx.checkpoint()
        st = g.status_report()
        state = st["state"]
        if not states or states[-1] != state:
            states.append(state)
        f = st.get("FS") or st.get("F")
        if f:
            try:
                peak = max(peak, float(str(f).split(",")[0]))
            except ValueError:
                pass
        if state.startswith("Idle") and (time.time() - t0 >= grace or len(states) > 1):
            return peak, states, st
        time.sleep(poll)
    return peak, states + ["TIMEOUT"], st


def machine_idle(ctx, timeout=15.0):
    """The machine itself idle - the kernel has played out the stream
    depth and the decel tail behind grblHAL's Idle. Every motion test ends
    on this, so it hands the machine back at rest."""
    ok = ctx.forgectrl.wait_idle(timeout, abort=ctx.aborted)
    ctx.check(ok, "the machine did not return to idle within %.0f s of the last move", timeout)


def clean_slate(ctx, g):
    st = g.status_report()
    ctx.log("connect: %s", st["state"])
    if any(k in st["state"] for k in ("Alarm", "Door", "Hold")):
        g.realtime(0x18)                     # soft reset
        ctx.sleep(2)
        g.drain()
        st = g.status_report()
        if "Alarm" in st["state"]:
            ctx.log("unlock: %s", g.command("$X"))
    st = g.status_report()
    ctx.check(st["state"].startswith("Idle"), "controller is %s, expected Idle", st["state"])
    return st


@test("motion.pacing", title="Protocol-loop pacing (idle, parked, moving) and hold/resume position",
      subsystem="motion", kind="auto", est_min=1,
      covers=_MOTION_COVERS, requires=["kernel.latch-locked-idle"],
      steps=["Bed clear; the head needs 30 mm of free +X travel."],
      description="Idle CPU is low; a job parked in a completed feed hold is coarse-paced (not "
                  "busy-spinning at the motion rate); active motion is tight-paced; a feed-hold "
                  "mid-move then resume preserves position (the feeder never starves).")
def pacing(ctx):
    dist, feed = 30.0, 600.0
    pid = controller_pid()
    ev = ctx.evidence
    ev["controller_pid"] = pid
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        g.command("M5")
        g.command("G91")
        idle = cpu_percent(ctx, pid, 3)
        ev["idle_cpu_pct"] = round(idle, 1)
        ctx.log("[1] idle CPU = %.1f%%", idle)

        start = g.status_report().get("MPos")
        ctx.check(start, "no MPos in the status report")
        g.command("G1 X%.3f F%.0f" % (dist, feed), timeout=0.5)
        ctx.sleep(0.6)
        moving = cpu_percent(ctx, pid, 1.0)
        st_mv = g.status_report()["state"]
        ev["moving_cpu_pct"] = round(moving, 1)
        ctx.log("[3] state=%s CPU during move = %.1f%%", st_mv, moving)

        g.realtime(ord("!"))                 # feed hold
        wait_state(ctx, g, "Hold", 5)
        ctx.sleep(1.5)                       # decel completes (Hold:1 -> Hold:0)
        held = g.status_report()
        parked = cpu_percent(ctx, pid, 3)
        ev["held_state"] = held["state"]
        ev["parked_cpu_pct"] = round(parked, 1)
        ctx.log("[2] %s: CPU parked in Hold = %.1f%%", held["state"], parked)

        g.realtime(ord("~"))                 # resume
        peak, states, st = wait_idle(ctx, g, 30)
        ctx.check("TIMEOUT" not in states, "did not return to Idle after the resume: %s", states)
        end = st.get("MPos")
        moved = end[0] - start[0]
        ev["moved_mm"] = round(moved, 3)
        ctx.log("[4] start X=%.3f end X=%.3f moved=%.3f (expect %.1f)", start[0], end[0], moved, dist)
        # return to the starting position
        g.command("G1 X%.3f F%.0f" % (-dist, feed), timeout=0.5)
        wait_idle(ctx, g, 30)
        g.command("G90")
        final = g.status_report().get("MPos")
        ev["final_drift_mm"] = round(final[0] - start[0], 3) if final else None
    machine_idle(ctx)

    ctx.check(abs(moved - dist) < 0.05, "hold+resume lost steps: moved %.3f of %.1f mm", moved, dist)
    ctx.check(parked < moving * 0.5 and parked < 8.0,
              "parked Hold is not coarse-paced: %.1f%% (moving %.1f%%)", parked, moving)
    ctx.check(idle < 8.0, "idle CPU %.1f%%", idle)
    ctx.log("PASS: idle %.1f%%, moving %.1f%%, parked %.1f%%, hold/resume exact", idle, moving, parked)


@test("motion.jog-roundtrip", title="Motion quality: bounded jogs, max rate, diagonal, hold/resume",
      subsystem="motion", kind="operator", est_min=3,
      covers=_MOTION_COVERS, requires=["kernel.latch-locked-idle"],
      steps=["Park the head with at least 60 mm of free +X and 40 mm of free +Y travel; bed clear.",
             "Watch the gantry: it must move on every jog and end where it started."],
      description="Sanity jogs (X, Y 40 mm out/back at F2400), max-rate X out/back (60 mm at "
                  "F12000), a diagonal out/back, then a G1 with a feed-hold/resume in the middle. "
                  "No jog refused, every move returns to Idle, position drift within 0.05 mm, and "
                  "the operator saw the gantry move.")
def jog_roundtrip(ctx):
    ev = ctx.evidence
    ctx.instruct("Head parked with >= 60 mm free +X and >= 40 mm free +Y, bed clear, lid closed. "
                 "Watch the gantry during this test.")
    with ctx.grbl() as g:
        st0 = clean_slate(ctx, g)
        start = st0.get("MPos")
        ctx.check(start, "no MPos in the status report")
        ev["start"] = start
        moves = []
        for name, out, back in (
                ("X sanity 40mm", "$J=G91X40F2400", "$J=G91X-40F2400"),
                ("Y sanity 40mm", "$J=G91Y40F2400", "$J=G91Y-40F2400"),
                ("X max-rate 60mm", "$J=G91X60F12000", "$J=G91X-60F12000"),
                ("diag 40mm", "$J=G91X40Y40F8000", "$J=G91X-40Y-40F8000")):
            for jog in (out, back):
                r = g.command(jog)
                ctx.check(not any(x.startswith("error") for x in r), "%s: jog refused: %s", name, r)
                peak, states, _ = wait_idle(ctx, g)
                leg = "out" if jog == out else "back"
                ctx.log("%s %s: peak %.0f mm/min, states %s", name, leg, peak, states)
                moves.append({"name": name, "leg": leg, "peak": peak, "states": states})
                ctx.check("TIMEOUT" not in states, "%s %s did not return to Idle", name, leg)
        ev["moves"] = moves
        maxrate = max(m["peak"] for m in moves if m["name"].startswith("X max-rate"))
        ev["max_rate_peak"] = maxrate
        ctx.check(maxrate >= 6000, "max-rate jog peaked at only %.0f mm/min", maxrate)

        # feed-hold mid-move: G1 at 600 mm/min takes 3 s for 30 mm
        g.command("G91")
        g.command("G1X30F600", timeout=0.5)
        ctx.sleep(1.0)
        g.realtime(ord("!"))
        ctx.sleep(0.8)
        held = g.status_report()
        ev["held_state"] = held["state"]
        ctx.log("after !: %s", held["state"])
        g.realtime(ord("~"))
        peak, states, _ = wait_idle(ctx, g)
        ctx.log("after ~: states %s", states)
        g.command("G1X-30F2400", timeout=0.5)
        wait_idle(ctx, g)
        g.command("G90")
        final = g.status_report().get("MPos")
        ev["final"] = final
        drift = max(abs(a - b) for a, b in zip(final[:2], start[:2]))
        ev["drift_mm"] = round(drift, 3)
        ctx.log("final drift %.3f mm (start %s, final %s)", drift, start, final)
    machine_idle(ctx)
    ctx.check("Hold" in held["state"], "feed hold did not park (state %s)", held["state"])
    ctx.check(drift <= 0.05, "position drift %.3f mm", drift)
    ctx.confirm("Did the gantry move on every jog (X, Y, the fast X, the diagonal, the held move) "
                "and end where it started?")
    ctx.log("PASS: %d jogs, peak %.0f mm/min, hold parked, drift %.3f mm, operator confirmed",
            len(moves), maxrate, drift)


# ---------------------------------------------------------------- liveness

@test("motion.liveness-probe", title="Supervisor motion-liveness verdict", subsystem="motion",
      kind="auto", est_min=1,
      covers=[("forgectrl", "src/super.c"), ("forgectrl", "src/liveness.c"), ("kernel-module-glowforge", "**")],
      requires=["kernel.latch-locked-idle"],
      steps=["Bed clear, lid closed: the probe jogs the head 15 mm out and back (+X first); "
             "forgectrl is restarted once for a fresh probe."],
      description="forgectrl's supervisor reports the head-accelerometer liveness probe as "
                  "verified for the running controller (the DRV8825s are not wedged); when the "
                  "probe was skipped at spawn, the controller is respawned once so it runs. Then "
                  "the regression: with every axis masked (cnc/motor_lock=15, as a bench tool "
                  "may leave it) forgectrl is restarted and its fresh probe must still read "
                  "MOTION OK - the probe unmasks the axes itself - with the head-accel p2p at "
                  "or above the moving threshold.")
def liveness_probe(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    _liveness_verdict(ctx, fc, ev)
    _liveness_masked_restart(ctx, fc, ev)


def _liveness_verdict(ctx, fc, ev):
    st, m = fc.get("/mode")
    ctx.check(st == 200 and isinstance(m, dict), "GET /mode -> %s", st)
    ev["mode_before"] = m
    ctx.log("mode: %s", m)
    ctx.check(m.get("motion") != "fault", "supervisor reports motion-fault: %s", m)
    if m.get("motion") != "verified":
        ctx.log("probe %s at the last spawn - respawning the controller so it runs", m.get("motion"))
        st, body = fc.post("/controller/stop")
        ctx.check(st == 200, "POST /controller/stop -> %s", st)
        ctx.sleep(2)
        st, body = fc.post("/controller/start")
        ctx.check(st == 200, "POST /controller/start -> %s", st)
        t0 = time.time()
        while time.time() - t0 < 60:
            ctx.sleep(1)
            st, m = fc.get("/mode")
            if isinstance(m, dict) and m.get("controller") == "running":
                break
        ctx.sleep(3)
        st, m = fc.get("/mode")
    ev["mode_after"] = m
    ctx.log("mode after: %s", m)
    ctx.check(m.get("controller") == "running", "controller is %s", m.get("controller"))
    ctx.check(m.get("motion") == "verified", "liveness is %r, expected verified", m.get("motion"))


FORGECTRL_LOG = "/data/log/forgefirm/forgectrl/forgectrl.log"


def _log_offset(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _probe_lines(path, offset):
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return [ln.strip() for ln in data.splitlines() if "liveness probe:" in ln]


def _liveness_masked_restart(ctx, fc, ev):
    """The regression: a leftover motor_lock must not read as a wedge."""
    ctx.check(fc.wait_idle(15, abort=ctx.aborted), "machine not idle before the masked restart")
    x0 = _kernel_x_mm(ctx)
    hw.sysfs_write("cnc/motor_lock", "15")
    ctx.log("masked every axis (cnc/motor_lock=15); restarting forgectrl for a fresh probe")
    off = _log_offset(FORGECTRL_LOG)
    rc, out = hw.initd("forgectrl", "restart")
    ctx.check(rc == 0, "forgectrl restart -> rc %s", rc)
    m = None
    t0 = time.time()
    while time.time() - t0 < 150:
        ctx.checkpoint()
        try:
            st, m = fc.get("/mode")
        except hw.HwError:
            m = None                # the daemon is still coming up
        if isinstance(m, dict) and ((m.get("controller") == "running" and m.get("motion") == "verified")
                                    or m.get("controller") == "motion-fault"):
            break
        ctx.sleep(1)
    lines = _probe_lines(FORGECTRL_LOG, off)
    for ln in lines:
        ctx.log("  %s", ln.split(" INFO ", 1)[-1] if " INFO " in ln else ln[-160:])
    ev["masked_restart"] = {"mode": m, "probe_lines": lines[-4:], "motor_lock_after": ctx.sysfs("cnc/motor_lock")}
    ctx.check(m and m.get("controller") == "running" and m.get("motion") == "verified",
              "fresh probe under a leftover mask did not verify motion: %s", m)
    ctx.check(lines and "MOTION OK" in lines[0],
              "the first probe after the restart was not MOTION OK: %s", lines[:1])
    ctx.check(len(lines) == 1, "the probe needed the recovery ladder (%d probes) - a false dead verdict", len(lines))
    ctx.check(ctx.sysfs("cnc/motor_lock") == "8", "motor_lock reads %s after the controller start (expected 8)",
              ctx.sysfs("cnc/motor_lock"))
    ctx.check(fc.wait_idle(15, abort=ctx.aborted), "machine not idle after the probe")
    x1 = _kernel_x_mm(ctx)
    ctx.log("kernel X %s -> %s mm across the probe (out and back)", x0, x1)
    ctx.log("PASS: masked restart probed MOTION OK on the first try, mask cleared, controller up")


# ---------------------------------------------------------------- cancel / abort

@test("motion.cancel-abort", title="Jog cancel and controlled abort recover cleanly", subsystem="motion",
      kind="auto", est_min=2,
      covers=_MOTION_COVERS, requires=["motion.pacing"],
      steps=["Bed clear; the head needs 40 mm of free +X travel."],
      description="A jog-cancel (0x85) stops a jog short of its target and returns to Idle with "
                  "position preserved; a ^X abort mid-move (what the sender's Stop sends) "
                  "decelerates under control into Alarm with machine position retained, leaves the "
                  "head where it stopped - no return-to-start, that is the lid policy's move alone - "
                  "and $X recovers to Idle with a subsequent jog running (no driver wedge: the rail "
                  "never cycled).")
def cancel_abort(ctx):
    ev = ctx.evidence
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        start = g.status_report()["MPos"]
        # jog cancel
        g.command("$J=G91X40F2400")
        ctx.sleep(0.4)
        g.realtime(0x85)
        st = wait_state(ctx, g, "Idle", 5)
        ctx.check(st is not None, "not Idle within 5 s of the jog cancel")
        p1 = st["MPos"]
        moved1 = p1[0] - start[0]
        ev["cancel_moved_mm"] = round(moved1, 3)
        ctx.log("jog cancel: moved %.3f mm of 40 (state %s)", moved1, st["state"])
        ctx.check(0.5 < moved1 < 39.0, "jog cancel did not stop short of the target (%.3f mm)", moved1)
        # ^X abort mid-move
        g.command("G91")
        g.command("G1X30F600", timeout=0.5)
        ctx.sleep(1.0)
        g.realtime(0x18)
        st = wait_state(ctx, g, "Alarm", 5)
        ctx.check(st is not None, "^X did not land in Alarm within 5 s")
        p2 = st["MPos"]
        moved2 = p2[0] - p1[0]
        ev["abort_moved_mm"] = round(moved2, 3)
        ctx.log("^X abort: state %s, moved %.3f mm of 30, position retained %s", st["state"], moved2, p2)
        ctx.check(0.5 < moved2 < 29.5, "abort position not retained/plausible (%.3f mm)", moved2)
        r = g.command("$X")
        ctx.log("$X -> %s", r)
        st = wait_state(ctx, g, "Idle", 5)
        ctx.check(st is not None, "$X did not recover to Idle")
        # A sender abort is not a lid cancel: it stops where it stopped and
        # the head stays there. Only the lid/interlock policy returns to the
        # job start, and an unasked-for return move would be a surprise to
        # whoever pressed Stop.
        text = drain_text(g, 2.0)
        ev["abort_returned_home"] = "returned to the job start" in text
        p3 = g.status_report()["MPos"]
        ev["abort_drift_after_recovery_mm"] = round(abs(p3[0] - p2[0]), 3)
        ctx.log("after $X: %s (moved %.3f mm since the abort)", p3, ev["abort_drift_after_recovery_mm"])
        ctx.check(not ev["abort_returned_home"], "a sender abort triggered the return-to-start motion")
        ctx.check(ev["abort_drift_after_recovery_mm"] <= 0.05,
                  "the head moved %.3f mm on its own after a sender abort",
                  ev["abort_drift_after_recovery_mm"])
        # a jog after the abort proves the drivers are alive; return to start
        back = -(p2[0] - start[0])
        r = g.command("$J=G91X%.3fF2400" % back)
        ctx.check(not any(x.startswith("error") for x in r), "return jog refused: %s", r)
        peak, states, st = wait_idle(ctx, g, 30)
        ctx.check("TIMEOUT" not in states, "return jog did not complete: %s", states)
        final = st["MPos"]
        drift = abs(final[0] - start[0])
        ev["final_drift_mm"] = round(drift, 3)
        ctx.log("returned: drift %.3f mm", drift)
        ctx.check(drift <= 0.05, "position drift %.3f mm after cancel/abort/return", drift)
        g.command("G90")
    machine_idle(ctx)


# ---------------------------------------------------------------- dead-man

def _kernel_x_mm(ctx):
    pos = (ctx.forgectrl.status().get("pos") or {})
    return pos.get("x")


def _return_x(ctx, delta_mm):
    """Jog back by the kernel-measured X delta (grbl's own position may be
    untrusted after a kill; the kernel counters kept counting)."""
    if delta_mm is None or abs(delta_mm) < 0.05:
        return
    with ctx.grbl() as g:
        st = g.status_report()["state"]
        if st.startswith("Alarm"):
            g.command("$X")
        g.command("$J=G91X%.3fF1200" % (-delta_mm))
        wait_idle(ctx, g, 30)
    machine_idle(ctx)


@test("motion.deadman", title="Dead-man: controller kill, controller hang, forgectrl restart mid-move",
      subsystem="motion", kind="auto", est_min=4,
      covers=_MOTION_COVERS + [("forgectrl", "src/main.c"), ("forgectrl", "init/**")],
      requires=["motion.cancel-abort", "kernel.k1-k2"],
      steps=["Bed clear; the head needs 40 mm of free +X travel and must not be at the left rail."],
      description="SIGKILL of the controller mid-move: the supervisor reaps it, safes (cnc/stop, "
                  "latch relocked - it never unlocked), and respawns within seconds. SIGSTOP (a "
                  "hang) mid-move: the ring drains into a kernel underrun (fast halt, latch "
                  "locked); the hung process is killed and the supervisor respawns. forgectrl "
                  "restart mid-move: the busy controller finishes the move unmanaged and the new "
                  "daemon retakes supervision at idle. After each drill the head is jogged back "
                  "by the kernel-measured distance.")
def deadman(ctx):
    import os as _os
    import signal as _signal
    fc = ctx.forgectrl
    ev = ctx.evidence

    def latch_locked():
        v = hw.sysfs_int("cnc/interlock_circuit")
        return v is not None and bool(v & (1 << 3))

    def wait_running(timeout=30, not_pid=None):
        """A running controller; with not_pid, one other than that pid (a
        killed controller can still read as running until it is reaped)."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            st, m = fc.get("/mode")
            if (isinstance(m, dict) and m.get("controller") == "running" and m.get("pid")
                    and m.get("pid") != not_pid):
                return m
            ctx.sleep(0.5)
        return None

    # ---- 1. SIGKILL mid-move
    m0 = wait_running(10)
    ctx.check(m0, "controller not running")
    pid0 = m0["pid"]
    x0 = _kernel_x_mm(ctx)
    unlocked_seen = False
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        g.command("G91")
        g.command("G1X30F300", timeout=0.5)
        ctx.sleep(1.0)
        _os.kill(pid0, _signal.SIGKILL)
        ctx.log("SIGKILL sent to controller pid %d mid-move", pid0)
    t0 = time.time()
    while time.time() - t0 < 15:
        if not latch_locked():
            unlocked_seen = True
        st, m = fc.get("/mode")
        if isinstance(m, dict) and m.get("controller") == "running" and m.get("pid") != pid0:
            break
        ctx.sleep(0.2)
    m1 = wait_running(30)
    respawn_s = round(time.time() - t0, 1)
    ev["sigkill"] = {"old_pid": pid0, "new": m1, "respawn_s": respawn_s, "unlocked_seen": unlocked_seen}
    ctx.log("after SIGKILL: respawned as %s in %s s; latch unlocked seen: %s", m1, respawn_s, unlocked_seen)
    ctx.check(m1 and m1.get("pid") != pid0, "supervisor did not respawn the controller")
    ctx.check(not unlocked_seen, "the latch unlocked during the kill/respawn")
    ctx.check(m1.get("motion") != "fault", "motion fault after the respawn")
    ctx.sleep(3)
    x1 = _kernel_x_mm(ctx)
    ctx.log("kernel X: %s -> %s mm", x0, x1)
    _return_x(ctx, (x1 - x0) if (x0 is not None and x1 is not None) else None)

    # ---- 2. SIGSTOP (hang) mid-move -> kernel underrun
    m1 = wait_running(10)
    pid1 = m1["pid"]
    x0 = _kernel_x_mm(ctx)
    underruns0 = hw.sysfs_int("cnc/underruns", 0)
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        g.command("G91")
        g.command("G1X30F300", timeout=0.5)
        ctx.sleep(1.0)
        _os.kill(pid1, _signal.SIGSTOP)
        ctx.log("SIGSTOP sent to controller pid %d mid-move", pid1)
        t0 = time.time()
        kstate = None
        while time.time() - t0 < 10:
            kstate = hw.sysfs_read("cnc/state")
            if kstate == "underrun":
                break
            ctx.sleep(0.05)
        halt_s = round(time.time() - t0, 2)
        ev["sigstop"] = {"kernel_state": kstate, "halt_s": halt_s, "latch_locked": latch_locked(),
                         "underruns": hw.sysfs_int("cnc/underruns", 0)}
        ctx.log("after SIGSTOP: kernel %s in %s s, latch locked %s, underruns %s -> %s",
                kstate, halt_s, latch_locked(), underruns0, ev["sigstop"]["underruns"])
        _os.kill(pid1, _signal.SIGKILL)       # the hung controller cannot recover itself
    ctx.check(kstate == "underrun", "the ring did not drain into a kernel underrun (state %s)", kstate)
    ctx.check(latch_locked(), "latch unlocked after the underrun")
    m2 = wait_running(30, not_pid=pid1)
    ev["sigstop"]["respawn"] = m2
    ctx.check(m2 and m2.get("pid") != pid1, "supervisor did not respawn after the hang")
    ctx.sleep(3)
    x1 = _kernel_x_mm(ctx)
    _return_x(ctx, (x1 - x0) if (x0 is not None and x1 is not None) else None)

    # ---- 3. forgectrl restart mid-move: the move finishes, supervision retaken at idle
    m2 = wait_running(10)
    pid2 = m2["pid"]
    x0 = _kernel_x_mm(ctx)
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        g.command("G91")
        g.command("G1X30F300", timeout=0.5)     # ~6 s of motion
        ctx.sleep(1.0)
        rc, out = hw.initd("forgectrl", "restart")
        ctx.log("forgectrl restart mid-move -> rc %s", rc)
        peak, states, st = wait_idle(ctx, g, 30)
        ev["restart"] = {"rc": rc, "states": states}
        ctx.log("move after the restart: states %s", states)
        ctx.check("TIMEOUT" not in states, "the move did not finish after the forgectrl restart")
        g.command("G90")
    t0 = time.time()
    m3 = None
    while time.time() - t0 < 60:
        st, m3 = fc.get("/mode")
        if isinstance(m3, dict) and m3.get("controller") == "running":
            break
        ctx.sleep(1)
    ev["restart"]["mode_after"] = m3
    ctx.log("mode after restart: %s", m3)
    ctx.check(m3 and m3.get("controller") == "running", "supervision not retaken after the restart: %s", m3)
    ctx.check(m3.get("motion") == "verified", "motion not verified after the retake: %s", m3)
    # the retake, by design: the busy controller (unmanaged, its own fd carrying
    # the dead-man) finished its move; at idle the new supervisor stopped it,
    # re-probed motion, and started a supervised one under the broker
    ev["restart"]["replaced_at_idle"] = m3.get("pid") != pid2
    ctx.log("retake: unmanaged pid %s finished the move; supervised pid %s started at idle",
            pid2, m3.get("pid"))
    ctx.check(latch_locked(), "latch unlocked after the restart drill")
    x1 = _kernel_x_mm(ctx)
    _return_x(ctx, (x1 - x0) if (x0 is not None and x1 is not None) else None)
    machine_idle(ctx)
    ctx.log("PASS: kill respawned in %s s, hang -> underrun in %s s, restart retook supervision (pid %s)",
            respawn_s, halt_s, m3.get("pid"))


# ------------------------------------------------- lid / button (the factory's)

_LID_COVERS = _MOTION_COVERS + [("grblhal-glowforge", "src/glowforge_switches.c"),
                                ("grblhal-glowforge", "src/glowforge_switch_map.h"),
                                ("grblhal-glowforge", "src/glowforge_laser.c")]


def kernel_xy_mm(ctx):
    """The kernel's own position counters, in mm (forgectrl /status pos):
    what the machine physically did, independent of what grbl believes."""
    pos = (ctx.forgectrl.status().get("pos") or {})
    return float(pos.get("x", 0.0)), float(pos.get("y", 0.0))


def check_kernel_returned(ctx, ev, k0, tol_mm=0.1, tag=""):
    """After a return-to-start: the kernel counters must be back where the
    job started too. grbl's own drift can read 0.000 while the head never
    moved (a run the kernel did not take), which is exactly the failure
    that must not pass."""
    k1 = kernel_xy_mm(ctx)
    kdrift = max(abs(k1[0] - k0[0]), abs(k1[1] - k0[1]))
    ev[(tag + "_" if tag else "") + "kernel_drift_mm"] = round(kdrift, 3)
    ctx.log("kernel counters: start (%.2f, %.2f) -> now (%.2f, %.2f), drift %.3f mm",
            k0[0], k0[1], k1[0], k1[1], kdrift)
    ctx.check(kdrift <= tol_mm,
              "the kernel counters did not return to the job start (drift %.3f mm) - "
              "the return move was counted by grbl but not played by the machine", kdrift)


def drain_text(g, seconds):
    """Everything the controller said in the next `seconds`."""
    end = time.time() + seconds
    text = ""
    while time.time() < end:
        text += g.drain()
        time.sleep(0.1)
    return text


def expect_cancel_and_return(ctx, g, ev, start, k0, why, tag):
    """The cancel policy's whole tail, shared by every trigger that ends a
    job this way (lid or interlock, from Run or from a hold): the reason is
    reported, the controller resets without an alarm and with the position
    kept, and the head goes back to where the job started - which the KERNEL
    counters have to confirm, not grbl's belief about them."""
    text = drain_text(g, 3.0)
    msgs = [ln for ln in text.splitlines()
            if ln.startswith("[MSG:") or "help]" in ln or ln.startswith("ALARM")]
    ev[tag + "_messages"] = msgs
    ctx.log("[%s] controller: %s", tag, msgs)
    cancel_msg = "%s - job cancelled" % why
    ctx.check(cancel_msg in text, "[%s] the job was not cancelled with %r as the reason", tag, why)
    ctx.check("help]" in text, "[%s] no reset banner after the cancel (the sender must see the job end)", tag)
    ctx.check("ALARM" not in text, "[%s] an alarm was raised on the cancel (position should be kept)", tag)
    t0 = time.time()
    returned = "returned to the job start" in text
    while not returned and time.time() - t0 < 30:
        ctx.checkpoint()
        text += g.drain()
        returned = "returned to the job start" in text
        time.sleep(0.2)
    ev[tag + "_returned_message"] = returned
    ctx.check(returned, "[%s] the head did not report returning to the job start within 30 s", tag)
    st = wait_state(ctx, g, "Idle", 5)
    ctx.check(st is not None, "[%s] not Idle after the return (state %s)", tag,
              g.status_report()["state"])
    drift = max(abs(st["MPos"][i] - start[i]) for i in range(2))
    ev[tag + "_drift_mm"] = round(drift, 3)
    ctx.log("[%s] back at the job start: drift %.3f mm", tag, drift)
    ctx.check(drift <= 0.05, "[%s] head not back at the job start (drift %.3f mm)", tag, drift)
    machine_idle(ctx, 10)
    check_kernel_returned(ctx, ev, k0, tag=tag)
    return drift


@test("motion.button-hold-resume", title="The button pauses and resumes a job",
      subsystem="motion", kind="operator", est_min=2,
      covers=_LID_COVERS, requires=["motion.pacing"],
      steps=["Bed clear; the head needs 40 mm of free +X travel. No laser is involved.",
             "Press the button once when told (pause), and once more when told (resume)."],
      description="A travel job is running; one press of the big button feed-holds it (the sender "
                  "sees Hold), the next press resumes it (Run) and the move completes with its "
                  "position intact - the factory's pause/resume on the machine.")
def button_hold_resume(ctx):
    ev = ctx.evidence
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        start = g.status_report()["MPos"]
        g.command("M5")
        g.command("G91")
        g.command("G1X40F300", timeout=0.5)               # an 8 s move
        ctx.sleep(0.5)
        ctx.check(g.status_report()["state"].startswith("Run"), "the move did not start")
        g.drain()                                     # the message window opens at the prompt
        ctx.instruct("The head is moving. Press the button once now, then click Done.")
        st, text = wait_state_text(ctx, g, "Hold", 8)
        ctx.check(st is not None, "the press did not hold the job (state %s)", g.status_report()["state"])
        ev["held_state"] = st["state"]
        ev["held_at_mm"] = round(st["MPos"][0] - start[0], 3)
        ev["pause_message"] = "job paused" in text
        ctx.log("held: %s at %.3f mm of 40; message seen: %s", st["state"], ev["held_at_mm"],
                ev["pause_message"])
        g.drain()
        ctx.instruct("The head is stopped. Press the button once more now, then click Done.")
        # The press is proven by the job LEAVING the hold. Catching it in Run
        # is a race: a pause late in the move leaves a fraction of a second of
        # travel, which can be over before the next poll - the machine did
        # exactly the right thing and the test would still have called it a
        # failure.
        st, text = wait_left_state(ctx, g, "Hold", 10)
        ev["state_after_resume"] = st["state"] if st else None
        ev["resume_message"] = "job resumed" in text
        ctx.check(st is not None, "the second press did not resume the job (still held: %s)",
                  g.status_report()["state"])
        # Leaving the hold for Run or Idle is the resume; leaving it for Alarm
        # or Door is something else entirely, and must not read as a pass.
        ctx.check(st["state"].startswith(("Run", "Idle")),
                  "the job left the hold into %s, not into motion", st["state"])
        ctx.log("resumed: %s; message seen: %s", ev["state_after_resume"], ev["resume_message"])
        peak, states, st = wait_idle(ctx, g, 40)
        ctx.check("TIMEOUT" not in states, "the resumed move did not complete: %s", states)
        moved = st["MPos"][0] - start[0]
        ev["moved_mm"] = round(moved, 3)
        ctx.log("move completed after pause/resume: %.3f mm of 40", moved)
        ctx.check(abs(moved - 40.0) <= 0.05, "the resumed move did not land on its target (%.3f mm)", moved)
        g.command("$J=G91X-40F2400")
        wait_idle(ctx, g, 30)
        g.command("G90")
    machine_idle(ctx)
    ctx.log("PASS: button press held the job (%s), the next press resumed it, target reached", ev["held_state"])


@test("motion.lid-cancel-home", title="Lid open during a job - running or paused - cancels it and returns "
                                     "to the job start",
      subsystem="motion", kind="operator", est_min=5,
      covers=_LID_COVERS, requires=["motion.pacing", "motion.cancel-abort"],
      steps=["Bed clear; the head needs 40 mm of free +X travel. No laser is involved.",
             "Open the lid when told, and leave it open until the head has come back (twice: once "
             "with the job running, once with it paused on the button)."],
      description="A travel job is running when the lid opens: the job parks (planned deceleration), "
                  "the reason is reported, the controller resets (position kept, no alarm - the "
                  "sender's job is over), and the head returns on its own to where the job started "
                  "with the lid still open; the controller ends Idle at the start position. The same "
                  "job paused on the button takes the same path - a lid open from the hold cancels "
                  "and returns, it never resumes. With lid_policy=cancel (the default).")
def lid_cancel_home(ctx):
    ev = ctx.evidence
    policy = (ctx.forgectrl.settings() or {}).get("lid_policy") or "cancel"
    ev["lid_policy"] = policy
    ctx.check(policy == "cancel", "lid_policy is %r; this test needs cancel", policy)
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        start = g.status_report()["MPos"]
        k0 = kernel_xy_mm(ctx)
        ev["kernel_start"] = k0
        ev["start"] = start
        g.command("M5")
        g.command("G91")
        g.command("G1X40F300", timeout=0.5)               # an 8 s move
        ctx.sleep(0.5)
        ctx.check(g.status_report()["state"].startswith("Run"), "the move did not start")
        g.drain()                                     # the message window opens at the prompt
        ctx.instruct("The head is moving. Open the lid NOW and leave it open, then click Done.")
        drift = expect_cancel_and_return(ctx, g, ev, start, k0, "lid opened", "running")
        sw = (ctx.forgectrl.status().get("switches") or {})
        ev["lid_at_return"] = sw.get("lid")
        ctx.instruct("Close the lid, then click Done.")
        ctx.sleep(1)
        # a jog afterward proves the controller is usable without $X
        r = g.command("$J=G91X5F1200")
        ctx.check(not any(x.startswith("error") for x in r), "jog refused after the cancel: %s", r)
        wait_idle(ctx, g, 15)
        g.command("$J=G91X-5F1200")
        wait_idle(ctx, g, 15)

        # -- the same cancel, entered from a hold ---------------------------
        # A job paused on the button must not be resumable past a lid open:
        # the armed window and the hardware button latch have to agree, so
        # the lid ends the job here exactly as it does from Run.
        start2 = g.status_report()["MPos"]
        k1 = kernel_xy_mm(ctx)
        ev["hold_start"] = start2
        g.command("G91")                                  # the reset restored G90
        g.command("G1X40F300", timeout=0.5)
        ctx.sleep(0.5)
        ctx.check(g.status_report()["state"].startswith("Run"), "the second move did not start")
        g.drain()
        ctx.instruct("The head is moving again. Press the button once now (pause), then click Done.")
        st, held = wait_state_text(ctx, g, "Hold", 8)
        ctx.check(st is not None, "the press did not hold the job (state %s)", g.status_report()["state"])
        ev["hold_state"] = st["state"]
        ev["hold_pause_message"] = "job paused" in held
        ctx.log("paused: %s; message seen: %s", st["state"], ev["hold_pause_message"])
        g.drain()
        ctx.instruct("The job is paused. Open the lid NOW and leave it open, then click Done.")
        hold_drift = expect_cancel_and_return(ctx, g, ev, start2, k1, "lid opened", "hold")
        ctx.check(not g.status_report()["state"].startswith("Hold"),
                  "the controller is still holding after the lid cancelled the paused job")
        ctx.instruct("Close the lid, then click Done.")
        ctx.sleep(1)
        r = g.command("$J=G91X5F1200")
        ctx.check(not any(x.startswith("error") for x in r), "jog refused after the paused cancel: %s", r)
        wait_idle(ctx, g, 15)
        g.command("$J=G91X-5F1200")
        wait_idle(ctx, g, 15)
        g.command("G90")
    machine_idle(ctx)
    ctx.log("PASS: lid open cancelled the job from Run (drift %.3f mm) and from the hold (drift %.3f mm), "
            "reset without alarm, head returned to the start both times", drift, hold_drift)


@test("motion.interlock-cancel-home", title="The interlock loop cancels a job like the lid and returns to "
                                           "the job start",
      subsystem="motion", kind="operator", est_min=4,
      covers=_LID_COVERS, requires=["motion.lid-cancel-home"],
      steps=["Bed clear; the head needs 60 mm of free +X travel. No laser is involved.",
             "Be able to open the remote-interlock loop: unplug the Pro's interlock plug, or pull the "
             "jumper at J8 on a Basic/Plus. Restore it at the end.",
             "Open the interlock when told and leave it open until the head has come back."],
      description="The remote-interlock loop is the lid's equal in the cancel policy: opening it mid-job "
                  "cancels the job with 'interlock open' named as the reason - the lid's own message would "
                  "be wrong here - and sends the head back to the job start with the loop still open. "
                  "(An open lid not stopping the park is the lid test's park, which runs with the lid open "
                  "throughout; in GRBL mode the park is a rapid too short to open a lid during, so the "
                  "mid-park lid edge is the cloud test's.)")
def interlock_cancel_home(ctx):
    ev = ctx.evidence
    policy = (ctx.forgectrl.settings() or {}).get("lid_policy") or "cancel"
    ev["lid_policy"] = policy
    ctx.check(policy == "cancel", "lid_policy is %r; this test needs cancel", policy)
    sw = (ctx.forgectrl.status().get("switches") or {})
    ctx.check(sw.get("interlock_ok"), "the interlock loop already reads open - close it before this test")
    with ctx.grbl() as g:
        clean_slate(ctx, g)
        start = g.status_report()["MPos"]
        k0 = kernel_xy_mm(ctx)
        ev["start"] = start
        ev["kernel_start"] = k0
        g.command("M5")
        g.command("G91")
        g.command("G1X60F300", timeout=0.5)               # a 12 s move
        ctx.sleep(0.5)
        ctx.check(g.status_report()["state"].startswith("Run"), "the move did not start")
        g.drain()
        ctx.instruct("The head is moving. Open the INTERLOCK loop now (unplug it / pull the jumper) and "
                     "leave it open, then click Done.")
        sw = (ctx.forgectrl.status().get("switches") or {})
        ev["interlock_ok_after_pull"] = sw.get("interlock_ok")
        ctx.check(sw.get("interlock_ok") is False,
                  "the interlock still reads closed - the loop was not opened (switches: %s)", sw)
        drift = expect_cancel_and_return(ctx, g, ev, start, k0, "interlock open", "interlock")
        sw = (ctx.forgectrl.status().get("switches") or {})
        ev["switches_at_return"] = {"lid": sw.get("lid"), "interlock_ok": sw.get("interlock_ok")}
        ctx.log("at the end of the park: %s", ev["switches_at_return"])
        ctx.check(sw.get("interlock_ok") is False,
                  "the interlock was closed again before the park finished - the park ran with the loop "
                  "restored, not open")
        ctx.instruct("Restore the interlock loop (plug/jumper back in), then click Done.")
        ctx.sleep(1)
        sw = (ctx.forgectrl.status().get("switches") or {})
        ev["restored"] = {"lid": sw.get("lid"), "interlock_ok": sw.get("interlock_ok")}
        ctx.check(sw.get("interlock_ok"), "the interlock loop is still open - restore it before continuing")
        r = g.command("$J=G91X5F1200")
        ctx.check(not any(x.startswith("error") for x in r), "jog refused after the cancel: %s", r)
        wait_idle(ctx, g, 15)
        g.command("$J=G91X-5F1200")
        wait_idle(ctx, g, 15)
        g.command("G90")
    machine_idle(ctx)
    ctx.log("PASS: interlock open cancelled the job with its own reason and the head returned to the "
            "start (drift %.3f mm) with the loop still open", drift)


@test("motion.lid-policy-hold", title="lid_policy=hold parks the job in Door and a cycle start resumes it",
      subsystem="motion", kind="operator", est_min=4,
      covers=_LID_COVERS + [("forgectrl", "src/settings.*")], requires=["motion.lid-cancel-home"],
      steps=["Bed clear; the head needs 40 mm of free +X travel. No laser is involved.",
             "Open the lid when told, then close it when told; the job finishes after that."],
      description="The other lid policy, kept for senders that expect stock grblHAL: with "
                  "lid_policy=hold a lid open parks the job in the door state and holds it there - "
                  "no cancel, no return home - and once the lid is closed a cycle start finishes the "
                  "move with its position intact. The setting is restored to cancel at the end.")
def lid_policy_hold(ctx):
    ev = ctx.evidence
    fc = ctx.forgectrl
    was = (fc.settings() or {}).get("lid_policy") or "cancel"
    ev["lid_policy_before"] = was
    st, _b = fc.post("/settings", data={"lid_policy": "hold"})
    ctx.check(st == 200, "could not set lid_policy=hold (%s)", st)
    ctx.check(((fc.settings() or {}).get("lid_policy")) == "hold", "lid_policy did not take")
    try:
        with ctx.grbl() as g:
            clean_slate(ctx, g)
            start = g.status_report()["MPos"]
            g.command("M5")
            g.command("G91")
            g.command("G1X40F300", timeout=0.5)           # an 8 s move
            ctx.sleep(0.5)
            ctx.check(g.status_report()["state"].startswith("Run"), "the move did not start")
            g.drain()
            ctx.instruct("The head is moving. Open the lid NOW and leave it open, then click Done.")
            st, text = wait_state_text(ctx, g, "Door", 8)
            ev["door_state"] = st["state"] if st else g.status_report()["state"]
            ctx.check(st is not None, "the lid did not park the job in Door (state %s)", ev["door_state"])
            ev["messages"] = [ln for ln in text.splitlines() if ln.startswith("[MSG:")]
            ctx.check("job cancelled" not in text, "the job was cancelled under lid_policy=hold: %s", ev["messages"])
            ctx.check("returned to the job start" not in text,
                      "the head returned to the job start under lid_policy=hold")
            held = g.status_report()["MPos"]
            ev["parked_at"] = held
            ctx.log("parked in %s at %s", ev["door_state"], held)
            ctx.instruct("Close the lid, then click Done.")
            ctx.sleep(1)
            ev["state_after_close"] = g.status_report()["state"]
            ctx.log("after the lid closed: %s (a cycle start is needed)", ev["state_after_close"])
            g.realtime(0x7E)                              # ~ cycle start
            peak, states, st = wait_idle(ctx, g, 30)
            ev["states_after_resume"] = states
            ctx.check("TIMEOUT" not in states, "the job did not finish after the resume: %s", states)
            final = st["MPos"]
            moved = final[0] - start[0]
            ev["moved_mm"] = round(moved, 3)
            ctx.log("finished: moved %.3f mm of 40 (states %s)", moved, states)
            ctx.check(abs(moved - 40.0) <= 0.05,
                      "the resumed job did not finish its move (%.3f mm of 40)", moved)
            g.command("$J=G91X-40F1200")
            wait_idle(ctx, g, 30)
            g.command("G90")
        machine_idle(ctx)
    finally:
        st, _b = fc.post("/settings", data={"lid_policy": was})
        ev["lid_policy_restored"] = (fc.settings() or {}).get("lid_policy")
        ctx.log("lid_policy restored to %s", ev["lid_policy_restored"])
    ctx.check(ev["lid_policy_restored"] == was, "lid_policy was not restored to %r", was)
    ctx.log("PASS: lid_policy=hold parked the job in Door and the cycle start finished it (%.3f mm)",
            ev["moved_mm"])
