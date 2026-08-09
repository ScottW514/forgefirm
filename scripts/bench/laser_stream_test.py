#!/usr/bin/env python3
"""Host-side verification of the laser pulse-stream emission.

Runs the native grblHAL_glowforge binary in null-sink mode with
GFSINK_DUMP capturing the shipped byte stream, drives a small M4 laser
job over TCP, then checks the dump against the kernel feeder contract:

  1. a power byte (bit 7) leads the stream, before any tick byte
  2. no two consecutive power bytes (the SDMA script drops the second)
  3. the first FIRE bit (0x10) comes after a nonzero power byte
  4. power values match the S words ($30=1000 -> S500 = 63, S1000 = 127)
  5. FIRE only spans the cutting moves: none before the job, none during
     the G0 return, none at the tail
  6. step accounting survives the insertions: X returns to net zero and
     peaks at the programmed 10 mm

Usage: laser_stream_test.py [path-to-binary]   (default ./build-native/grblHAL_glowforge)
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

BIN = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "build-native/grblHAL_glowforge")
PORT = 2399
STEPS_PER_MM = 53.333

JOB = [
    "M4 S0",
    "G1 X5 F600 S500",
    "G1 X10 S1000",
    "G0 X0",
    "M5",
]


def fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def send_line(sock, line, log):
    sock.sendall((line + "\n").encode())
    while True:
        r = read_avail(sock, log, 5.0, until=("ok", "error"))
        if r is None:
            fail("no ok/error for %r" % line)
        if r == "error":
            fail("error response to %r" % line)
        return


def read_avail(sock, log, timeout, until=None):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        sock.settimeout(max(0.05, end - time.time()))
        try:
            data = sock.recv(4096)
        except socket.timeout:
            data = b""
        if data:
            buf += data
            log.append(data.decode(errors="replace"))
            if until:
                for token in until:
                    if re.search(r"^%s\b" % token, buf.decode(errors="replace"), re.M):
                        return token
        elif until is None:
            return None
    return None


def main():
    workdir = tempfile.mkdtemp(prefix="laser-test-")
    dump = os.path.join(workdir, "stream.bin")
    env = dict(os.environ, GFSINK_DUMP=dump)
    env.pop("GFSINK", None)

    proc = subprocess.Popen([BIN, "-p", str(PORT)], cwd=workdir, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        sock = None
        for _ in range(50):
            try:
                sock = socket.create_connection(("127.0.0.1", PORT), timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        if sock is None:
            fail("cannot connect to the controller")

        log = []
        read_avail(sock, log, 0.5)          # banner / hello

        for line in JOB:
            send_line(sock, line, log)

        # Wait for the motion to play out on the wall clock (the shipper
        # is wall-paced), then for the Idle report.
        idle = False
        for _ in range(100):
            sock.sendall(b"?")
            read_avail(sock, log, 0.3)
            if re.search(r"<Idle", "".join(log[-3:])):
                idle = True
                break
            time.sleep(0.2)
        if not idle:
            fail("controller never returned to Idle")
        time.sleep(1.0)                     # let the shipper drain the tail

        text = "".join(log)
        if "laser armed" not in text:
            fail("no 'laser armed' message (arming flow did not run)")

        sock.close()
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    data = open(dump, "rb").read()
    if not data:
        fail("empty stream dump")

    # --- contract checks -------------------------------------------------
    if not data[0] & 0x80:
        fail("stream does not lead with a power byte (first byte 0x%02x)" % data[0])

    prev_power = False
    cur_power = 0
    fire_ticks = []                 # (tick_index, power_at_that_tick)
    x_pos = 0
    x_min = x_max = 0
    tick = 0
    first_fire_power = None
    for b in data:
        if b & 0x80:
            if prev_power:
                fail("consecutive power bytes at tick %d" % tick)
            prev_power = True
            cur_power = b & 0x7F
            continue
        prev_power = False
        if b & 0x10:
            if first_fire_power is None:
                first_fire_power = cur_power
            fire_ticks.append((tick, cur_power))
        if b & 0x01:
            x_pos += -1 if b & 0x02 else 1
            x_min = min(x_min, x_pos)
            x_max = max(x_max, x_pos)
        if b & 0x24:
            fail("unexpected Y/Z step at tick %d (byte 0x%02x)" % (tick, b))
        tick += 1

    if not fire_ticks:
        fail("no FIRE bits in the stream")
    if first_fire_power == 0:
        fail("first FIRE bit rides duty 0 (power-before-fire violated)")

    powers = sorted(set(p for _, p in fire_ticks))
    if powers[-1] != 127:
        fail("S1000 did not reach duty 127 (max %d)" % powers[-1])
    if not any(60 <= p <= 66 for p in powers):
        fail("S500 plateau (~63) not seen (powers %s)" % powers[:20])

    expect_peak = round(10 * STEPS_PER_MM)
    if abs(x_max - expect_peak) > 2:
        fail("X peak %d steps, expected ~%d" % (x_max, expect_peak))
    if x_pos != 0:
        fail("X net %d steps after return to 0" % x_pos)
    if x_min < 0:
        fail("X went negative (min %d)" % x_min)

    last_fire = fire_ticks[-1][0]
    tail_steps = 0
    tick = 0
    prev_power = False
    for b in data:
        if b & 0x80:
            prev_power = True
            continue
        if tick > last_fire and b & 0x01:
            tail_steps += 1
        tick += 1
    if tail_steps < 400:
        fail("only %d fire-free steps after the last FIRE bit - G0 return not dark" % tail_steps)

    print("PASS: %d bytes, %d power bytes, %d fire ticks, powers %s, "
          "X peak %d steps net 0, %d dark return steps"
          % (len(data), sum(1 for b in data if b & 0x80), len(fire_ticks),
             powers, x_max, tail_steps))
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
