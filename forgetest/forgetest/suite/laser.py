"""laser.* - LIVE laser tests, ported from `scripts/bench/live_fire_drills.py`.

Every test here can emit. The page starts one only with the operator's
eye-protection / fire-watch / exhaust acknowledgment; the test then
prompts for the scrap and the button, streams a small job through the
controller, and the machine fires only after the operator presses the
physical arm button - nothing here defeats that gate, and forgetest
never touches the laser latch. One emission per test; on abort or error
the job is soft-reset (`^X`: controlled stop, latch relocked). The
witnesses are forgectrl's `/status` (`laser.emission_samples` = the
kernel's LASER_ON sample count, `hv_current_raw`, `lid_ir`) and
`/cool/status` (`armed`), sampled at ~8 Hz through the arm -> fire ->
disarm lifecycle.
"""
import time

from ..catalog import test
from .. import hw
from ..runner import Failed

_LASER_COVERS = [("grblhal-glowforge", "src/**"), ("kernel-module-glowforge", "**"),
                 ("forgectrl", "src/super.c"), ("forgectrl", "src/cool.c"),
                 ("forgectrl", "src/status.c"), ("forgectrl", "src/main.c")]

ARM_CUE = ("LIVE FIRE. Eye protection on, exhaust running, fire watch and extinguisher in reach, "
           "scrap under the head with room to move (%s), lid closed. When the job starts the "
           "white button lights and the stream blocks until you press the physical arm button; "
           "the machine fires only after your press. Ready?")


def sample(ctx):
    """One combined /status + /cool/status sample, or None on error."""
    fc = ctx.forgectrl
    try:
        st1, st = fc.get("/status")
        st2, cs = fc.get("/cool/status")
    except hw.HwError:
        return None
    if st1 != 200 or st2 != 200 or not isinstance(st, dict) or not isinstance(cs, dict):
        return None
    return {
        "t": time.time(),
        "kstate": st.get("state"),
        "emission": (st.get("laser") or {}).get("emission_samples"),
        "pgood": (st.get("laser") or {}).get("pgood_samples"),
        "faults": st.get("faults"),
        "hv": st.get("hv_current_raw"),
        "ir": st.get("lid_ir"),
        "homed": st.get("homed"),
        "armed": cs.get("armed"),
        "fire_watch": cs.get("fire_watch"),
        "verdict": cs.get("verdict"),
    }


def prepare(ctx, g):
    """Guarantee a clean Idle start: clear a latched Door hold or an Alarm."""
    st = g.status_report()
    if "Door" in st["state"] or "Hold" in st["state"]:
        g.realtime(0x18)
        ctx.sleep(2)
        g.drain()
        st = g.status_report()
    if "Alarm" in st["state"]:
        ctx.log("unlock: %s", g.command("$X"))
        st = g.status_report()
    ctx.log("connect: %s", st["state"])
    ctx.check(st["state"].startswith("Idle"), "controller is %s, expected Idle", st["state"])
    return st


def stream(g, lines):
    for ln in lines:
        g.send_raw((ln + "\n").encode())


def run_and_sample(ctx, g, job, sample_hz=8, overall_timeout=200):
    """Stream the job; sample forgectrl through arm -> fire -> disarm.
    Completes on: emission seen then Idle > 3 s; or armed then disarmed
    with no fire, Idle > 3 s, > 15 s in; or the overall timeout."""
    samples = []
    period = 1.0 / sample_hz
    s0 = sample(ctx)
    if s0:
        samples.append(s0)
    stream(g, job)
    t_start = time.time()
    next_t = t_start
    seen_emission = seen_armed = disarmed_now = False
    idle_since = None
    while time.time() - t_start < overall_timeout:
        ctx.checkpoint()
        now = time.time()
        if now >= next_t:
            smp = sample(ctx)
            if smp:
                samples.append(smp)
                if smp["emission"] and smp["emission"] > 0:
                    seen_emission = True
                if smp["armed"]:
                    seen_armed = True
                disarmed_now = seen_armed and not smp["armed"]
            next_t = now + period
        st = g.status_report()["state"]
        if st.startswith("Idle"):
            if idle_since is None:
                idle_since = now
            idle_for = now - idle_since
            if seen_emission and idle_for > 3.0:
                break
            if disarmed_now and (now - t_start) > 15 and idle_for > 3.0:
                break
        else:
            idle_since = None
        time.sleep(0.05)
    return samples


class LiveJob:
    """Leaves the laser commanded off on every exit; a soft reset on
    abort/failure stops motion, relocks, and closes the armed window."""

    def __init__(self, ctx, g):
        self.ctx, self.g = ctx, g

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                self.ctx.log("stopping the job: soft reset (%s)", exc_type.__name__)
                self.g.realtime(0x18)
                time.sleep(1)
            self.g.command("M5", timeout=1)
        except Exception:  # noqa: BLE001 - best effort on the way out
            pass
        return False


def wait_disarm(ctx, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        ctx.checkpoint()
        s = sample(ctx)
        if s and not s["armed"]:
            return time.time() - t0
        time.sleep(0.5)
    return None


@test("laser.emission-witness", title="Live emission witness (S400 vector mark) and job-based disarm",
      subsystem="laser", kind="live", always=True, est_min=5,
      covers=_LASER_COVERS,
      requires=["kernel.latch-locked-idle", "kernel.k1-k2", "motion.jog-roundtrip"],
      steps=["Scrap under the head with 20 mm of free +X and +Y travel; lid closed; exhaust on.",
             "Press the physical button when it lights white (the arm)."],
      description="A 20 mm square outline at S400/F600 in dynamic laser mode: emission_samples "
                  "(the kernel's LASER_ON sample count) goes nonzero during the fire window and "
                  "returns to 0 at Idle, HV current rises during the burn, the armed window is "
                  "observed, and the M2 program end disarms promptly at Idle (job-based, not "
                  "the 60 s idle grace). The operator confirms the mark.")
def emission_witness(ctx):
    ev = ctx.evidence
    with ctx.grbl() as g, LiveJob(ctx, g):
        prepare(ctx, g)
        base = sample(ctx)
        ctx.check(base, "forgectrl /status or /cool/status unavailable")
        ev["pre_fire"] = base
        ctx.log("pre-fire: emission=%s hv=%s armed=%s verdict=%s", base["emission"], base["hv"],
                base["armed"], base["verdict"])
        ctx.check(not base["emission"], "emission_samples nonzero before the job (%s)", base["emission"])
        ctx.instruct(ARM_CUE % "20 mm +X and +Y")
        job = ["G91", "G21", "M4", "S400",
               "G1 X20 F600", "G1 Y20 F600", "G1 X-20 F600", "G1 Y-20 F600",
               "M5", "G90", "M2"]
        samples = run_and_sample(ctx, g, job)
        emis = [s["emission"] for s in samples if s["emission"] is not None]
        peak = max(emis) if emis else 0
        end = emis[-1] if emis else None
        hv = [s["hv"] for s in samples if s["hv"] is not None]
        ir_peak = [0, 0, 0, 0]
        for s in samples:
            if s["ir"] and len(s["ir"]) == 4:
                for i in range(4):
                    ir_peak[i] = max(ir_peak[i], s["ir"][i])
        armed_seen = any(s["armed"] for s in samples)
        ev.update({"samples": len(samples), "emission_peak": peak, "emission_end": end,
                   "hv_min": min(hv) if hv else None, "hv_max": max(hv) if hv else None,
                   "lid_ir_peak": ir_peak, "armed_seen": armed_seen,
                   "pgood_peak": max((s["pgood"] for s in samples if s["pgood"] is not None), default=None)})
        ctx.log("emission_samples peak=%s end=%s; hv %s..%s; lid_ir peak %s; armed seen %s",
                peak, end, ev["hv_min"], ev["hv_max"], ir_peak, armed_seen)
        # X-3: job-based disarm at Idle after M2
        dt = wait_disarm(ctx, 75)
        ev["disarm_after_idle_s"] = round(dt, 1) if dt is not None else None
        ctx.log("time-to-disarm after Idle: %s s", ev["disarm_after_idle_s"])
    ctx.check(armed_seen, "the armed window was never observed (arm refused, or no button press)")
    ctx.check(peak > 0, "no emission witnessed (emission_samples stayed 0)")
    ctx.check(end == 0, "emission_samples did not return to 0 at Idle (%s)", end)
    ctx.check(hv and max(hv) > min(hv), "HV current did not rise during the burn (%s..%s)",
              ev["hv_min"], ev["hv_max"])
    ctx.check(dt is not None and dt < 10.0,
              "the M2 job did not disarm promptly at Idle (%s s; the idle grace is ~60 s)",
              ev["disarm_after_idle_s"])
    ctx.confirm("Did the laser mark a 20 mm square outline on the scrap, and is the machine now "
                "idle with the button dark?")
    ctx.log("PASS: emission peak %s -> 0, HV %s..%s, disarmed %.1f s after Idle, mark confirmed",
            peak, ev["hv_min"], ev["hv_max"], dt)


@test("laser.disarm-in-hold", title="Disarm grace counts down in Hold", subsystem="laser",
      kind="live", est_min=4,
      covers=_LASER_COVERS,
      requires=["laser.emission-witness"],
      steps=["Scrap under the head with 40 mm of free +X travel; lid closed; exhaust on.",
             "Press the physical button when it lights white."],
      description="Arm and start a +X move at S400/F300, feed-hold it after ~2 s of motion, and "
                  "hold: the disarm grace must count down while held and close the armed window "
                  "(armed -> false) without the job resuming.")
def disarm_in_hold(ctx):
    ev = ctx.evidence
    with ctx.grbl() as g, LiveJob(ctx, g):
        prepare(ctx, g)
        ctx.instruct(ARM_CUE % "40 mm +X")
        stream(g, ["G91", "G21", "M4", "S400", "G1 X40 F300"])
        ctx.log("armed; waiting for motion to start (arm + your button press)...")
        t0 = time.time()
        st = None
        while time.time() - t0 < 180:
            ctx.checkpoint()
            st = g.status_report()["state"]
            if st.startswith("Run"):
                break
            time.sleep(0.1)
        ctx.check(st and st.startswith("Run"), "motion never started (state=%s) - arm refused or no press", st)
        ctx.log("moving under laser: %s; feed-hold in 2 s", st)
        ctx.sleep(2)
        g.realtime(ord("!"))
        t1 = time.time()
        while time.time() - t1 < 5:
            st = g.status_report()["state"]
            if st.startswith("Hold"):
                break
            time.sleep(0.1)
        ev["held_state"] = st
        ctx.log("feed-held mid-move: %s; watching the disarm grace count down IN HOLD", st)
        ctx.check(st.startswith("Hold"), "feed hold did not park (state %s)", st)
        t0 = time.time()
        disarmed_at = None
        left_hold = None
        while time.time() - t0 < 120:
            ctx.checkpoint()
            s = sample(ctx)
            held = g.status_report()["state"].startswith("Hold")
            if s and not s["armed"]:
                disarmed_at = time.time() - t0
                break
            if not held and left_hold is None:
                left_hold = g.status_report()["state"]
                ctx.log("note: left Hold (state=%s) before disarm", left_hold)
            time.sleep(1)
        ev["disarmed_after_s"] = round(disarmed_at, 1) if disarmed_at is not None else None
        ev["left_hold"] = left_hold
        # recover: laser off, abort out of hold
        g.command("M5", timeout=1)
        g.realtime(0x18)
        ctx.sleep(1)
        if "Alarm" in g.status_report()["state"]:
            g.command("$X")
    ctx.check(disarmed_at is not None, "still armed after 120 s in Hold")
    ctx.check(left_hold is None, "the job left Hold (%s) before the disarm", left_hold)
    ctx.log("PASS: disarmed in Hold after %.1f s", disarmed_at)
    ctx.confirm("Did the head stop after ~2 s of the +X move and stay stopped, with the button "
                "going dark on its own about a minute later?")


@test("laser.expected-stop", title="Armed kill on the expected-stop path (POST /controller/stop)",
      subsystem="laser", kind="live", est_min=4,
      covers=_LASER_COVERS + [("forgectrl", "src/main.c")],
      requires=["laser.emission-witness"],
      steps=["Scrap under the head with 40 mm of free +X and +Y travel; lid closed; exhaust on.",
             "Press the physical button when it lights white.",
             "The controller is left stopped until you judge the stop; the test then restarts it."],
      description="Start a mark job at S400/F200; once emission is live, POST /controller/stop. "
                  "Emission must drop to 0 within 2.5 s and stay 0, the kernel must not be "
                  "running, and the supervisor's restart is a separate, operator-judged step "
                  "(POST /controller/start, no motion, no laser).")
def expected_stop(ctx):
    ev = ctx.evidence
    fc = ctx.forgectrl
    with ctx.grbl() as g, LiveJob(ctx, g):
        prepare(ctx, g)
        ctx.instruct(ARM_CUE % "40 mm +X and +Y")
        stream(g, ["G91", "G21", "M4", "S400",
                   "G1 X40 F200", "G1 Y40 F200", "G1 X-40 F200", "G1 Y-40 F200",
                   "M5", "G90", "M2"])
        t0 = time.time()
        smp = None
        seen = False
        while time.time() - t0 < 240:
            ctx.checkpoint()
            smp = sample(ctx)
            if smp and smp["emission"] and smp["emission"] > 0:
                seen = True
                break
            time.sleep(0.15)
        if not seen:
            g.realtime(0x18)
            raise Failed("no emission seen within 240 s (arm refused, or no button press)")
        ctx.log("emission live (%s) - stopping the controller NOW", smp["emission"])
        t_stop = time.time()
        code, body = fc.post("/controller/stop")
        post_dt = time.time() - t_stop
        ctx.log("POST /controller/stop -> %s %s (%.2f s)", code, body, post_dt)
        trail = []
        for _ in range(40):                 # ~5 s at 8 Hz
            s = sample(ctx)
            if s:
                trail.append((round(time.time() - t_stop, 2), s["emission"], s["kstate"], s["armed"]))
            time.sleep(0.12)
        for t in trail:
            ctx.log("  post-stop %s", t)
        zero_at = next((t for t, e, _, _ in trail if e == 0), None)
        tail_zero = all(e == 0 for _, e, _, _ in trail[-16:])
        not_running = all(k != "running" for _, _, k, _ in trail[-16:])
        st_mode, mode = fc.get("/mode")
        ev.update({"post_status": code, "post_s": round(post_dt, 2), "zero_at_s": zero_at,
                   "tail_zero": tail_zero, "kernel_not_running": not_running, "mode_after_stop": mode,
                   "trail": trail})
        ctx.log("emission first 0 at +%s s; last 2 s all zero: %s; kernel not running: %s; /mode %s",
                zero_at, tail_zero, not_running, mode)
    ctx.check(code == 200, "POST /controller/stop -> %s", code)
    ctx.check(zero_at is not None and zero_at < 2.5, "emission did not drop within 2.5 s (first 0 at %s)", zero_at)
    ctx.check(tail_zero, "emission returned after the stop")
    ctx.check(not_running, "the kernel was still running after the stop")
    ctx.instruct("The controller is STOPPED (supervision held). Judge the stop on the scrap - a "
                 "short cut, then an abrupt end - and confirm the machine is quiet; then Done to "
                 "restart the controller (no motion, no laser).")
    st, body = fc.post("/controller/start")
    ctx.log("POST /controller/start -> %s %s", st, body)
    ctx.check(st == 200, "POST /controller/start -> %s", st)
    ctx.sleep(6)
    st, mode = fc.get("/mode")
    ev["mode_after_start"] = mode
    ctx.log("/mode after start: %s", mode)
    ctx.check(isinstance(mode, dict) and mode.get("controller") == "running",
              "controller not running after the restart: %s", mode)
    ctx.log("PASS: stop in %.2f s, emission 0 at +%s s, controller restarted", post_dt, zero_at)


@test("laser.kill-mid-fire", title="Armed kill: SIGKILL of the controller while emitting",
      subsystem="laser", kind="live", est_min=4,
      covers=_LASER_COVERS,
      requires=["laser.expected-stop", "motion.deadman"],
      steps=["Scrap under the head with 40 mm of free +X and +Y travel; lid closed; exhaust on.",
             "Press the physical button when it lights white."],
      description="Start a mark job at S400/F200; once emission is live, SIGKILL the controller. "
                  "The supervisor's exit safing must end the fire tail within the ring's in-flight "
                  "window: emission drops to 0 within 2.5 s and stays 0, the kernel is not "
                  "running, the latch reads locked, and the controller is respawned.")
def kill_mid_fire(ctx):
    import os as _os
    import signal as _signal
    ev = ctx.evidence
    fc = ctx.forgectrl
    st, m0 = fc.get("/mode")
    ctx.check(st == 200 and isinstance(m0, dict) and m0.get("controller") == "running", "controller not running: %s", m0)
    pid = m0.get("pid")
    with ctx.grbl() as g, LiveJob(ctx, g):
        prepare(ctx, g)
        ctx.instruct(ARM_CUE % "40 mm +X and +Y")
        stream(g, ["G91", "G21", "M4", "S400",
                   "G1 X40 F200", "G1 Y40 F200", "G1 X-40 F200", "G1 Y-40 F200",
                   "M5", "G90", "M2"])
        t0 = time.time()
        smp = None
        seen = False
        while time.time() - t0 < 240:
            ctx.checkpoint()
            smp = sample(ctx)
            if smp and smp["emission"] and smp["emission"] > 0:
                seen = True
                break
            time.sleep(0.15)
        if not seen:
            g.realtime(0x18)
            raise Failed("no emission seen within 240 s (arm refused, or no button press)")
        ctx.log("emission live (%s) - SIGKILL controller pid %s NOW", smp["emission"], pid)
        t_kill = time.time()
        _os.kill(pid, _signal.SIGKILL)
        trail = []
        for _ in range(40):                 # ~5 s at 8 Hz
            s = sample(ctx)
            if s:
                trail.append((round(time.time() - t_kill, 2), s["emission"], s["kstate"], s["armed"]))
            time.sleep(0.12)
    for t in trail:
        ctx.log("  post-kill %s", t)
    zero_at = next((t for t, e, _, _ in trail if e == 0), None)
    tail_zero = all(e == 0 for _, e, _, _ in trail[-16:])
    not_running = all(k != "running" for _, _, k, _ in trail[-16:])
    ilk = hw.sysfs_int("cnc/interlock_circuit")
    locked = ilk is not None and bool(ilk & (1 << 3))
    ev.update({"pid": pid, "zero_at_s": zero_at, "tail_zero": tail_zero, "kernel_not_running": not_running,
               "latch_locked": locked, "trail": trail})
    ctx.log("emission first 0 at +%s s; last 2 s all zero: %s; kernel not running: %s; latch locked: %s",
            zero_at, tail_zero, not_running, locked)
    ctx.check(zero_at is not None and zero_at < 2.5, "emission did not drop within 2.5 s (first 0 at %s)", zero_at)
    ctx.check(tail_zero, "emission returned after the kill")
    ctx.check(not_running, "the kernel was still running after the kill")
    ctx.check(locked, "latch not locked after the kill")
    t0 = time.time()
    m1 = None
    while time.time() - t0 < 60:
        st, m1 = fc.get("/mode")
        if isinstance(m1, dict) and m1.get("controller") == "running" and m1.get("pid") != pid:
            break
        ctx.sleep(1)
    ev["mode_after"] = m1
    ctx.log("/mode after the kill: %s", m1)
    ctx.check(m1 and m1.get("controller") == "running" and m1.get("pid") != pid,
              "supervisor did not respawn the controller: %s", m1)
    ctx.confirm("Did the cut end abruptly at the kill (a short line, no run-on), with the machine "
                "quiet and the button dark now?")
    ctx.log("PASS: emission 0 at +%s s after SIGKILL, latch locked, controller respawned", zero_at)
