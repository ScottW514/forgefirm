import socket, subprocess, time
import os

HOST = os.environ.get('GF_HOST')
if not HOST:
    raise SystemExit('set GF_HOST to the machine IP address')

def board(cmd):
    r = subprocess.run(['wsl', '-d', 'forge-yocto', '--', 'ssh',
                        '-o', 'PreferredAuthentications=none',
                        'root@' + HOST, cmd],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip().replace('\n', ' ')

ATTRS = ('head/air_assist_pwm head/air_assist_tach head/purge_air '
         'thermal/exhaust_pwm thermal/tach_exhaust '
         'thermal/intake_pwm thermal/tach_intake_1 thermal/tach_intake_2 '
         'thermal/water_pump_on thermal/tec_on pic/water_temp_1 pic/water_temp_2')

def snap(tag):
    vals = board('cd /sys/glowforge && cat ' + ATTRS).split()
    keys = [a.split('/')[-1] for a in ATTRS.split()]
    print(tag)
    for k, v in zip(keys, vals):
        print('  %-18s %s' % (k, v))

s = socket.create_connection((HOST, 23), timeout=5)
s.settimeout(0.15)
def drain():
    out = b''
    try:
        while True:
            d = s.recv(4096)
            if not d: break
            out += d
    except socket.timeout: pass
    return out.decode('ascii', 'replace')
def cmd(l, w=0.4):
    s.sendall(l.encode() + b'\n'); time.sleep(w); return drain().strip()

time.sleep(0.5); drain()

snap('--- baseline (driver idle profile)')
w2 = board('cat /sys/glowforge/pic/water_temp_2')
print('water_temp_2 = %s -> %.1f C' % (w2, int(w2) * -0.09653 + 94))

print()
print('=== M8: cut-profile fans ON (loud) ===')
print('M8:', cmd('M8'))
time.sleep(4)                      # spin-up
snap('--- during M8')

print()
print('=== M9: cooldown (fans stay on ~15 s) ===')
print('M9:', cmd('M9'))
time.sleep(3)
snap('--- during cooldown (should still be at run values)')
time.sleep(14)                     # past the 15 s cooldown
snap('--- after cooldown (should be idle: AA 204, EF 0, IF 0)')
s.sendall(b'?'); time.sleep(0.3)
t = drain()
print('grbl:', t[t.rfind('<'):t.rfind('>') + 1] if '<' in t else t)
