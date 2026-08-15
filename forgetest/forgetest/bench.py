"""The bench diagnostics page: registry of the bench tools and the
subprocess runner behind the #bench tab.

The registry lists every tool of scripts/bench (the README is the human
index; this is the machine one) with its safety class and argument spec.
A tool is runnable from the page once `ported` is set: the script is
installed under the tool directory (/usr/share/forgetest/bench on the
image, override FORGETEST_BENCH_DIR) and runs as a subprocess with the
form's arguments, output streamed to the page. Unported tools are listed
so the catalog of what exists is complete, with Start disabled.

Safety classes:
  dry       reads or dry motion, no emission, forgectrl stays up
  takeover  needs forgectrl stopped and the pulse device free
  live      laser emission possible (operator acknowledgment required)
  scope     needs bench instrumentation on top of the class before it

Bench runs are recorded in <data>/bench.jsonl and never enter a campaign.
"""
import json
import os
import shlex
import sys
import threading

from .log import data_dir, now_ts

DEFAULT_TOOL_DIR = "/usr/share/forgetest/bench"


def _arg(name, type="str", default=None, help="", choices=None):
    a = {"name": name, "type": type, "default": default, "help": help}
    if choices:
        a["choices"] = list(choices)
    return a


TOOLS = [
    # -- board-side, dry ------------------------------------------------------
    {"id": "check-pwm", "title": "Laser PWM register check", "script": "check_pwm.py",
     "safety": "dry", "where": "board", "ported": True, "args": [],
     "desc": "Reads PWM2 PWMCR/PWMPR via /dev/mem; expects divider 13 x ~127 counts = ~40 kHz. Read-only."},
    {"id": "pacing-test", "title": "Protocol-loop pacing check", "script": "pacing_test.py",
     "safety": "dry", "where": "board", "ported": True,
     "args": [_arg("mm", "float", 30.0, "jog distance (+X first)"), _arg("feed", "float", 600.0, "feed rate")],
     "desc": "Dry motion: idle/parked states coarse-paced, active motion tight-paced, hold/resume mid-move keeps position."},
    {"id": "bench-m2", "title": "Motion-quality bench", "script": "bench_m2.py",
     "safety": "dry", "where": "board", "ported": True, "args": [],
     "argv_fixed": ["127.0.0.1"],
     "desc": "Bounded round-trip jogs (sanity, max-rate, diagonal) + feed-hold/resume; reports peak feed, transitions, drift."},
    {"id": "bench-phase2", "title": "End-of-data protocol bench", "script": "bench_phase2.py",
     "safety": "takeover", "where": "board", "ported": True, "args": [],
     "desc": "Underrun detection/ack, parked no-replay guard, resume(0), continuous feed, run/underrun cycles. Motors locked, laser latched."},
    {"id": "cp-watchdog", "title": "HV charge-pump watchdog timing", "script": "cp_watchdog_timing.py",
     "safety": "dry", "where": "board", "ported": True,
     "args": [_arg("duration_s", "float", 14.0, "capture length")],
     "desc": "Latches CHG_PUMP feed pulses, polls the watchdog readbacks while commanding short local jogs. Motion only, laser locked."},
    {"id": "accel-fast", "title": "Head accelerometer sampler", "script": "accel_fast.py",
     "safety": "dry", "where": "board", "ported": True,
     "args": [_arg("duration_s", "float", 5.0, "capture length"),
              _arg("jog1", "str", None, "optional mid-capture jog, e.g. $J=G91X20F2400"),
              _arg("jog2", "str", None, "optional second jog")],
     "desc": "Direct-I2C sampler for the head-bus LIS2HH12s with optional mid-capture jogs. CSV to /tmp/accel.csv."},
    {"id": "bump-seek", "title": "Accelerometer bump-seek homing prototype", "script": "bump_seek.py",
     "safety": "dry", "where": "board", "ported": True,
     "args": [_arg("direction", "choice", "-", "X direction", ["-", "+"]),
              _arg("feed", "int", 120, "creep feed"), _arg("segment_mm", "float", 15.0, "jog segment"),
              _arg("max_mm", "float", 200.0, "travel bound")],
     "desc": "Creeps toward a rail in bounded jog segments, detects the contact jolt, jog-cancels and backs off."},
    # -- board-side, takeover / scope ------------------------------------------
    {"id": "pwm-sweep", "title": "LASER_PWM scope sweep", "script": "pwm_sweep.py",
     "safety": "scope", "where": "board", "ported": False,
     "args": [_arg("mode", "choice", "check", "check = read-only, sweep = duty staircase", ["check", "sweep"])],
     "desc": "check: readbacks + PWM2 dump; sweep: PWMSAR through 50/25/75/6/100 percent with 4 s holds. Locked state only."},
    {"id": "pwm-hold", "title": "LASER_PWM scope hold", "script": "pwm_hold.py",
     "safety": "scope", "where": "board", "ported": False,
     "args": [_arg("sar", "int", 64, "PWMSAR value"), _arg("seconds", "int", 10, "hold time")],
     "desc": "Holds one PWMSAR value for a scope window, then restores. Locked state only."},
    {"id": "fire-test", "title": "FIRE drop-timing test (A/B/U)", "script": "fire_test.py",
     "safety": "takeover", "where": "board", "ported": True,
     "args": [_arg("mode", "choice", "A", "A latch locked, B unlocked/unarmed, U true underrun", ["A", "B", "U"])],
     "desc": "Duty 0 throughout; refuses to unlock if HV reports good. Software witnesses + the PSU-connector LASER_ON scope point."},
    {"id": "pwm-stream", "title": "LASER_PWM stream-path test", "script": "pwm_stream_test.py",
     "safety": "takeover", "where": "board", "ported": False, "args": [],
     "desc": "Streams power bytes only (no steps, no FIRE, motor_lock=15, latch locked) through /dev/glowforge."},
    {"id": "gate-a-kernel", "title": "Kernel laser-safety drills K1/K2/K3", "script": "gate_a_kernel_drills.py",
     "safety": "takeover", "where": "board", "ported": True,
     "args": [_arg("drill", "choice", "K1", "K1 stop floor, K2 resume honors latch, K3 mid-ramp unlock", ["K1", "K2", "K3"])],
     "desc": "Software witnesses (cnc/state, laser_enable, laser_on, interlock bit 3); K3 refuses if HV reports good."},
    {"id": "platform-drills", "title": "Kernel platform drills", "script": "platform_drills.py",
     "safety": "takeover", "where": "board", "ported": True,
     "args": [_arg("drill", "choice", "decay", "deadman / rmmod / decay / led / all",
                   ["deadman", "rmmod", "decay", "led", "all"])],
     "desc": "Dead-man trip readback, rmmod/modprobe cycles under load, decay/microstep readback, LED sequence."},
    # -- cooling ------------------------------------------------------------------
    {"id": "flow-confirm", "title": "Coolant flow suspicion/confirmation drill", "script": "flow_confirm_drill.py",
     "safety": "dry", "where": "board", "ported": True, "args": [],
     "desc": "One M8 session walks the verdict state machine through real pump-off transients; PASS/FAIL per transition."},
    {"id": "flow-escalate", "title": "Coolant starved re-check escalation drill", "script": "flow_escalate_drill.py",
     "safety": "dry", "where": "board", "ported": False, "args": [],
     "desc": "With the pump off the job-start check reads SUSPECT and the driver must escalate to FAULT."},
    {"id": "flow-characterize", "title": "Coolant flow characterization", "script": "flow_characterize.py",
     "safety": "dry", "where": "host", "ported": False,
     "args": [_arg("duty", "int", 30, "heater duty percent")],
     "desc": "Baseline -> flow -> no-flow -> recovery with the factory temperature curve; aborts past 45 C downstream."},
    {"id": "flow-sustained", "title": "Coolant sustained re-check run", "script": "flow_sustained.py",
     "safety": "dry", "where": "host", "ported": False, "args": [],
     "desc": "Long run of the real re-check cadence via M8: verdicts, false faults, loop heat accumulation."},
    {"id": "flow-warm", "title": "Coolant warm-baseline validation", "script": "flow_warm_validate.py",
     "safety": "dry", "where": "host", "ported": False, "args": [],
     "desc": "Runs the real check from a heater-warmed baseline."},
    {"id": "flow-recheck", "title": "Coolant re-check characterization", "script": "flow_recheck_char.py",
     "safety": "dry", "where": "host", "ported": False, "args": [],
     "desc": "Short in-run re-checks and the differential metric."},
    {"id": "flow-sampler", "title": "Coolant sampler", "script": "flow_sampler.py",
     "safety": "dry", "where": "board", "ported": True,
     "args": [_arg("duration_s", "int", 30, "capture length"), _arg("interval_s", "float", 1.0, "sample interval")],
     "desc": "Prints elapsed,raw_down,raw_up at the interval; the sampler behind the flow tools."},
    {"id": "temp-calibrate", "title": "Coolant temperature spot-check", "script": "temp_calibrate.py",
     "safety": "dry", "where": "host", "ported": False,
     "args": [_arg("mode", "choice", "watch", "watch / point / fit", ["watch", "point", "fit"]),
              _arg("measured_c", "float", None, "thermometer reading for point")],
     "desc": "Pairs a measured temperature with averaged raw readings; fits a per-machine line."},
    {"id": "fan-test", "title": "Fan/coolant bench", "script": "fan_test.py",
     "safety": "dry", "where": "host", "ported": False, "args": [],
     "desc": "Snapshots fan PWMs/tachs/temps, drives M8 -> cut fans, M9 -> cooldown -> idle. Host-side; port pending."},
    # -- laser (live) --------------------------------------------------------------
    {"id": "live-fire", "title": "LIVE laser drills", "script": "live_fire_drills.py",
     "safety": "live", "where": "board", "ported": False,
     "args": [_arg("drill", "choice", "witness", "witness / hold / faultpos", ["witness", "hold", "faultpos"])],
     "argv_fixed_after": ["127.0.0.1"],
     "desc": "Emission witness, disarm grace in Hold, stale-origin refusal. The operator's arm press is required for every drill."},
    # -- host-side harnesses (CI) ------------------------------------------------------
    {"id": "laser-stream-test", "title": "Laser pulse-stream emission harness", "script": "laser_stream_test.py",
     "safety": "dry", "where": "host", "ported": False, "args": [],
     "desc": "Null-sink controller stream capture against the feeder contract. Runs in the grblHAL repo's CI."},
    {"id": "laser-lifecycle-test", "title": "Armed-window lifecycle harness", "script": "laser_lifecycle_test.py",
     "safety": "dry", "where": "host", "ported": False, "args": [],
     "desc": "Arm/disarm lifecycle on the null-sink controller. Runs in the grblHAL repo's CI."},
    {"id": "puls-profile", "title": "Factory .puls profile decoder", "script": "puls_profile.py",
     "safety": "dry", "where": "host", "ported": False, "args": [],
     "desc": "Decodes factory pulse streams into velocity/accel profiles. Runs anywhere; needs a .puls file."},
]


class Bench:
    def __init__(self, tools=None, tool_dir=None, index_path=None):
        self.tools = list(tools if tools is not None else TOOLS)
        self._by_id = {t["id"]: t for t in self.tools}
        self._tool_dir = tool_dir
        self.index_path = index_path or os.path.join(data_dir(), "bench.jsonl")
        self._lock = threading.Lock()

    def tool_dir(self):
        return self._tool_dir or os.environ.get("FORGETEST_BENCH_DIR") or DEFAULT_TOOL_DIR

    def get(self, tool_id):
        return self._by_id.get(tool_id)

    def command(self, tool, args):
        """argv for a tool with the form's arguments. Returns
        (ok, argv, error)."""
        script = os.path.join(self.tool_dir(), tool["script"])
        if not os.path.exists(script):
            return False, None, "script not installed: %s" % tool["script"]
        argv = [sys.executable, script] + list(tool.get("argv_fixed", []))
        for spec in tool.get("args", []):
            raw = args.get(spec["name"], spec.get("default"))
            if raw is None or raw == "":
                if spec.get("default") is None:
                    continue  # optional and absent
                raw = spec["default"]
            try:
                if spec["type"] == "int":
                    val = str(int(raw))
                elif spec["type"] == "float":
                    val = repr(float(raw))
                elif spec["type"] == "choice":
                    if str(raw) not in spec["choices"]:
                        return False, None, "%s must be one of %s" % (spec["name"], spec["choices"])
                    val = str(raw)
                else:
                    val = str(raw)
                    if any(ch in val for ch in "\0\n\r"):
                        return False, None, "%s: invalid characters" % spec["name"]
            except (TypeError, ValueError):
                return False, None, "%s: invalid %s" % (spec["name"], spec["type"])
            argv.append(val)
        argv += list(tool.get("argv_fixed_after", []))
        return True, argv, None

    def record(self, tool, args, run):
        rec = {"ts": run.started_ts, "tool": tool["id"], "args": args, "result": run.finished,
               "log_tail": run.lines[-50:]}
        with self._lock:
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            with open(self.index_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")

    def last_runs(self):
        out = {}
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    out[rec.get("tool")] = {"ts": rec.get("ts"), "result": rec.get("result"),
                                            "args": rec.get("args")}
        except OSError:
            pass
        return out

    def listing(self):
        last = self.last_runs()
        items = []
        for t in self.tools:
            item = {k: t[k] for k in ("id", "title", "script", "safety", "where", "ported", "args", "desc")}
            item["installed"] = os.path.exists(os.path.join(self.tool_dir(), t["script"]))
            item["last"] = last.get(t["id"])
            items.append(item)
        return items

    def describe_command(self, tool, args):
        ok, argv, err = self.command(tool, args)
        return " ".join(shlex.quote(a) for a in argv) if ok else err
