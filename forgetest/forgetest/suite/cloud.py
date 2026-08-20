"""cloud.* - the controller mode switch and the optional Glowforge web-service
mode (gfcloud daemon, gfhome homing runner). The mode-switch test makes the
grbl -> cloud -> grbl round trip; the job-behavior tests run in cloud mode
and leave the machine there (see enter_cloud)."""
import json
import os
import socket
import time

from ..catalog import test
from .. import hw
from ..baseline import read_position, read_program_total

_CLOUD_COVERS = [("forgefirm-app", "**"), ("python3-gfhardware", "**"), ("python3-gfutilities", "**"),
                 ("forgectrl", "src/super.c"), ("forgectrl", "src/main.c")]

GF_LATEST = "/data/forgefirm/gf-latest.json"
GFCLOUD_LOG = "/data/log/forgefirm/gfcloud/gfcloud.log"
SESSION_MARKS = ("authenticate_machine SUCCESS", "ws_connect ESTABLISHED")
RETURN_MAX_MM = 600.0       # the head comes back from the home corner across the bed


def log_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def session_lines(path, offset):
    """New gfcloud log lines since offset that carry a session mark."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return [ln.strip()[:160] for ln in data.splitlines() if any(m in ln for m in SESSION_MARKS)]


def session_established(lines):
    return all(any(m in ln for ln in lines) for m in SESSION_MARKS)


def return_head(ctx, feed=2400):
    """Jog the head back to where the run found it: cloud mode re-zeroed the
    kernel counters at the starting position, so the counters now read the
    displacement (the home corner). Ends on the machine idle."""
    fc = ctx.forgectrl
    pos = fc.status().get("pos") or {}
    x, y = float(pos.get("x", 0.0)), float(pos.get("y", 0.0))
    ctx.log("head displacement since the switch: X %.3f Y %.3f mm", x, y)
    ctx.check(abs(x) <= RETURN_MAX_MM and abs(y) <= RETURN_MAX_MM,
              "displacement %.1f/%.1f mm exceeds %.0f mm - not jogging back", x, y, RETURN_MAX_MM)
    if abs(x) < 0.05 and abs(y) < 0.05:
        return
    with ctx.grbl() as g:
        st = g.status_report()["state"]
        if st.startswith("Alarm"):
            g.command("$X")
        r = g.command("$J=G91X%.3fY%.3fF%d" % (-x, -y, feed))
        ctx.check(not any(k.startswith("error") for k in r), "return jog refused: %s", r)
        t0 = time.time()
        while time.time() - t0 < 120:
            ctx.checkpoint()
            st = g.status_report()["state"]
            if st.startswith("Idle") and time.time() - t0 > 0.5:
                break
            time.sleep(0.2)
        g.command("G90")
    ctx.check(fc.wait_idle(15, abort=ctx.aborted), "machine not idle after the return jog")
    pos = fc.status().get("pos") or {}
    ctx.log("head returned: counters X %.3f Y %.3f mm", float(pos.get("x", 0)), float(pos.get("y", 0)))
    ctx.check(abs(float(pos.get("x", 0))) < 0.1 and abs(float(pos.get("y", 0))) < 0.1,
              "head not back at the start after the return jog: %s", pos)


def wait_mode(ctx, fc, want_mode, want_controller="running", timeout=90):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        ctx.checkpoint()
        st, m = fc.get("/mode")
        if st == 200 and isinstance(m, dict):
            last = m
            if m.get("mode") == want_mode and m.get("controller") == want_controller:
                return m
            if m.get("controller") == "motion-fault":
                break
        time.sleep(1)
    return last


def grbl_port_open(timeout=5):
    try:
        s = socket.create_connection((os.environ.get("GRBL_HOST") or "127.0.0.1",
                                      int(os.environ.get("GRBL_PORT") or 23)), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


@test("cloud.mode-switch", title="Controller mode switch grbl -> cloud -> grbl", subsystem="cloud",
      kind="auto", est_min=4,
      covers=_CLOUD_COVERS, requires=["forgectrl.auth", "motion.pacing"],
      steps=["Bed clear: the cloud client homes the head to the corner on connect (the factory "
             "hunt) and the test jogs it back to where it started afterward. Cloud credentials "
             "configured; the machine on the network."],
      description="POST /mode switches to the cloud controller: gfcloud comes up under "
                  "supervision, authenticates and establishes its service session (its own log "
                  "lines are the evidence; the connect-time firmware probe is recorded when "
                  "configured); the camera service survives the switch; switching back brings "
                  "grblHAL up with the Grbl port open and Idle, and the head returns to its start.")
def mode_switch(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    st, m0 = fc.get("/mode")
    ctx.check(st == 200 and isinstance(m0, dict), "GET /mode -> %s", st)
    ev["mode_before"] = m0
    ctx.log("mode before: %s", m0)
    ctx.check(m0.get("mode") == "grbl", "start this test in grbl mode (now %s)", m0.get("mode"))
    st, cam0 = fc.get("/cam/status")
    ev["cam_before"] = cam0
    probe_before = None
    try:
        probe_before = os.stat(GF_LATEST).st_mtime
    except OSError:
        pass
    log_offset = log_size(GFCLOUD_LOG)
    lamp0 = hw.sysfs_read("pic/lid_led")

    st, body = fc.post("/mode", data={"controller": "cloud"})
    ctx.log("POST /mode controller=cloud -> %s %s", st, body)
    ctx.check(st == 200, "mode switch to cloud refused: %s %s", st, body)
    m = wait_mode(ctx, fc, "cloud", timeout=90)
    ev["mode_cloud"] = m
    ctx.log("mode after switch: %s", m)
    ctx.check(m and m.get("mode") == "cloud" and m.get("controller") == "running",
              "cloud controller did not come up: %s", m)
    # the client's own session lines are the evidence of a live cloud session
    t0 = time.time()
    session = []
    probe = None
    while time.time() - t0 < 120:
        ctx.checkpoint()
        session = session_lines(GFCLOUD_LOG, log_offset)
        if session_established(session):
            break
        time.sleep(2)
    ev["session"] = session
    for ln in session:
        ctx.log("  gfcloud: %s", ln.split(" ", 1)[-1] if " " in ln else ln)
    try:
        mt = os.stat(GF_LATEST).st_mtime
        if probe_before is None or mt > probe_before:
            with open(GF_LATEST) as f:
                probe = json.load(f)
    except (OSError, ValueError):
        pass
    ev["gf_probe"] = probe
    ctx.log("cloud session established: %s; firmware probe: %s", session_established(session), probe)
    st, cam1 = fc.get("/cam/status")
    ev["cam_during_cloud"] = cam1
    ctx.check(st == 200 and isinstance(cam1, dict), "camera status lost during cloud mode (%s)", st)

    st, body = fc.post("/mode", data={"controller": "grbl"})
    ctx.log("POST /mode controller=grbl -> %s %s", st, body)
    ctx.check(st == 200, "mode switch back to grbl refused: %s %s", st, body)
    m = wait_mode(ctx, fc, "grbl", timeout=120)
    ev["mode_after"] = m
    ctx.log("mode after switch back: %s", m)
    ctx.check(m and m.get("mode") == "grbl" and m.get("controller") == "running",
              "grbl controller did not come back: %s", m)
    ctx.check(m.get("motion") != "fault", "motion fault after the switch")
    ctx.sleep(3)
    ctx.check(grbl_port_open(), "Grbl port not open after the switch back")
    with ctx.grbl() as g:
        st = g.status_report()["state"]
        ev["grbl_state"] = st
        ctx.log("grbl state after: %s", st)
        ctx.check(st.startswith("Idle") or st.startswith("Alarm"), "grbl reports %s", st)
    ctx.check(session_established(session),
              "the cloud client never established its service session (no credentials, no "
              "network, or the service refused) - cloud mode not proven")
    st, cam2 = fc.get("/cam/status")
    ev["cam_after"] = cam2
    ctx.check(st == 200, "camera status lost after the switch back")
    # cloud mode's connect cleared the kernel counters at the starting position
    # and its hunt homed the head: bring it back
    ctx.counters_rezeroed()
    return_head(ctx)
    # cloud mode sets its own lid-lamp level (LLvl) and leaves it: hand back the level found
    lamp1 = hw.sysfs_read("pic/lid_led")
    ev["lid_lamp"] = {"before": lamp0, "after_cloud": lamp1}
    if lamp0 is not None and lamp1 != lamp0:
        hw.sysfs_write("pic/lid_led", lamp0)
        ctx.log("lid lamp: cloud mode left %s, restored %s", lamp1, lamp0)


@test("cloud.gfhome-homing", title="Glowforge web-service homing ($H with homing_mode=gfcloud)",
      subsystem="cloud", kind="operator", est_min=5,
      covers=_CLOUD_COVERS + [("grblhal-glowforge", "src/**")], requires=[],
      steps=["homing_mode = gfcloud and cloud credentials configured; bed clear, lid closed.",
             "Watch the gantry: the service drives it to the corner with camera corrections.",
             "The machine ends homed, the head parked at the home corner (the position "
             "counters are re-anchored there)."],
      description="In grbl mode, $H runs gfhome: the web-service homing session with the "
                  "head-accelerometer motion witness. The controller returns to Idle with "
                  "homed:true within the session timeout, and the operator confirms the head "
                  "reached the home corner.")
def gfhome_homing(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    settings = fc.settings()
    hm = settings.get("homing_mode")
    ev["homing_mode"] = hm
    ctx.check(hm == "gfcloud", "homing_mode is %r, this test needs gfcloud", hm)
    ctx.instruct("Bed clear, lid closed, head anywhere. Watch the gantry during homing.")
    with ctx.grbl() as g:
        st = g.status_report()["state"]
        ctx.check(st.startswith("Idle") or st.startswith("Alarm"), "controller is %s", st)
        if st.startswith("Alarm"):
            g.command("$X")
        t0 = time.time()
        g.send_raw(b"$H\n")
        homed = False
        state = None
        while time.time() - t0 < 600:
            ctx.checkpoint()
            s = fc.status()
            state = s.get("state")
            try:
                gs = g.status_report()["state"]
            except hw.HwError:
                gs = "?"
            if s.get("homed") and gs.startswith("Idle"):
                homed = True
                break
            if gs.startswith("Alarm"):
                break
            time.sleep(2)
        ev["homing_s"] = round(time.time() - t0, 1)
        ev["homed"] = homed
        ctx.log("homing: homed=%s after %.1f s (kernel %s, grbl %s)", homed, ev["homing_s"], state, gs)
    ctx.check(homed, "homing did not complete (grbl %s)", gs)
    ctx.confirm("Did the head travel to the home corner under camera corrections and stop there?")
    # homed: the counters are re-anchored at the corner, where the head stays
    ctx.counters_rezeroed()
    ctx.check(fc.wait_idle(15, abort=ctx.aborted), "machine not idle after homing")


# ---- lid / button behavior of a cloud job (the factory's) ------------------
#
# These tests run IN cloud mode and stay there: enter_cloud() reuses a live
# cloud session when the machine is already in cloud mode (the operator
# switched once, on the panel or through an earlier test) and switches -
# once, declaring the change to the baseline - only when it finds GRBL
# mode. Nothing switches back; the operator does, when done. Each test
# judges the gfcloud log from its own window (the offset enter_cloud
# returns) and waits for the service's deferred moves (the re-hunt after a
# lid close, the hunt after a print) to finish before it ends, so the next
# run - or the operator - gets a quiet machine.

WS_MARKS = ("RX-EVENT: ready", "RX-EVENT: closed", "RECONNECTING", "CLOSING")
ACTIVITY_MARKS = ("start motion", "start return home", "starting run", "starting z homing cycle")
LOG_TAIL_BYTES = 4 << 20
QUIET_S = 8                 # the re-hunt's motions are ~4 s apart (a lid image between them)
QUIET_TIMEOUT_S = 180
HUNT_TIMEOUT_S = 180


def log_lines_since(path, offset):
    """New gfcloud log lines since offset (each 'ISO-time gfcloud[pid] LEVEL where message')."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def log_tail(path, max_bytes=LOG_TAIL_BYTES):
    """The last max_bytes of the log, as lines (the first may be partial)."""
    size = log_size(path)
    return log_lines_since(path, max(0, size - max_bytes))


def line_time(line):
    """Seconds (float) from the log line's ISO timestamp, or None."""
    try:
        ts = line.split(" ", 1)[0]
        head, frac = ts[:19], ts[19:]
        micro = 0.0
        if frac.startswith("."):
            digits = ""
            for ch in frac[1:]:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            micro = float("0." + digits) if digits else 0.0
        return time.mktime(time.strptime(head, "%Y-%m-%dT%H:%M:%S")) + micro
    except (ValueError, IndexError):
        return None


def wait_log(ctx, offset, needles, timeout, poll=0.5):
    """Wait until every needle has appeared in the gfcloud log since offset;
    returns {needle: first matching line or None}."""
    found = {n: None for n in needles}
    t0 = time.time()
    while time.time() - t0 < timeout:
        ctx.checkpoint()
        for ln in log_lines_since(GFCLOUD_LOG, offset):
            for n in needles:
                if found[n] is None and n in ln:
                    found[n] = ln
        if all(found.values()):
            break
        time.sleep(poll)
    return found


def action_finish_index(lines, action):
    """Index of the first '<action> [id]: finished with event ...' line, or None."""
    return next((i for i, ln in enumerate(lines)
                 if (action + " [") in ln and "finished with event" in ln), None)


def wait_action_finished(ctx, offset, action, timeout, poll=0.5):
    """The action's own terminal line ('<action> [id]: finished with event
    ":completed"' / '":cancelled"'), or None within timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        ctx.checkpoint()
        lines = log_lines_since(GFCLOUD_LOG, offset)
        i = action_finish_index(lines, action)
        if i is not None:
            return lines[i]
        time.sleep(poll)
    return None


def message(line):
    """The message part of a log line (after 'ISO-time gfcloud[pid]')."""
    return line.split(" ", 2)[-1] if line else None


def session_live(pid):
    """(live, detail): the running cloud client (gfcloud[pid]) has a live
    service session when its last websocket state line is 'ready' - a
    later 'closed'/'RECONNECTING'/'CLOSING' means it is not connected
    now. Without any line for that pid the newest lines of the log stand
    in (the client may log under a wrapper's pid)."""
    tag = "gfcloud[%s]" % pid if pid else None
    last_pid = last_any = None
    for ln in log_tail(GFCLOUD_LOG):
        for m in WS_MARKS:
            if m in ln:
                last_any = m
                if tag and tag in ln:
                    last_pid = m
    last = last_pid if last_pid is not None else last_any
    where = "pid %s" % pid if last_pid is not None else "newest lines"
    return last == "RX-EVENT: ready", "%s: last websocket state %s" % (where, last)


def wait_quiet(ctx, offset, quiet_s=None, timeout=None):
    """The service's moves are over: the machine idle and no new service
    activity in the log (a motion, a park, a run, a lens homing) for
    quiet_s (default QUIET_S; timeout QUIET_TIMEOUT_S). False on timeout."""
    quiet_s = QUIET_S if quiet_s is None else quiet_s
    timeout = QUIET_TIMEOUT_S if timeout is None else timeout
    fc = ctx.forgectrl
    t0 = time.time()
    n_seen = -1
    last_change = t0
    while time.time() - t0 < timeout:
        ctx.checkpoint()
        lines = log_lines_since(GFCLOUD_LOG, offset)
        n = sum(1 for ln in lines if any(m in ln for m in ACTIVITY_MARKS))
        if n != n_seen:
            n_seen = n
            last_change = time.time()
        if fc.status().get("state") == "idle" and time.time() - last_change >= quiet_s:
            return True
        time.sleep(0.5)
    return False


def wait_session(ctx, offset, timeout=120):
    session = []
    t0 = time.time()
    while time.time() - t0 < timeout:
        ctx.checkpoint()
        session = session_lines(GFCLOUD_LOG, offset)
        if session_established(session):
            return session
        time.sleep(2)
    return session


def fresh_cloud_connect(ctx):
    """A NEW cloud client with a fresh service session (its connect-time
    hunt follows): in cloud mode the controller is restarted through the
    supervisor's stop/start lever; in GRBL mode the mode is switched (and
    the change declared - the machine stays in cloud mode). Returns the log
    offset from before the connect, so the caller sees the whole session."""
    fc = ctx.forgectrl
    st, m = fc.get("/mode")
    ctx.check(st == 200 and isinstance(m, dict), "GET /mode -> %s", st)
    offset = log_size(GFCLOUD_LOG)
    if m.get("mode") == "cloud":
        ctx.log("cloud mode: restarting the cloud client for a fresh connect (was pid %s)", m.get("pid"))
        st, body = fc.post("/controller/stop")
        ctx.check(st == 200, "controller stop refused: %s %s", st, body)
        m = wait_mode(ctx, fc, "cloud", want_controller="standby", timeout=30)
        ctx.check(m and m.get("controller") == "standby", "the cloud client did not stop: %s", m)
        st, body = fc.post("/controller/start")
        ctx.check(st == 200, "controller start refused: %s %s", st, body)
    else:
        ctx.log("%s mode: switching to cloud", m.get("mode"))
        st, body = fc.post("/mode", data={"controller": "cloud"})
        ctx.check(st == 200, "mode switch to cloud refused: %s %s", st, body)
    m = wait_mode(ctx, fc, "cloud", timeout=90)
    ctx.check(m and m.get("mode") == "cloud" and m.get("controller") == "running",
              "cloud controller did not come up: %s", m)
    ctx.mode_changed("cloud")
    session = wait_session(ctx, offset)
    ctx.check(session_established(session),
              "the cloud client never established its service session (no credentials, no "
              "network, or the service refused)")
    ctx.log("cloud session established (pid %s)", m.get("pid"))
    return offset


def enter_cloud(ctx):
    """Cloud mode with a live service session and a quiet machine. An
    existing cloud session is reused; from GRBL mode the switch is made
    once (its connect-time hunt is waited out) and the machine stays in
    cloud mode. Returns the log offset where the test's own window begins."""
    fc = ctx.forgectrl
    st, m = fc.get("/mode")
    ctx.check(st == 200 and isinstance(m, dict), "GET /mode -> %s", st)
    if m.get("mode") == "cloud" and m.get("controller") == "running":
        live, detail = session_live(m.get("pid"))
        ctx.check(live, "cloud mode is up (pid %s) but the client has no live service session (%s) - "
                  "check credentials and network, or restart the controller", m.get("pid"), detail)
        ctx.log("cloud mode already up (pid %s), service session live - reusing it", m.get("pid"))
        offset = log_size(GFCLOUD_LOG)
    else:
        offset = fresh_cloud_connect(ctx)
        hunt = wait_action_finished(ctx, offset, "hunt", HUNT_TIMEOUT_S)
        ctx.check(hunt, "the service sent no connect-time hunt (or it never finished) within %d s",
                  HUNT_TIMEOUT_S)
        ctx.log("connect-time hunt: %s", message(hunt))
    ctx.check(wait_quiet(ctx, offset), "the cloud client was still running service moves after %d s",
              QUIET_TIMEOUT_S)
    return log_size(GFCLOUD_LOG)


def settle_cloud(ctx, offset):
    """End of a cloud test: the service's follow-up moves (a hunt after a
    print, the re-hunt after a lid close) done and the machine idle."""
    ctx.check(wait_quiet(ctx, offset), "the service was still moving the head %d s after the test",
              QUIET_TIMEOUT_S)
    ctx.log("cloud mode stays up; the machine is quiet")


def wait_print_running(ctx, offset, timeout):
    """The PRINT is running: a "starting run" line after the print's button
    wait (the connect-time hunt and the service's moves before it are runs
    too, and must not be mistaken for the print). Returns the line or None."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        ctx.checkpoint()
        lines = log_lines_since(GFCLOUD_LOG, offset)
        wait_i = next((i for i, ln in enumerate(lines) if "waiting for button" in ln), None)
        if wait_i is not None:
            run = next((ln for ln in lines[wait_i:] if "starting run" in ln), None)
            if run:
                return run
        time.sleep(0.5)
    return None


def latch_locked():
    ilk = hw.sysfs_int("cnc/interlock_circuit")
    return ilk is not None and bool(ilk & (1 << 3))


APP_PRINT_CUE = ("In the Glowforge app: scrap on the bed, lid closed, a SMALL engrave or score job "
                 "(about 30 s) set up. Click Done here, then press Print in the app and press the "
                 "physical button when it lights white.")

CANCELLED = 'finished with event ":cancelled"'
COMPLETED = 'finished with event ":completed"'
CLOUD_STEP = ("Cloud credentials configured; the machine in cloud mode (the test switches once from "
              "GRBL mode and stays in cloud mode; switch back on the panel when done).")


def judge_abort_tail(ctx, ev, offset, tag, fin):
    """The tail every cloud abort shares: the park ran to completion, the head
    is back at the job start by the KERNEL counters (cloud clears them at every
    job start, so a completed park reads back at zero - stale ring bytes played
    ahead of it would not), the print ended ':cancelled', the latch is locked
    and the armed window closed."""
    ctx.check(ctx.forgectrl.wait_idle(15, abort=ctx.aborted), "[%s] machine not idle after the park", tag)
    kpos = read_position()
    ev[tag + "_counters_after_park"] = kpos
    ctx.log("[%s] kernel counters after the park: %s", tag, kpos)
    ctx.check(kpos is not None and abs(kpos[0]) <= 3 and abs(kpos[1]) <= 3,
              "[%s] the head did not come back to the job start (kernel counters %s)", tag, kpos)
    ctx.check(fin and CANCELLED in fin, "[%s] the print did not end ':cancelled': %s", tag,
              message(fin) or "no finish line")
    st, cs = ctx.forgectrl.get("/cool/status")
    ev[tag + "_armed_after"] = cs.get("armed") if isinstance(cs, dict) else None
    ev[tag + "_latch_locked"] = latch_locked()
    ctx.check(not ev[tag + "_armed_after"], "[%s] armed window still open after the abort", tag)
    ctx.check(ev[tag + "_latch_locked"], "[%s] kernel latch not locked after the abort", tag)


@test("cloud.lid-interlock-abort", title="Lid and interlock each abort a cloud print; the park ignores "
                                         "an open lid",
      subsystem="cloud", kind="live", est_min=11,
      covers=_CLOUD_COVERS + [("forgectrl", "src/super.c")],
      requires=["laser.emission-witness"],
      steps=[CLOUD_STEP, "The app open in a browser; scrap on the bed and a small engrave/score job "
                         "ready - the test runs TWO prints.",
             "Be able to open the remote-interlock loop for the second print: unplug the Pro's "
             "interlock plug, or pull the jumper at J8 on a Basic/Plus. Restore it at the end.",
             "Print 1: press the button to start, open the lid a few seconds in. Print 2: press the "
             "button to start, open the interlock a few seconds in, then open the lid as well while "
             "the head is parking."],
      description="Both enclosure triggers, on one setup, behaving as the factory's do. The lid: the "
                  "edge reaches the controlled stop within milliseconds, the head returns home at "
                  "once with the lid still open, the latch relocks and the armed window closes, and "
                  "the job ends ':cancelled'. The remote-interlock loop: the same tail, and opening "
                  "the lid while THAT park is running does not interrupt it - the park is deliberately "
                  "immune, so it always reports complete.")
def lid_interlock_abort(ctx):
    ev = ctx.evidence
    sw = (ctx.forgectrl.status().get("switches") or {})
    ctx.check(sw.get("interlock_ok"), "the interlock loop already reads open - close it before this test")
    offset = enter_cloud(ctx)

    # -- print 1: the lid ----------------------------------------------------
    ctx.instruct(APP_PRINT_CUE)
    got = wait_print_running(ctx, offset, 300)
    ctx.check(got, "print 1 never reached its run within 300 s (not started, or the button not pressed)")
    ctx.instruct("The head is moving. Open the lid NOW, then click Done. Leave it open until the head "
                 "has returned to the corner.")
    needles = ["lid opened", "lid opened mid-run; stopping motion", "start return home",
               "return home complete"]
    got = wait_log(ctx, offset, needles, 90)
    fin = wait_action_finished(ctx, offset, "print", 60)
    got["print finished"] = fin
    ev["lid_log"] = {k: message(v) for k, v in got.items()}
    for k, v in got.items():
        ctx.log("  [lid] %s: %s", k, "seen" if v else "MISSING")
    ctx.check(got["lid opened mid-run; stopping motion"], "the lid open did not stop the run")
    # The lid edge that stopped the run is the LAST "lid opened" edge line
    # before the stop line (an earlier open, e.g. to place the scrap, is
    # not the one).
    lines = log_lines_since(GFCLOUD_LOG, offset)
    stop_i = next((i for i, ln in enumerate(lines) if "lid opened mid-run; stopping motion" in ln), None)
    edge_line = None
    if stop_i is not None:
        edge_line = next((ln for ln in reversed(lines[:stop_i])
                          if "_switch_event lid opened" in ln or ln.rstrip().endswith(" lid opened")), None)
    t_edge = line_time(edge_line) if edge_line else None
    t_stop = line_time(lines[stop_i]) if stop_i is not None else None
    if t_edge is not None and t_stop is not None:
        ev["edge_to_stop_ms"] = round((t_stop - t_edge) * 1000, 1)
        ctx.log("lid edge -> stop: %s ms", ev["edge_to_stop_ms"])
        ctx.check(ev["edge_to_stop_ms"] < 60, "stop was not edge-driven (%s ms after the lid edge)",
                  ev["edge_to_stop_ms"])
    ctx.check(got["start return home"] and got["return home complete"],
              "the park did not run to completion with the lid open")
    judge_abort_tail(ctx, ev, offset, "lid", fin)
    ctx.confirm("Did the head stop as soon as the lid opened and go straight home with the lid "
                "still open, and does the app show the print as cancelled?")
    ctx.instruct("Close the lid, then click Done.")
    settle_cloud(ctx, offset)

    # -- print 2: the interlock, with the lid opened during the park ---------
    offset = log_size(GFCLOUD_LOG)
    ctx.instruct(APP_PRINT_CUE)
    got = wait_print_running(ctx, offset, 300)
    ctx.check(got, "print 2 never reached its run within 300 s (not started, or the button not pressed)")
    ctx.instruct("The head is moving. Open the INTERLOCK loop now (unplug it / pull the jumper), then "
                 "click Done.")
    sw = (ctx.forgectrl.status().get("switches") or {})
    ev["interlock_ok_after_pull"] = sw.get("interlock_ok")
    ctx.check(sw.get("interlock_ok") is False,
              "the interlock still reads closed - the loop was not opened (switches: %s)", sw)
    stop_line = "interlock opened mid-run; stopping motion"
    got = wait_log(ctx, offset, [stop_line, "start return home"], 90)
    ctx.check(got[stop_line], "the interlock open did not stop the run")
    ctx.check(got["start return home"], "the abort did not start the return home")
    ctx.instruct("The head is on its way back. Open the LID now as well, then click Done - leave both "
                 "open until the head has stopped.")
    done = wait_log(ctx, offset, ["return home complete"], 90)
    fin = wait_action_finished(ctx, offset, "print", 60)
    ev["interlock_log"] = {stop_line: message(got[stop_line]),
                           "start return home": message(got["start return home"]),
                           "return home complete": message(done["return home complete"]),
                           "print finished": message(fin)}
    for k, v in ev["interlock_log"].items():
        ctx.log("  [interlock] %s: %s", k, "seen" if v else "MISSING")
    ctx.check(done["return home complete"],
              "the park did not run to completion with the lid opened during it")
    sw = (ctx.forgectrl.status().get("switches") or {})
    ev["switches_at_return"] = {"lid": sw.get("lid"), "interlock_ok": sw.get("interlock_ok")}
    ctx.check(sw.get("lid") is False,
              "the lid was not open at the end of the park - the park's immunity was not exercised")
    judge_abort_tail(ctx, ev, offset, "interlock", fin)
    ctx.confirm("Did the head stop when the interlock opened and go back to the corner without the "
                "open lid interrupting it, and does the app show the print as cancelled?")
    ctx.instruct("Close the lid and restore the interlock loop (plug/jumper back in), then click Done.")
    sw = (ctx.forgectrl.status().get("switches") or {})
    ev["restored"] = {"lid": sw.get("lid"), "interlock_ok": sw.get("interlock_ok")}
    ctx.check(sw.get("interlock_ok"), "the interlock loop is still open - restore it before continuing")
    settle_cloud(ctx, offset)
    ctx.log("PASS: lid open -> stop in %s ms and park with the lid open; interlock open -> the same "
            "tail with the park running through a lid edge; both prints ':cancelled'",
            ev.get("edge_to_stop_ms"))


@test("cloud.lid-during-button-wait", title="Lid open at the cloud button prompt cancels the print",
      subsystem="cloud", kind="operator", est_min=6,
      covers=_CLOUD_COVERS, requires=[],
      steps=[CLOUD_STEP, "The app open; any small job ready (nothing will fire).",
             "Print from the app; when the button lights white, do NOT press it - open the lid."],
      description="A cloud print waiting for the button is cancelled by the lid: the wait ends "
                  "with the lid named as the reason, the laser latch relocks, the armed window "
                  "closes, no run starts, and the job ends ':cancelled'.")
def lid_during_button_wait(ctx):
    ev = ctx.evidence
    offset = enter_cloud(ctx)
    ctx.instruct("In the Glowforge app: lid closed, a small job set up. Click Done here, then press "
                 "Print in the app. When the button lights white, do NOT press it.")
    got = wait_log(ctx, offset, ["waiting for button"], 300)
    ctx.check(got["waiting for button"], "the print never reached the button wait")
    ctx.instruct("The button is lit. Open the lid now (do not press the button), then click Done.")
    relock = "button wait lid opened - relocking the laser"
    got = wait_log(ctx, offset, [relock], 60)
    fin = wait_action_finished(ctx, offset, "print", 60)
    ev["log"] = {relock: bool(got[relock]), "print finished": message(fin)}
    ctx.check(got[relock], "the lid did not end the button wait")
    ctx.check(fin and CANCELLED in fin, "the print did not end ':cancelled': %s",
              message(fin) or "no finish line")
    # No run may start between the button wait and the cancel: the print
    # itself, or a park (the head never moved, there is nothing to park).
    # The service's moves BEFORE the print are legitimate runs and are
    # outside this window.
    lines = log_lines_since(GFCLOUD_LOG, offset)
    wait_i = next((i for i, ln in enumerate(lines) if "waiting for button" in ln), None)
    end_i = action_finish_index(lines, "print")
    if end_i is None or wait_i is None or end_i < wait_i:
        end_i = len(lines)
    ran = ([ln for ln in lines[wait_i:end_i] if "starting run" in ln]
           if wait_i is not None else [])
    ev["runs_started_after_wait"] = len(ran)
    ctx.check(not ran, "a run started after the lid-open cancel (%d)", len(ran))
    st, cs = ctx.forgectrl.get("/cool/status")
    ev["armed_after"] = cs.get("armed") if isinstance(cs, dict) else None
    ev["latch_locked"] = latch_locked()
    ctx.check(not ev["armed_after"], "armed window still open after the cancel")
    ctx.check(ev["latch_locked"], "kernel latch not locked after the cancel")
    ctx.confirm("Did the button go dark when the lid opened, with no motion, and does the app show "
                "the print as cancelled?")
    ctx.instruct("Close the lid, then click Done.")
    settle_cloud(ctx, offset)
    ctx.log("PASS: lid open at the button prompt cancelled the print; latch locked, armed=false")


@test("cloud.hunt-lid-open", title="A cloud hunt runs with the lid open",
      subsystem="cloud", kind="operator", est_min=5,
      covers=_CLOUD_COVERS + [("forgectrl", "src/super.c")], requires=[],
      steps=[CLOUD_STEP, "Bed clear.",
             "Open the lid when asked and leave it open through the connect-time hunt of the fresh "
             "cloud client the test starts (in cloud mode the client is restarted; from GRBL mode "
             "the switch is made)."],
      description="The service's connect-time hunt (lens homing plus its XY hunt) is not gated by "
                  "the lid: it runs and reports ':completed' with the lid open, as the factory's does. "
                  "The service's moves after the lid closes again are waited out.")
def hunt_lid_open(ctx):
    ev = ctx.evidence
    ctx.instruct("Open the lid and leave it open, then click Done.")
    sw = (ctx.forgectrl.status().get("switches") or {})
    ev["lid_before"] = sw.get("lid")
    ctx.check(not sw.get("lid"), "the lid reads closed (%s)", sw)
    offset = fresh_cloud_connect(ctx)
    # The hunt's own terminal line ("hunt [id]: finished with event ..."):
    # it must be :completed, and no lid refusal may precede it. Service
    # motions AFTER the hunt are rightly refused with the lid open and
    # are outside this window.
    hunt_line = wait_action_finished(ctx, offset, "hunt", HUNT_TIMEOUT_S)
    ev["hunt_line"] = message(hunt_line)
    ctx.check(hunt_line, "the service sent no hunt (or it never finished) within %d s of the session",
              HUNT_TIMEOUT_S)
    lines = log_lines_since(GFCLOUD_LOG, offset)
    hunt_i = action_finish_index(lines, "hunt")
    refused = [ln for ln in lines[:hunt_i] if "unsafe to move" in ln]
    ev["refusals_before_hunt_end"] = len(refused)
    ctx.check(not refused, "the hunt was refused for the lid (%d 'unsafe to move')", len(refused))
    ctx.check(COMPLETED in hunt_line, "the hunt did not complete: %s", ev["hunt_line"])
    ctx.log("hunt with the lid open: %s", ev["hunt_line"])
    ctx.confirm("Did the lens home (Z motion) with the lid open, with no error in the app?")
    ctx.instruct("Close the lid, then click Done. (The service now re-finds the head: several "
                 "moves with lid images between them - the test waits them out.)")
    settle_cloud(ctx, offset)
    lines = log_lines_since(GFCLOUD_LOG, offset)
    ev["motions_after_lid_close"] = sum(1 for ln in lines if "motion [" in ln and COMPLETED in ln)
    ctx.log("PASS: the connect-time hunt ran and completed with the lid open; %d service motion(s) "
            "completed after the lid closed", ev["motions_after_lid_close"])


@test("cloud.pause-resume", title="Button pauses and resumes a cloud print (factory backtrack + lead)",
      subsystem="cloud", kind="live", est_min=8,
      covers=_CLOUD_COVERS + [("forgectrl", "src/main.c")],
      requires=["laser.emission-witness"],
      steps=[CLOUD_STEP, "The app open; scrap on the bed and a small engrave/score job (about 60 s) ready.",
             "Print from the app and press the button when it lights; a few seconds into the run "
             "press it again (pause), wait ~3 s, press again (resume); let the job finish."],
      description="Pressing the button during a cloud print pauses it the factory way - controlled "
                  "stop, backtrack with the laser off, print:paused - and the next press resumes "
                  "with the laser-off lead, print:resumed; the job then completes and parks. The "
                  "latch stays unlocked and the armed window open through the pause. The same "
                  "print is where the job's lifecycle shows: a print warms up before its first "
                  "fire and rests after its park, both non-zero, while the connect-time hunt in "
                  "the same session does neither.")
def pause_resume(ctx):
    ev = ctx.evidence
    offset = enter_cloud(ctx)
    ctx.instruct(APP_PRINT_CUE)
    got = wait_print_running(ctx, offset, 300)
    ctx.check(got, "the print never reached its run within 300 s (not started, or the button not pressed)")
    ctx.instruct("The head is moving. Press the button once NOW (pause), watch the head stop and back up "
                 "a few millimeters, wait about 3 seconds, press it again (resume), then click Done.")
    got = wait_log(ctx, offset, ["button pressed mid-run; pausing", "paused at",
                                 "button pressed while paused; resuming"], 90)
    ev["log"] = {k: bool(v) for k, v in got.items()}
    ctx.check(got["button pressed mid-run; pausing"], "the press did not pause the run")
    ctx.check(got["paused at"], "the pause did not settle (no 'paused at')")
    ctx.check(got["button pressed while paused; resuming"], "the second press did not resume")
    st, cs = ctx.forgectrl.get("/cool/status")
    ev["armed_after_resume"] = cs.get("armed") if isinstance(cs, dict) else None
    ctx.log("armed after the resume: %s", ev["armed_after_resume"])
    fin = wait_action_finished(ctx, offset, "print", 300)
    got = wait_log(ctx, offset, ["return home complete"], 5)
    ev["log_end"] = {"return home complete": bool(got["return home complete"]),
                     "print finished": message(fin)}
    ctx.check(fin, "the print did not finish within 300 s of the resume")
    ctx.check(COMPLETED in fin, "the print did not complete after the resume: %s", message(fin))
    ctx.check(got["return home complete"], "the post-print park did not complete")
    relocked = [ln for ln in log_lines_since(GFCLOUD_LOG, offset)
                if "relocking the laser" in ln or ("print [" in ln and CANCELLED in ln)]
    ev["relock_or_cancel_lines"] = len(relocked)
    ctx.check(not relocked, "the pause relocked or cancelled the job (%s)", relocked[:2])
    ctx.confirm("Did the head stop and back up a few millimeters (laser off) on the first press, "
                "resume on the second, and did the job finish and the app show it complete?")

    # The job's lifecycle, from the same print: a warm-up before the first
    # fire and a rest after the park are equipment protection the service
    # assumes has happened, and a machine configured to skip them says so in
    # the log rather than quietly not doing them.
    lines = log_lines_since(GFCLOUD_LOG, offset)
    holds = {"warm up": None, "cool down": None}
    for ln in lines:
        for phase in holds:
            if holds[phase] is None and ("%s: holding" % phase) in ln:
                holds[phase] = ln.strip()[:160]
            if holds[phase] is None and ("%s: skipped" % phase) in ln:
                holds[phase] = ln.strip()[:160]
    ev["lifecycle"] = holds
    ctx.log("warm-up: %s", holds["warm up"])
    ctx.log("rest: %s", holds["cool down"])
    for phase in ("warm up", "cool down"):
        ctx.check(holds[phase] is not None, "the print logged no %s at all", phase)
        ctx.check(holds[phase] and "holding" in holds[phase],
                  "the print skipped its %s (%s): the config still carries a zero",
                  phase, holds[phase])
    # A hunt is not a print: the connect-time hunt ran in this same session
    # and must not have held for either period.
    hunt_end = next((i for i, ln in enumerate(lines) if "waiting for button" in ln), len(lines))
    early_holds = [ln.strip()[:120] for ln in lines[:hunt_end]
                   if "warm up: holding" in ln or "cool down: holding" in ln]
    ev["holds_before_the_print"] = early_holds
    ctx.check(not early_holds, "a hunt or motion held for a print's periods: %s", early_holds[:2])

    settle_cloud(ctx, offset)
    ctx.log("PASS: button pause/resume mid-print, warm-up and rest observed, job completed "
            "and parked")


@test("cloud.oversize-stream", title="A print longer than the ring is fed while it plays",
      subsystem="cloud", kind="live", est_min=12,
      covers=_CLOUD_COVERS,
      requires=["cloud.lid-interlock-abort", "cloud.pause-resume"],
      steps=[CLOUD_STEP,
             "Scrap on the bed and a LONG job ready in the app - one whose run time is longer "
             "than the ring holds (over an hour at the usual print tick). A full-bed raster "
             "engrave is the easy way to get one.",
             "Print from the app and press the button when it lights. Let it cut for about two "
             "minutes, pause and resume it with the button, then cancel the print from the app."],
      description="The service sends one pulse file for a print however long it is, and a long one "
                  "is several times the ring: the machine holds the job in memory, fills the ring, "
                  "starts, and tops the ring up as it drains. This checks the signature of that - "
                  "the device in live-feed mode, the kernel's program total growing during the run, "
                  "and no underrun - that a live-fed print pauses and resumes the factory way, the "
                  "ring having kept the history to back into, and that the job still cancels "
                  "cleanly.")
def oversize_stream(ctx):
    ev = ctx.evidence
    offset = enter_cloud(ctx)
    before = hw.sysfs_int("cnc/underruns", 0)
    ev["underruns_before"] = before
    ctx.instruct("Start the long print from the app and press the button when it lights.")
    got = wait_print_running(ctx, offset, 600)
    ctx.check(got, "the print never reached its run within 600 s")

    # The load says so in as many words, and the device is in live-feed mode.
    got = wait_log(ctx, offset, ["job is longer than the ring"], 30)
    ev["log"] = {k: bool(v) for k, v in got.items()}
    ctx.check(got["job is longer than the ring"],
              "the job fit the ring: pick a longer one, this test needs a job the ring cannot hold")
    streaming = hw.sysfs_int("cnc/streaming", 0)
    ev["streaming"] = streaming
    ctx.check(streaming == 1, "cnc/streaming is %s during a live-fed run", streaming)

    # The proof the feed is live: the kernel's idea of how long the program is
    # keeps growing while it plays.
    first = read_program_total()
    ctx.log("program total at the start of the run: %s bytes", first)
    ctx.instruct("Let it cut for about two minutes, then click Done (do not cancel yet).")
    grown = read_program_total()
    ev["total_first"], ev["total_later"] = first, grown
    ctx.log("program total two minutes in: %s bytes (+%s)", grown, (grown or 0) - (first or 0))
    ctx.check(first is not None and grown is not None and grown > first,
              "the program total did not grow during the run (%s -> %s): the ring was not being "
              "topped up", first, grown)
    after = hw.sysfs_int("cnc/underruns", 0)
    ev["underruns_during"] = after
    ctx.check(after == before, "the ring ran dry during the run (underruns %s -> %s)", before, after)

    # The pause on a live feed: the ring keeps the history to back into, so a
    # streamed print retraces and leads back on exactly like a preloaded one.
    ev["max_backtrack"] = hw.sysfs_int("cnc/max_backtrack", 0)
    ctx.log("max_backtrack while the feed runs: %s steps", ev["max_backtrack"])
    ctx.instruct("Press the button once (pause), watch the head stop and back up a few "
                 "millimeters, wait about 3 seconds, press it again (resume), then click Done.")
    got = wait_log(ctx, offset, ["button pressed mid-run; pausing", "paused at",
                                 "button pressed while paused; resuming"], 90)
    ev["pause_log"] = {k: bool(v) for k, v in got.items()}
    ctx.check(got["button pressed mid-run; pausing"], "the press did not pause the live-fed run")
    ctx.check(got["paused at"], "the pause did not settle (no 'paused at')")
    ctx.check(got["button pressed while paused; resuming"], "the second press did not resume")
    backtracked = [ln for ln in log_lines_since(GFCLOUD_LOG, offset)
                   if "backtrack refused" in ln]
    ev["backtrack_refused_lines"] = backtracked[:2]
    ctx.check(not backtracked, "the live-fed pause could not back up (%s)", backtracked[:1])
    ctx.check(hw.sysfs_int("cnc/underruns", 0) == before,
              "the pause or the resume starved the ring")
    ctx.confirm("Did the head back up a few millimeters with the laser off on the first press, "
                "and pick the cut back up on the second?")

    ctx.instruct("Now cancel the print from the app.")
    fin = wait_action_finished(ctx, offset, "print", 300)
    ev["print_finished"] = message(fin)
    ctx.check(fin, "the cancelled print did not finish within 300 s")
    ctx.check(CANCELLED in fin, "the cancelled print did not report cancelled: %s", message(fin))
    ctx.check(hw.sysfs_int("cnc/streaming", 0) == 0,
              "the device was left in live-feed mode after the job ended")
    ctx.check(hw.sysfs_int("cnc/underruns", 0) == before,
              "the cancel produced an underrun")
    settle_cloud(ctx, offset)
    ctx.log("PASS: a job longer than the ring ran live-fed, total grew, no underrun, clean cancel")


@test("cloud.pause-cancel-paths", title="A paused cloud print is cancelled by the lid, and a running one "
                                        "by the app",
      subsystem="cloud", kind="live", est_min=12,
      covers=_CLOUD_COVERS, requires=["cloud.pause-resume", "cloud.lid-interlock-abort"],
      steps=[CLOUD_STEP, "The app open in a browser; scrap on the bed and a small engrave/score job "
                         "ready - the test runs TWO prints.",
             "Print 1: press the button to start, press it again a few seconds in (pause), then open "
             "the lid.",
             "Print 2: press the button to start, then cancel the print from the app while it runs."],
      description="The two ways a print ends other than finishing, each from the state the factory ends "
                  "it in: a job paused on the button is cancelled by the lid - there is no resume past a "
                  "lid open - and a running job is cancelled from the app. Both take the same tail: the "
                  "motion stops, the head parks back at the job start, the latch relocks and the armed "
                  "window closes, and the print ends ':cancelled'.")
def pause_cancel_paths(ctx):
    ev = ctx.evidence
    offset = enter_cloud(ctx)

    # -- print 1: paused on the button, then the lid ------------------------
    ctx.instruct(APP_PRINT_CUE)
    got = wait_print_running(ctx, offset, 300)
    ctx.check(got, "print 1 never reached its run within 300 s (not started, or the button not pressed)")
    ctx.instruct("The head is moving. Press the button once NOW (pause), watch it stop and back up a "
                 "few millimeters, then click Done.")
    got = wait_log(ctx, offset, ["button pressed mid-run; pausing", "paused at"], 90)
    ev["paused"] = {k: bool(v) for k, v in got.items()}
    ctx.check(got["button pressed mid-run; pausing"], "the press did not pause print 1")
    ctx.check(got["paused at"], "the pause did not settle (no 'paused at')")
    ctx.instruct("The print is paused. Open the lid NOW, then click Done - leave it open until the head "
                 "has returned to the corner.")
    lid_stop = "lid opened mid-run; stopping motion"
    got = wait_log(ctx, offset, [lid_stop, "start return home", "return home complete"], 120)
    fin1 = wait_action_finished(ctx, offset, "print", 60)
    ev["lid_from_pause"] = {k: message(v) for k, v in got.items()}
    ev["lid_from_pause"]["print finished"] = message(fin1)
    for k, v in ev["lid_from_pause"].items():
        ctx.log("  [print 1] %s: %s", k, "seen" if v else "MISSING")
    ctx.check(got[lid_stop], "the lid did not end the paused print")
    ctx.check(got["return home complete"], "the paused print did not park to completion")
    ctx.check(fin1 and CANCELLED in fin1, "print 1 did not end ':cancelled': %s",
              message(fin1) or "no finish line")
    ctx.check(ctx.forgectrl.wait_idle(15, abort=ctx.aborted), "machine not idle after print 1's park")
    kpos = read_position()
    ev["counters_after_print1"] = kpos
    ctx.check(kpos is not None and abs(kpos[0]) <= 3 and abs(kpos[1]) <= 3,
              "print 1 did not come back to the job start (kernel counters %s)", kpos)
    st, cs = ctx.forgectrl.get("/cool/status")
    ev["armed_after_print1"] = cs.get("armed") if isinstance(cs, dict) else None
    ev["latch_locked_after_print1"] = latch_locked()
    ctx.check(not ev["armed_after_print1"], "armed window still open after the paused print was cancelled")
    ctx.check(ev["latch_locked_after_print1"],
              "kernel latch not locked after the paused print was cancelled")
    ctx.instruct("Close the lid, then click Done.")
    settle_cloud(ctx, offset)

    # -- print 2: cancelled from the app ------------------------------------
    offset = log_size(GFCLOUD_LOG)
    ctx.instruct(APP_PRINT_CUE)
    got = wait_print_running(ctx, offset, 300)
    ctx.check(got, "print 2 never reached its run within 300 s (not started, or the button not pressed)")
    ctx.instruct("The head is moving. Cancel the print from the app now, then click Done.")
    svc_stop = "action cancelled mid-run; stopping motion"
    got = wait_log(ctx, offset, [svc_stop, "start return home", "return home complete"], 120)
    fin2 = wait_action_finished(ctx, offset, "print", 60)
    ev["service_cancel"] = {k: message(v) for k, v in got.items()}
    ev["service_cancel"]["print finished"] = message(fin2)
    for k, v in ev["service_cancel"].items():
        ctx.log("  [print 2] %s: %s", k, "seen" if v else "MISSING")
    ctx.check(got[svc_stop], "the app's cancel did not stop the run")
    ctx.check(got["return home complete"], "the cancelled print did not park to completion")
    ctx.check(fin2 and CANCELLED in fin2, "print 2 did not end ':cancelled': %s",
              message(fin2) or "no finish line")
    ctx.check(ctx.forgectrl.wait_idle(15, abort=ctx.aborted), "machine not idle after print 2's park")
    kpos = read_position()
    ev["counters_after_print2"] = kpos
    ctx.check(kpos is not None and abs(kpos[0]) <= 3 and abs(kpos[1]) <= 3,
              "print 2 did not come back to the job start (kernel counters %s)", kpos)
    st, cs = ctx.forgectrl.get("/cool/status")
    ev["armed_after_print2"] = cs.get("armed") if isinstance(cs, dict) else None
    ev["latch_locked_after_print2"] = latch_locked()
    ctx.check(not ev["armed_after_print2"], "armed window still open after the app cancel")
    ctx.check(ev["latch_locked_after_print2"], "kernel latch not locked after the app cancel")
    ctx.confirm("Did both prints end back at the corner, dark, and does the app show both as cancelled?")
    settle_cloud(ctx, offset)
    ctx.log("PASS: a paused print cancelled by the lid and a running print cancelled from the app both "
            "stopped, parked, relocked and reported ':cancelled'")
