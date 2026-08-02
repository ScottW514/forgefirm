#!/usr/bin/env python3
"""Hold LASER_PWM at one duty value for a measurement window, then restore.
Usage: pwm_hold.py [sar] [seconds]  (defaults: 8, 30)"""
import mmap, struct, sys, time

PWM2_BASE = 0x02084000
SAR_OFF = 0x0C

sar = int(sys.argv[1]) if len(sys.argv) > 1 else 8
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 30

with open('/dev/mem', 'r+b') as f:
    m = mmap.mmap(f.fileno(), 4096, mmap.MAP_SHARED,
                  mmap.PROT_READ | mmap.PROT_WRITE, offset=PWM2_BASE)
    sar0 = struct.unpack('<I', m[SAR_OFF:SAR_OFF + 4])[0]
    m[SAR_OFF:SAR_OFF + 4] = struct.pack('<I', sar)
    print('PWMSAR=%d held for %d s (was %d)...' % (sar, secs, sar0))
    sys.stdout.flush()
    time.sleep(secs)
    m[SAR_OFF:SAR_OFF + 4] = struct.pack('<I', sar0)
    print('restored PWMSAR=%d' % sar0)
    with open('/sys/glowforge/cnc/laser_on_sampled') as s:
        print('laser_on_sampled =', s.read().strip())
    m.close()
