#!/usr/bin/env python3
"""Bench drill for the starved-re-check escalation path.

Runs ON THE BOARD against a controller started with a short
confirmation budget (GFCOOL_CONFIRM_MAX_S=45; see the runbook for the
manual start line). With the pump off, the job-start check reads
over-limit -> SUSPECT; the cooked stagnant loop then cannot pass the
settle gate within 45 s, so the budget expires and the driver must
escalate: "COOLANT FLOW FAULT: no clean re-check within 45 s".

Prints PASS/FAIL and leaves the machine idle: M9 sent, pump on,
heater off.
"""
import select
import socket
import time

T0 = time.monotonic()


def el():
    return time.monotonic() - T0


def log(msg):
    print('%7.1f  %s' % (el(), msg), flush=True)


def pump(on):
    with open('/sys/glowforge/thermal/water_pump_on', 'w') as f:
        f.write('1' if on else '0')
    log('** pump -> %s' % ('ON' if on else 'OFF'))


s = socket.create_connection(('127.0.0.1', 23), timeout=5)
s.setblocking(False)
buf = b''


def wait_msg(substrs, deadline):
    global buf
    while el() < deadline:
        r, _, _ = select.select([s], [], [], 0.2)
        if not r:
            continue
        data = s.recv(4096)
        if data:
            buf += data
        while b'\n' in buf:
            line, buf = buf.split(b'\n', 1)
            line = line.strip().decode('ascii', 'replace')
            if line.startswith('[MSG'):
                log('<< ' + line)
                for m in substrs:
                    if m in line:
                        return line
    return None


ok = True
try:
    time.sleep(0.5)
    pump(False)
    log('--- M8 with the pump off')
    s.sendall(b'M8\n')

    if wait_msg(['FLOW SUSPECT'], el() + 180) is None:
        log('!! no SUSPECT within 180 s')
        ok = False
    elif wait_msg(['no clean re-check within'], el() + 120) is None:
        log('!! no escalation FAULT within 120 s of the suspect')
        ok = False
finally:
    try:
        s.sendall(b'M9\n')
        time.sleep(1.0)
    except OSError:
        pass
    s.close()
    pump(True)
    with open('/sys/glowforge/thermal/heater_pwm', 'w') as f:
        f.write('0')
    log('--- M9 sent, pump on, heater off')

print('ESCALATION DRILL %s' % ('COMPLETE' if ok else 'FAILED'), flush=True)
