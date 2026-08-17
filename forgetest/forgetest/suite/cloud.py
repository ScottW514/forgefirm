"""cloud.* - the controller mode switch and the optional Glowforge web-service
mode (gfcloud daemon, gfhome homing runner)."""
import json
import os
import socket
import time

from ..catalog import test
from .. import hw
from ..baseline import read_position

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
      covers=_CLOUD_COVERS + [("grblhal-glowforge", "src/**")], requires=["cloud.mode-switch"],
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

def log_lines_since(path, offset):
    """New gfcloud log lines since offset (each 'ISO-time gfcloud[pid] LEVEL where message')."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


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


def enter_cloud(ctx):
    """Switch to the cloud controller and wait for its service session.
    Returns (log offset at the switch, lid lamp level before)."""
    fc = ctx.forgectrl
    st, m0 = fc.get("/mode")
    ctx.check(st == 200 and isinstance(m0, dict) and m0.get("mode") == "grbl",
              "start this test in grbl mode (now %s)", m0)
    lamp0 = hw.sysfs_read("pic/lid_led")
    offset = log_size(GFCLOUD_LOG)
    st, body = fc.post("/mode", data={"controller": "cloud"})
    ctx.check(st == 200, "mode switch to cloud refused: %s %s", st, body)
    m = wait_mode(ctx, fc, "cloud", timeout=90)
    ctx.check(m and m.get("mode") == "cloud" and m.get("controller") == "running",
              "cloud controller did not come up: %s", m)
    t0 = time.time()
    session = []
    while time.time() - t0 < 120:
        ctx.checkpoint()
        session = session_lines(GFCLOUD_LOG, offset)
        if session_established(session):
            break
        time.sleep(2)
    ctx.check(session_established(session), "the cloud client never established its service session")
    ctx.log("cloud session established")
    return offset, lamp0


def leave_cloud(ctx, lamp0):
    """Back to grbl; the head returns to where the run found it."""
    fc = ctx.forgectrl
    st, body = fc.post("/mode", data={"controller": "grbl"})
    ctx.check(st == 200, "mode switch back to grbl refused: %s %s", st, body)
    m = wait_mode(ctx, fc, "grbl", timeout=120)
    ctx.check(m and m.get("mode") == "grbl" and m.get("controller") == "running",
              "grbl controller did not come back: %s", m)
    ctx.sleep(3)
    ctx.counters_rezeroed()
    return_head(ctx)
    lamp1 = hw.sysfs_read("pic/lid_led")
    if lamp0 is not None and lamp1 != lamp0:
        hw.sysfs_write("pic/lid_led", lamp0)


def latch_locked():
    ilk = hw.sysfs_int("cnc/interlock_circuit")
    return ilk is not None and bool(ilk & (1 << 3))


APP_PRINT_CUE = ("In the Glowforge app: scrap on the bed, lid closed, a SMALL engrave or score job "
                 "(about 30 s) set up. Click Done here, then press Print in the app and press the "
                 "physical button when it lights white.")

CANCELLED = 'finished with event ":cancelled"'
COMPLETED = 'finished with event ":completed"'


@test("cloud.lid-abort", title="Lid open during a cloud print: stop, park with the lid open, cancelled",
      subsystem="cloud", kind="live", est_min=8,
      covers=_CLOUD_COVERS, requires=["cloud.mode-switch", "laser.emission-witness"],
      steps=["Cloud credentials configured; the app open in a browser; scrap on the bed and a small "
             "engrave/score job ready.",
             "Print from the app and press the button when it lights; open the lid a few seconds "
             "into the run."],
      description="A cloud print aborted by the lid behaves as the factory's does: the edge "
                  "reaches the controlled stop within milliseconds, the head returns home at "
                  "once with the lid still open, the laser latch relocks and the armed window "
                  "closes, and the job ends ':cancelled'.")
def lid_abort(ctx):
    ev = ctx.evidence
    offset, lamp0 = enter_cloud(ctx)
    try:
        ctx.instruct(APP_PRINT_CUE)
        got = wait_log(ctx, offset, ["starting run"], 300)
        ctx.check(got["starting run"], "no run started within 300 s (print not started, or button not pressed)")
        ctx.instruct("The head is moving. Open the lid NOW, then click Done. Leave it open until the head "
                     "has returned to the corner.")
        needles = ["lid opened", "lid opened mid-run; stopping motion", "start return home",
                   "return home complete", CANCELLED]
        got = wait_log(ctx, offset, needles, 90)
        ev["log"] = {k: (v.split(" ", 2)[-1] if v else None) for k, v in got.items()}
        for k, v in got.items():
            ctx.log("  %s: %s", k, "seen" if v else "MISSING")
        ctx.check(got["lid opened mid-run; stopping motion"], "the lid open did not stop the run")
        t_edge = line_time(got["lid opened"]) if got["lid opened"] else None
        t_stop = line_time(got["lid opened mid-run; stopping motion"])
        if t_edge is not None and t_stop is not None:
            ev["edge_to_stop_ms"] = round((t_stop - t_edge) * 1000, 1)
            ctx.log("lid edge -> stop: %s ms", ev["edge_to_stop_ms"])
            ctx.check(ev["edge_to_stop_ms"] < 60, "stop was not edge-driven (%s ms after the lid edge)",
                      ev["edge_to_stop_ms"])
        ctx.check(got["start return home"] and got["return home complete"],
                  "the park did not run to completion with the lid open")
        # the machine, not the client: the job started at counters (0,0,0)
        # (cloud clears them at every job start), so a completed park reads
        # back there - stale ring bytes replayed ahead of the park would not
        ctx.check(ctx.forgectrl.wait_idle(15, abort=ctx.aborted), "machine not idle after the park")
        kpos = read_position()
        ev["kernel_counters_after_park"] = kpos
        ctx.log("kernel counters after the park: %s", kpos)
        ctx.check(kpos is not None and abs(kpos[0]) <= 3 and abs(kpos[1]) <= 3,
                  "the head did not come back to the job start (kernel counters %s)", kpos)
        ctx.check(got[CANCELLED], "the print did not end ':cancelled'")
        st, cs = ctx.forgectrl.get("/cool/status")
        ev["armed_after"] = cs.get("armed") if isinstance(cs, dict) else None
        ev["latch_locked"] = latch_locked()
        ctx.check(not ev["armed_after"], "armed window still open after the abort")
        ctx.check(ev["latch_locked"], "kernel latch not locked after the abort")
        ctx.confirm("Did the head stop as soon as the lid opened and go straight home with the lid "
                    "still open, and does the app show the print as cancelled?")
        ctx.instruct("Close the lid, then click Done.")
        ctx.sleep(3)
    finally:
        leave_cloud(ctx, lamp0)
    ctx.log("PASS: lid open -> stop in %s ms, park completed with the lid open, ':cancelled'",
            ev.get("edge_to_stop_ms"))


@test("cloud.lid-during-button-wait", title="Lid open at the cloud button prompt cancels the print",
      subsystem="cloud", kind="operator", est_min=6,
      covers=_CLOUD_COVERS, requires=["cloud.mode-switch"],
      steps=["Cloud credentials configured; the app open; any small job ready (nothing will fire).",
             "Print from the app; when the button lights white, do NOT press it - open the lid."],
      description="A cloud print waiting for the button is cancelled by the lid: the wait ends "
                  "with the lid named as the reason, the laser latch relocks, the armed window "
                  "closes, no run starts, and the job ends ':cancelled'.")
def lid_during_button_wait(ctx):
    ev = ctx.evidence
    offset, lamp0 = enter_cloud(ctx)
    try:
        ctx.instruct("In the Glowforge app: lid closed, a small job set up. Click Done here, then press "
                     "Print in the app. When the button lights white, do NOT press it.")
        got = wait_log(ctx, offset, ["waiting for button"], 300)
        ctx.check(got["waiting for button"], "the print never reached the button wait")
        ctx.instruct("The button is lit. Open the lid now (do not press the button), then click Done.")
        needles = ["button wait lid opened - relocking the laser", CANCELLED]
        got = wait_log(ctx, offset, needles, 60)
        ev["log"] = {k: bool(v) for k, v in got.items()}
        ctx.check(got["button wait lid opened - relocking the laser"], "the lid did not end the button wait")
        ctx.check(got[CANCELLED], "the print did not end ':cancelled'")
        ran = [ln for ln in log_lines_since(GFCLOUD_LOG, offset) if "starting run" in ln]
        ev["runs_started"] = len(ran)
        ctx.check(not ran, "a run started despite the lid-open cancel")
        st, cs = ctx.forgectrl.get("/cool/status")
        ev["armed_after"] = cs.get("armed") if isinstance(cs, dict) else None
        ev["latch_locked"] = latch_locked()
        ctx.check(not ev["armed_after"], "armed window still open after the cancel")
        ctx.check(ev["latch_locked"], "kernel latch not locked after the cancel")
        ctx.confirm("Did the button go dark when the lid opened, with no motion, and does the app show "
                    "the print as cancelled?")
        ctx.instruct("Close the lid, then click Done.")
        ctx.sleep(3)
    finally:
        leave_cloud(ctx, lamp0)
    ctx.log("PASS: lid open at the button prompt cancelled the print; latch locked, armed=false")


@test("cloud.hunt-lid-open", title="A cloud hunt runs with the lid open",
      subsystem="cloud", kind="operator", est_min=5,
      covers=_CLOUD_COVERS, requires=["cloud.mode-switch"],
      steps=["Cloud credentials configured; bed clear.",
             "Open the lid BEFORE the test switches to cloud mode and leave it open through the "
             "connect-time hunt."],
      description="The service's connect-time hunt (lens homing plus its XY hunt) is not gated by "
                  "the lid: it runs and reports ':completed' with the lid open, as the factory's does.")
def hunt_lid_open(ctx):
    ev = ctx.evidence
    ctx.instruct("Open the lid and leave it open, then click Done.")
    sw = (ctx.forgectrl.status().get("switches") or {})
    ev["lid_before"] = sw.get("lid")
    ctx.check(not sw.get("lid"), "the lid reads closed (%s)", sw)
    offset, lamp0 = enter_cloud(ctx)
    try:
        got = wait_log(ctx, offset, ["hunt [", COMPLETED], 180)
        ev["log"] = {k: bool(v) for k, v in got.items()}
        refused = [ln for ln in log_lines_since(GFCLOUD_LOG, offset) if "unsafe to move" in ln]
        ev["refusals"] = len(refused)
        ctx.check(got["hunt ["], "the service sent no hunt within 180 s of the session")
        ctx.check(not refused, "the hunt was refused for the lid (%d 'unsafe to move')", len(refused))
        ctx.check(got[COMPLETED], "the hunt did not complete")
        ctx.confirm("Did the lens home (Z motion) with the lid open, with no error in the app?")
        ctx.instruct("Close the lid, then click Done.")
        ctx.sleep(3)
    finally:
        leave_cloud(ctx, lamp0)
    ctx.log("PASS: the connect-time hunt ran and completed with the lid open")


@test("cloud.pause-resume", title="Button pauses and resumes a cloud print (factory backtrack + lead)",
      subsystem="cloud", kind="live", est_min=8,
      covers=_CLOUD_COVERS + [("forgectrl", "src/main.c")],
      requires=["cloud.mode-switch", "laser.emission-witness"],
      steps=["Cloud credentials configured; the app open; scrap on the bed and a small engrave/score "
             "job (about 60 s) ready.",
             "Print from the app and press the button when it lights; a few seconds into the run "
             "press it again (pause), wait ~3 s, press again (resume); let the job finish."],
      description="Pressing the button during a cloud print pauses it the factory way - controlled "
                  "stop, backtrack with the laser off, print:paused - and the next press resumes "
                  "with the laser-off lead, print:resumed; the job then completes and parks. The "
                  "latch stays unlocked and the armed window open through the pause.")
def pause_resume(ctx):
    ev = ctx.evidence
    offset, lamp0 = enter_cloud(ctx)
    try:
        ctx.instruct(APP_PRINT_CUE)
        got = wait_log(ctx, offset, ["starting run"], 300)
        ctx.check(got["starting run"], "no run started within 300 s (print not started, or button not pressed)")
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
        got = wait_log(ctx, offset, ["return home complete", COMPLETED], 300)
        ev["log_end"] = {k: bool(v) for k, v in got.items()}
        ctx.check(got[COMPLETED], "the print did not complete after the resume")
        ctx.check(got["return home complete"], "the post-print park did not complete")
        relocked = [ln for ln in log_lines_since(GFCLOUD_LOG, offset)
                    if "relocking the laser" in ln or CANCELLED in ln]
        ev["relock_or_cancel_lines"] = len(relocked)
        ctx.check(not relocked, "the pause relocked or cancelled the job (%s)", relocked[:2])
        ctx.confirm("Did the head stop and back up a few millimeters (laser off) on the first press, "
                    "resume on the second, and did the job finish and the app show it complete?")
    finally:
        leave_cloud(ctx, lamp0)
    ctx.log("PASS: button pause/resume mid-print, job completed and parked")
