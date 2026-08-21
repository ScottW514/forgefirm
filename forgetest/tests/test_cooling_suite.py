"""cooling.fans-quiet-after-motion replayed host-side under the real
runner Context against a scripted machine: a fake forgectrl (/status
fans, /cool/status phase), a fake kernel sysfs (the fan duties), and a
fake Grbl port that answers '?' and every command.

The bench case that motivated this: the test started one second after
the engine of a previous test went idle, took the tachs still coasting
at the cooldown level as its idle reference, and then waited for the
fans to come back UP to it. The idle reference now needs the engine
idle, the idle duty applied, and tachs that have stopped changing; the
pass condition is at-or-below that level, and every sample is logged.
"""
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest

import helpers
from forgetest.runner import Context, Failed, Run
from forgetest.suite import cooling


class FakeGrbl:
    """Answers '?' with an Idle report and every line with ok."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(2)
        os.environ["GRBL_HOST"] = "127.0.0.1"
        os.environ["GRBL_PORT"] = str(self.sock.getsockname()[1])
        self.commands = []
        self.on_command = None
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        self.sock.settimeout(0.2)
        while not self._stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                continue
            threading.Thread(target=self._client, args=(c,), daemon=True).start()

    def _client(self, c):
        c.settimeout(0.1)
        buf = b""
        c.sendall(b"\r\nGrbl 1.1f ['$' for help]\r\n")
        while not self._stop:
            try:
                d = c.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not d:
                break
            for ch in d:
                if ch == 0x3F:                      # '?'
                    c.sendall(b"<Idle|MPos:0.000,0.000,0.000|FS:0,0>\r\n")
                elif ch in (0x18, 0x85):
                    pass
                else:
                    buf += bytes([ch])
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.decode().strip()
                if line:
                    self.commands.append(line)
                    if self.on_command:
                        self.on_command(line)
                    c.sendall(b"ok\r\n")
        c.close()

    def close(self):
        self._stop = True
        self.sock.close()
        for k in ("GRBL_HOST", "GRBL_PORT"):
            os.environ.pop(k, None)


class FansQuietTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="forgetest-cool-")
        self.sysfs = os.path.join(self.tmp, "sysfs") + os.sep
        os.makedirs(self.sysfs + "thermal")
        os.environ["GF_SYSFS_ROOT"] = self.sysfs
        self.fc = helpers.FakeForgectrl().start()
        self.grbl = FakeGrbl()
        self.saved = (cooling.SAMPLE_S, cooling.IDLE_REF_TIMEOUT_S, cooling.COOLDOWN_TIMEOUT_S)
        cooling.SAMPLE_S = 0.1
        cooling.IDLE_REF_TIMEOUT_S = 3
        cooling.COOLDOWN_TIMEOUT_S = 4
        self.fc.state["cool"] = {"phase": "idle", "armed": False, "hold": False}
        self.duty(0, 0)
        self.fans(0, 736, 733)

    def tearDown(self):
        cooling.SAMPLE_S, cooling.IDLE_REF_TIMEOUT_S, cooling.COOLDOWN_TIMEOUT_S = self.saved
        self.grbl.close()
        self.fc.stop()
        os.environ.pop("GF_SYSFS_ROOT", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- the machine -------------------------------------------------------
    def duty(self, exhaust, intake):
        for attr, v in (("thermal/exhaust_pwm", exhaust), ("thermal/intake_pwm", intake)):
            with open(self.sysfs + attr, "w") as f:
                f.write(str(v))

    def fans(self, exhaust, i1, i2, air=2080):
        self.fc.state["status"] = dict(self.fc.state["status"],
                                       fans={"air_assist": air, "exhaust": exhaust, "intake_1": i1, "intake_2": i2})

    def run_engine(self):
        """M8 -> run profile; M9 -> smoke phase, then idle duty, then the
        tachs coast down (a few samples of spin-down), like forgectrl's
        engine on the bench."""
        def on_command(line):
            if line == "M8":
                self.duty(65535, 43278)
                self.fc.state["cool"]["phase"] = "run"
                self.fans(6753, 3212, 3328, air=10997)
            elif line == "M9":
                def cooldown():
                    self.fc.state["cool"]["phase"] = "smoke"
                    time.sleep(0.3)
                    self.fc.state["cool"]["phase"] = "idle"
                    self.duty(0, 0)
                    for ex, i1 in ((5030, 3319), (3100, 2200), (1200, 1300), (0, 740)):
                        self.fans(ex, i1, i1 + 5)
                        time.sleep(0.25)
                threading.Thread(target=cooldown, daemon=True).start()
        self.grbl.on_command = on_command

    def run_test(self):
        run = Run("test", "cooling.fans-quiet-after-motion", "t")
        ctx = Context(run, None, helpers.make_test("cooling.fans-quiet-after-motion", []))
        cooling.fans_quiet(ctx)
        return run

    # -- cases ------------------------------------------------------------------
    def test_idle_machine_passes_and_logs_every_sample(self):
        self.run_engine()
        run = self.run_test()
        self.assertEqual(run.evidence["before"]["exhaust"], 0)
        self.assertIsNotNone(run.evidence["settle_s"])
        self.assertEqual(run.evidence["duty_after"], cooling.IDLE_DUTY)
        self.assertIn("M8", self.grbl.commands)
        self.assertIn("M9", self.grbl.commands)
        cooldown_lines = [ln for ln in run.lines if "cooldown +" in ln]
        self.assertGreaterEqual(len(cooldown_lines), 2, run.lines)

    def test_a_spin_down_in_progress_is_not_taken_as_the_idle_reference(self):
        """The bench case: the previous test's fans are still coasting when
        this one starts. The reference waits for them to settle, and the
        run passes instead of waiting for the fans to come back up."""
        self.run_engine()
        self.fans(5030, 3319, 3377)                      # coasting, engine already idle, duty 0

        def coast():
            for ex, i1 in ((3900, 2600), (2500, 1700), (1100, 1000), (0, 736), (0, 736)):
                time.sleep(0.12)
                self.fans(ex, i1, i1 + 5)
        threading.Thread(target=coast, daemon=True).start()
        run = self.run_test()
        self.assertEqual(run.evidence["before"]["exhaust"], 0, run.evidence["before"])
        self.assertGreater(run.evidence["idle_ref_s"], 0.3)
        self.assertIsNotNone(run.evidence["settle_s"])
        self.assertTrue(any("idle ref:" in ln for ln in run.lines))

    def test_fans_left_running_fail_with_the_reference_in_the_message(self):
        def on_command(line):
            if line == "M8":
                self.duty(65535, 43278)
                self.fc.state["cool"]["phase"] = "run"
                self.fans(6753, 3212, 3328)
            # M9 ignored: the run profile stays on
        self.grbl.on_command = on_command
        run = Run("test", "cooling.fans-quiet-after-motion", "t")
        ctx = Context(run, None, helpers.make_test("cooling.fans-quiet-after-motion", []))
        with self.assertRaises(Failed) as cm:
            cooling.fans_quiet(ctx)
        self.assertIn("did not return to the idle profile", str(cm.exception))
        self.assertIn("idle reference", str(cm.exception))
        self.assertIn("65535", str(cm.exception))

    def test_a_reference_that_never_settles_fails_early_and_says_so(self):
        def churn():
            seq = (1000, 4000, 2500, 700, 3300, 1600, 4200)        # aperiodic against the sampler
            i = 0
            while not self.grbl._stop:
                v = seq[i % len(seq)]
                i += 1
                self.fans(v, v, v)
                time.sleep(0.03)
        threading.Thread(target=churn, daemon=True).start()
        run = Run("test", "cooling.fans-quiet-after-motion", "t")
        ctx = Context(run, None, helpers.make_test("cooling.fans-quiet-after-motion", []))
        with self.assertRaises(Failed) as cm:
            cooling.fans_quiet(ctx)
        self.assertIn("never settled to an idle reference", str(cm.exception))
        self.assertEqual(self.grbl.commands, [])         # nothing was jogged


if __name__ == "__main__":
    unittest.main()
