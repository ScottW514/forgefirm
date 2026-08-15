"""motion.* - the motion controller under grblHAL: dry motion, no emission.

Ported from `scripts/bench/pacing_test.py` (protocol-loop pacing) and
`scripts/bench/bench_m2.py` (motion-quality bench). Every move is relative
and round-trip; the laser stays latched (the tests never touch it); the
suite is the only Grbl client while a test runs.
"""
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


def wait_idle(ctx, g, timeout=30.0, poll=0.05):
    """Poll until Idle; returns (peak_feed_mm_min, states_seen, final_report)."""
    peak = 0.0
    states = []
    deadline = time.time() + timeout
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
        if state.startswith("Idle"):
            return peak, states, st
        time.sleep(poll)
    return peak, states + ["TIMEOUT"], st


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
      steps=["Bed clear, lid closed: the probe jogs the head a few mm (+X first)."],
      description="forgectrl's supervisor reports the head-accelerometer liveness probe as "
                  "verified for the running controller (the DRV8825s are not wedged); when the "
                  "probe was skipped at spawn, the controller is respawned once so it runs.")
def liveness_probe(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
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


# ---------------------------------------------------------------- cancel / abort

@test("motion.cancel-abort", title="Jog cancel and controlled abort recover cleanly", subsystem="motion",
      kind="auto", est_min=2,
      covers=_MOTION_COVERS, requires=["motion.pacing"],
      steps=["Bed clear; the head needs 40 mm of free +X travel."],
      description="A jog-cancel (0x85) stops a jog short of its target and returns to Idle with "
                  "position preserved; a ^X abort mid-move decelerates under control into Alarm "
                  "with machine position retained, $X recovers to Idle, and a subsequent jog runs "
                  "(no driver wedge: the rail never cycled).")
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

    def wait_running(timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            st, m = fc.get("/mode")
            if isinstance(m, dict) and m.get("controller") == "running" and m.get("pid"):
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
    m2 = wait_running(30)
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
    ctx.check(m3.get("pid") == pid2, "the busy controller was replaced (%s -> %s) instead of retaken",
              pid2, m3.get("pid"))
    ctx.check(latch_locked(), "latch unlocked after the restart drill")
    x1 = _kernel_x_mm(ctx)
    _return_x(ctx, (x1 - x0) if (x0 is not None and x1 is not None) else None)
    ctx.log("PASS: kill respawned in %s s, hang -> underrun in %s s, restart retook pid %s",
            respawn_s, halt_s, pid2)
