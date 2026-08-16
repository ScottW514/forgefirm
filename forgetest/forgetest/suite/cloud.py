"""cloud.* - the controller mode switch and the optional Glowforge web-service
mode (gfcloud daemon, gfhome homing runner)."""
import json
import os
import socket
import time

from ..catalog import test
from .. import hw

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
