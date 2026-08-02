#!/usr/bin/env python3
"""FIRE-line drop-timing test - runs ON the board. Usage: fire_test.py A|B

Stream: power(0) first byte (duty forced to ZERO before any FIRE bit -
the run-start reset would otherwise leave it at 100%), then
1 s pads / 2.000 s FIRE bits / 1 s pads / 2.000 s FIRE bits ending
exactly at end-of-data (the backstop edge the gate wants timed).
No step bytes; motor_lock=15; streaming=0 (normal completion).

Phase A: laser latch LOCKED - expects nothing on the LASER_ON pin.
Phase B: latch UNLOCKED for the run (re-locked in finally). Refuses to
run if laser_pgood reports the HV supply good. Duty is zero throughout.
"""
import fcntl, os, struct, sys, time

TICK_HZ = 10000
FIRE = b'\x10'
PAD = b'\x00'


def wr(attr, val):
    with open('/sys/glowforge/' + attr, 'w') as f:
        f.write(str(val))


def rd(attr):
    with open('/sys/glowforge/' + attr) as f:
        return f.read().strip()


def rd_pos():
    with open('/sys/glowforge/cnc/position', 'rb') as f:
        raw = f.read(32)
    return struct.unpack('<5i', raw[:20])


def snap(tag):
    print('%s: state=%s laser_enable=%s laser_on=%s laser_on_sampled=%s interlock=%s'
          % (tag, rd('cnc/state'), rd('cnc/laser_enable'), rd('cnc/laser_on'),
             rd('cnc/laser_on_sampled'), rd('cnc/interlock_circuit')))


mode = sys.argv[1].upper() if len(sys.argv) > 1 else 'A'

stream = (
    bytes([0x80]) +                # power = 0: duty zero before any FIRE bit
    PAD * TICK_HZ +                # 1 s baseline
    FIRE * (2 * TICK_HZ) +         # 2.000 s FIRE window (bounded by pads)
    PAD * TICK_HZ +                # 1 s gap
    FIRE * (2 * TICK_HZ)           # 2.000 s FIRE window ending AT end-of-data
)

print('phase %s: stream %d bytes = %.3f s' % (mode, len(stream), len(stream) / TICK_HZ))

if mode == 'B':
    pgood = rd('cnc/laser_pgood')
    if pgood != '0':
        print('ABORT: laser_pgood=%s (HV supply reports good) - refusing phase B' % pgood)
        sys.exit(1)

snap('pre ')
wr('cnc/motor_lock', 15)
wr('cnc/step_freq', TICK_HZ)
wr('cnc/laser_latch', 1)

fd = os.open('/dev/glowforge', os.O_WRONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.lseek(fd, 1, os.SEEK_SET)
    wr('cnc/enable', 1)
    time.sleep(0.5)
    os.write(fd, stream)
    pos_before = rd_pos()

    if mode == 'B':
        wr('cnc/laser_latch', 0)   # UNLOCK for this run only
        print('latch UNLOCKED for phase B run')

    wr('cnc/run', 1)
    t0 = time.time()
    sampled_mid = False
    state = ''
    while time.time() - t0 < 20:
        state = rd('cnc/state')
        if not sampled_mid and 1.5 < time.time() - t0 < 3.0:
            snap('mid (inside FIRE window)')
            sampled_mid = True
        if state != 'running':
            break
        time.sleep(0.1)
    print('done: state=%s after %.1f s' % (state, time.time() - t0))
finally:
    wr('cnc/laser_latch', 1)       # re-lock unconditionally
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)

pos_after = rd_pos()
print('pos before=%s after=%s MOVED=%s' % (pos_before, pos_after, pos_before[:3] != pos_after[:3]))
snap('post')
print('underruns=%s faults=%s' % (rd('cnc/underruns'), rd('cnc/faults')))
wr('cnc/disable', 1)
print('safe state restored: state=%s latch=LOCKED' % rd('cnc/state'))
