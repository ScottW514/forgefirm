"""The cloud.* job-behavior tests against a fake forgectrl and a replayed
gfcloud log: the real test functions run under the real runner Context,
the operator prompts answered by a script that also drives the replay
(open the lid -> the machine's lid reads open; close it -> the service's
re-hunt lines land). The log lines are the machine's own: bench excerpts
(the lid-abort, button-wait, and lid-open-hunt runs) and, for the pause,
the run loop's lines as its host test emits them on the print skeleton
of the lid-abort excerpt.

What is proven here: the tests find the right lines in real log noise,
reuse an existing cloud session and never switch back, restart the client
for a fresh hunt, judge the print's own finish line (not another action's),
wait the service's deferred moves out, and fail for the right reasons."""
import os
import shutil
import struct
import tempfile
import threading
import time
import unittest

import helpers
from forgetest.runner import Context, Failed, Run
from forgetest.suite import cloud

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")


def fixture(name):
    with open(os.path.join(FIX, "gfcloud-%s.log" % name), "rb") as f:
        return f.read().decode().splitlines()


# What the build under test logs around a print, in the machine's own format.
WARM_UP_LINE = ("2026-08-17T09:44:02.100000+00:00 gfcloud[1522] INFO "
                "machine:_dwell warm up: holding 3.0 s")
COOL_DOWN_LINE = ("2026-08-17T09:45:31.700000+00:00 gfcloud[1522] INFO "
                  "machine:_dwell cool down: holding 10.0 s")
PROGRESS_LINE = ("2026-08-17T09:44:05.200000+00:00 gfcloud[1522] INFO "
                 "machine:__init__ print:progress: reporting against 47848 bytes every 30 s")


def cut(lines, marker, count=1):
    """(before, after) at the count-th line containing marker (the line
    itself opens `after`)."""
    n = 0
    for i, ln in enumerate(lines):
        if marker in ln:
            n += 1
            if n == count:
                return lines[:i], lines[i:]
    raise KeyError(marker)


class Script:
    """Answers every prompt with its first option; a hook per prompt
    substring drives the fake machine and the log replay."""

    def __init__(self, run, hooks=None):
        self.run = run
        self.hooks = hooks or {}
        self.asked = []
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.stop = False

    def start(self):
        self.th.start()
        return self

    def _loop(self):
        seen = None
        while not self.stop:
            p = self.run.prompt
            if p and p["id"] != seen:
                seen = p["id"]
                self.asked.append(p["question"])
                for key, fn in self.hooks.items():
                    if key in p["question"]:
                        fn()
                self.run.answer(p["id"], p["options"][0])
            time.sleep(0.02)


class CloudSuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="forgetest-cloud-")
        self.log = os.path.join(self.tmp, "gfcloud.log")
        open(self.log, "wb").close()
        self.sysfs = os.path.join(self.tmp, "sysfs") + os.sep
        os.makedirs(self.sysfs + "cnc")
        self._attr("cnc/interlock_circuit", "45")          # latch locked (bit 3)
        self._pos(0, 0, 3)
        os.environ["GF_SYSFS_ROOT"] = self.sysfs
        self.fc = helpers.FakeForgectrl().start()
        self.saved = (cloud.GFCLOUD_LOG, cloud.QUIET_S, cloud.QUIET_TIMEOUT_S, cloud.HUNT_TIMEOUT_S)
        cloud.GFCLOUD_LOG = self.log
        cloud.QUIET_S = 0.4
        cloud.QUIET_TIMEOUT_S = 3
        cloud.HUNT_TIMEOUT_S = 8
        self.script = None

    def tearDown(self):
        if self.script:
            self.script.stop = True
        self.fc.stop()
        cloud.GFCLOUD_LOG, cloud.QUIET_S, cloud.QUIET_TIMEOUT_S, cloud.HUNT_TIMEOUT_S = self.saved
        os.environ.pop("GF_SYSFS_ROOT", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- fakes -----------------------------------------------------------
    def _attr(self, attr, val):
        with open(self.sysfs + attr, "w") as f:
            f.write(val)

    def _pos(self, x, y, z):
        with open(self.sysfs + "cnc/position", "wb") as f:
            f.write(struct.pack("<3i2I", x, y, z, 0, 0))

    def append(self, lines, delay=0.0):
        def go():
            if delay:
                time.sleep(delay)
            with open(self.log, "ab") as f:
                f.write(("\n".join(lines) + "\n").encode())
        if delay:
            threading.Thread(target=go, daemon=True).start()
        else:
            go()

    def in_cloud(self, pid=2278):
        self.fc.state["mode"] = {"mode": "cloud", "controller": "running", "pid": pid, "motion": "verified"}
        self.fc.state["settings"]["controller_mode"] = "cloud"

    def lid(self, closed):
        self.fc.state["status"]["switches"]["lid"] = bool(closed)

    def run_test(self, fn, hooks=None, test_id="cloud.x"):
        run = Run("test", test_id, test_id)
        run.baseline_captured = {"mode": self.fc.state["mode"]["mode"], "position": [0, 0, 0]}
        ctx = Context(run, None, helpers.make_test(test_id, []))
        self.script = Script(run, hooks).start()
        try:
            fn(ctx)
        finally:
            self.script.stop = True
        return run

    def assertFails(self, fn, needle, hooks=None):
        with self.assertRaises(Failed) as cm:
            self.run_test(fn, hooks)
        self.assertIn(needle, str(cm.exception))
        return cm.exception

    # -- session detection -------------------------------------------------
    def test_session_live_is_per_client(self):
        lines = fixture("huntlid")
        # the old client (1927) closed and left; the new one (2278) is ready
        self.append(lines)
        self.assertTrue(cloud.session_live(2278)[0])
        self.assertFalse(cloud.session_live(1927)[0])
        # an unknown pid falls back to the newest lines (ready)
        self.assertTrue(cloud.session_live(9999)[0])
        # a drop after the ready line: not live until it is ready again
        self.append(["2026-08-17T10:00:00.000000+00:00 gfcloud[2278] INFO websocket:_on_close RX-EVENT: closed (1006, )",
                     "2026-08-17T10:00:00.100000+00:00 gfcloud[2278] INFO websocket:run RECONNECTING"])
        live, detail = cloud.session_live(2278)
        self.assertFalse(live)
        self.assertIn("RECONNECTING", detail)
        self.append(["2026-08-17T10:00:06.000000+00:00 gfcloud[2278] INFO websocket:_on_open RX-EVENT: ready"])
        self.assertTrue(cloud.session_live(2278)[0])

    def test_enter_cloud_reuses_a_live_session_and_never_switches(self):
        self.in_cloud()
        self.append(fixture("huntlid"))
        run = self.run_test(lambda ctx: cloud.enter_cloud(ctx))
        self.assertTrue(any("reusing it" in l for l in run.lines), run.lines)
        self.assertEqual(self.fc.posts, [])
        self.assertEqual(run.baseline_captured["mode"], "cloud")

    def test_enter_cloud_refuses_a_dead_session(self):
        self.in_cloud(pid=1927)                 # the client that shut down in the excerpt
        self.append(fixture("huntlid"))
        self.assertFails(cloud.enter_cloud, "no live service session")

    def test_enter_cloud_switches_once_from_grbl_and_declares_it(self):
        lines = fixture("huntlid")
        pre, post = cut(lines, "gfuiservice:__init__ INITIALIZED")
        self.append(pre)

        def on_post(path, form):
            if path == "/mode":
                self.append(post, delay=0.2)    # the new client's session + hunt + moves
            return None
        self.fc.on_post = on_post
        run = self.run_test(lambda ctx: cloud.enter_cloud(ctx))
        self.assertEqual([p for p, _ in self.fc.posts], ["/mode"])
        self.assertEqual(self.fc.state["mode"]["mode"], "cloud")
        self.assertEqual(run.baseline_captured["mode"], "cloud")     # declared: the baseline keeps it
        self.assertTrue(any("connect-time hunt" in l and ":completed" in l for l in run.lines), run.lines)

    def test_enter_cloud_waits_for_the_service_to_stop_moving(self):
        self.in_cloud()
        self.append(fixture("huntlid"))
        # a motion in flight (never idle within the timeout) fails, and says so
        self.fc.state["status"]["state"] = "running"
        self.assertFails(cloud.enter_cloud, "still running service moves")

    # -- the hunt with the lid open ------------------------------------------
    def test_hunt_lid_open_restarts_the_client_in_cloud_mode(self):
        self.in_cloud(pid=1927)
        lines = fixture("huntlid")
        pre, post = cut(lines, "gfuiservice:__init__ INITIALIZED")
        hunt_part, close_part = cut(post, "_switch_event lid closed")
        self.append(pre)

        def on_post(path, form):
            if path == "/controller/stop":
                self.fc.state["mode"] = dict(self.fc.state["mode"], controller="standby", pid=0)
            elif path == "/controller/start":
                self.fc.state["mode"] = dict(self.fc.state["mode"], controller="running", pid=2278)
                self.append(hunt_part, delay=0.2)
            return None
        self.fc.on_post = on_post

        def lid_closed():
            self.lid(True)
            self.append(close_part, delay=0.2)
        run = self.run_test(cloud.hunt_lid_open,
                            hooks={"Open the lid": lambda: self.lid(False), "Close the lid": lid_closed},
                            test_id="cloud.hunt-lid-open")
        self.assertEqual([p for p, _ in self.fc.posts], ["/controller/stop", "/controller/start"])
        ev = run.evidence
        self.assertIn(":completed", ev["hunt_line"])
        self.assertEqual(ev["refusals_before_hunt_end"], 0)
        self.assertEqual(ev["motions_after_lid_close"], 3)
        self.assertEqual(self.fc.state["mode"]["mode"], "cloud")     # still cloud
        self.assertTrue(any("PASS:" in l for l in run.lines))
        # the prompts, in order: open, confirm lens, close
        self.assertEqual(len(self.script.asked), 3)

    def test_hunt_lid_open_from_grbl_switches_and_stays(self):
        lines = fixture("huntlid")
        pre, post = cut(lines, "gfuiservice:__init__ INITIALIZED")
        hunt_part, close_part = cut(post, "_switch_event lid closed")
        self.append(pre)

        def on_post(path, form):
            if path == "/mode":
                self.append(hunt_part, delay=0.2)
            return None
        self.fc.on_post = on_post
        run = self.run_test(cloud.hunt_lid_open,
                            hooks={"Open the lid": lambda: self.lid(False),
                                   "Close the lid": lambda: (self.lid(True), self.append(close_part, delay=0.2))})
        self.assertEqual([p for p, _ in self.fc.posts], ["/mode"])
        self.assertEqual(self.fc.state["mode"]["mode"], "cloud")
        self.assertEqual(run.baseline_captured["mode"], "cloud")
        self.assertIn(":completed", run.evidence["hunt_line"])

    def test_hunt_lid_open_needs_the_lid_open(self):
        self.in_cloud()
        self.append(fixture("huntlid"))
        self.assertFails(cloud.hunt_lid_open, "lid reads closed")

    def test_hunt_refused_for_the_lid_fails(self):
        self.in_cloud(pid=1927)
        lines = fixture("huntlid")
        pre, post = cut(lines, "gfuiservice:__init__ INITIALIZED")
        # a refusal ahead of the hunt's end (the lid gating the hunt would look like this)
        i = next(i for i, l in enumerate(post) if "z_axis:home starting z homing cycle" in l)
        post = post[:i] + ["2026-08-17T09:45:10.595000+00:00 gfcloud[2278] INFO machine:_safe_to_move lid opened, unsafe to move"] + post[i:]
        self.append(pre)

        def on_post(path, form):
            if path == "/controller/stop":
                self.fc.state["mode"] = dict(self.fc.state["mode"], controller="standby", pid=0)
            elif path == "/controller/start":
                self.fc.state["mode"] = dict(self.fc.state["mode"], controller="running", pid=2278)
                self.append(post, delay=0.1)
            return None
        self.fc.on_post = on_post
        self.assertFails(cloud.hunt_lid_open, "refused for the lid", hooks={"Open the lid": lambda: self.lid(False)})

    # -- pause / resume ---------------------------------------------------------
    def replay_print(self, name, at_run, at_end, tail_delay=0.3):
        """Split a print excerpt into: up to the run's RUNNING line
        (lands when the operator says Print is done), the block landing at
        the mid-run prompt, and the rest."""
        lines = fixture(name)
        pre, rest = cut(lines, "waiting for button")
        run_pre, rest = cut(rest, "current state: MachineState.RUNNING")     # the PRINT's run
        # The excerpt was captured before the machine held for a warm-up and
        # a rest, and before it reported a print's progress; the replay
        # carries those lines where it emits them now, rather than editing
        # what the machine actually said that day.
        run_pre = run_pre + [WARM_UP_LINE, PROGRESS_LINE]
        pre, rest = pre + run_pre + [rest[0]], rest[1:]
        mid, tail = cut(rest, at_end)
        tail = tail + [COOL_DOWN_LINE]
        return {"Click Done here": lambda: self.append(pre, delay=0.1),
                at_run: lambda: (self.append(mid, delay=0.05), self.append(tail, delay=tail_delay))}

    def test_pause_resume_passes_on_the_machines_lines(self):
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.000000+00:00 gfcloud[1522] INFO authentication:authenticate_machine SUCCESS",
                     "2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready",
                     "2026-08-17T09:41:00.900000+00:00 gfcloud[1522] INFO websocket:ws_connect ESTABLISHED"])
        hooks = self.replay_print("pause", "Press the button once NOW", "current state: MachineState.IDLE")
        self.fc.state["cool"]["armed"] = True
        run = self.run_test(cloud.pause_resume, hooks=hooks, test_id="cloud.pause-resume")
        ev = run.evidence
        self.assertEqual(ev["log"], {"button pressed mid-run; pausing": True, "paused at": True,
                                     "button pressed while paused; resuming": True})
        self.assertTrue(ev["armed_after_resume"])
        self.assertIn(":completed", ev["log_end"]["print finished"])
        self.assertTrue(ev["log_end"]["return home complete"])
        self.assertEqual(ev["relock_or_cancel_lines"], 0)
        self.assertEqual(self.fc.posts, [])
        self.assertTrue(any("PASS: button pause/resume" in l for l in run.lines))
        # the post-print hunt was waited out
        self.assertTrue(any("machine is quiet" in l for l in run.lines))

    def test_pause_resume_fails_when_the_print_is_cancelled_instead(self):
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready"])
        lines = fixture("pause")
        lines = [l.replace('print [1576550507]: finished with event ":completed"',
                           'print [1576550507]: finished with event ":cancelled"') for l in lines]
        pre, rest = cut(lines, "current state: MachineState.RUNNING")
        pre, rest = pre + [rest[0]], rest[1:]
        hooks = {"Click Done here": lambda: self.append(pre, delay=0.1),
                 "Press the button once NOW": lambda: self.append(rest, delay=0.05)}
        self.assertFails(cloud.pause_resume, "did not complete after the resume", hooks=hooks)

    def test_pause_resume_fails_without_the_pause_line(self):
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready"])
        lines = [l for l in fixture("pause") if "button pressed mid-run" not in l]
        pre, rest = cut(lines, "current state: MachineState.RUNNING")
        pre, rest = pre + [rest[0]], rest[1:]
        # the wait for the pause lines is 90 s: shorten it through the module's poll by
        # ending the log early - the finish line arrives, but the pause never does
        saved = cloud.wait_log

        def fast_wait_log(ctx, offset, needles, timeout, poll=0.5):
            return saved(ctx, offset, needles, min(timeout, 1.5), poll=0.1)
        cloud.wait_log = fast_wait_log
        try:
            hooks = {"Click Done here": lambda: self.append(pre, delay=0.1),
                     "Press the button once NOW": lambda: self.append(rest, delay=0.05)}
            self.assertFails(cloud.pause_resume, "did not pause the run", hooks=hooks)
        finally:
            cloud.wait_log = saved

    # -- the lid/interlock abort and the button-wait tests, on their excerpts ------
    # -- the merged lid + interlock abort test -------------------------------
    def abort_parts(self):
        """The lid-abort excerpt split for the merged test: the print
        prologue (replayed for both prints), the lid stop + park + cancel,
        and the same tail with the interlock as the trigger, cut where the
        test stops to have the lid opened during the park."""
        lines = fixture("lidabort")
        pre, rest = cut(lines, "waiting for button")
        run_pre, rest = cut(rest, "machine:_run_loop starting run")
        pre, rest = pre + run_pre + [rest[0]], rest[1:]
        ilk = [l.replace("lid opened mid-run; stopping motion",
                         "interlock opened mid-run; stopping motion") for l in rest]
        stop, tail = cut(ilk, "start return home")
        return pre, rest, stop + [tail[0]], tail[1:]

    def abort_hooks(self, pre, lid_tail, ilk_stop, ilk_park, prints):
        def next_print():
            prints.append(1)
            self.append(pre, delay=0.1)

        def pull_interlock():
            self.fc.state["status"]["switches"]["interlock_ok"] = False
            self.append(ilk_stop, delay=0.05)

        def restore():
            self.lid(True)
            self.fc.state["status"]["switches"]["interlock_ok"] = True
        return {"Click Done here": next_print,
                "Open the lid NOW": lambda: (self.lid(False), self.append(lid_tail, delay=0.05)),
                "Close the lid, then click Done": lambda: self.lid(True),
                "Open the INTERLOCK loop now": pull_interlock,
                "Open the LID now as well": lambda: (self.lid(False),
                                                     self.append(ilk_park, delay=0.05)),
                "Close the lid and restore the interlock": restore}

    def test_lid_interlock_abort_on_the_bench_excerpt(self):
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready"])
        prints = []
        run = self.run_test(cloud.lid_interlock_abort,
                            hooks=self.abort_hooks(*self.abort_parts(), prints),
                            test_id="cloud.lid-interlock-abort")
        ev = run.evidence
        self.assertEqual(len(prints), 2)                      # two prints, one cue each
        # print 1: the lid
        self.assertLess(ev["edge_to_stop_ms"], 60)
        self.assertIn(":cancelled", ev["lid_log"]["print finished"])
        self.assertEqual(ev["lid_counters_after_park"], [0, 0, 3])
        self.assertTrue(ev["lid_latch_locked"])
        self.assertFalse(ev["lid_armed_after"])
        # print 2: the interlock, with the lid opened during the park
        self.assertFalse(ev["interlock_ok_after_pull"])
        self.assertIn(":cancelled", ev["interlock_log"]["print finished"])
        self.assertTrue(ev["interlock_log"]["return home complete"])
        self.assertEqual(ev["switches_at_return"], {"lid": False, "interlock_ok": False})
        self.assertEqual(ev["interlock_counters_after_park"], [0, 0, 3])
        self.assertTrue(ev["interlock_latch_locked"])
        self.assertEqual(ev["restored"], {"lid": True, "interlock_ok": True})
        self.assertEqual(self.fc.posts, [])
        self.assertTrue(any("PASS: lid open" in l for l in run.lines), run.lines)

    def test_lid_interlock_abort_refuses_when_the_loop_is_already_open(self):
        self.in_cloud(pid=1522)
        self.fc.state["status"]["switches"]["interlock_ok"] = False
        self.assertFails(cloud.lid_interlock_abort, "already reads open")

    def test_lid_interlock_abort_fails_when_the_park_stops_at_the_lid(self):
        # the regression this guards: a park an open lid can interrupt
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready"])
        pre, lid_tail, ilk_stop, ilk_park = self.abort_parts()
        ilk_park = [l for l in ilk_park if "return home complete" not in l]
        saved = cloud.wait_log

        def fast_wait_log(ctx, offset, needles, timeout, poll=0.5):
            return saved(ctx, offset, needles, min(timeout, 1.5), poll=0.1)
        cloud.wait_log = fast_wait_log
        try:
            self.assertFails(cloud.lid_interlock_abort, "did not run to completion",
                             hooks=self.abort_hooks(pre, lid_tail, ilk_stop, ilk_park, []))
        finally:
            cloud.wait_log = saved

    def test_lid_interlock_abort_fails_when_the_lid_stop_is_not_edge_driven(self):
        # a polled stop (the pre-parity behavior) shows up as a long edge->stop gap
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready"])
        pre, lid_tail, ilk_stop, ilk_park = self.abort_parts()
        lid_tail = [l.replace("2026-08-17T09:42:30.838627", "2026-08-17T09:42:31.838627")
                    if "lid opened mid-run; stopping motion" in l else l for l in lid_tail]
        self.assertFails(cloud.lid_interlock_abort, "not edge-driven",
                         hooks=self.abort_hooks(pre, lid_tail, ilk_stop, ilk_park, []))

    def test_lid_during_button_wait_on_the_bench_excerpt(self):
        self.in_cloud(pid=1927)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1927] INFO websocket:_on_open RX-EVENT: ready"])
        lines = fixture("buttonwait")
        pre, rest = cut(lines, "waiting for button")
        pre, rest = pre + [rest[0]], rest[1:]
        hooks = {"Click Done here": lambda: self.append(pre, delay=0.1),
                 "Open the lid now": lambda: self.append(rest, delay=0.05)}
        run = self.run_test(cloud.lid_during_button_wait, hooks=hooks, test_id="cloud.lid-during-button-wait")
        ev = run.evidence
        self.assertEqual(ev["runs_started_after_wait"], 0)
        self.assertIn(":cancelled", ev["log"]["print finished"])
        self.assertTrue(ev["latch_locked"])
        self.assertEqual(self.fc.posts, [])
        self.assertTrue(any("PASS: lid open at the button prompt" in l for l in run.lines))

    # -- a paused print cancelled by the lid, a running one by the app --------
    def cancel_parts(self):
        """(print prologue, the pause lines, the lid stop + park + cancel,
        the same tail with the app's cancel as the trigger)."""
        lines = fixture("lidabort")
        pre, rest = cut(lines, "waiting for button")
        run_pre, rest = cut(rest, "machine:_run_loop starting run")
        pre, rest = pre + run_pre + [rest[0]], rest[1:]
        paused = ["2026-08-17T09:42:25.500000+00:00 gfcloud[1522] INFO machine:_run_loop "
                  "button pressed mid-run; pausing",
                  "2026-08-17T09:42:26.100000+00:00 gfcloud[1522] INFO machine:_run_loop "
                  "paused at Position(x=41.2, y=17.0, z=0.0)"]
        app_cancel = [l.replace("lid opened mid-run; stopping motion",
                                "action cancelled mid-run; stopping motion") for l in rest]
        return pre, paused, rest, app_cancel

    def test_pause_cancel_paths_on_the_bench_excerpt(self):
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready"])
        pre, paused, lid_tail, app_tail = self.cancel_parts()
        prints = []

        def next_print():
            prints.append(1)
            self.append(pre, delay=0.1)
        run = self.run_test(cloud.pause_cancel_paths,
                            hooks={"Click Done here": next_print,
                                   "Press the button once NOW": lambda: self.append(paused, delay=0.05),
                                   "Open the lid NOW": lambda: (self.lid(False),
                                                                self.append(lid_tail, delay=0.05)),
                                   "Close the lid, then click Done": lambda: self.lid(True),
                                   "Cancel the print from the app now": lambda: self.append(app_tail,
                                                                                            delay=0.05)},
                            test_id="cloud.pause-cancel-paths")
        ev = run.evidence
        self.assertEqual(len(prints), 2)                      # two prints, one cue each
        self.assertEqual(ev["paused"], {"button pressed mid-run; pausing": True, "paused at": True})
        self.assertIn(":cancelled", ev["lid_from_pause"]["print finished"])
        self.assertIn(":cancelled", ev["service_cancel"]["print finished"])
        self.assertTrue(ev["lid_from_pause"]["return home complete"])
        self.assertTrue(ev["service_cancel"]["return home complete"])
        self.assertEqual(ev["counters_after_print1"], [0, 0, 3])
        self.assertEqual(ev["counters_after_print2"], [0, 0, 3])
        self.assertTrue(ev["latch_locked_after_print1"] and ev["latch_locked_after_print2"])
        self.assertFalse(ev["armed_after_print1"] or ev["armed_after_print2"])
        self.assertEqual(self.fc.posts, [])
        self.assertTrue(any("PASS: a paused print cancelled by the lid" in l for l in run.lines), run.lines)

    def test_pause_cancel_paths_fails_when_the_paused_print_resumes_instead(self):
        # a lid that resumed (or was ignored) leaves the print ':completed'
        self.in_cloud(pid=1522)
        self.append(["2026-08-17T09:41:00.500000+00:00 gfcloud[1522] INFO websocket:_on_open RX-EVENT: ready"])
        pre, paused, lid_tail, _app = self.cancel_parts()
        lid_tail = [l.replace(':cancelled"', ':completed"') for l in lid_tail]
        self.assertFails(
            cloud.pause_cancel_paths, "print 1 did not end ':cancelled'",
            hooks={"Click Done here": lambda: self.append(pre, delay=0.1),
                   "Press the button once NOW": lambda: self.append(paused, delay=0.05),
                   "Open the lid NOW": lambda: (self.lid(False), self.append(lid_tail, delay=0.05))})

    def test_print_finish_is_the_prints_not_another_actions(self):
        # a motion that completes before the print must not satisfy the print's finish
        lines = fixture("lidabort")
        i = cloud.action_finish_index(lines, "print")
        j = cloud.action_finish_index(lines, "motion")
        self.assertIsNotNone(i)
        self.assertIsNotNone(j)
        self.assertLess(j, i)
        self.assertIn(":cancelled", lines[i])
        self.assertIn(":completed", lines[j])


if __name__ == "__main__":
    unittest.main()
