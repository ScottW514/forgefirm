#!/usr/bin/env python3
"""Host-side verification of the operator-armed window lifecycle.

Runs the native grblHAL_glowforge binary in null-sink mode (no
hardware, no root; arming is automatic without the physical button)
and drives jobs over TCP, asserting the window's state machine on the
reported messages:

  1. the first laser-on of a job arms exactly once, and the window
     persists across M5/M3 toggles within the job (no re-prompt)
  2. program end (M2) closes the window: the disarm lands promptly,
     and the next job arms afresh
  3. a sender change closes the window: a reconnected client must
     re-arm - the displaced session's consent does not carry over
  4. the spindle-off grace counts down in HOLD, not only in Idle - a
     job abandoned in feed hold disarms after laser_disarm_s
  5. arming is refused while the cooling verdict blocks fire, and no
     armed message appears

The disarm grace is shortened via a temp config (GFHOME_CONF) and the
cooling verdict is published hermetically (GF_VERDICT_FILE), the same
overrides the emission harness uses.

Usage: laser_lifecycle_test.py [path-to-binary]
       (default ./build-native/grblHAL_glowforge)
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

BIN = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build-native/grblHAL_glowforge")
PORT = 2398

ARMED = "laser armed"
DISARMED = "laser disarmed - latch locked"
BLOCKED = "laser fire blocked"


def fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def read_avail(sock, log, timeout, until=None):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        sock.settimeout(max(0.05, end - time.time()))
        try:
            data = sock.recv(4096)
        except socket.timeout:
            data = b""
        except OSError:
            return None
        if data:
            buf += data
            log.append(data.decode(errors="replace"))
            if until:
                text = buf.decode(errors="replace")
                for token in until:
                    if token in text or re.search(r"^%s\b" % re.escape(token), text, re.M):
                        return token
        elif until is None:
            return None
    return None


def send_line(sock, line, log, tolerate_error=False):
    sock.sendall((line + "\n").encode())
    r = read_avail(sock, log, 5.0, until=("ok", "error"))
    if r is None:
        fail("no ok/error for %r" % line)
    if r == "error" and not tolerate_error:
        fail("error response to %r" % line)
    return r


def wait_for(log, needle, timeout, sock=None):
    """Wait until needle appears in the accumulated log (draining the
    socket while waiting when one is given)."""
    end = time.time() + timeout
    while time.time() < end:
        if needle in "".join(log):
            return True
        if sock is not None:
            read_avail(sock, log, 0.2)
        else:
            time.sleep(0.1)
    return False


def wait_idle(sock, log):
    for _ in range(100):
        sock.sendall(b"?")
        read_avail(sock, log, 0.3)
        if re.search(r"<Idle", "".join(log[-3:])):
            return
        time.sleep(0.2)
    fail("controller never returned to Idle")


def publish_verdicts(path, stop, fire_ok):
    while not stop.is_set():
        body = ('{"ts_mono":%.3f,"fire_ok":%s,"hold":false,'
                '"resume_ok":true,"reason":""}'
                % (time.clock_gettime(time.CLOCK_MONOTONIC),
                   "true" if fire_ok else "false"))
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(body)
        os.replace(tmp, path)
        stop.wait(0.5)


class Session:
    """One controller process with the lifecycle overrides applied."""

    def __init__(self, name, fire_ok=True, disarm_s=2):
        self.name = name
        self.workdir = tempfile.mkdtemp(prefix="laser-lifecycle-")
        conf = os.path.join(self.workdir, "forgefirm.conf")
        with open(conf, "w") as f:
            f.write("laser_disarm_s = %d\n" % disarm_s)
        verdict = os.path.join(self.workdir, "cooling.state")
        env = dict(os.environ, GF_VERDICT_FILE=verdict, GFHOME_CONF=conf,
                   FFLOG_STDERR="1")
        env.pop("GFSINK", None)
        self.stop = threading.Event()
        self.pub = threading.Thread(target=publish_verdicts,
                                    args=(verdict, self.stop, fire_ok),
                                    daemon=True)
        self.pub.start()
        self.proc = subprocess.Popen([BIN, "-p", str(PORT)],
                                     cwd=self.workdir, env=env,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)
        self.log = []
        self.sock = self.connect()

    def connect(self):
        for _ in range(50):
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=1)
                read_avail(s, self.log, 0.5)    # banner
                return s
            except OSError:
                time.sleep(0.1)
        err = b""
        if self.proc.poll() is not None:
            err = self.proc.stderr.read() or b""
        fail("[%s] cannot connect to the controller (exit=%s)\n%s"
             % (self.name, self.proc.poll(), err.decode(errors="replace")))

    def armed_count(self):
        return "".join(self.log).count(ARMED)

    def disarmed_count(self):
        return "".join(self.log).count(DISARMED)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
        self.proc.send_signal(signal.SIGINT)
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.stop.set()
        self.pub.join(2)
        shutil.rmtree(self.workdir, ignore_errors=True)


def test_job_window():
    """Rules 1 + 2: arm once per job, persist across M5/M3, close at M2,
    fresh consent for the next job. The grace is set far beyond the test
    horizon so only the program-end close can produce the disarm."""
    s = Session("job-window", disarm_s=60)
    try:
        send_line(s.sock, "M4 S100", s.log)
        send_line(s.sock, "G1 X1 F600", s.log)
        if not wait_for(s.log, ARMED, 5, s.sock):
            fail("[job-window] first laser-on did not arm")
        send_line(s.sock, "M5", s.log)
        send_line(s.sock, "M3 S200", s.log)
        send_line(s.sock, "G1 X0 F600", s.log)
        wait_idle(s.sock, s.log)
        if s.armed_count() != 1:
            fail("[job-window] M5/M3 inside one job re-prompted the arm "
                 "(armed messages: %d)" % s.armed_count())
        send_line(s.sock, "M2", s.log)
        if not wait_for(s.log, DISARMED, 5, s.sock):
            fail("[job-window] program end (M2) did not close the armed window")
        send_line(s.sock, "M4 S100", s.log)
        send_line(s.sock, "G1 X1 F600", s.log)
        if not wait_for(s.log, ARMED, 5, s.sock) or s.armed_count() != 2:
            fail("[job-window] next job after M2 did not arm afresh")
        wait_idle(s.sock, s.log)
        print("PASS [job-window]: armed once per job, M2 closed the window, "
              "next job re-armed")
    finally:
        s.close()


def test_sender_change():
    """Rule 3: a reconnected sender must re-arm. The grace is set far
    beyond the test horizon so only the sender change can close the
    window, and the first job ends in M5 so the next M4 is a fresh
    laser-on edge (the arm prompt fires on the off->on edge)."""
    s = Session("sender-change", disarm_s=60)
    try:
        send_line(s.sock, "M4 S100", s.log)
        send_line(s.sock, "G1 X1 F600", s.log)
        if not wait_for(s.log, ARMED, 5, s.sock):
            fail("[sender-change] first laser-on did not arm")
        send_line(s.sock, "M5", s.log)
        wait_idle(s.sock, s.log)
        s.sock.close()
        time.sleep(0.5)
        s.sock = s.connect()
        before = s.armed_count()
        send_line(s.sock, "M4 S100", s.log)
        send_line(s.sock, "G1 X0 F600", s.log)
        end = time.time() + 5
        while time.time() < end and s.armed_count() != before + 1:
            read_avail(s.sock, s.log, 0.2)
        if s.armed_count() != before + 1:
            fail("[sender-change] the reconnected sender inherited the "
                 "displaced session's armed window")
        wait_idle(s.sock, s.log)
        print("PASS [sender-change]: displaced consent did not survive; "
              "the new sender re-armed")
    finally:
        s.close()


def test_hold_grace():
    """Rule 4: the disarm grace counts down in HOLD."""
    s = Session("hold-grace", disarm_s=2)
    try:
        send_line(s.sock, "M4 S100", s.log)
        send_line(s.sock, "G1 X30 F60", s.log)     # ~30 s move
        if not wait_for(s.log, ARMED, 5, s.sock):
            fail("[hold-grace] job did not arm")
        time.sleep(1.0)
        s.sock.sendall(b"!")                        # feed hold
        if not wait_for(s.log, DISARMED, 10, s.sock):
            fail("[hold-grace] a job abandoned in Hold stayed armed past "
                 "the disarm grace")
        print("PASS [hold-grace]: the armed window closed while parked in Hold")
    finally:
        s.close()


def test_verdict_blocks_arm():
    """Rule 5: a blocking cooling verdict refuses the arm."""
    s = Session("verdict-blocked", fire_ok=False)
    try:
        send_line(s.sock, "M4 S100", s.log, tolerate_error=True)
        send_line(s.sock, "G1 X1 F600", s.log, tolerate_error=True)
        if not wait_for(s.log, BLOCKED, 5, s.sock):
            fail("[verdict-blocked] no refusal message for a blocking verdict")
        if ARMED in "".join(s.log):
            fail("[verdict-blocked] armed despite a blocking cooling verdict")
        print("PASS [verdict-blocked]: arming refused while fire_ok=false")
    finally:
        s.close()


def test_sigterm_mid_job():
    """Rule 5: a termination signal during an armed job is a STOP, not a
    "finish the job first". The supervisor's expected-stop path (mode
    switch, diagnostics, the emergency lever) delivers SIGTERM; the
    controller must bring motion to a controlled stop, close the armed
    window (latch relocked) and exit promptly - long before the job
    would have ended and inside the supervisor's SIGKILL grace."""
    s = Session("sigterm-mid-job", disarm_s=60)
    try:
        send_line(s.sock, "M4 S100", s.log)
        send_line(s.sock, "G1 X300 F60", s.log)          # a 5-minute move
        if not wait_for(s.log, ARMED, 5, s.sock):
            fail("[sigterm-mid-job] the job did not arm")
        # Let the run get under way.
        deadline = time.time() + 5
        running = False
        while time.time() < deadline and not running:
            s.sock.sendall(b"?")
            read_avail(s.sock, s.log, 0.3)
            running = "<Run" in "".join(s.log[-5:])
        if not running:
            fail("[sigterm-mid-job] the job never reported Run")
        t0 = time.time()
        s.proc.send_signal(signal.SIGTERM)
        # Keep draining the sender socket so the disarm report is captured.
        exited = False
        while time.time() - t0 < 10:
            read_avail(s.sock, s.log, 0.2)
            if s.proc.poll() is not None:
                exited = True
                break
        dt = time.time() - t0
        if not exited:
            fail("[sigterm-mid-job] the controller did not exit within 10 s of "
                 "SIGTERM during a job (it must stop, not finish the job)")
        if dt > 3.0:
            fail("[sigterm-mid-job] exit took %.1f s after SIGTERM (want < 3 s)" % dt)
        if s.disarmed_count() < 1:
            fail("[sigterm-mid-job] no disarm (latch relock) reported before exit")
        if s.proc.returncode != 0:
            fail("[sigterm-mid-job] exit status %s (want a clean 0)" % s.proc.returncode)
        print("PASS [sigterm-mid-job]: SIGTERM during a job stopped it, relocked "
              "the latch and exited in %.2f s" % dt)
    finally:
        s.close()


def main():
    if not os.path.isfile(BIN):
        fail("controller binary not found at %s" % BIN)
    test_job_window()
    test_sender_change()
    test_hold_grace()
    test_verdict_blocks_arm()
    test_sigterm_mid_job()
    print("PASS: the armed-window lifecycle holds")


if __name__ == "__main__":
    main()
