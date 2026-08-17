"""The baseline: fixed resting values are restored, preserved values are
handed back, every deviation is a recorded leftover. Runs against a fake
sysfs tree; forgectrl is unreachable (service-side checks skip)."""
import json
import os
import shutil
import struct
import tempfile
import unittest

from forgetest import baseline


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="forgetest-bl-")
        self.sysfs = os.path.join(self.tmp, "sysfs") + os.sep
        self.leds = os.path.join(self.tmp, "leds") + os.sep
        for group in ("cnc", "pic", "head", "thermal"):
            os.makedirs(self.sysfs + group)
        for name in baseline.BUTTON_LEDS + ("lid_led",):
            os.makedirs(self.leds + name)
            self._led(name, "0")
        # a clean machine
        for attr, val in baseline.FIXED_SYSFS + baseline.IDLE_READBACKS:
            self._attr(attr, val)
        self._attr("cnc/interlock_circuit", "45")
        self._attr("pic/lid_led", "0")
        self._pos(0, 0, 0)
        os.environ["GF_SYSFS_ROOT"] = self.sysfs
        os.environ["GF_LEDS_ROOT"] = self.leds
        os.environ["FORGECTRL_URL"] = "http://127.0.0.1:1"      # nothing listens
        baseline.Baseline._unreachable_until = 0.0
        self.lines = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k in ("GF_SYSFS_ROOT", "GF_LEDS_ROOT", "FORGECTRL_URL"):
            os.environ.pop(k, None)

    def _attr(self, attr, val):
        with open(self.sysfs + attr, "w") as f:
            f.write(str(val))

    def _read(self, attr):
        with open(self.sysfs + attr) as f:
            return f.read().strip()

    def _led(self, name, val):
        with open(self.leds + name + "/brightness", "w") as f:
            f.write(val)
        # the class interface writes 'target'; the fake mirrors it into brightness
        # only when the test asks (see _sync_leds)

    def _sync_leds(self):
        for name in baseline.BUTTON_LEDS:
            p = self.leds + name + "/target"
            if os.path.exists(p):
                with open(p) as f:
                    v = f.read().strip()
                with open(self.leds + name + "/brightness", "w") as f:
                    f.write(v)

    def _pos(self, x, y, z):
        with open(self.sysfs + "cnc/position", "wb") as f:
            f.write(struct.pack("<5i", x, y, z, 0, 0))

    def bl(self):
        return baseline.Baseline(self.lines.append)

    def test_clean_machine_has_no_leftovers(self):
        left = self.bl().enforce("pre", captured=None)
        self.assertEqual(left, [])
        self.assertTrue(any("pre: clean" in l for l in self.lines))

    def test_fixed_values_are_restored_and_recorded(self):
        self._attr("cnc/motor_lock", "15")
        self._attr("cnc/step_freq", "10000")
        self._attr("cnc/streaming", "1")
        left = self.bl().enforce("post", captured=None)
        items = {x.item: x for x in left}
        self.assertEqual(set(items), {"cnc/motor_lock", "cnc/step_freq", "cnc/streaming"})
        for x in left:
            self.assertEqual(x.action, "restored", str(x))
        self.assertEqual(self._read("cnc/motor_lock"), "8")
        self.assertEqual(self._read("cnc/step_freq"), "28160")
        self.assertEqual(self._read("cnc/streaming"), "0")
        self.assertEqual(items["cnc/motor_lock"].found, "15")
        self.assertEqual(items["cnc/motor_lock"].expected, "8")

    def test_unlocked_latch_is_relocked(self):
        self._attr("cnc/interlock_circuit", "5")        # bit 3 clear = unlocked
        left = self.bl().enforce("post", captured=None)
        self.assertEqual([x.item for x in left], ["laser_latch"])
        self.assertEqual(self._read("cnc/laser_latch"), "1")

    def test_readonly_deviation_is_unrestorable(self):
        self._attr("cnc/state", "disabled")
        left = self.bl().enforce("post", captured=None)
        self.assertEqual([(x.item, x.action) for x in left], [("cnc/state", "unrestorable")])

    def test_button_leds_are_turned_off(self):
        self._led("button_led_2", "255")
        left = self.bl().enforce("post", captured=None)
        self.assertEqual([x.item for x in left], ["leds/button_led_2"])
        self._sync_leds()
        self.assertEqual(baseline.read_led("button_led_2"), "0")

    def test_preserved_position(self):
        b = self.bl()
        cap = b.capture()
        self.assertEqual(cap["position"], [0, 0, 0])
        # the run shifted the counters
        self._pos(1000, 0, 0)
        left = b.enforce("post", captured=cap)
        items = {x.item: x for x in left}
        self.assertEqual(set(items), {"position"})
        # no GRBL controller on the host: the head cannot be jogged back
        self.assertTrue(items["position"].action.startswith("unrestorable"), items["position"].action)
        self.assertEqual(items["position"].found, [1000, 0, 0])

    def test_lamp_needs_forgectrl(self):
        # the lamp's idle level comes from forgectrl's settings: without the
        # daemon there is nothing to compare against
        self._attr("pic/lid_led", "77")
        left = self.bl().enforce("pre", captured=None)
        self.assertEqual(left, [])
        self.assertEqual(self._read("pic/lid_led"), "77")

    def test_no_sysfs_means_skip(self):
        os.environ["GF_SYSFS_ROOT"] = os.path.join(self.tmp, "nope") + os.sep
        left = self.bl().enforce("pre", captured=None)
        self.assertEqual(left, [])
        self.assertTrue(any("kernel sysfs not present" in l for l in self.lines))

    def test_boot_reference_needs_a_recent_boot(self):
        os.environ["FORGETEST_BOOT_ID"] = "test-boot"
        try:
            # no reference file, uptime unknown on a host without /proc/uptime,
            # or too old: None, with the reason logged
            ref = baseline.boot_reference(self.lines.append, self.tmp)
            up = baseline.uptime_s()
            if up is None or up > baseline.BOOT_MAX_AGE_S:
                self.assertIsNone(ref)
                self.assertTrue(any("no fresh-boot reference" in l for l in self.lines))
            else:
                # a young host: the reference is taken from the fake tree
                self.assertIsNotNone(ref)
                self.assertEqual(ref["sysfs"]["cnc/motor_lock"], "8")
                self.assertTrue(os.path.exists(os.path.join(self.tmp, "boot-test-boot.json")))
                # and loaded back the second time
                self.lines[:] = []
                ref2 = baseline.boot_reference(self.lines.append, self.tmp)
                self.assertEqual(ref2["ts"], ref["ts"])
                self.assertTrue(any("reference loaded" in l for l in self.lines))
        finally:
            os.environ.pop("FORGETEST_BOOT_ID", None)

    def test_fixed_constants_checked_against_a_dump(self):
        ref = {"sysfs": {"cnc/motor_lock": "8", "cnc/step_freq": "10000"}}
        diffs = baseline.check_fixed_against(ref, self.lines.append)
        self.assertEqual(diffs, ["cnc/step_freq: boot=10000 constant=28160"])


    # -- the reference is taken after the controller applied its config -----

    def _probe_state(self):
        # what the kernel shows between the supervisor's motion probe and
        # the GRBL controller's init writes
        self._attr("cnc/motor_lock", "0")
        self._attr("cnc/step_freq", "10000")
        self._attr("cnc/y_mode", "1")

    def test_wait_configured_returns_once_the_controller_wrote_its_config(self):
        self._probe_state()
        calls = {"n": 0}

        def sleep(_s):
            calls["n"] += 1
            if calls["n"] == 3:             # the controller's init writes land
                for attr, val in baseline.CONFIGURED_MARKERS:
                    self._attr(attr, val)
        ok = baseline.wait_controller_configured(
            self.lines.append, {"controller": "running", "mode": "grbl", "motion": "verified"},
            timeout=5, sleep=sleep)
        self.assertTrue(ok)
        self.assertTrue(any("controller configured" in l for l in self.lines))
        self.assertGreaterEqual(calls["n"], 4)      # 3 polls + the settle

    def test_wait_configured_times_out_and_says_so(self):
        self._probe_state()
        t = {"now": 0.0}
        real_time = baseline.time.time
        baseline.time.time = lambda: t["now"]
        try:
            def sleep(s):
                t["now"] += s
            ok = baseline.wait_controller_configured(
                self.lines.append, {"controller": "running", "mode": "grbl"}, timeout=2, sleep=sleep)
        finally:
            baseline.time.time = real_time
        self.assertFalse(ok)
        self.assertTrue(any("did not apply its config" in l for l in self.lines))

    def test_wait_configured_is_a_noop_outside_grbl_mode(self):
        self._probe_state()
        ok = baseline.wait_controller_configured(
            self.lines.append, {"controller": "running", "mode": "cloud"}, timeout=1,
            sleep=lambda s: self.fail("slept in cloud mode"))
        self.assertTrue(ok)
        ok = baseline.wait_controller_configured(
            self.lines.append, {"controller": "stopped", "mode": "grbl"}, timeout=1,
            sleep=lambda s: self.fail("slept with the controller stopped"))
        self.assertTrue(ok)

    def test_preconfig_reference_is_recognized(self):
        self.assertTrue(baseline.reference_preconfig(
            {"sysfs": {"cnc/motor_lock": "0", "cnc/step_freq": "10000", "cnc/y_mode": "1"}}))
        self.assertFalse(baseline.reference_preconfig(
            {"sysfs": {"cnc/motor_lock": "8", "cnc/step_freq": "28160", "cnc/y_mode": "8"}}))
        # a genuinely different single constant is a machine fact, not pre-config
        self.assertFalse(baseline.reference_preconfig(
            {"sysfs": {"cnc/motor_lock": "8", "cnc/step_freq": "10000", "cnc/y_mode": "8"}}))
        self.assertFalse(baseline.reference_preconfig({"sysfs": {}}))

    def test_stale_preconfig_reference_is_retaken_on_a_fresh_boot(self):
        os.environ["FORGETEST_BOOT_ID"] = "test-boot-2"
        try:
            path = os.path.join(self.tmp, "boot-test-boot-2.json")
            with open(path, "w") as f:
                json.dump({"ts": "old", "sysfs": {"cnc/motor_lock": "0", "cnc/step_freq": "10000",
                                                     "cnc/y_mode": "1"}}, f)
            ref = baseline.boot_reference(self.lines.append, self.tmp)
            up = baseline.uptime_s()
            if up is None or up > baseline.BOOT_MAX_AGE_S:
                # too old to retake: the stale reference stands, marked
                self.assertTrue(any("predates the controller's config" in l for l in self.lines))
                self.assertEqual(ref["ts"], "old")
            else:
                self.assertTrue(any("retaking" in l for l in self.lines))
                self.assertEqual(ref["sysfs"]["cnc/motor_lock"], "8")
        finally:
            os.environ.pop("FORGETEST_BOOT_ID", None)


if __name__ == "__main__":
    unittest.main()
