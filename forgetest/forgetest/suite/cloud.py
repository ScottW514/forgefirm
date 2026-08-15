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
      steps=["Bed clear (the supervisor's liveness probe may jog the head a few mm on a "
             "controller spawn). Cloud credentials configured; the machine on the network."],
      description="POST /mode switches to the cloud controller: gfcloud comes up under "
                  "supervision and records its connect-time service probe (/status gfsvc); the "
                  "camera service survives the switch; switching back brings grblHAL up with the "
                  "Grbl port open and Idle.")
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

    st, body = fc.post("/mode", data={"controller": "cloud"})
    ctx.log("POST /mode controller=cloud -> %s %s", st, body)
    ctx.check(st == 200, "mode switch to cloud refused: %s %s", st, body)
    m = wait_mode(ctx, fc, "cloud", timeout=90)
    ev["mode_cloud"] = m
    ctx.log("mode after switch: %s", m)
    ctx.check(m and m.get("mode") == "cloud" and m.get("controller") == "running",
              "cloud controller did not come up: %s", m)
    # the connect-time service probe is the evidence of a live cloud session
    t0 = time.time()
    probe = None
    while time.time() - t0 < 120:
        ctx.checkpoint()
        try:
            mt = os.stat(GF_LATEST).st_mtime
            if probe_before is None or mt > probe_before:
                with open(GF_LATEST) as f:
                    probe = json.load(f)
                break
        except (OSError, ValueError):
            pass
        time.sleep(2)
    ev["gf_probe"] = probe
    ctx.log("cloud service probe: %s", probe)
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
    ctx.check(probe is not None, "the cloud controller never recorded a service probe "
              "(no credentials, no network, or the service refused) - cloud mode not proven")
    st, cam2 = fc.get("/cam/status")
    ev["cam_after"] = cam2
    ctx.check(st == 200, "camera status lost after the switch back")


@test("cloud.gfhome-homing", title="Glowforge web-service homing ($H with homing_mode=gfcloud)",
      subsystem="cloud", kind="operator", est_min=5,
      covers=_CLOUD_COVERS + [("grblhal-glowforge", "src/**")], requires=["cloud.mode-switch"],
      steps=["homing_mode = gfcloud and cloud credentials configured; bed clear, lid closed.",
             "Watch the gantry: the service drives it to the corner with camera corrections."],
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
