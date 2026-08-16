"""The runner: executes one acceptance test or one bench tool at a time.

Acceptance tests run in a worker thread with a Context: log lines, an
operator prompt channel (the page shows the question, the answer comes
back through the API), an abort flag, an evidence dict, hardware helpers,
and the takeover wrapper for tests that need forgectrl out of the way.
Results are appended to the log with the fingerprint the test ran under;
the campaign rules (campaign.py) do the rest.

Bench tools are subprocesses (bench.py registry): same single slot, same
log pane, no campaign effect.

Safety, in code rather than convention: a live test starts only with the
operator's acknowledgment in the request; the runner never touches the
laser latch; a takeover always ends with forgectrl started again, and a
marker file makes a crash mid-takeover recoverable at the next start.
"""
import os
import random
import subprocess
import threading
import time
import traceback

from . import artifact as _artifact
from . import baseline as _baseline
from . import campaign as _campaign
from . import catalog as _catalog
from . import hw
from .log import now_ts, data_dir

MAX_LINES = 4000


class Aborted(Exception):
    pass


class Failed(Exception):
    pass


class Run:
    def __init__(self, kind, id, title):
        self.kind = kind          # 'test' | 'bench'
        self.id = id
        self.title = title
        self.started = time.time()
        self.started_ts = now_ts()
        self.lines = []
        self.dropped = 0
        self.prompt = None        # {"id","question","options"}
        self.answers = []
        self.evidence = {}
        self.aborted = threading.Event()
        self.finished = None      # {"result","message","duration_s"}
        self.proc = None
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._answer = None
        self._prompt_seq = 0

    def log(self, msg):
        line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
        with self._lock:
            if len(self.lines) >= MAX_LINES:
                self.lines.pop(0)
                self.dropped += 1
            self.lines.append(line)

    def snapshot(self, tail=200):
        with self._lock:
            lines = self.lines[-tail:]
            prompt = dict(self.prompt) if self.prompt else None
        return {
            "kind": self.kind, "id": self.id, "title": self.title,
            "started": self.started_ts, "elapsed_s": int(time.time() - self.started),
            "log": lines, "dropped": self.dropped, "prompt": prompt,
            "finished": self.finished, "aborting": self.aborted.is_set(),
        }

    # -- prompt channel -----------------------------------------------
    def ask(self, question, options):
        with self._cv:
            self._prompt_seq += 1
            pid = "p%d" % self._prompt_seq
            self.prompt = {"id": pid, "question": question, "options": list(options)}
            self._answer = None
            while self._answer is None and not self.aborted.is_set():
                self._cv.wait(0.5)
            self.prompt = None
            if self.aborted.is_set() and self._answer is None:
                raise Aborted("aborted at prompt")
            ans = self._answer
            self._answer = None
        self.answers.append({"ts": now_ts(), "question": question, "answer": ans})
        return ans

    def answer(self, prompt_id, value):
        with self._cv:
            if not self.prompt or self.prompt["id"] != prompt_id:
                return False
            if value not in self.prompt["options"]:
                return False
            self._answer = value
            self._cv.notify_all()
            return True

    def abort(self):
        self.aborted.set()
        with self._cv:
            self._cv.notify_all()
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass


class Context:
    """What a test function gets."""

    def __init__(self, run, runner, test):
        self.run = run
        self.runner = runner
        self.test = test
        self.evidence = run.evidence
        self._forgectrl = None

    # -- reporting -----------------------------------------------------
    def log(self, msg, *args):
        self.run.log(msg % args if args else msg)

    def check(self, cond, msg, *args):
        if not cond:
            raise Failed(msg % args if args else msg)

    def fail(self, msg, *args):
        raise Failed(msg % args if args else msg)

    def aborted(self):
        return self.run.aborted.is_set()

    def checkpoint(self):
        if self.aborted():
            raise Aborted("aborted")

    def sleep(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.checkpoint()
            time.sleep(min(0.25, max(0.0, deadline - time.time())))

    # -- operator ------------------------------------------------------
    def prompt(self, question, options=("Yes", "No")):
        self.log("PROMPT: %s", question)
        ans = self.run.ask(question, options)
        self.log("ANSWER: %s", ans)
        return ans

    def confirm(self, question):
        """Yes/No question; a No is a test failure."""
        ans = self.prompt(question, ("Yes", "No"))
        if ans != "Yes":
            raise Failed("operator answered No: %s" % question)
        return True

    def instruct(self, text):
        """A step for the operator; continues on Done, fails on Cannot."""
        ans = self.prompt(text, ("Done", "Cannot"))
        if ans != "Done":
            raise Failed("operator could not: %s" % text)

    # -- hardware ------------------------------------------------------
    @property
    def forgectrl(self):
        if self._forgectrl is None:
            self._forgectrl = hw.Forgectrl()
        return self._forgectrl

    def sysfs(self, attr, default=None):
        return hw.sysfs_read(attr, default)

    def sysfs_int(self, attr, default=None):
        return hw.sysfs_int(attr, default)

    def grbl(self):
        return hw.Grbl()

    def takeover(self):
        return Takeover(self.run.log, self.test.id)


class Takeover:
    """Hardware takeover: the controller is stopped through the supervisor,
    forgectrl is stopped, the marker records the ownership, and forgectrl
    is started again on every exit path. Used by takeover tests (through
    Context.takeover()) and by takeover bench tools."""

    # Controller-owned kernel attributes a takeover drill may change:
    # captured on enter, written back on exit before forgectrl starts, so
    # the supervisor's liveness probe runs on the machine it expects (a
    # leftover motor_lock=15 masks the probe's steps: no motion by
    # construction, a false driver-wedge verdict, the rail-off ladder).
    PRESERVE = ("cnc/motor_lock", "cnc/step_freq", "cnc/ramp_rate", "cnc/streaming",
                "cnc/x_mode", "cnc/y_mode", "cnc/x_decay", "cnc/y_decay",
                "pic/x_step_current", "pic/y_step_current")

    def __init__(self, log, who):
        self.log = log            # callable(str)
        self.who = who
        self.marker = marker_path()
        self.saved = {}

    def wait_settled(self):
        return _baseline.Baseline(self.log).wait_settled()

    def restore_attrs(self):
        """Write the captured kernel attributes back and relock the latch."""
        for attr, val in self.saved.items():
            try:
                hw.sysfs_write(attr, val)
            except OSError as e:
                self.log("takeover: WARNING could not restore %s=%s: %s" % (attr, val, e))
        try:
            hw.sysfs_write("cnc/laser_latch", "1")
        except OSError as e:
            self.log("takeover: WARNING could not relock the latch: %s" % e)

    def __enter__(self):
        log = self.log
        log("takeover: waiting for forgectrl to be settled")
        self.wait_settled()
        for attr in self.PRESERVE:
            v = hw.sysfs_read(attr)
            if v is not None:
                self.saved[attr] = v
        if self.saved:
            log("takeover: preserving %s" % ", ".join("%s=%s" % kv for kv in self.saved.items()))
        log("takeover: stopping the controller through forgectrl")
        try:
            st, body = hw.Forgectrl().post("/controller/stop")
            log("takeover: POST /controller/stop -> %s" % st)
        except hw.HwError as e:
            log("takeover: forgectrl unreachable (%s)" % e)
        with open(self.marker, "w") as f:
            f.write("%s %s\n" % (now_ts(), self.who))
        rc, out = hw.initd("forgectrl", "stop")
        log("takeover: forgectrl stop -> rc %s" % rc)
        deadline = time.time() + 15
        while time.time() < deadline and (hw.pidof("forgectrl") or hw.pidof("grblHAL_glowfor")):
            time.sleep(0.5)
        left = hw.pidof("forgectrl") + hw.pidof("grblHAL_glowfor")
        if left:
            self.__exit__(None, None, None)
            raise Failed("takeover: processes still alive after stop: %s" % left)
        log("takeover: pulse device free")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.restore_attrs()
        rc, out = hw.initd("forgectrl", "start")
        self.log("takeover: forgectrl start -> rc %s" % rc)
        try:
            os.remove(self.marker)
        except OSError:
            pass
        # leave the machine settled for whatever runs next: the probe
        # move done, the controller back (or the ladder's verdict logged)
        self.wait_settled()
        return False


def marker_path():
    return os.environ.get("FORGETEST_MARKER") or "/run/forgetest.active"


class Runner:
    def __init__(self, log, manifest, registry, bench=None):
        self.log = log
        self.manifest = manifest
        self.registry = registry
        self.bench = bench
        self.catalog_hash = _catalog.catalog_hash(registry)
        self._lock = threading.Lock()
        self.current = None
        self.last = None
        self.messages = []
        self.boot_ref = None
        self.recover()
        threading.Thread(target=self._take_boot_reference, daemon=True,
                         name="forgetest-bootref").start()

    def _take_boot_reference(self):
        try:
            self.boot_ref = _baseline.boot_reference(self._note, data_dir())
        except Exception as e:  # noqa: BLE001
            self._note("baseline: boot reference failed: %s: %s" % (type(e).__name__, e))

    def _note(self, msg):
        """A runner-level line: kept in messages for the page (bounded)."""
        with self._lock:
            self.messages.append(msg)
            del self.messages[:-50]

    # -- startup recovery ------------------------------------------------
    def recover(self):
        m = marker_path()
        if os.path.exists(m):
            try:
                with open(m) as f:
                    who = f.read().strip()
            except OSError:
                who = "?"
            self.messages.append("recovered a takeover left by '%s': starting forgectrl" % who)
            hw.initd("forgectrl", "start")
            try:
                os.remove(m)
            except OSError:
                pass

    # -- state -----------------------------------------------------------
    def tests(self):
        return _catalog.all_tests(self.registry)

    def running_id(self):
        r = self.current
        return r.id if r and r.kind == "test" and not r.finished else None

    def state(self):
        records = self.log.read()
        st = _campaign.compute(records, self.tests(), self.manifest, self.catalog_hash,
                               running=self.running_id())
        st["catalog_hash"] = self.catalog_hash
        st["manifest"] = {"sha": self.manifest.content_sha, "identity": self.manifest.identity_sha(),
                          "image": self.manifest.image_name, "version": self.manifest.version}
        st["log_corrupt"] = self.log.corrupt
        st["messages"] = list(self.messages)
        r = self.current
        st["running"] = r.snapshot() if r and not r.finished else None
        last = r if (r and r.finished) else self.last
        st["last_run"] = last.snapshot() if last else None
        return st, records

    def busy(self):
        r = self.current
        return bool(r and not r.finished)

    # -- campaign actions -------------------------------------------------
    def _open_campaign_if_needed(self, state):
        if state["campaign"]:
            return state["campaign"]
        cid = "c-%s-%04x" % (time.strftime("%Y%m%d%H%M%S", time.gmtime()), random.randrange(1 << 16))
        rec = self.log.append({"t": "campaign", "id": cid, "manifest_sha": self.manifest.content_sha,
                               "catalog_hash": self.catalog_hash, "image": self.manifest.version})
        return rec

    def invalidate(self, reason):
        reason = (reason or "").strip()
        if not reason:
            return False, "a reason is required"
        if self.busy():
            return False, "a run is in progress"
        self.log.append({"t": "invalidate", "reason": reason})
        return True, "all results invalidated; a full campaign is required"

    def reset(self, reason=""):
        if self.busy():
            return False, "a run is in progress"
        self.log.append({"t": "reset", "reason": (reason or "").strip()})
        return True, "campaign reset"

    def export(self):
        state, records = self.state()
        art = _artifact.build(state, self.tests(), self.manifest, records, self.catalog_hash)
        self.log.append({"t": "export", "artifact_sha256": art["sha256"], "authorized": art["authorized"],
                         "campaign": (state["campaign"] or {}).get("id")})
        return art

    # -- starting -----------------------------------------------------------
    def start_test(self, test_id, ack_live=False):
        t = _catalog.get(test_id, self.registry)
        if t is None:
            return False, "unknown test"
        with self._lock:
            if self.busy():
                return False, "a run is in progress"
            state, _ = self.state()
            ts = state["tests"][t.id]
            if not ts["requires_met"]:
                return False, "prerequisites not satisfied: %s" % ", ".join(ts["missing_requires"])
            if t.kind == "live" and not ack_live:
                return False, "live test: acknowledge eye protection, fire watch, and exhaust first"
            campaign = self._open_campaign_if_needed(state)
            run = Run("test", t.id, t.title)
            self.last = self.current
            self.current = run
        run.log("start %s (%s, %s) in campaign %s" % (t.id, t.kind, t.hardware, campaign["id"]))
        if t.kind == "live":
            run.evidence["operator"] = {"ack_live": True, "ts": now_ts()}
        th = threading.Thread(target=self._exec_test, args=(t, run, campaign), daemon=True,
                              name="forgetest-run")
        th.start()
        return True, "started"

    # -- baseline around every run -----------------------------------------
    def _baseline_pre(self, run):
        """Bring the machine to the fresh-boot idle state before a run and
        record what the previous run left behind. Returns the captured
        preserved state for the post pass."""
        bl = _baseline.Baseline(run.log, abort=run.aborted.is_set)
        ref = self.boot_ref
        session = {"sysfs": {a: (ref.get("sysfs") or {}).get(a) for a in _baseline.PRESERVED_SYSFS}} if ref else None
        left = bl.enforce("pre", captured=session)
        if left:
            who = self.last.id if self.last is not None else "an earlier run"
            self.messages.append("leftovers before %s (left by %s): %s"
                                 % (run.id, who, "; ".join(str(x) for x in left)))
        run.evidence["baseline"] = {"pre": [x.as_dict() for x in left]}
        return bl.capture()

    def _baseline_post(self, run, captured):
        bl = _baseline.Baseline(run.log)
        left = bl.enforce("post", captured=captured)
        run.evidence.setdefault("baseline", {})["post"] = [x.as_dict() for x in left]
        if left:
            self.messages.append("leftovers after %s: %s" % (run.id, "; ".join(str(x) for x in left)))
        return left

    def _exec_test(self, t, run, campaign):
        ctx = Context(run, self, t)
        fp = t.fingerprint(self.manifest)
        result, message = _campaign.PASS, ""
        captured = None
        try:
            captured = self._baseline_pre(run)
            t.fn(ctx)
            if run.aborted.is_set():
                result, message = _campaign.ABORTED, "aborted"
        except Aborted as e:
            result, message = _campaign.ABORTED, str(e) or "aborted"
        except Failed as e:
            result, message = _campaign.FAIL, str(e)
        except Exception as e:  # noqa: BLE001 - an erroring test is a failed test
            result, message = _campaign.ERROR, "%s: %s" % (type(e).__name__, e)
            run.log(traceback.format_exc().rstrip())
        try:
            self._baseline_post(run, captured)
        except Exception as e:  # noqa: BLE001 - never lose the result over the cleanup
            run.log("baseline: post pass errored: %s: %s" % (type(e).__name__, e))
        duration = int(time.time() - run.started)
        run.log("result %s%s" % (result, (": " + message) if message else ""))
        rec = {"t": "result", "campaign": campaign["id"], "test": t.id, "result": result,
               "fingerprint": fp, "manifest_sha": self.manifest.content_sha,
               "image": self.manifest.version, "duration_s": duration, "message": message,
               "evidence": run.evidence, "answers": run.answers, "log": list(run.lines)}
        self.log.append(rec)
        run.finished = {"result": result, "message": message, "duration_s": duration}

    # -- bench tools ---------------------------------------------------------
    def start_bench(self, tool_id, args=None, ack_live=False):
        if self.bench is None:
            return False, "no bench registry"
        tool = self.bench.get(tool_id)
        if tool is None:
            return False, "unknown tool"
        if not tool.get("ported"):
            return False, "tool not yet ported to the bench page"
        ok, argv, err = self.bench.command(tool, args or {})
        if not ok:
            return False, err
        if tool.get("safety") == "live" and not ack_live:
            return False, "live tool: acknowledge eye protection, fire watch, and exhaust first"
        with self._lock:
            if self.busy():
                return False, "a run is in progress"
            run = Run("bench", tool["id"], tool["title"])
            self.last = self.current
            self.current = run
        run.log("bench %s: %s" % (tool["id"], " ".join(argv)))
        th = threading.Thread(target=self._exec_bench, args=(tool, run, argv, args or {}),
                              daemon=True, name="forgetest-bench")
        th.start()
        return True, "started"

    def _exec_bench(self, tool, run, argv, args):
        rc = None
        message = ""
        captured = None
        try:
            captured = self._baseline_pre(run)
            env = dict(os.environ)
            env.setdefault("PYTHONUNBUFFERED", "1")
            takeover = Takeover(run.log, "bench:" + tool["id"]) if tool.get("safety") == "takeover" else None
            if takeover is not None:
                takeover.__enter__()
            try:
                run.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            env=env, cwd=self.bench.tool_dir())
                for raw in iter(run.proc.stdout.readline, b""):
                    run.log(raw.decode("utf-8", "replace").rstrip())
                run.proc.stdout.close()
                rc = run.proc.wait()
            finally:
                if takeover is not None:
                    takeover.__exit__(None, None, None)
            if run.aborted.is_set():
                message = "aborted"
        except Exception as e:  # noqa: BLE001
            message = "%s: %s" % (type(e).__name__, e)
            run.log(message)
        try:
            self._baseline_post(run, captured)
        except Exception as e:  # noqa: BLE001
            run.log("baseline: post pass errored: %s: %s" % (type(e).__name__, e))
        duration = int(time.time() - run.started)
        result = "ABORTED" if run.aborted.is_set() else ("OK" if rc == 0 else "EXIT %s" % rc)
        run.log("bench %s finished: %s" % (tool["id"], result))
        run.finished = {"result": result, "message": message, "duration_s": duration, "rc": rc}
        self.bench.record(tool, args, run)

    # -- control --------------------------------------------------------------
    def answer(self, prompt_id, value):
        r = self.current
        if not r or r.finished:
            return False, "nothing is running"
        if r.answer(prompt_id, value):
            return True, "answered"
        return False, "no such prompt (or the answer is not one of the options)"

    def abort(self):
        r = self.current
        if not r or r.finished:
            return False, "nothing is running"
        r.abort()
        return True, "abort requested"
