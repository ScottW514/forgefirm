"""The fresh-boot idle state: what every test starts from and leaves behind.

The runner checks the machine against this baseline before a run and
restores it after (on every exit path), so a test cannot hand the next one
- or the operator - a machine that only looks idle. Two kinds of items:

  fixed      a resting value the boot establishes and nothing at idle
             changes: kernel module defaults, forgectrl's start-up writes,
             the GRBL controller's init writes. Verified against the value,
             restored by writing it back.
  preserved  state with no resting policy that a run must hand back as it
             found it: the position counters, the settings map, the
             controller mode. Captured before the run, compared after,
             restored where the interface allows.

The lid lamp is fixed too, at forgectrl's `lid_lamp_idle` setting (unset =
236): the daemon asserts it at start and at every controller spawn.

Everything found off-baseline is a "leftover": logged, kept in the run's
evidence, and surfaced on the page. The pre-run pass attributes leftovers
to the previous run; the post-run pass attributes them to the run itself.
The machine is restored either way - a leftover is a defect in the test
that made it, not a reason to hand the dirt on.
"""
import json
import os
import struct
import time

from . import hw
from .log import now_ts

# GRBL-mode resting values (kernel attribute -> value as read back), as a
# fresh boot of the dev image leaves them (2026-08-16 bench dump).
# motor_lock/x_mode/y_mode/x_decay/y_decay and the hold currents are the
# GRBL controller's init writes (glowforge_io.c), step_freq its default
# machine tick, ramp_rate the module default; streaming is only ever 1
# inside a live job; the head white LED is a camera lamp, off at idle; the
# loop heater and TEC are the diagnostics' tools, off at idle.
FIXED_SYSFS = [
    ("cnc/motor_lock", "8"),
    ("cnc/x_mode", "8"),
    ("cnc/y_mode", "8"),
    ("cnc/x_decay", "1"),
    ("cnc/y_decay", "1"),
    ("cnc/step_freq", "28160"),         # GFSINK_RATE_DEFAULT (grblHAL stepper_stream.c)
    ("cnc/ramp_rate", "125000"),
    ("cnc/streaming", "0"),
    ("pic/x_step_current", "33"),
    ("pic/y_step_current", "5"),
    ("head/white_led", "0"),
    ("thermal/heater_pwm", "0"),
    ("thermal/tec_on", "0"),
]

# Read-only readbacks with their idle values (no direct restore: the state
# comes right through forgectrl - see restore_forgectrl - or is fatal).
IDLE_READBACKS = [
    ("cnc/state", "idle"),
    ("cnc/laser_enable", "0"),
    ("cnc/laser_on", "0"),
    ("cnc/faults", "0"),
]

LATCH_BIT = 0x08                    # interlock_circuit bit 3: latch locked

BUTTON_LEDS = ("button_led_1", "button_led_2", "button_led_3")

PRESERVED_SYSFS = []                # sysfs attrs captured before, restored after

LID_LAMP_ATTR = "pic/lid_led"
LID_LAMP_DEFAULT = "236"            # forgectrl's lid_lamp_idle default

BOOT_MAX_AGE_S = 600                # a boot reference is taken only this soon after boot
SETTLE_S = 150                      # the supervisor's probe + rail-off ladder
CAM_IDLE_S = 20                     # camera engine idle stop is 10 s
COOL_IDLE_S = 120                   # cooldown after motion
IDLE_S = 30                         # cnc/state back to idle after a job

XY_STEPS_PER_MM = 53.333            # boards/glowforge.h (x8 microstepping)
RETURN_MAX_MM = 100.0               # a displaced head is jogged back at most this far


def leds_root():
    r = os.environ.get("GF_LEDS_ROOT") or "/sys/class/leds/"
    return r if r.endswith("/") else r + "/"


def read_led(name):
    try:
        with open(leds_root() + name + "/brightness") as f:
            return f.read().strip()
    except OSError:
        return None


def write_led(name, value):
    with open(leds_root() + name + "/target", "w") as f:
        f.write(str(value))


def read_position():
    """(x, y, z) step counters, or None when unreadable."""
    try:
        with open(hw.sysfs_root() + "cnc/position", "rb") as f:
            raw = f.read(32)
        return list(struct.unpack("<3i", raw[:12]))
    except (OSError, struct.error):
        return None


class Leftover:
    def __init__(self, item, found, expected, action):
        self.item = item
        self.found = found
        self.expected = expected
        self.action = action        # "restored" | "unrestorable" | "waited" | "failed: ..."

    def as_dict(self):
        return {"item": self.item, "found": self.found, "expected": self.expected,
                "action": self.action}

    def __str__(self):
        return "%s=%s (expected %s) -> %s" % (self.item, self.found, self.expected, self.action)


class Baseline:
    """One instance per run: capture() before, check() around, restore()
    after. `log` is a callable(str); every line is prefixed 'baseline:'."""

    _unreachable_until = 0.0        # class-wide: skip forgectrl for a while after a miss

    def __init__(self, log, abort=None):
        self._log = log
        self.abort = abort or (lambda: False)
        self.captured = None
        self.forgectrl = None

    def log(self, msg):
        self._log("baseline: " + msg)

    # -- forgectrl access ------------------------------------------------
    def fc(self):
        if self.forgectrl is None:
            self.forgectrl = hw.Forgectrl()
        return self.forgectrl

    def fc_get(self, path):
        if time.time() < Baseline._unreachable_until:
            return None, None
        try:
            st, body = self.fc().get(path)
        except hw.HwError:
            Baseline._unreachable_until = time.time() + 30
            return None, None
        if st is None:
            Baseline._unreachable_until = time.time() + 30
        return st, body

    def fc_post(self, path, **kw):
        try:
            return self.fc().post(path, **kw)
        except hw.HwError as e:
            return None, str(e)

    def wait_settled(self, timeout=SETTLE_S, unreachable_s=10):
        """Block until forgectrl reports a settled supervisor: motion
        verified (the probe passed), motion-fault (the ladder exhausted),
        or standby (the manual stop lever). Gives up after unreachable_s
        without an answer. Returns the last /mode body (None if unreachable)."""
        t0 = time.time()
        deadline = t0 + timeout
        last = seen = heard = None
        pending_since = None        # verified but not running: the spawn follows
        while time.time() < deadline and not self.abort():
            try:
                st, body = self.fc().get("/mode")
            except hw.HwError:
                st, body = None, None
            if st is None and heard is None and time.time() - t0 >= unreachable_s:
                self.log("forgectrl unreachable for %d s - not waiting for it" % unreachable_s)
                Baseline._unreachable_until = time.time() + 30
                return None
            if st == 200 and isinstance(body, dict):
                heard = time.time()
                last = body
                key = (body.get("controller"), body.get("motion"))
                if key != seen:
                    seen = key
                    self.log("/mode controller=%s motion=%s" % key)
                ctl = body.get("controller")
                if ctl in ("motion-fault", "standby") or (ctl == "running" and body.get("motion") == "verified"):
                    if ctl == "motion-fault":
                        self.log("WARNING - motion liveness ladder failed, controllers are "
                                 "down (motion-fault); retry via POST /mode")
                    return body
                if body.get("motion") == "verified":
                    # the probe passed; the spawn (or a respawn backoff of up to
                    # 30 s) is in flight - give it a bounded moment
                    pending_since = pending_since or time.time()
                    if time.time() - pending_since > 35:
                        return body
                else:
                    pending_since = None
            time.sleep(1.0)
        self.log("WARNING - forgectrl did not settle within %d s (last /mode: %s)" % (timeout, last))
        return last

    # -- capture -------------------------------------------------------
    def capture(self):
        """Record the preserved state before a run."""
        cap = {"sysfs": {}, "position": read_position(), "settings": None, "mode": None}
        for attr in PRESERVED_SYSFS:
            cap["sysfs"][attr] = hw.sysfs_read(attr)
        st, body = self.fc_get("/settings")
        if st == 200 and isinstance(body, dict):
            cap["settings"] = {k: v for k, v in body.items() if isinstance(v, str)}
        st, body = self.fc_get("/mode")
        if st == 200 and isinstance(body, dict):
            cap["mode"] = body.get("mode")
        self.captured = cap
        return cap

    # -- check + restore -----------------------------------------------
    def enforce(self, phase, captured=None):
        """Bring the machine to the baseline; returns the list of leftovers.
        phase is 'pre' or 'post' (log wording only). captured is the
        preserved state to hand back (post) - None compares nothing."""
        left = []
        self._forgectrl_side(left)
        self._kernel_side(left)
        self._lamp_side(left)
        self._preserved(left, captured)
        if left:
            self.log("%s: %d leftover(s): %s" % (phase, len(left), "; ".join(str(x) for x in left)))
        else:
            self.log("%s: clean" % phase)
        return left

    def _wait(self, what, pred, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout and not self.abort():
            if pred():
                return time.time() - t0
            time.sleep(1.0)
        return None

    def _forgectrl_side(self, left):
        st, mode = self.fc_get("/mode")
        if st != 200 or not isinstance(mode, dict):
            self.log("forgectrl not answering - service-side checks skipped")
            return
        # a diagnostic left running seizes the thermal hardware: abort it
        st, d = self.fc_get("/diag/status")
        if st == 200 and isinstance(d, dict) and d.get("running"):
            self.fc_post("/diag/abort")
            w = self._wait("diag idle", lambda: not (self.fc_get("/diag/status")[1] or {}).get("running"), 60)
            left.append(Leftover("diag", d.get("tool"), "not running",
                                 "aborted" if w is not None else "failed: still running"))
        # the camera engine stops itself 10 s after the last client
        st, c = self.fc_get("/cam/status")
        if st == 200 and isinstance(c, dict) and c.get("running"):
            w = self._wait("cam idle", lambda: not (self.fc_get("/cam/status")[1] or {}).get("running"),
                           CAM_IDLE_S)
            if w is None:
                left.append(Leftover("cam.running", True, False, "failed: still running"))
        # supervisor: the captured mode, controller running, motion verified
        want = (self.captured or {}).get("mode") or mode.get("mode") or "grbl"
        if mode.get("mode") != want:
            st, body = self.fc_post("/mode", data={"controller": want})
            mode = self.wait_settled() or mode
            left.append(Leftover("mode", mode.get("mode"), want,
                                 "restored" if mode.get("mode") == want else "failed: %s %s" % (st, body)))
        if mode.get("controller") == "motion-fault":
            st, body = self.fc_post("/mode", data={"controller": want})
            mode = self.wait_settled() or mode
            left.append(Leftover("controller", "motion-fault", "running",
                                 "restored" if mode.get("controller") == "running"
                                 else "failed: %s" % mode.get("controller")))
        elif mode.get("controller") == "standby":
            st, body = self.fc_post("/controller/start")
            mode = self.wait_settled() or mode
            left.append(Leftover("controller", "standby", "running",
                                 "restored" if mode.get("controller") == "running"
                                 else "failed: %s" % mode.get("controller")))
        elif mode.get("controller") != "running" or mode.get("motion") != "verified":
            before = (mode.get("controller"), mode.get("motion"))
            mode = self.wait_settled() or mode
            if mode.get("controller") == "running" and mode.get("motion") == "verified":
                left.append(Leftover("controller", "%s/%s" % before, "running/verified", "waited"))
            else:
                left.append(Leftover("controller", "%s/%s" % before, "running/verified",
                                     "failed: %s/%s" % (mode.get("controller"), mode.get("motion"))))
        # machine state through /status
        st, s = self.fc_get("/status")
        if st == 200 and isinstance(s, dict):
            if s.get("state") != "idle":
                if s.get("state") == "underrun":
                    try:
                        hw.sysfs_write("cnc/stop", "1")     # ack
                    except OSError:
                        pass
                w = self._wait("idle", lambda: (self.fc_get("/status")[1] or {}).get("state") == "idle", IDLE_S)
                left.append(Leftover("state", s.get("state"), "idle",
                                     "waited" if w is not None else "failed: not idle"))
            if s.get("laser_locked") is False:
                try:
                    hw.sysfs_write("cnc/laser_latch", "1")
                    act = "restored"
                except OSError as e:
                    act = "failed: %s" % e
                left.append(Leftover("laser_locked", False, True, act))
        # cooling engine idle, unarmed
        st, c = self.fc_get("/cool/status")
        if st == 200 and isinstance(c, dict):
            if c.get("phase") != "idle" or c.get("armed") or c.get("hold"):
                found = "%s/armed=%s/hold=%s" % (c.get("phase"), c.get("armed"), c.get("hold"))
                w = self._wait("cool idle", lambda: (lambda x: x.get("phase") == "idle" and not x.get("armed")
                                                    and not x.get("hold"))(self.fc_get("/cool/status")[1] or {}),
                               COOL_IDLE_S)
                left.append(Leftover("cool", found, "idle/unarmed/no hold",
                                     "waited" if w is not None else "failed: still %s" % found))

    def _lamp_side(self, left):
        """The lid lamp at forgectrl's idle level (the lid_lamp_idle setting)."""
        st, body = self.fc_get("/settings")
        if st != 200 or not isinstance(body, dict):
            return
        want = (body.get("lid_lamp_idle") or "").strip() or LID_LAMP_DEFAULT
        got = hw.sysfs_read(LID_LAMP_ATTR)
        if got is None or got == want:
            return
        try:
            hw.sysfs_write(LID_LAMP_ATTR, want)
            back = hw.sysfs_read(LID_LAMP_ATTR)
            act = "restored" if back == want else "failed: reads %s" % back
        except OSError as e:
            act = "failed: %s" % e
        left.append(Leftover(LID_LAMP_ATTR, got, want, act))

    def _kernel_side(self, left):
        if hw.sysfs_read("cnc/state") is None:
            self.log("kernel sysfs not present - kernel-side checks skipped")
            return
        for attr, want in IDLE_READBACKS:
            got = hw.sysfs_read(attr)
            if got is not None and got != want:
                left.append(Leftover(attr, got, want, "unrestorable"))
        ilk = hw.sysfs_int("cnc/interlock_circuit")
        if ilk is not None and not (ilk & LATCH_BIT):
            try:
                hw.sysfs_write("cnc/laser_latch", "1")
                act = "restored"
            except OSError as e:
                act = "failed: %s" % e
            left.append(Leftover("laser_latch", "unlocked (interlock 0x%x)" % ilk, "locked", act))
        for attr, want in FIXED_SYSFS:
            got = hw.sysfs_read(attr)
            if got is None or got == want:
                continue
            try:
                hw.sysfs_write(attr, want)
                back = hw.sysfs_read(attr)
                act = "restored" if back == want else "failed: reads %s" % back
            except OSError as e:
                act = "failed: %s" % e
            left.append(Leftover(attr, got, want, act))
        for name in BUTTON_LEDS:
            got = read_led(name)
            if got is not None and got != "0":
                try:
                    write_led(name, 0)
                    act = "restored"
                except OSError as e:
                    act = "failed: %s" % e
                left.append(Leftover("leds/" + name, got, "0", act))

    def _return_head(self, was, now):
        """Jog the head back along its own path by the kernel-measured X/Y
        delta (Z is never touched), through the GRBL controller. Bounded:
        beyond RETURN_MAX_MM per axis, or without a running GRBL
        controller, the counters are reported and left."""
        dx = (now[0] - was[0]) / XY_STEPS_PER_MM
        dy = (now[1] - was[1]) / XY_STEPS_PER_MM
        if abs(dx) < 0.02 and abs(dy) < 0.02:
            return "unrestorable (Z only)" if now[2] != was[2] else "restored"
        if abs(dx) > RETURN_MAX_MM or abs(dy) > RETURN_MAX_MM:
            return "unrestorable: %.1f/%.1f mm exceeds %.0f mm" % (dx, dy, RETURN_MAX_MM)
        # a controller may be inside a respawn backoff (seconds): wait for it
        mode = None
        deadline = time.time() + 30
        while time.time() < deadline:
            st, mode = self.fc_get("/mode")
            if (st == 200 and isinstance(mode, dict) and mode.get("mode") == "grbl"
                    and mode.get("controller") == "running"):
                break
            if st is None:
                break
            time.sleep(1.0)
        if not (isinstance(mode, dict) and mode.get("mode") == "grbl"
                and mode.get("controller") == "running"):
            return "unrestorable: no running GRBL controller"
        try:
            with hw.Grbl() as g:
                rep = g.status_report()
                if rep["state"].startswith("Alarm"):
                    g.command("$X")
                g.command("$J=G91X%.3fY%.3fF1200" % (-dx, -dy))
                deadline = time.time() + 60
                while time.time() < deadline:
                    rep = g.status_report()
                    if rep["state"].startswith("Idle") and time.time() > deadline - 59.5:
                        break
                    time.sleep(0.2)
                g.command("G90")
        except (hw.HwError, OSError) as e:
            return "failed: %s" % e
        self.fc().wait_idle(15)
        back = read_position()
        if back is not None and abs(back[0] - was[0]) <= 2 and abs(back[1] - was[1]) <= 2:
            self.log("head jogged back %.3f/%.3f mm to its start" % (-dx, -dy))
            return "restored (jogged back %.1f/%.1f mm)" % (-dx, -dy)
        return "failed: counters read %s after the return jog" % back

    def _preserved(self, left, captured):
        if not captured:
            return
        for attr, was in (captured.get("sysfs") or {}).items():
            now = hw.sysfs_read(attr)
            if was is None or now is None or now == was:
                continue
            try:
                hw.sysfs_write(attr, was)
                back = hw.sysfs_read(attr)
                act = "restored" if back == was else "failed: reads %s" % back
            except OSError as e:
                act = "failed: %s" % e
            left.append(Leftover(attr, now, was, act))
        was = captured.get("position")
        now = read_position()
        if was is not None and now is not None and now != was:
            left.append(Leftover("position", now, was, self._return_head(was, now)))
        was = captured.get("settings")
        if was:
            st, body = self.fc_get("/settings")
            if st == 200 and isinstance(body, dict):
                for k, v in was.items():
                    if body.get(k) == v:
                        continue
                    st2, b2 = (self.fc_post("/settings", params={k: ""}) if v == ""
                               else self.fc_post("/settings", data={k: v}))
                    left.append(Leftover("settings." + k, body.get(k), v,
                                         "restored" if st2 == 200 else "failed: %s %s" % (st2, b2)))


# ------------------------------------------------------------ boot reference

def boot_id():
    v = os.environ.get("FORGETEST_BOOT_ID")
    if v:
        return v
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        return None


def uptime_s():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def dump_sysfs():
    """Every readable text attribute under the module's sysfs root, by
    'group/attr'; the binary position attribute decoded to (x, y, z)."""
    out = {}
    root = hw.sysfs_root()
    for group in ("cnc", "pic", "head", "thermal"):
        d = root + group
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            path = "%s/%s" % (d, n)
            if os.path.isdir(path) or n in ("uevent",):
                continue
            key = "%s/%s" % (group, n)
            if key == "cnc/position":
                out[key] = read_position()
                continue
            try:
                with open(path, "rb") as f:
                    raw = f.read(256)
            except OSError:
                continue
            try:
                out[key] = raw.decode("ascii").strip()
            except UnicodeDecodeError:
                out[key] = "<binary %d bytes>" % len(raw)
    return out


def dump_all(bl):
    """The whole idle picture: sysfs, LEDs, forgectrl's status endpoints."""
    d = {"sysfs": dump_sysfs(), "leds": {}, "forgectrl": {}}
    for name in BUTTON_LEDS + ("lid_led",):
        d["leds"][name] = read_led(name)
    for path in ("/mode", "/status", "/cool/status", "/cam/status", "/diag/status", "/settings"):
        st, body = bl.fc_get(path)
        d["forgectrl"][path] = body if st == 200 else None
    return d


def check_fixed_against(ref, log):
    """Compare the fixed constants with a fresh-boot dump; log the diffs
    (a differing constant is a fact about this machine, not a leftover)."""
    diffs = []
    sysfs = ref.get("sysfs") or {}
    for attr, want in FIXED_SYSFS + IDLE_READBACKS:
        got = sysfs.get(attr)
        if got is not None and got != want:
            diffs.append("%s: boot=%s constant=%s" % (attr, got, want))
    for d in diffs:
        log("baseline: NOTE fresh boot differs from the fixed value - " + d)
    return diffs


def boot_reference(log, data_dir):
    """The fresh-boot idle state of this boot: loaded from
    <data_dir>/boot-<boot_id>.json when forgetest already took it, taken
    now (after the supervisor settles) when the boot is recent, None
    otherwise. Blocks for the settle - call from a background thread."""
    bid = boot_id()
    if not bid:
        return None
    path = os.path.join(data_dir, "boot-%s.json" % bid)
    try:
        with open(path) as f:
            ref = json.load(f)
        log("baseline: fresh-boot reference loaded (%s, taken %s)" % (path, ref.get("ts")))
        return ref
    except (OSError, ValueError):
        pass
    up = uptime_s()
    if up is None or up > BOOT_MAX_AGE_S:
        log("baseline: no fresh-boot reference for this boot (uptime %s s > %d s); "
            "power-cycle to take one" % (up, BOOT_MAX_AGE_S))
        return None
    bl = Baseline(log)
    bl.wait_settled()
    ref = dump_all(bl)
    ref.update({"ts": now_ts(), "boot_id": bid, "uptime_s": uptime_s()})
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(path, "w") as f:
            json.dump(ref, f, indent=1, sort_keys=True)
    except OSError as e:
        log("baseline: could not save the fresh-boot reference: %s" % e)
    log("baseline: fresh-boot reference taken at uptime %.0f s (%d sysfs attrs)"
        % (ref["uptime_s"], len(ref["sysfs"])))
    check_fixed_against(ref, log)
    return ref
