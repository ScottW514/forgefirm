# ForgeFIRM bring-up status & cold-start runbook

Last updated: **2026-08-15** — **unified logging landed in every repo
(code-complete, host-verified end to end, pushed, pins bumped): rsyslog
is the system logger and the only log writer, every ForgeFIRM process
emits through syslog under its own program name, each logger has its own
directory under `/data/log/forgefirm/`, per-logger disk and remote levels
plus a remote syslog target are machine settings (applied at reboot) with
a Logs tab in the panel (levels, live viewer, sanitized tar.gz export for
issue reports). It is an image change (rsyslog replaces busybox
syslogd/klogd) and rides the next full image flash — bench validation
checklist is "Next work" item 14.** Before that: **audit remediation Phases 0 through 11
landed: every one of the 159 findings from the independent whole-tree
audit dated 2026-08-13 has its fix committed** (the remediation was
sequenced behind two gates — GATE A, uncommanded energy, before any
further live-fire; GATE B, control surface + release, before any
published release — and both are bench-closed, see the campaign record
below). Image `20260814223300` (forgefirm-image + forgefirm-image-dev)
carries every kernel/image row through Phase 9 and is flashed on the
bench; built-image checks pass: the release rootfs has root locked (`*`
in `/etc/shadow`), no watchdog daemon, forgefirm-logrotate installed,
and `K80grblhal`/`K80gfcloud` ahead of `K90forgectrl` at runlevel 6;
the kernel config carries `CONFIG_IMX2_WDT`, `CONFIG_PANIC_ON_OOPS`,
and `CONFIG_PREEMPT`; the DTB fallback bootargs is console-only;
`glowforge.ko` (the full hardening batch) is in `/lib/modules`. The
Phase 11 sweep (below) is host-verified, pinned, and its controller and
daemon halves are installed on the bench; its kernel half is doc/SPDX-only.
**Image `20260815105250` (forgefirm-image + forgefirm-image-dev) is built
on the Phase 11 pins** — the first image whose license manifest declares
`python3-gfhardware` as `MIT & LGPL-2.1-or-later` and `wlconf` as
`GPL-2.0-only` (packaged output) — with the same built-image checks passing
(root locked, no watchdog daemon, K80/K90 order, `glowforge.ko` and both
controller binaries present) and the buildpaths QA warning gone (the shipped
grblHAL `--version` flags string carries no host paths). Its only build
warning is a stamp-taint note from an earlier forced `do_compile`. **Flashed
on the bench by the operator 2026-08-15** — the board now runs the pinned
Phase 11 userspace from the image rather than hot-installed binaries. With
that, the audit's working files (the findings list, the remediation plan)
are retired: every finding is fixed, every deliberate leftover lives in
"Next work" below, and this runbook is the record.

**Bench campaign — opened 2026-08-14; image `20260814223300` flashed and
booted.** Post-flash health check passes on the board: it reports
`20260814223300 (dev)`; kernel `6.12.20-fslc` with `CONFIG_PREEMPT` and
the console-only `panic=10` command line; `CONFIG_IMX2_WDT` and
`CONFIG_PANIC_ON_OOPS` present in the running config; the hardened
`glowforge.ko` loaded with the 16 MiB `cnc-pulsebuf` no-map pool mapped
and SDMA channel 26 / EPIT up; forgectrl holds `/dev/glowforge` (40 V up,
dead-man active) and supervises the grbl controller with the
motion-liveness probe reading **verified**; the latch reads **locked**
and faults 0 at idle; the only `watchdogd` is the kernel kthread (no
userspace watchdog daemon). **GATE B is bench-verified on the
software/control-surface side.** From a second LAN host every
state-changing endpoint refuses an unauthenticated write
(`403 authentication required`); a spoofed non-literal `Host`, a
non-literal `Origin`, and a cross-site `Sec-Fetch-Site` are each refused
(`403 request origin refused`); `/cool/state` refuses a non-loopback peer
(`403 loopback only`); the four-POST unsigned-flash chain
(`upload → apply?confirm_unsigned=1 → boot → reboot`) and
`restore/factory` are each refused unauthenticated; `/fuse-identity` is
fully token-gated (F-1, F-2, F-19). The authenticated max-length
`POST /settings` probe passes without a crash: a 300-character value is
refused `400`, thirteen 16-character in-range values are accepted `200`,
and `/status`, the panel `/`, and `/settings` all keep serving, with the
settings restore verified byte-identical to the pre-test snapshot (F-4,
F-18). On-board build facts re-confirmed on the running image:
controllers stop at `K80` before forgectrl at `K90` (rc0/rc6, B-4); the
forgefirm logrotate config and init lever are installed (F-16); there is
no `/etc/watchdog.conf` or watchdog init (B-8); the wlconf data files are
0644 (B-16); the panel token is stored 0600 (the settings file's 0600
creation is Phase 11's F-23, host-verified there). **GATE A dry motion
drills pass
(latch locked, no emission, operator watching):** bounded relative jogs
move the gantry (operator-witnessed) and the grblHAL position counter
tracks the commanded moves exactly, returning to rest; a
jog-cancel (`0x85`) stops the jog cleanly short of target and returns to
`Idle` with position preserved; a feed-hold (`!`) parks with the feed
ramping to 0 (`Hold:1`→`Hold:0`) and a resume (`~`) completes the move
with no lost-step alarm; a `^X` abort decelerates under control into
`Alarm` with machine position retained, `$X` recovers to `Idle`, and a
subsequent jog runs — no DRV8825 wedge after the abort (the rail never
cycled). **Dry dead-man / disruption drills pass (latch locked, no
emission):** with only the broker and the controller holding
`/dev/glowforge` — no stray process pins it (F-6) — a `SIGKILL` of the
controller mid-move is reaped by the supervisor, which writes `cnc/stop`
+ `cnc/laser_latch=1`, unlinks the homing anchor, and respawns a fresh
controller in about a second with the latch never unlocking (F-3); a
`SIGSTOP` (hang) mid-move drains the ring into a kernel `pulse data
underrun; position no longer trusted`, halting motion fast with the latch
locked while the cooling engine's report-silence clock runs past its
window; and a `forgectrl restart` mid-move leaves the busy controller
running (reparented), lets the move finish uninterrupted, never unlinks
the cooling verdict, and has the new daemon stand by and retake at idle
(F-12). The liveness probe's designed skip-on-open path — the safety-chain
output is known to de-assert during motion, so an at-that-moment read can
skip the probe, proceed without a motion fault, and re-probe on the next
spawn — was exercised and behaved per `liveness.c`. **GATE A kernel drills PASS on this image (operator present, HV
unpowered, software witnesses — the bit-to-pin correspondence was
scope-pinned 2026-08-02):** run with forgectrl stopped so the pulse
device is free (`scripts/bench/gate_a_kernel_drills.py`). K1: a
controlled stop from the 10 kHz cloud tick decelerates in 0.091 s
(theoretical ramp 0.072 s) to `idle` with no max-rate burst and no
fault. K2: with the latch locked, a `stop` + `resume +200` replays a
2 s FIRE window with `laser_enable`/`laser_on` at 0 throughout and
interlock pinned at 13 — the waypoint provably completed (the position
counter advanced all 1000 masked steps; `motor_lock` masks the output
drive, not the counters). K3: `laser_latch=0` written inside the accel
ramp drives the latch pin (interlock 13→5, bit 3 clear) but the FIRE
output drive is never restored while the run is in flight —
`laser_enable` 0 for the entire 3.5 s FIRE-bit stream. `fire_test.py`
A/B/U reproduce the 2026-08-02 reference on the rebuilt kernel: A
(latch locked) pins interlock at 13 through 40,000 FIRE bits; B (latch
unlocked, chain unarmed) shows `laser_enable=1`/interlock 7 mid-window
with `laser_on`/`laser_on_sampled` 0 — the safety AND-gate holds; U
reaches a true underrun, the backstop drops FIRE, and `stop` acks it.
**GATE A IS CLOSED**: every Phase 1 row is fixed, the G-1 assertion is
green in CI, and the drills above are the bench log. Live fire is
permitted again. The masked K2 steps leave the un-anchored X counter
offset (+1000 steps); `homed:false` already enforces the re-home.

**The campaign caught a live defect (fixed same day):** the liveness
probe's enclosure guard read the combined-doors EV_SW bit with the
sense inverted (bit 3 set means *closed*, as the controller's switch
map decodes; the guard treated set as *open*), so the probe skipped on
every spawn with the lid closed — and would have moved the gantry with
it open. Verified live against `EVIOCGSW` (lid closed, bit 3 = 1,
probe reporting "door/interlock open"). Fixed in forgectrl `424f185`
and hot-deployed; on the next start the probe genuinely ran and the
supervision behaved exactly as designed: a first gray-zone read (head
accel p2p x=455, below the ≥500 moving threshold) was treated as NO
MOTION and re-probed rather than false-passed, and the second probe
returned MOTION OK (p2p x=3919, y=1636) — the DRV8825s are not wedged
after the drill session's rail cycles.

**X-2 connection-flood robustness exercised (dry):** a 500-connection
slow-drip flood from a second LAN host drove forgectrl from 7 to a peak
of 379 open fds, where it plateaued — MHD's own connection handling
caps concurrency far below the raised 4096 `RLIMIT_NOFILE`, so the
flood could not manufacture the EMFILE that the X-2 fix guards against.
The daemon never crashed, the kernel `cnc/state` stayed readable
throughout (two local `/status` probes timed out at the peak and
recovered within a second), and it returned to 7 fds with `/status`
`200` after the flood drained. The fail-closed branch itself
(`machine_is_idle()` returns busy on any `rd_attr` failure) is now
covered by a host unit test in forgectrl CI
(`tests/status_idle_test.c`, X-2): it points the sysfs reader at a temp
tree via a `GF_SYSFS_ROOT` seam and asserts not-idle on a missing state
file and under real fd exhaustion (`EMFILE`) — the connection-flood
trigger the runtime flood cannot reach while MHD caps connections below
the fd limit. Test-the-test verified: a fail-open revert fails it. Note for F-15/X-6: the
absence of an explicit `MHD_OPTION_CONNECTION_LIMIT` + per-IP cap is
still the deferred half; the default ceiling held here but a per-IP cap
remains the right hardening.

**Idle-CPU diagnosis + pacing fix (2026-08-14).** The controller was
found at ~28% CPU while the machine appeared idle. Traced to grblHAL
being parked in the safety-door state (`Door:0`) — entered when the lid
was opened for inspection between drills, and held there awaiting a
cycle-start even after the lid closed. In any state other than
`STATE_IDLE`/`STATE_ALARM` the driver's `serial_wait` took the 200 µs
segment-production pace, so a parked Door (or Hold) busy-spun the
protocol thread. Not a regression in the audit work; the parked-state
pacing had always been tight. Fixed in grblHAL `b2cad8d`
(`motion_parked()`): a completed feed hold, a parked door (ajar or
closed), and sleep now take the coarse idle poll, while the motion
sub-phases (`Hold_Pending` decel, `Parking_Retracting`/`Resuming`) keep
the tight pace. Hot-deployed; pin bumped and fetch-verified.
**Bench-validated dry (`scripts/bench/pacing_test.py`):** idle 2.7%,
active move 35% (tight, segments flowing), parked `Hold:0` 2.7% (was
~28%), parked `Door:1`/`Door:0` 3.0% (was ~28%), and a mid-move
feed-hold→resume preserved position exactly (30.000 mm, no lost steps —
the feeder never starved through the decel and resume ramps). This pin
bump also rides P10's grblHAL CI/tests and the mlockall-root-only change
into the next image.

**Live-fire drills PASS (operator armed, S400/40% vector marks on
scrap, `scripts/bench/live_fire_drills.py`):**

- **Phase 5 A-1 emission witness — PASS.** On a commanded fire window
  `cnc/laser_on_sampled` (surfaced as `/status` `laser.emission_samples`)
  goes to its full 255 count and returns to 0 at Idle, across two
  separate burns. This is the reliable live-emission witness.
- **Phase 5 A-5 HV telemetry — PASS.** `pic/hv_current` (`hv_current_raw`)
  tracks the cut: 0 at idle, 0→1023/661/482 raw during the three burns
  (the tube draws real current). The only HV witness on this PSU —
  `hv_voltage` is grounded, as the audit noted.
- **Phase 5 A-2 lid IR — characterized, gate left watch-only.** A 40 %
  vector cut lifts the four `pic/lid_ir` channels only ~+3 counts over
  the ambient baseline (37/36/40/40 → peaks ~40/39/42/43) — barely above
  the ±3-count ambient noise, i.e. a weak fire signal at this power.
  `cool_fire_ir_delta` therefore stays 0 (watch-only) until a
  representative high-power job is characterized; a real ignition flare
  is far brighter than a cut, so the eventual threshold sits well above
  both the cut delta and the noise (a floor near 15 counts is the
  working target, not yet committed). forgectrl's per-job telemetry line
  logs baseline/peak for all four channels.
- **pgood is not a usable witness on this PSU.** `cnc/laser_pgood_sampled`
  stayed 0 (forgectrl reads <128 as "not good") through every burn even
  while `hv_current` rail'd and the tube cut — so A-1's "surface
  laser_pgood loss" warning is a false alarm on this hardware and must
  be gated/suppressed here (or documented as expected); the emission and
  HV witnesses are the trustworthy ones. Recorded for the A-1 follow-up.
- **Phase 4 X-3 job-based disarm — PASS.** A job ending in `M2`
  (program end, as LightBurn sends) disarms in **0.1 s** at Idle; a job
  with no program end falls back to the ~60 s `laser_disarm_s` idle
  grace (measured 56.8 s). The window is job-based, not 60-s-idle-based.
- **Phase 4 G-10 disarm-in-Hold — PASS.** Armed, fired a +X move,
  feed-held mid-move (`Hold:1`); the disarm grace counts down while held
  and closes the window at 61.3 s (the bug left a job abandoned in Hold
  armed for hours).

**Live defect caught and fixed by the campaign:** the liveness probe's
enclosure guard read the combined-doors EV_SW bit with inverted sense
(bit 3 set = *closed*, per the switch map; the guard treated set as
*open*), so the wedge probe skipped on every spawn with the lid closed
and would have moved the gantry with it open. Fixed in forgectrl
`424f185`, hot-deployed; the probe then ran for real and behaved as
designed — a gray-zone first read (head-accel p2p x=455, below the ≥500
threshold) was retried rather than false-passed, and the retry returned
MOTION OK (p2p x=3919, y=1636). The forgectrl pin is bumped to
`424f185` (fetch-verified) so the fix also rides the next image, not
only the hot-deploy.

**Closed by host unit test instead of a bench drill:** G-4 (the arm
must re-check `gfcool_fire_ok()` after the button wait — the verdict can
go bad during a wait that runs for minutes) now has a grblHAL CI test
(`tests/laser_arm_test.c`) that includes the driver source, stubs the
core, and drives the real `gflaser_arm()` with a good-then-bad verdict
sequence, asserting the arm refuses at the post-wait re-check (latch
locked, window never opened, alarm raised). Test-the-test verified:
removing the re-check fails it. This is cleaner than the bench drill,
which needed the pump killed in the instant after the press. **Still
config-dependent, left as-is:** Phase 6's "armed job refuses at the
stale origin after an underrun" (GRBL mode permits unhomed cutting), and
the core underrun behavior — `pulse data underrun; position no longer
trusted` with the homing anchor unlinked — is already logged in the dry
dead-man drills above. Live fire only with
the operator armed: eye protection, fire watch, exhaust running.

The lid-IR **ambient baseline** for the fire-watch characterization is
captured on this image (600 samples over 5.6 min at 2 Hz, lid closed,
machine idle, coolant ≈25 °C): `lid_ir_1..4` read 37.3 ±0.6, 36.3 ±0.6,
39.5 ±0.7, and 40.0 ±0.6 raw counts (total spread ±3 counts),
`hv_current` reads 0 throughout, and the emission witness
(`laser_on_sampled`) read 0 on all 600 samples — the idle plumbing for
the emission/fire/HV evidence is verified quiet end to end (`/status`
carries the sensed rows; `/cool/status` reports `fire_watch:"watch"`).
Dataset: `scripts/bench/lid_ir_ambient_baseline.csv`. When the fire
characterization sets `cool_fire_ir_delta`, it must land comfortably
above the worst normal-cut peak delta and never below ~15 counts, so
ambient noise can never trip the fire abort. The three pending GATE A
kernel drills are scripted and staged on the bench
(`scripts/bench/gate_a_kernel_drills.py`): K1 proves the
controlled-stop deceleration floor at the default cloud tick, K2
proves a resume waypoint honors the locked latch through a replayed
FIRE window, and K3 proves a mid-ramp latch unlock never re-arms the
FIRE drive — each with software witnesses (`laser_enable`, `laser_on`,
`laser_on_sampled`, interlock bit 3) plus the PSU-connector LASER_ON
scope point, run with forgectrl stopped so the pulse device is free.

**Bench session 2026-08-15 (image `20260815105250`, operator present) —
two live-fire findings closed, one real defect found and fixed.**
Lid-IR characterization at cutting power: three 30 mm squares on scrap
(S1000 F300, S1000 F150, S800 F600); the engine's per-job telemetry read
run-start baseline → peak `58/59/64/63 → 62/60/66/66`, `56/56/61/62 →
60/61/66/68`, `56/55/61/63 → 61/60/65/66` — a worst normal-cut rise of
**+6 counts** on any channel, against ±3 counts of ambient noise. Ambient
that day read ~57–64 vs 37–40 on 08-14 (day-to-day drift ≈ +22 counts),
which is why the gate keys off the run-start baseline and never off an
absolute level. `cool_fire_ir_delta = 15` is the sized gate (≥ 2× the
worst cut rise, at the ~15-count floor); it is a hand-edited
`/data/forgefirm.conf` key, **set on the bench 2026-08-15** (verified
present, file 0600), and takes effect at the next run start — the fire
watch is armed from here on and the next real jobs are the false-trip
watch. **Flame
signature, measured the same day (machine idle):** a small candle burning
on the bed under the closed lid read `38–41 / 38–41 / 42–45 / 42–45`
against a lid-open level of `36 / 35 / 38 / 39` and a lid-closed-empty
control of `34–37 / 34–36 / 36–39 / 37–40` — closing the lid changes
nothing, the candle is **+3 to +6 counts on all four channels** for as
long as it burns. That is the same size as a full-power cut's rise, so a
threshold cannot separate a candle-sized flame from cutting and the
15-count gate will not react to a flame that small; what a material fire
of a size worth stopping for produces is unmeasured. **Then the decisive measurement, dry, the same
day: the lid-IR channels track the lid LED.** `lid_led` 0 → `2 2 1 2`,
8 → `2 2 3 2`, 131 (the resting level) → `54 55 61 62`, 255 → `172 171
190 188`. The sensors are, first of all, a photometer for the lid lamp;
every rise measured above (cuts +4–6, candle +3–6, the "+22 drift"
between sessions) is a small modulation on a lamp-set level. forgectrl's
camera engine drives `pic/lid_led` for every lid capture (132 during the
grab, previous level restored), and the resting level is not fixed (131
here, 8 after one reboot, cloud mode sets its own `LLvl`) — so a snapshot
mid-run can step every channel by tens of counts and a fixed-count gate
fires a phantom FIRE stop. **`cool_fire_ir_delta` was therefore set back
to 0 (watch-only) the same day**; the gate stays disabled until the fire
watch is lamp-aware (Next work item 10). **Armed kill on
the expected-stop path — first run FAILED, defect fixed, re-run PASS.**
With emission live, `POST /controller/stop` returned only after 5.30 s
and the operator saw ~17 mm / ~5 s of continued cutting before a
decelerated stop: the supervisor's SIGTERM was honored by the controller
as "exit once motion is done" (`driver.c` exited only outside
CYCLE/JOG/HOMING), so the job ran on until the 5 s SIGKILL escalation
and the exit safing (`escalating to SIGKILL`, exit status 0x9). Fixed on
both sides and bench-proven the same session: forgectrl `3edb7bd` writes
`cnc/stop` + `cnc/laser_latch=1` **before** the SIGTERM (kernel-level,
instantaneous, no-op when idle); grblHAL `5960f05` treats SIGINT/SIGTERM
during motion as `^X` (controlled decel, latch relocked, alarm) and exits
on the next pass, with the handler kept installed so the supervisor's
second SIGTERM cannot hard-kill it mid-cleanup — CI case
`sigterm-mid-job` (exit in 0.10 s; the old logic fails it). Re-run with
the new binaries installed: POST returned in 0.46 s, `grbl controller
exited (status 0x0)` with no SIGKILL, kernel `idle` and `armed:false` at
the first post-stop sample, emission gone within the counter's ~1 s
window; the operator saw ~1 s / a few mm of cut, then the stop. Also
found and fixed: `auth.c` read `X-ForgeFIRM-Token`/`Host`/`Origin`/
`Sec-Fetch-Site` case-sensitively (a title-casing client was refused);
now `u_map_get_case`. Bench tooling for the session is committed
(`scripts/bench/platform_drills.py`, `live_fire_drills.py` `ircut` /
`expstop` / `ctrlstart`, `fdscan.sh`). Session rules, now standing: one
live-laser run per turn with the operator's confirmation before the next;
only observations, never inferences, in live-fire reporting.
**Dry drills the same session, all PASS on the board:** decay/microstep
readback per axis (every value reads back, out-of-range `3` refused
`EINVAL`); dead-man trip readback (closing the flock'd fd mid-run →
`closed while locked and driver is running! Emergency stop`, `pic`/`head`/
`thermal: making safe`; heater and TEC off, measure laser, UV LED and Z
driver off, pump/exhaust/intake/air-assist **unchanged**); three
`rmmod`/`modprobe` cycles with a thread reading state/position/faults/
hall_sensor throughout (6618 reads served, 14162 refused while unloaded,
no oops/BUG/WARNING); the LED sequence (all bright / all dark / button
pulse 300 ms / restore) behaved as commanded, operator-witnessed;
the module's probe lines read `EPIT clock 66000000 Hz` and `SDMA channel
26 reserved for pulse playback (script at halfword 7680)` with no bank
warnings; forgectrl's helper children (`curl` during `/update/check`, the
snapshot path) never hold a pulse-device descriptor — only the controller
does; a `$H` gfcloud homing session completed in 56 s with 7 accelerometer
motion windows above the 500-count threshold at the ~100 Hz sampler
(anchor written, `H:1`); a kernel panic (`sysrq c`) mid-move stopped
motion instantly (operator-witnessed) and the board rebooted on `panic=10`
into a healthy state (liveness MOTION OK, controller running, latch
commanded locked). Observed once, cause not established: after the three
module reloads the first liveness probe read NO MOTION (p2p 343/241); the
ladder's rail-off/re-probe recovered it (p2p 3466/2163) — a module reload
resets the analog configuration, and the ladder exists for this.
**Head-absent negatives (head unplugged, machine powered up):** the head
driver fails probe (`head not detected`) and the whole `head/` sysfs
group is absent, so every head attribute reads as missing rather than
as a number; neither the daemon nor the controller logs anything
repetitive with the head gone; the liveness probe skips (`head
accelerometer not found`) and the controller starts. Three findings,
fixed and re-proven the same session: `/status switches.head` was EV_SW
bit 7 raw (reads `true` with the head unplugged) — now real presence
(the head group exists) and it read `false`; `/mode` said `motion:
"verified"` after a probe that could not run — now `"unverified"`
(forgectrl `73eda9a`); and **nothing gated arming on
head presence** — the GRBL controller now refuses the first laser-on
of a job when the head group is absent, before the latch unlocks and
before the button lights (grblHAL `91807a2`, "laser fire blocked: no head
detected" + `ALARM:3`, operator-witnessed: the button stayed dark).
The K-11 runtime-I²C-error case (a present head answering badly) and
the C-3 failed-head-capture case are not reachable with the head
unplugged and stay open.

**Phase 11 (licensing, legal, and documentation hygiene — the last
phase) is code-complete and host-verified, 2026-08-15.** Licensing:
`python3-gfhardware` declares the libdc1394 Bayer decoder it compiles
into `gfhardware._cam` (`MIT AND LGPL-2.1-or-later` in `setup.py`, SPDX
lines on `bayer.c`/`.h`, the LGPL text shipped, the rebuild/relink offer
stated in its README) and the BSP recipe carries `MIT & LGPL-2.1-or-later`
with checksums on both license texts and the decoder header; the `wlconf`
recipe declares the three regimes its vendored TI tarball actually
contains (`GPL-2.0-only & BSD-3-Clause & TI-TSPA`, checksums on the
GPL notice, `COPYING`, and the TSPA `LICENCE`; the packaged output is the
GPL-2.0-only `wlconf/` subtree — nothing from `hw/firmware/` is
installed; provenance recorded as TI WiLink8 R8.7 SP3 with its sha256;
the TSPA text lives in the layer's `custom-licenses`); `python-gfutilities`
anchors its checksum to the upstream repo's own `LICENSE`; the dead
`meta-openglow-bsp` layer is removed; SPDX identifiers now sit on every
grblHAL driver source, every kernel-module source and header, and the
cloud-mode app files; the kernel module credits both authors and the
third-party SDMA assembler tools. `bitbake -c populate_lic` on
`python3-gfhardware`, `wlconf`, and `python3-gfutilities` succeeds against
the bumped pins and deploys the expected license files. Controller
robustness (grblHAL `da4c8eb`, CI green host-side): the pulse write
treats `-ENOMEM`/`-EAGAIN` as bounded back-off (the UAPI's backpressure
semantics), retries `EINTR`, and completes partial writes; the verdict
parser trusts only a complete document (closing brace, 1 KiB buffer)
and defaults a missing `hold` to true; the listen socket and accepted
clients are close-on-exec so the homing runner can never keep port 23
bound; a missing or unwritable settings file falls back to a RAM-backed
NVS with a diagnostic instead of a crash-respawn loop; `-e`/`-p`
argument walks, the `serial_wait` ≥1 s busy spin, `GFSINK_RATE`/
`GFSINK_DEPTH_MS` ranges, the blocking delay's `sys.abort` test, and
`gfio_wr_attr` short-write/`EINTR`/missing-attr semantics are all fixed;
messages from the SCHED_FIFO shipper and from under the stream lock go
through a raw `write(2)` (no stdio lock convoy); the `--version` C-flags
string no longer carries toolchain path-remapping flags (the buildpaths
QA warning). Daemon robustness (forgectrl `ed2934b`, `-Werror` build +
unit test green): the controller environment is built before `fork()`
and passed to `execle()` (no `setenv` in the child of a multithreaded
parent), a SIGKILL escalation is never aimed at a pid the supervisor
thread already reaped, the settings file is created 0600 (the cloud
password lives there; the Python side matches), the verdict publisher
refuses an over-long document, and the release download carries
`curl --max-filesize`. `laser_button_timeout_s`, `laser_disarm_s`, and
`rail_settle_s` are accepted by `POST /settings` (bounded like the
controller's clamps) and have a home on the panel's GRBL tab. Docs:
`kas/README.md` #5 states the real 16 MiB ring arithmetic (~84 s at
200 kHz; the PREEMPT_RT decision stands on the bounded-queue-depth
argument), the deleted `kernel-module-glowforge.bbappend`/externalsrc
references are gone from kas, `release.sh`, and the cold-build workflow,
`BUILD.md` clones only what a builder needs, `README.md` states the
homing dependency honestly (GRBL mode jogs and cuts cloud-free; `$H` is
camera-referenced homing that needs a Glowforge session until switch
homing lands), `CLOUD.md` and `SERVICES.md` agree that the supervisor
starts controllers, `UAPI.md`'s sysfs tree lists `free`/`streaming`/
`underruns` (with `free` stated as advisory — the `-ENOMEM` write return
is the backpressure primitive) and the `position` counter wrap/saturate
behavior, `SERVICES.md` carries a monotonic-clock rule (no RTC on the
board), the `COOL_FLOW_RISE_C` derivation is documented for a third party
to re-run (`scripts/bench/README.md`; the bench tools take `GF_HOST` and
`GF_SSH`), the pre-first-light no-fire drill's citation names the retained
reproductions (its one-off script was never committed), British spellings
are corrected (the wire-protocol literal `cancelled` untouched),
`3d-models/` is a git repo, dev-machine paths and the build-distro name are
out of every tracked file, and the doc-nit bundle (dual-boot wording,
`tested_against_gf` described as it is wired, the image recipe comment,
the bench README tool list, the panel's System tab) is closed. Pins:
forgectrl `ed2934b`, grblHAL `da4c8eb`, kernel module `1862ad3`,
gfhardware `6c7534a`, gfutilities `6d309ae` — all pushed, bumped, and
`bitbake -c fetch`-verified. **Bench (operator, 2026-08-15): the new
controller and daemon binaries are installed on the board and the
settings file is confirmed 0600** — Phase 11 has no open items.

**Phase 10 (tests & CI) is code-complete; the safety rules are now
machine-enforced.** The grblHAL controller repo's CI builds the
null-sink binary (driver sources under `-Werror`; the core submodule
is upstream code and exempt) and runs three suites on every push: the
**laser stream emission harness** (the G-1 class), a new
**armed-window lifecycle harness** (`scripts/bench/
laser_lifecycle_test.py`: arm-once-per-job with M5/M3 persistence and
the M2 close, sender-change re-consent, grace countdown in Hold, and
blocking-verdict arm refusal — test-the-test proven: a build with the
job-based window reverted fails the first discriminating assertion),
and a **switch-map decode truth table** (D-13): the EV_SW mapping is
extracted into a pure header and asserted, including the inverted
remote-interlock sense whose flip would read a Pro lockout as
satisfied-while-open, and the opt-in e-stop gating. forgectrl's CI
builds with `-Werror` and the tree is warning-free (the remaining
unused-result and deliberate-truncation warnings are now explicit)
(D-30). `kernel-module-glowforge` has a CI at all (D-4): it
cross-compiles the module against linux-fslc 6.12 with the Glowforge
BSP overlay and config fragment, hardfp toolchain, `KCFLAGS=-Werror`
— the same bar the recipe holds — with symbol resolution left to the
image build (a `modules_prepare` tree has no `Module.symvers`). Every
CI sequence was validated locally before pushing — and CI immediately
earned its keep: running the harnesses as a non-root user exposed that
the controller's `mlockall(MCL_FUTURE)` under a finite
`RLIMIT_MEMLOCK` makes every later thread-stack mmap count against the
limit, killing the stream threads at startup. Root (the production
spawn) carries `CAP_IPC_LOCK` and is exempt, so the flashed image is
unaffected; the lock is now root-only (grblHAL `12977eb`). Not
host-testable (bench items, documented per phase): the kernel latch
relock-on-close and dead-man trip, and the motion-liveness gate.

**Phase 9 (build, BSP, and release engineering) is code-complete and
host-verified** (all shell changes pass bash and POSIX-sh syntax
checks; forgectrl builds clean). Shutdown order: controllers stop at
K80, before forgectrl at K90, so runlevel 0/6 never tears down the
cooling engine, fire gates, and broker under a running controller
(B-4). The grblhal/gfcloud init scripts are real emergency levers
routed through new authenticated `POST /controller/stop|start`
endpoints — stop halts the child and holds supervision suspended, not
idle-gated — with `status` verbs and path-anchored pkill fallbacks
(B-6); the forgectrl `restart` self-kill guard matches
`/proc/pid/exe` (B-5). `slotmigrate` gets the 2048-sector grow
tolerance (no more MBR rewrite every boot on disks where the grow
cannot land exactly), progress verification, and a three-attempt
`resize2fs` bound with the counter on p3 (B-7). `CONFIG_IMX2_WDT` is
pinned and the unconfigured watchdog daemon is deliberately dropped —
the hardware watchdog is a boot/system watchdog, and a userspace
petter only added the mid-job-reset failure mode (B-8). The
booted-slot write guard compares device numbers and fails closed under
any `root=` spelling (F-8); settings writes fsync before rename and
never rewrite a file they could not read in full (F-11); the /data
logs rotate size-capped at boot and hourly, and the camera stats spam
dropped ~100× (F-16). Release path: `release.sh` rejects multiple
versions and requires factory-era verification (explicit bypass only);
`mkfw.sh` refuses to pack without the post-sign self-check; the
installer verifies archive product/platform and prompts on a signed
downgrade instead of installing it silently; installer/ffboot temp
paths are `mktemp` (B-13, B-18, B-19, B-20). DTS: the bootargs
fallback is console-only (no `quiet`, no hardcoded SD root) and the
stale 128 MiB ring comment reads 16 MiB (B-11, B-12); wlconf data
files are 0644 (B-16); the U-Boot v2020.01 pin's security posture is
recorded in the recipe (B-17); the bench build scripts carry no
machine-local paths (B-14) and the SSH banner escape is fixed (B-15).
**Bench items:** runlevel 6 teardown order observed; `forgectrl
restart` actually restarts; the routed emergency stop holds the
controller down; a boot on a disk that cannot grow-to-last-sector does
not rewrite the MBR; a `PARTUUID=` cmdline still refuses a write into
the running slot.

**Phase 8 (kernel-module hardening) is code-complete; rides the image
flash.** Probe: `/dev/glowforge` registers last so the error unwind can
never deregister a device userspace already opened; the unwind clears
the SDMA interrupt callback (previously dangling into devm-freed driver
data across an `-EPROBE_DEFER` cycle) and releases the state dirent
(K-7). Remove: every userspace surface comes down before the hardware —
a concurrent attribute read can no longer reach `gpio_get_value` on
freed descriptors — and the dirent is `sysfs_put`, not leaked (K-8).
The fan-tach spinlock is initialized and taken in the IRQ handler (the
cooling engine's fan verdicts ride these two 64-bit timestamps, which
tear on arm32 unlocked) (K-9); tach IRQ setup cleans up after itself
and records only actually-requested IRQs, with idempotent teardown
(K-10). The LED trigger removes its attributes before the sync timer
delete and serializes the simulation step against its store handlers
(K-15). The kernel dead-man now **halts instead of disabling** — no
40 V rail drop, so a crash recovery is never left in the exact state
that wedges the DRV8825 drivers (K-18). Bounds: the safing-path
pin-change off-by-one (K-14); `ignored_faults` capped to the documented
0–7 with the probe fault state decided on the masked value (K-16);
`PIN_LASER_ON_HEAD` joins the SDMA pin set and the stop/shutdown
change sets (K-19); the run-start no-data gate refuses the run on a
failed head fetch (K-20); PIC single-register writes reject values
above the documented 10-bit range instead of wrapping (K-21).
**Bench (on the flashed image):** module load/unload clean under
`CONFIG_DEBUG_MUTEXES`; forced `-EPROBE_DEFER` unwinds without a
dangling callback; concurrent `cat` during remove does not fault; the
Phase 1/3/5/6 kernel drills all re-run green on this one image.

**Phase 6 (motion integrity) is code-complete and host-verified.** A
mid-run underrun or stepper fault is no longer silently absorbed: the
shipper polls `cnc/state` at its own cadence while a kernel run is in
flight and raises the stream fault path — disarm, homing-anchor
invalidation, alarm — the moment it happens (G-2), and the sanctioned
one-shot underrun retry now invalidates the anchor and logs
position-untrusted instead of leaving `homed:true` standing (G-3). The
supervisor unlinks `/run/grblhal.homed` on every controller transition,
so a homed GRBL anchor cannot survive into cloud mode, which re-zeros
the counters it anchors (X-5). Kernel rows (**ride the pending image
flash**): backtrack is bounded by what is physically intact in the ring
and refused outright once the ring has been live-streamed since the
last clear (K-5); `resume` range-checks against the 28-bit waypoint
field instead of silently truncating — 268 435 457 no longer becomes a
waypoint of 1 (K-12); `pulsebuf_total_bytes` is 64-bit with a
saturating 32-bit position ABI, so a long stream cannot wrap it
mid-soak (K-5); ring mutators are mutex-serialized — concurrent
writers on the inherited fd, the clear-vs-run TOCTOU, and the
run-start scratch publish (K-13); and `STATE_FAULT` is recoverable via
`enable` once every non-ignored fault line physically reads clear, so
an edge glitch no longer bricks motion until module reload (K-6).
UAPI.md documents all the contract changes.

**Phase 7 (cloud-mode robustness) is code-complete and host-verified;
all hot-deployable.** Cloud now fails toward stopped-and-safe: the
service loop survives malformed frames with safing in a `finally`, and
a dead WS client thread ends the session cleanly for the supervisor to
respawn (C-2); network exceptions no longer kill the reconnect thread —
an hourly reconnect during a DNS blip cannot take the machine offline
permanently (C-4); the in-run safety poll cannot be raised out of
(`cnc.state` degrades to FAULT, the verdict reader covers `TypeError`
and future-dated timestamps) and `_action_cleanup` stops motion, not
just the beam (C-6, C-24); an accepted action is never dropped and a
crashed one emits a terminal `:failed` (C-11, C-12); the cooling
reporter is exception-proof with a parting report (C-13); Z homing is
bounded (C-15). Input clamps: pulse-header values clamp to their
now-live min/max bounds before touching motion hardware (C-9);
`load_motion` validates the header before the first byte reaches the
ring and its failure return is handled (C-10); the −273.15 dead-sensor
sentinel no longer passes the start-temp gate (C-16); the dead
`firmware_download()` is deleted (C-19); `EMULATOR.BYPASS_HOMING` keys
on a code-set emulator marker (C-21). Hygiene: tokens no longer reach
the logs — no forced DEBUG, no sign-in dump, owner-only log files
(C-8); the homing accelerometer witness samples at ~100 Hz instead of
saturating the head I²C bus (C-14; re-verify the motion-window counts
against the characterized thresholds on the next live homing); one
hostname derivation, fuzz-verified over 200 k serials with the
short-serial trailing dash fixed (C-18); bounded TX queue + locked
`response_id` (C-20); plus C-17/C-22/C-23. **Bench items:** null-sink
starve drill (sender alarms, `homed` invalidated, armed job refuses at
the stale origin); `STATE_FAULT` glitch recovery without a module
reload; malformed-frame and DNS-blip injections against a live
session; oversize/bad-header job rejected before the ring loads.

**Phase 5 (physical-evidence instrumentation) is code-complete and
host-verified.** The machine now watches what it *does*, not just what
it commanded. The cooling engine's 1 Hz tick runs the witnesses:
`cnc/laser_on_sampled` — the sampled, gated output of the hardware
AND-gate — is the emission ground truth, and emission sensed with no
armed window in the recent past stops motion and locks the latch
(repeating while the evidence persists); laser power-good degradation
during an armed window warns once per session; `cnc/faults`
transitions are warned during a run; `pic/hv_current` (the only live
HV telemetry) is ranged per job (A-1, A-4, A-5). The GRBL controller
carries its own in-process witness: emission sensed while the armed
window is closed relocks the latch and raises an alarm (A-1 ctrl
half). The four `pic/lid_ir_*` channels are polled every tick — each
job logs baseline and peaks (the characterization dataset), and the
fire-abort gate (`cool_fire_ir_delta`: sustained rise above run-start
baseline → motion stopped, latch locked, verdict `FIRE` + hold, smoke
airflow held) **ships watch-only (delta 0) until the sensors are
characterized on the bench** (A-2). `/status` exposes the sampled
evidence, faults, HV, and lid IR; the panel's latch row is relabeled
*commanded* with sensed emission and power rows beside it. Cloud: a
failed head capture can no longer leave the measure laser lit — the
capture runs under try/finally and `_action_cleanup` extinguishes the
head emitters (C-3). Kernel (rides the pending image flash): the head
I²C read helpers return signed values with errno propagated, so a bus
glitch reads as an error instead of `beam_detect_analog=65531` /
`accel_irq=1` — the witnesses can no longer be spoofed by a failed
read (K-11). Host verification: forgectrl and the controller build
clean, stream harness all-PASS byte-identical, cloud client
byte-compiles. **Bench items:** command a fire window and confirm
`laser_on_sampled` tracks it (and confirm the idle-state PGOOD
polarity for the panel row); force a head I²C error and confirm the
witnesses report error, not a positive; baseline the lid IR channels
across real jobs and set `cool_fire_ir_delta`; confirm a failed head
capture leaves the measure laser off.

**Phase 4 (stale-gate cluster) is code-complete and host-verified; all
of it is hot-deployable (no kernel rows).** The operator-armed window
is now **job-based**, not 60-second-idle-based: it closes at program
end (`M2`/`M30`/`%`, through the kernel-idle-guarded relock so a queue
tail is never severed), whenever the sender connection changes (the
serial layer exposes a client-session generation; the press that armed
the window belongs to the displaced session), and after the disarm
grace — which now counts down in Hold, Door, and Tool Change too, so a
job abandoned in Hold no longer sits armed for hours (X-3, G-10). The
coolant fire gate is re-checked after the button wait, immediately
before the window opens (G-4), and the wait budget is clamped to
1–3600 s — garbage or zero can no longer mean wait-forever with the
latch unlocked (G-18). Cloud mode's `_button_wait` gets the same
treatment: bounded by the shared `laser_button_timeout_s`, lid
re-checked every pass, and timeout/lid/cancel all relock the latch and
disarm (C-7). The cloud cancel-drop is fixed: a settings action
rejected mid-print no longer wipes the running action's id, so a
subsequent cancel actually stops the cut (C-1). forgectrl: a
controller stop that times out restores supervision instead of leaving
the machine permanently controller-less (F-7); settings mutations are
lock-serialized and a multi-key POST lands as one atomic replace
(F-10); graceful shutdown is busy-aware — fans hold their duty and the
verdict ages out instead of being unlinked, so `forgectrl restart` no
longer feed-holds a live cut and drops exhaust (F-12; the flow-check
heater still goes off unconditionally, as this engine's own heat
source). Host verification: forgectrl and the controller build clean,
the null-sink stream harness passes all emission rules byte-identical
to the recorded baseline, and both Python clients byte-compile.
**Bench items:** finish a job and confirm disarm at Idle within the
cycle (not at +60 s); abandon a job in Hold and confirm it disarms;
kill the pump during the button wait and confirm arming refuses;
cancel a cloud print with a settings action in flight and confirm
motion stops; `forgectrl restart` mid-(dry)-cut holds exhaust. These
are dry/no-fire drills except where GATE A already applies.

**Phase 3 (broker ownership / dead-man second pass) is code-complete
and host-verified.** The "broker changed who owns safing" theme is
closed on the code side. The supervisor writes the two safing lines
(`cnc/stop`, `cnc/laser_latch=1`) on **every** transition out of a
running child — mode switch, diagnostics suspend, shutdown, not just
unexpected death — and again immediately after a SIGKILL escalation
(F-3). The cooling engine is the dead-man for **hangs**: a controller
silent past the 5 s report timeout with the armed window open — or with
`cnc/state` still reading `running` (a preloaded cloud ring can play
for minutes with no live feeder) — gets the same two writes from the
engine itself, and exhaust/intake never drop below cooldown duty while
the kernel still reports a run in progress (X-1). The broker fd is now
`O_CLOEXEC` with only the controller spawn clearing the flag, so
`curl`/`fwup`/`media-ctl` children can no longer pin the pulse device,
defeat the final-close backstop, or EBUSY-storm a respawn (F-6). The
GRBL stream shutdown relocks the latch explicitly, since under the
broker its close is not the final close (G-6); the cloud `_shutdown`
hook stops motion, locks the latch, and files a final disarmed/idle
report in **all** modes — gfcloud and gfhome share the hook (C-5).
OOM/RT hardening: `oom_score_adj` respawn wrapper −1000 / daemon −900 /
controllers −500, and the controller `mlockall`s so the SCHED_FIFO
shipper cannot take a major page fault (X-6; the MHD connection cap
remains the deferred half of F-15). Kernel rows **ride the pending
image flash**: pulse-device exclusivity is an atomic in-use bit instead
of a mutex locked in `open()` and unlocked in `release()` — cross-task
release is the *normal* case under the broker (K-4); a fresh open
starts with the flock dead-man disarmed and shared locks are rejected
(K-17); `thermal_make_safe()` de-energizes only the heat sources
(heater, TEC) — the coolant pump and exhaust/intake stay with the
cooling engine, so a dead-man trip no longer stops circulation and
airflow over a hot tube or airlocks the pump, and the heater soft-PWM
duty is zeroed so its timer holds the pin low (X-4). SERVICES.md now
records the watchdog scope — the hardware watchdog is a boot/system
watchdog, not a laser-safety watchdog; the fast beam stop is the
ring-drain chain, and the cloud-ring-depth residual is covered by the
engine's hang dead-man (X-7) — plus the full dead-man ownership map.
Host verification: forgectrl and the controller build clean
(`-Wall -Wextra`), the null-sink stream harness passes all emission
rules on the changed controller, and the cloud client byte-compiles.
**Bench drills pend the image flash**: SIGSTOP a controller
mid-(dry)-run — motion stopped and latch locked within the silence
window, airflow held at ≥ cooldown duty; kill forgectrl during an
update download — no pinned device, no EBUSY respawn storm; re-run the
armed kill drill on the *expected*-stop path; a kernel dead-man trip
leaves pump and airflow running.

**Phase 2 (GATE B, control surface + release) is code-complete and
host-verified.** forgectrl now has one auth layer applied to every
endpoint (`src/auth.c`): a first-boot bearer token in `/data`, embedded
in the panel and required on every state-changing call; a Host
address-literal check plus `Sec-Fetch-Site`/`Origin` validation that
refuses cross-site (CSRF) and DNS-rebinding requests; `/cool/state`
restricted to a loopback peer so a LAN client can no longer spoof a
thermal stand-down (F-1, F-2). The irrevocable fuse view and
unsigned-firmware installs additionally require the physical button held
(F-19, F-1). A native unit test of the real `auth.c` decision logic
passes all ten cases (authorized POST allowed; CSRF refused even with a
token; rebinding host refused; missing/wrong token refused; panel
bootstrap refused over a rebinding host; loopback report allowed, LAN
spoof refused). Also fixed: the `reply_settings` accumulator overflow
and its unbounded validators (F-4, F-18); cooling-tunable caps + a
resume-below-max cross-check + a loud flow-checks-disabled indicator
(F-5); the upload path is auth+idle+job gated (F-9); the liveness probe
refuses to move the gantry with a lid/interlock open (F-13);
`update_job_running()` cross-checks added to the diag and mode-switch
gates (F-14, partial — targeted checks, not yet a single-lock arbiter);
`machine_is_idle()` fails **closed** on a read error so a connection
flood can no longer read as idle mid-cut (X-2); the fd ceiling is raised
(F-15, partial — the MHD connection cap and moving the camera
`ensure_engine` `popen()`s out of the HTTP callback are deferred);
`esc()` and the panel attribute/innerHTML interpolations are escaped
(F-20); the restore `sh -c` double-shell is gone and the archive name is
charset-restricted (B-9). Release engineering: `debug-tweaks` moved out
of the shared kas config into `forgefirm-image-dev.bb` so the release
`forgefirm-image` is no longer passwordless-root, with a `release.sh`
gate that reads the built rootfs `/etc/shadow` and fails on an empty
root password (B-1); the installer copies `ffboot` out of the
signature-verified new rootfs instead of curl-ing it from a mutable ref
(B-2); `CONFIG_PANIC_ON_OOPS=y` + `panic=10` route a kernel oops into
the laser-safing panic handler (B-3, rides the image flash). **GATE B
requires a bench pass** (a CSRF probe from a second host rejected; a
spoofed `/cool/state` no longer drops the fans; a 13-max-length
`POST /settings` does not crash the daemon; a built release image shows
a non-empty root password), after which — combined with Phase 0's
safety/regulatory text — the first public `.fw` is allowed.

Phase 0: user-facing laser-safety and
regulatory text is in place (LIGHTBURN.md "Before you cut", README,
INSTALL.md "Regulatory and legal" + updater-first update path, a
persistent panel safety banner), the walkthrough no longer claims the
laser cannot fire, bench-machine identity and the signing-key location
are scrubbed from tracked files (bench scripts take `GF_HOST`), and
every repo has a commit-msg hook enforcing commit attribution. Phase 1
(GATE A, uncommanded energy) is **code-complete and host-verified**:
the stream engine records the cycle-end laser-off so idle-gap pads ship
dark and every stream terminates FIRE-clear (G-1), latch writes are
serialized against the shipper's relight (G-5) with the arm-state and
verdict caches made properly atomic (G-19/G-20/G-21), the cooling
report path moved to a bounded-connect reporter thread off the protocol
thread (A-3/G-7), and gf.lock is priority-inheriting with PIC-SPI and
rail-settle work moved outside it (G-8). Kernel fixes K-1 (saturating
decel ramp + EPIT divisor clamp), K-2 (resume-waypoint latch guard) and
K-3 (latch writes under status_lock; FIRE drive never restored mid-run
or mid-ramp) are code-complete and **ride the pending full-image
flash** with the platform-hygiene batch. `scripts/bench/
laser_stream_test.py` now asserts the termination and zero-step-gap
rules across M4, M3-to-stream-end, and cycle-churn sessions (with a
hermetic cooling-verdict publisher): all PASS on the fixed controller
(the M4 session reproduces the recorded baseline byte-for-byte:
28 354 fire ticks, X peak 533 net 0, 534 dark return steps), and a
build with only the G-1 hunks reverted FAILS on the M3 termination
rule — the harness catches the defect class. **GATE A stays open — no
live-fire — until the flashed image passes the bench drills**
(controlled stop decelerates at the default cloud tick, resume with the
latch locked stays laser-less, mid-ramp latch writes do not re-arm
FIRE) and the harness is wired into CI.

Previously — **shared machine services complete and
closed out (2026-08-13).** forgectrl is the one machine-services daemon behind both
controller modes: the cooling engine (single owner of the thermal
hardware), controller-mode supervision, the pulse-device broker, and
the motion-liveness gate. Both controllers are cooling-engine clients
that enforce the published verdict in-process, and cloud mode ran an
**11.4 h signed-in soak** on that final stack (12 auth-token refreshes,
clean stop from the panel and from SIGTERM). First light landed
2026-08-11 (GRBL mode, operator-run) and the armed kill-mid-FIRE drill
passed 2026-08-12. The contract is `forgectrl/docs/SERVICES.md`;
what is left of that work is item 8 under Next work.

Previously — **SD images 20260808011035 built**
(forgefirm-image + -dev): the first images carrying the whole
control-panel era — gfcloud homing, the OpenGlow-branded panel with
the /status dashboard, controller-mode selector + boot dispatch, the
idle settings lock, and all four platform bug fixes (estop gate,
cnc.halt, forgectrl-routed captures, blocking dms chain). Also: the
control panel carries the
**OpenGlow visual identity** (navy header + recreated starburst
wordmark, light content, laser red as accent only) and the status
page is an **operational dashboard**: motion state + true machine
position (kernel step counters anchored at homing via
`/run/grblhal.homed` — the Grbl socket is never polled, a connection
there displaces the sender), coolant temps, pump/TEC, all four fan
tachs (air assist µs @ 8 ppr, chassis fans ns @ 2 ppr — live-checked),
laser lockout (interlock_circuit b3; `cnc/laser_latch` is
write-only), and the safety switches via EVIOCGSW (head sense reads
not-detected with a working head — display it dim, not alarming).
Previous same-day work: control panel + calibration + identity
overrides + multi-key `/settings`; **gfcloud homing LIVE-VERIFIED
end-to-end** ($H → homed at the factory corner in 65 s; four platform
bugs fixed — see Next work #3); fd-blocking protocol pacing; the
fortify step_us_min fix.
Read together with `kernel-module-glowforge/UAPI.md` (the pulse-stream
feeder contract) and `forgectrl/docs/SERVICES.md` (the machine-services
contract).

## Where the project stands

**Platform bring-up: complete and hardware-verified.** Both motion blockers
fixed (cnc probe / 40v-supply; SDMA script relocated to `<26 0xF00>` with a
pre-run integrity guard); the end-of-data protocol reworked and bench-proven
(underrun is a first-class `underrun` state behind the `streaming` attr;
16/16 protocol bench); laser PWM verified at 39.98 kHz (register level);
`CONFIG_PREEMPT=y`; uEnv/u-boot/ulfius build integrity restored; legacy
cloud mode repaired (nvmem identity → fuse hostname verified;
deadman/safety loop; camera error paths).

**The controller spike: achieved.**
- grblHAL (unmodified core) runs on the board, speaking Grbl
  1.1f over **TCP port 23** (LightBurn-confirmed).
- Underrun proof: 100 kHz × 120 s under full load, 150 ms queue, 0.2 ms
  worst write latency, zero underruns. Measured SDMA script ceiling:
  **~165 kHz effective** (~6 µs/byte).
- **The step backend works**: the driver resamples grblHAL's step
  events into pulse bytes and live-feeds `/dev/glowforge`. X and Y jogs
  from TCP G-code move the real gantry; grblHAL and kernel position
  counters agree step-for-step. Motion-only: the laser latch is forced
  locked, byte bit 4 is never emitted.

**First real LightBurn job: 2026-08-02, operator-verified.** Device
setup per `LIGHTBURN.md` (GRBL over TCP:23); a full design job — rapid
in, M4 dynamic-power cut trace at commanded speed, return rapid — ran
smoothly end to end on grblHAL-glowforge (laser locked, motion only).
Two driver fixes came out of the first attempts: the locked laser
spindle (M4/$32 support without fire capability) and the
continuation-wakeup cursor alignment (back-to-back cycles previously
clamped into step bursts — jerky, step-losing rapids; found via the
per-run `clamped` stat from the operator's own job log).

**Milestone 2 (motion quality): bench-verified 2026-08-02.** The factory
motion constants were extracted from the `_RESOURCES` pulse files
(`scripts/bench/puls_profile.py`) and applied end-to-end:
- grblHAL defaults now factory-true: 12000 mm/min max rate (X/Y),
  700/590 mm/s² accel (X/Y). Machine tick default 28160 Hz (the factory's
  own travel-move tick; 10 kHz caps an axis at 187.5 mm/s).
- The sink now applies the whole analog machine config itself at init
  (modes, decay, motor_lock, PIC currents) and switches PIC currents
  run↔hold around motion like the factory did (135/22 running, 33/5 idle,
  drop deferred until the kernel queue has drained).
- Bench (`scripts/bench/bench_m2.py`, all green): sustained 200 mm/s on a
  120 mm jog, exact round-trip positioning, feed-hold parks and resumes
  cleanly, current switching observed live, zero underruns at 28160 Hz.
- NOTE: stored $-settings beat freshly baked defaults — after changing
  `GLOWFORGE_DEFAULTS` values, run `$RST=$` once on the board (the sim
  persists settings in its eeprom file in /data).

**First light: 2026-08-11** — first GRBL-mode burn (operator-run
LightBurn job, chain armed; details in the laser item under Next work).

**Shared machine services: complete, bench-verified, and closed out
(2026-08-11 … 2026-08-13).**
forgectrl is the machine-services daemon: the cooling engine (single
thermal-hardware owner for both controller modes, flow verification and
over-temp policy behind the `/cool/state` + verdict-file channels), the
controller-mode supervisor (one managed child, live `POST /mode`
switching, crash respawn with machine safing, a respawn wrapper on
forgectrl itself with retake-at-idle), the pulse-device broker (one
exclusive `/dev/glowforge` hold for the daemon's lifetime — handovers
and respawns never cycle the 40 V rail), and the **motion-liveness
gate**: the head accelerometer is the only truth about physical motion
(the DRV8825 drivers can wedge unserviceably on rail glitches with
counters running normally — see the hardware facts bank), so the
supervisor probes real motion before each session's first controller
spawn and gfhome refuses to report a homing the accelerometer did not
witness. The contract for all of it is `forgectrl/docs/SERVICES.md`.
Both controllers are clients of the engine: the GRBL driver's
`glowforge_cooling.c` and the cloud client's `coolsvc.py` report job
state at 1 Hz and enforce the verdict file on their own fire paths,
each with a compiled-in run-duty fallback for the case where the engine
is provably absent. Drilled on the board with the operator present:
engine loss mid-flood and mid-flow-check (warning, fans held, heater
dropped, restore and resume), an armed kill-mid-FIRE (FIRE gone within
15–171 ms, latch relocked, burn line ends abruptly), over-temp hold and
auto-resume inside a real cycle, live mode switches, and a **11.4 h
cloud-mode soak** on the finished stack. Remaining polish: Next work
item 8.

## The bench

- **Board**: SSH `root@<machine-ip>` (dev images permit passwordless
  root login). The bench
  machine is a **Basic/Plus** (the control board is common to
  Basic/Plus/Pro). Dev image
  (`forgefirm-image-dev`) on SD; BusyBox userland + python3 + gdb/strace.
  Serial console on ttymxc0 available at the bench.
- **Deploying kernels**: re-burn the SD with the freshly built
  `forgefirm-image-dev-glowforge.rootfs.wic.gz` (deploy dir below).
  Why this works: U-Boot (in eMMC boot0) reads the saved env at eMMC
  user-area 0x80000, which selects the boot device (bench board:
  `mmcdev=0 mmcroot=/dev/mmcblk1p1` = SD), then loads `/boot/uEnv.txt`
  and `/boot/zImage` from that rootfs partition — so the kernel always
  comes from the burned SD. Full map: "eMMC boot & recovery
  architecture" in the facts bank below. **Module-only changes hot-swap**: scp `glowforge.ko`
  over `/lib/modules/<kver>/extras/`, then `rmmod glowforge && modprobe
  glowforge`. NOTE: a module reload turns off the lid LED (relight via
  `/sys/class/leds/lid_led*/target`) and resets analog config (below).
- **Module hot-swap vs kernel re-stamps**: the hot-swap only loads if
  the module was built against the FLASHED kernel's patch state. Any
  edit under the kernel recipe's overlay (e.g. glowforge.dts)
  re-stamps CONFIG_LOCALVERSION_AUTO — and the stamp does NOT
  reproduce by reverting the edit (the kernel patch tree is a fresh
  git commit each do_patch, not sstate-restored), so after any
  overlay edit the module can only ship with a full image flash.
  Batch kernel-overlay edits accordingly. In the tree awaiting the
  next SD burn (batch of 2026-08-08): CFG80211/MAC80211 flipped to
  modules (the regulatory.db boot-message fix, bench record below),
  CFG80211_DEFAULT_PS off (power save default; forgectrl pins it off
  at startup regardless), and `vs-supply = <&reg_3p3v>` on the lm75
  node (was the last queued cosmetic "dummy regulator" probe line
  besides the two SoC USB PHYs). Nothing else queued.
- **Build host**: a Linux build environment (a WSL2 distro works)
  holding the `forgefirm` + `meta-openglow` sibling checkout (`BUILD.md`);
  the ForgeFIRM source repos are fetched by pinned `SRCREV`. Build:
  `cd forgefirm && kas shell kas/forgefirm-glowforge.yml -c 'bitbake
  forgefirm-image forgefirm-image-dev'`. Artifacts:
  `forgefirm/build/tmp/deploy/images/glowforge/`.
- **fwup lab (host)**: a host directory (`<fwup-lab>` below) holds
  host-built `fwup-0.14.2` (factory-era) and `fwup-v1.16.0` under `bin/`
  and the DEV signing keypair `devkeys/fwup-key.{priv,pub}`
  (`fwup-key-raw.pub` = raw 32-byte form —
  what fwup 0.14.2 expects; 1.x reads both). Cross-version compat is
  proven both ways (modern-packed signed archives apply with 0.14.2;
  modern fwup verifies+applies the factory .fw — signer key
  2017-05-001.pub). The production signing-key ceremony
  (UPDATE-SYSTEM.md gate 8) was executed 2026-08-08. **The production
  release key is held offline by the operator** — the installer embeds
  its public key, so releases sign with that key only.
  Pack releases with `scripts/mkfw.sh`; the full pipeline is
  `scripts/release.sh`, invoked as:
  `FWUP=<fwup-lab>/bin/fwup-v1.16.0 FWUP_COMPAT=<fwup-lab>/bin/fwup-0.14.2
  FORGEFIRM_DEV_KEY=<fwup-lab>/devkeys/fwup-key.priv
  FORGEFIRM_SIGNING_KEY=<release key> RELEASE_STAGING_DIR=<dir>
  ./scripts/release.sh <version>` (the publish step needs an
  authenticated `gh`; release.sh prints the exact command).
- **Shell gotchas** (cost real time): PowerShell mangles embedded double
  quotes in git-commit here-strings (avoid `"` in messages); `wsl -- bash
  -c '...'` eats `$VAR` expansions (use script files run via PowerShell,
  not Git Bash, which MSYS-mangles `/mnt/c` paths).

## Running the controller (grblHAL-glowforge on the board)

Source: the `grblHAL-glowforge` sibling repo — the **canonical
grblHAL driver repo** (github.com/ScottW514/grblHAL-glowforge, branch
`main`): core as a submodule at `src/grbl` (→ ScottW514/core fork, branch
`forgefirm` = **upstream master + the step_us_min buffer fix pending
upstream**; the settings-write crash fix merged upstream 2026-08-04 as
grblHAL/core PR #999), `driver.c` implementing the HAL, machine
constants in `src/boards/glowforge.h`. **The controller is spawned and
supervised by forgectrl**: the supervisor starts the controller selected
by `controller_mode` (grbl | cloud) as a direct child, respawns it on a
crash (after safing the machine), and switches modes live via
`POST /mode` / the Status-tab selector. The `grblhal` and `gfcloud` init
scripts defer to it (they remain only as manual emergency stops). The
pulse device arrives as a broker-inherited fd (`GF_PULSE_FD`; see the
pulse-device ownership section of forgectrl `docs/SERVICES.md`) — the
device never closes across mode switches, homing handovers, or respawns,
so the 40 V rail never cycles as a side effect, and the supervisor
verifies **physical motion** (head-accelerometer liveness probe) before
the first controller spawn of each session. Architecture: a wall-paced producer thread runs
the core stepper ISR against a virtual step clock (1000× machine tick)
and maps step events to pulse bytes; a SCHED_FIFO shipper feeds
`/dev/glowforge` with the bounded queue; a recursive core mutex stands in
for interrupt masking. `GFSINK` unset = null-sink mode (full engine, no
hardware I/O — host testing).

1. Build: `bash <repo>/forgefirm/scripts/bench/build-glowforge.sh` in
   the build environment (from Windows, launch it through the WSL
   distro from PowerShell — Git Bash mangles `/mnt/c` paths). Produces
   `build-arm/grblHAL_glowforge` in the checkout (`-O1 -g`; machine
   constants live in `src/boards/glowforge.h`,
   force-included into the core: 53.333 µsteps/mm XY @ ×8, 2.832
   half-steps/mm Z, 0.417" Z travel, 12000 mm/min max, 700/590 mm/s²
   accel — factory-derived, see `puls_profile.py`).
2. Deploy: move the new binary over `/usr/bin/grblHAL_glowforge` (mv
   replaces the inode, so the running instance is untouched), then kill
   the running controller — the supervisor respawns it on the new binary
   within about a second.
3. Standalone start (bench/debug only — requires forgectrl stopped,
   since the broker's exclusive hold on `/dev/glowforge` makes any
   self-open fail EBUSY): `cd /data && GFSINK=/dev/glowforge
   grblHAL_glowforge -p 23 -e /data/EEPROM-glowforge.DAT`. Env knobs:
   `GFSINK_RATE` (machine tick, default 28160 Hz = factory travel tick),
   `GFSINK_DEPTH_MS` (queue depth = feed-hold latency, default 200).
   Standalone, the driver opens the device itself and every takeover
   runs the `rail_settle_s` off-period; under the broker it inherits
   the fd and skips the settle (the rail never dropped). The driver
   applies the full analog machine config at init either way (×8 modes,
   decay 1, motor_lock 8, laser latched, PIC hold currents) and swaps
   PIC run/hold currents around motion. If the baked $-defaults changed
   since the last run, `$RST=$` once (stored settings win). Each motion
   run logs a producer-stats line to stderr (callbacks, µs/call,
   max-behind, clamped) — clamped should stay 0.
4. Connect LightBurn/UGS to `<machine-ip>:23`, or jog raw:
   `$J=G91X40F1200`. `^X` mid-motion aborts via kernel `cnc/stop`
   (controlled decel) and raises an alarm; TCP disconnects never kill the
   process (the deadman fd stays held).

**Protocol-loop pacing is fd-blocking (2026-08-07).** `serial_wait()`
drains TX then `ppoll()`s the listen/client fds with the
state-dependent timeout (idle/alarm 10 ms — 1 ms while a delay
callback is pending — motion 200 µs), so traffic wakes the loop
instantly while idle ticks stay coarse. **Bench-verified: idle CPU
7–12% → ~2%** (1.95% with the camera streaming beside it), status
RTT ~1.0 ms median, jogs exact, `clamped 0` with an active stream.
Client RX is armed only while the ring has a full read's worth of
room, so a flow-control-violating sender is paced, not spun on.

**Fortify overflow fixed in the core (2026-08-07): images before this
fix boot with a DEAD controller.** The Yocto-built binary (compiled
with `-D_FORTIFY_SOURCE`) aborted at `settings_init` — "buffer
overflow detected" in /data/glowforge.log — before serving: the core's
`step_us_min[4]` holds `ftoa(hal.step_us_min, 1)` and our 28160 Hz
stream tick renders "35.5" (5 bytes). Bench builds (no fortify)
silently truncated the adjacent unit string instead, which is why it
never showed on the bench. Fixed by sizing the buffer (the single
local commit the core fork's `forgefirm` branch carries atop upstream
master); `$ES` now reports `[SETTING:0|…|35.5|…]` intact. Repro/diagnosis path if ever needed
again: `scripts/bench/build-glowforge.sh` variant with
`-D_FORTIFY_SOURCE=2`, gdb `set breakpoint pending on` + `break
__chk_fail`, run on the board. **Whole-image boot verified 2026-08-07
on the flashed 20260807214320 SD**: both services autostart from the
image binaries — grblHAL (fortified) serves at 1.0 ms RTT with exact
jogs, $0 min 35.5 intact, $H rejected ($22=0); forgectrl streams
15.0 fps, `"buffers":"cached"`, vpu, 41% CPU; grblHAL idle 2.1%.

## The machine-services daemon (forgectrl, port 8080)

Source: the `forgectrl` sibling repo — the **canonical repo**
(github.com/ScottW514/forgectrl, branch `main`, MIT). forgectrl is the
ForgeFIRM machine-services daemon: **controller-mode supervision** (it
spawns exactly one of grblHAL / gfcloud as a direct child, respawns on
crash after safing the machine, and switches live via `POST /mode`),
the **pulse-device broker** (one exclusive hold on `/dev/glowforge` for
its lifetime; controllers inherit the fd, the rail never cycles on
handovers, and the supervisor is the writers' dead-man), the
**motion-liveness gate** (head-accelerometer probe before the first
spawn of each session, with a rail-off recovery ladder for wedged
DRV8825 drivers and a loud `motion-fault` state), the **cooling
engine** (single owner of fans/pump/TEC/heater for both modes:
`POST /cool/state` job reports in, the `/run/forgefirm/cooling.state`
verdict file out), plus cameras, telemetry, settings, diagnostics, the
web panel, updates, and the **logging tree** (`GET /logs`, `/logs/tail`,
`POST /logs/export`; `forgectrl --render-syslog` at boot). It runs under
a respawn wrapper (its init script) and a restarted daemon retakes
supervision automatically once the machine is idle. The meta-forgefirm recipe pins its SRCREV (bump
deliberately after pushing) and installs the sysvinit script from the
repo's `init/`; bench builds cross-compile with
`forgefirm/scripts/bench/build-forgectrl.sh` (same toolchain-borrow
pattern as build-glowforge.sh). The **machine-services contract** —
the EV_SW switch map, the authoritative sensor conversions, the
hardware single-writer ownership matrix, the cooling channels, mode
supervision, pulse-device ownership, and logging — is
`forgectrl/docs/SERVICES.md` in the forgectrl repo. One ulfius daemon
serves it all, including both OV5648 cameras as MJPEG over the
mainline imx-media pipeline:

- `GET /` — the tabbed machine control panel (Status / Machine /
  GF Cloud / GRBL / Diagnostics / System; ui.c — System carries the
  A/B slot selection, ForgeFIRM updates, image install/restore, the
  wireless regulatory region, and reboot): status page with the
  controller-mode selector (live switch through the supervisor; the
  setting persists for boot), the operational dashboard, a scaled lid snapshot +
  on-demand live stream, and the settings forms for display units,
  homing method, home-position calibration, the nine cooling
  tunables, identity overrides, and the session timeout. All
  settings controls disable (with a banner) while the machine is not
  idle **or a diagnostic is running**. `/?action=stream|snapshot`
  remain the mjpg-streamer-
  compatible aliases (lid camera; LightBurn uses the stream one).
  **Panel conventions (2026-08-08, operator-directed):** the header
  identifies the machine by its **fuse identity** — the factory
  hostname derived from the OCOTP serial (HW_OCOTP_MAC0 base-23 over
  `BCDFGHJKMQRTVWXY2346789`, XXX-YYY; the C implementation matches
  gfhardware id.py over 200k random serials) — regardless of any
  cloud identity override; the `gf_hostname` override is REMOVED
  (the service hostname always derives from whichever serial is in
  effect — gfhome.py re-derives it from an overridden gf_serial);
  **units** are a display-only preference (`ui_units` metric |
  imperial): the backend stores metric, lengths convert mm↔in,
  absolute temps °C↔°F, temperature DELTAS (the flow-rise family)
  scale by 1.8 with no offset, and saves post **only fields whose
  display string changed** (dirty tracking — unit round-trips never
  masquerade as edits); **position always shows**, counters-only and
  painted red while unreferenced (the machine moves fine unhomed —
  relative to wherever it started), normal once anchored; sender
  hints are unopinionated (no named Grbl clients).
- `GET/POST /settings` — the shared machine settings store
  (/data/forgefirm.conf, validated keys incl. controller_mode and the
  cool_* cooling tunables,
  empty-value-clears via query params; gf_password write-only).
  **Writes 409 unless cnc/state is idle** (the controller and homing
  runner read the file mid-run) — live-verified during a jog — **and
  409 while a diagnostic owns the hardware**.
- `GET /mode` / `POST /mode?controller=grbl|cloud` — the supervisor:
  current mode, controller state (`running | stopped | standby |
  motion-fault`), pid, and the motion-liveness verdict
  (`verified | unverified | fault`); the POST is the live idle-gated
  mode switch and the retry lever after a motion fault.
- `POST /cool/state` (job-state reports from the active controller,
  level-triggered ~1 Hz) and `GET /cool/status` (engine phase, verdict,
  temps, report age) — the cooling engine's channels; the verdict the
  controllers enforce is the `/run/forgefirm/cooling.state` file, per
  the SERVICES.md contract.
- `POST /diag/flow-verify`, `POST /diag/flow-calibrate`,
  `POST /diag/abort`, `GET /diag/status` — the diagnostics runner
  (own section below). `GET /status` carries a `diag` flag for the
  UI lock.
- `GET /cam/stream?cam=lid|head` — multipart MJPEG at 1296×972 (2×2
  Bayer-superpixel demosaic, JPEG q75; `FORGECTRL_STREAM_Q` overrides;
  `FORGECTRL_STREAM_FPS` caps the frame rate, unset/0 = sensor max).
- `GET /cam/snapshot?cam=lid|head&res=full|half&q=1..100` — single JPEG,
  default full 2592×1944 (own MIT bilinear demosaic, output verified
  against the gfhardware reference grab).
- `GET /cam/status` — JSON (running/cam/clients/frames/fps/fps_cap/
  encoder/buffers).

Engine model: one worker owns the V4L2 node persistently (media-ctl /
v4l2-ctl configure sequences identical to gfhardware/cam.py, factory
exposure/gain/WB, software hflip in the demosaic); starts on demand,
full teardown after 10 s idle so gfhardware one-shot grabs still work.
The cameras share the hardware video-mux; the NEWEST request wins it
(single-operator model):
- **Streams preempt.** A STREAM request for the other camera kicks the
  current stream clients - their streams end cleanly (viewers freeze on
  the last frame) - and switches. The only stream failure mode is a
  switch timeout (a kicked client not draining within 3 s).
- **Snapshots borrow.** A snapshot of the other camera does not switch:
  the worker pauses the stream, switches, grabs one frame, switches
  back (~1-2 s freeze; "Head peek" on the index page uses this).
  Arbitration compares against the engine's home camera, so stream
  requests racing the borrow window preempt correctly.
The per-camera lamp (`pic/lid_led` / `head/white_led`) is raised to
`FORGECTRL_LAMP` (default 132) while capturing and restored on idle.

Bench (2026-08-03, on the board): stream **15.0 fps** sustained at
1296×972 (NEON demosaic + VPU encode; 3.2 fps on the full software
fallback);
full-res snapshot 2.4 s warm / 2.7 s cold (cold includes the pipeline
bring-up); two parallel same-camera clients share the frame rate; idle
teardown observed. Borrow verified: head snapshot 200 during a lid
stream, the stream riding through the ~1-2 s gap. Preemption verified:
a head-stream request ended the lid viewer's stream cleanly (curl exit
0 mid-stream) and was serving head frames within ~2 s; switching back
likewise. **Motion coexistence proven**: X
round-trip jogs at F1200 with an active stream — producer stats
`clamped 0`, max behind 4.5 ms (the daemon runs at nice +5, single
core). Run by hand: `/usr/bin/forgectrl &` — it logs through syslog
(`/data/log/forgefirm/forgectrl/forgectrl.log`; a terminal, or
`FFLOG_STDERR=1`, echoes the lines) — after `/etc/init.d/forgectrl stop`
(kill before scp when redeploying, text-file-busy).

**LightBurn consumes the stream directly — operator-verified
2026-08-03** ("without issue", via the mjpg-streamer-compatible
`/?action=stream` alias) while jogging the machine from the same
LightBurn session.

**VPU JPEG offload: DONE 2026-08-03, bench-verified — 7.9 fps** (2.5×
the software rate). The stream path demosaics the 2×2 superpixels
straight to planar YUV420 (JFIF full-range 601) and the **CODA960 VPU
JPEG encoder** (mainline coda, V4L2 mem2mem; found by personality, not
node number) does the encode: per-frame **copy 43 ms + convert 75 ms +
encode 7 ms**. Two hard-won facts:
- **Coherent V4L2 MMAP capture buffers are uncached** — demosaicing
  in-place out of one costs ~340 ms/frame at this resolution; one bulk
  memcpy into a cached bounce buffer first (43 ms) makes the same
  demosaic run in 75 ms. The bounce copy is now the fallback path only —
  non-coherent (cached) capture buffers (below) are the default on the
  patched kernel, and all camera paths read the capture buffer directly
  through them.
- The VPU encoder accepts 1296×972 exactly (no MCU-alignment padding
  needed) with quality via V4L2_CID_JPEG_COMPRESSION_QUALITY.
- **A CSI noise/glitch frame can out-size the coda driver's default
  ~2 B/px JPEG capture buffer** (kernel logs "JPEG too large for
  capture buffer" + a vb2 WARN; observed once under streaming+motion
  load). forgectrl requests 3 B/px and drops error-flagged dequeues as
  single bad frames — hardware encode stays active; software fallback
  engages only on repeated consecutive hard failures.
libjpeg remains the automatic fallback (`FORGECTRL_NO_VPU=1` forces
it) and the snapshot path; `/cam/status` reports `"encoder"`.

**NEON demosaic: DONE 2026-08-03 — 15.0 fps, sensor-limited.** The
YUV420 superpixel convert has a NEON kernel (vld2q deinterleave,
vrhaddq greens, vmlal/vrshrn luma, vpaddlq block sums for chroma;
`FORGECTRL_NO_NEON=1` forces scalar): convert 75 → 18 ms, per-frame
copy 34 + convert 18 + encode 7 ≈ 59 ms against the sensor's 66 ms
frame period. The NEON and scalar paths are bit-identical — proven on
a live frame via `FORGECTRL_NEON_CHECK=1` (one-shot memcmp, logs
IDENTICAL). Motion coexistence re-proven at 15 fps: jogs with an
active stream show clamped 0, max behind 7.2 ms (~4 % of the 200 ms
queue) — the worst-case contention signature so far; if real jobs
ever clamp, a stream-fps cap knob is the relief valve.
The IPU cannot help with demosaic (its IC is CSC/scale only — the
`imx-csc-scaler` at /dev/video8 matters only for a future full-res
stream). Not yet done: lens calibration / bed alignment (the
fisheye needs LightBurn's camera calibration pass), and the deferred
5.6 emulator homing-image smoke (the cloud emulator can now be pointed
at live snapshots).

**Non-coherent (cached) capture buffers + stream FPS cap: DONE
2026-08-07, bench-verified on the flashed patch-0010 image.** The
remaining per-frame CPU cost was the ~34 ms bulk copy out of the
uncached V4L2 MMAP buffer. forgectrl REQBUFS with
`V4L2_MEMORY_FLAG_NON_COHERENT`; kernel patch 0010 (meta-glowforge-bsp
linux-fslc, `allow_cache_hints` on the imx capture queue) makes vb2
honor it — CPU-cached mmaps with the cache invalidate done inside
DQBUF — so the demosaic reads the capture buffer in place and the
bounce copy disappears. **Bench (2026-08-07, flashed image): stream
stats `dqbuf 0 ms, copy 0 ms, convert 19-20 ms, encode 7 ms` (the
invalidate is sub-ms in practice), 15.0 fps sustained, daemon 41.5%
CPU with one viewer vs ~66% on the bounce path** — per-frame CPU
roughly halved (~27 ms vs ~60 ms busy). Full-res snapshot through the
cached path visually verified (clean fisheye bed image, live frames
differ). Detection is by the `MMAP_CACHE_HINTS` capability bit: on a
kernel without patch 0010 the daemon falls back to the bounce-copy
path unchanged — **fallback bench-verified 2026-08-07 on the
unpatched kernel** (copy 35 ms / convert 18 / encode 7, 15.0 fps, vpu
— identical to before). `/cam/status` reports
`"buffers":"cached|uncached"`; `FORGECTRL_NO_CACHED_BUFS` forces the
bounce path for A/B; the stats log line includes the DQBUF time.
`FORGECTRL_STREAM_FPS` caps the stream rate — capped frames are
requeued without demosaic/encode (snapshots still ride on them) and
don't count toward fps — **bench-verified 2026-08-07**: cap 5 →
5.0 fps exact, daemon 23% CPU vs ~66% uncapped (bounce path; the
relief valve if future CPU work needs headroom). Default stays sensor
max. Images from 20260807204056 carry forgectrl at the bumped SRCREV
(73283b6), so a fresh burn ships the right daemon.

## Diagnostics (forgectrl-owned hardware tests)

The Diagnostics tab runs tools that **take the hardware over**: the
runner (forgectrl diag.c, one slot) suspends the active controller
through the supervisor (launch is gated on cnc idle + no diagnostic),
drives the loop directly through sysfs — the same model as the bench
characterization scripts — and resumes the controller on every exit
path (completion, tool error, operator abort via `POST /diag/abort`,
safety ceiling); the controller that returns is the selected mode's,
whichever that is. The cooling engine suspends its own writes for the
duration and publishes fire-blocked. `/run/forgefirm-diag.active`
marks the ownership; forgectrl startup recovers a stale marker
(stand-down + controller resume), covering a daemon crash
mid-diagnostic. The laser is untouched throughout (latch stays
locked). While a diagnostic runs: settings POSTs 409, `/status`
reports `diag:true`, and the whole panel locks with a banner. Live
progress (phase, elapsed, both coolant temps, a scrolling log) streams
through `GET /diag/status` on a 2.5 s poll; results persist on the
page until the next run.

Cooling tools (both run at the *configured* duty/window/threshold so
the verdict applies to the check the driver actually runs; trials use
cut-profile chassis fans = the characterization condition; pump-off
windows hard-abort at 48 °C downstream):
- **flow-verify** (~3 min measured): one check with the pump on, one
  with it commanded off, judged against `cool_flow_rise`. PASS =
  threshold separates the readings; margins under 1.5 °C add a
  run-calibration warning.
- **flow-calibrate** (~15-25 min): 3 trials per case, alternating,
  with settle gates between; reports both bands and recommends
  threshold = (flow max + no-flow min)/2 with an Apply button, or
  refuses when the gap is under 3 °C (raise the duty and rerun) —
  the per-machine path for replacement coolant or a swapped pump.

**Cooling tunables are conf-backed**: the nine `cool_*` keys
(flow_rise, flow_heater_pct, flow_check_s, recheck_s, confirm_max_s,
temp_max, temp_resume, cooldown_s, cooldown_max_s) live in
`/data/forgefirm.conf` (forgectrl Machine tab, validated ranges), and
the **cooling engine** (forgectrl cool.c — the single fan/pump/TEC/
heater owner for both controller modes) re-reads them at **every run
start** (env `GFCOOL_*` > conf > compiled default; env stays the
bench-override path — it wins for the process lifetime). The GRBL
driver is a thin client of the engine: it reports job state, enforces
the published verdict in-process (fire gate, hold/resume, the
compiled-duty emergency fallback), and touches no thermal hardware
otherwise; the cloud client works the same way.

Bench record 2026-08-08 (hot-deployed binaries, all through the HTTP
API): **conf plumbing** — `cool_flow_rise=8` posted, next M8's healthy
check read `limit 8.0` → SUSPECT; key cleared mid-session, next M8
re-read 14.4 and the confirming pass cleared the suspicion (also
proving episode continuity across M9/M8). **Takeover** — during a
running verify: grblHAL process gone, marker present, settings POST
409, second start 409. **flow-verify PASS** in 2:42: flow 11.4
(dT 9.7) / threshold 14.4 / no-flow 17.6 (dT 12.8), margins +3.0 and
+3.2; controller back (fresh pid), marker removed, heater 0, pump on
after. Validation ranges live-checked (rise 0.5 → 400, pct 101 → 400,
confirm 45 → 400). UI browser-verified mid-run: Diagnostics panel
streaming phase/temps/log with the lock banner up, Machine tab
Cooling card showing defaults as placeholders, inputs disabled.
**flow-calibrate COMPLETE in 8:45**: flow band 11.6/12.0/12.0
(max 12.0), no-flow band 17.6/17.7/18.1 (min 17.6), gap 5.7 →
**recommended 14.8 — within 0.4 °C of the hand-derived 14.4** from
the original 60-run matrix (the tool independently reproducing the
ground-truth calibration). Result panel + Apply button
browser-verified: the click wrote `cool_flow_rise = 14.8` to the
conf (cleared after; the compiled default stands until the operator
chooses otherwise).

**Units/identity/position panel rework (2026-08-08, later):
OFFLINE-VERIFIED ONLY — board deploy + bump HELD during the
operator's firmware-upgrade bench testing.** Verified against the
`tools/mock.py` harness in forgectrl (serves the ui.c panel with
mock endpoints; POSTs logged): fuse-identity header (sample id), red
unreferenced position (needed the `.kv>span:first-child` selector
fix — the old descendant selector out-specified `.b-bad` on nested
value spans), imperial placeholders 14.4→25.9 (delta) / 33→91.4
(absolute), position 12.34 mm→0.486 in, dirty-save posting exactly
one changed key converted back (27 °F→15 °C), diag bands ×1.8 with
Apply still posting metric, and a units round-trip leaving nothing
dirty. The C serial→hostname derivation matches gfhardware id.py on
200k random 32-bit serials (host-side cross-check). Also
offline-verified the same way: the **fuse-identity viewer** (GF
Cloud tab, `GET /fuse-identity` fetched on demand only — serial,
derived hostname, and the 64-hex SRK password with a
keep-these-secret warning; modal outside the settings lock, both
dismiss paths clear the values from the DOM).
**LIVE-VERIFIED 2026-08-08 after the firmware-testing hold lifted**
(both binaries hot-deployed onto the fresh 20260808171449 image,
which already shipped the driver at the bumped pin): header reads
the machine's **real fuse identity** — the C derivation confirmed
against its known factory hostname — with
`gf_hostname`/`hostname` gone from /settings; position shows
0,0,0 in red on the unhomed fresh boot and re-renders in inches on
the live units toggle (placeholder 25.9, clean metric round-trip,
conf key cleared after); /fuse-identity returns the real 8-digit
serial + the derived hostname + a 64-hex password (verified by shape, not
echoed), modal opens and clears on close; driver smoke: one M8
flow check verified 10.5/9.5 on the redeployed binary. forgectrl
pin bumped to the panel rework revision.

**Wireless regulatory + region setting (2026-08-08, later):** the
boot-time `cfg80211: failed to load regulatory.db` never was a
missing file — packagegroup-base-wifi has always shipped
regulatory.db(.p7s) + iw on both images. The cause:
imx_v6_v7_defconfig builds cfg80211 IN (=y), so it requests the db at
~2.51 s, before `VFS: Mounted root` at ~2.62 s; the load fails (-2)
and stays failed — a later `iw reg set` alone does NOT retry the
file, only an explicit `iw reg reload` recovers it. Fixes shipped:
glowforge.cfg flips CFG80211/MAC80211 to =m (they load with wlcore at
~5.5 s, well after mount, so the direct load succeeds — kills the
message; in the kernel batch above, awaiting the next SD burn), and
forgectrl gained `wifi_country` (System-tab Wireless card, full ISO
3166-1 alpha-2 dropdown, default 00 = world) applied via
`iw reg reload` + `iw reg set <cc>` at daemon startup and on every
change. LIVE-VERIFIED on the flashed 20260808171449 image
(hot-deployed forgectrl): startup domain is the db-backed world
regdom (it shows the 755–928 MHz S1G rules only the db carries),
`POST /settings?wifi_country=US` flipped the kernel to
`country US: DFS-FCC`, and clearing the key returned 00 and removed
it from the conf. The release image still builds under the 200 MiB
slot cap; an explicit wireless-regdb-static image entry was reverted
as redundant (packagegroup-base-wifi covers it).
Power save: the flashed kernel default is on
(CFG80211_DEFAULT_PS=y), so the same forgectrl startup pass pins
`wlan0 power_save off` (cold-boot verified off on the flashed
image); the kernel batch flips the default off too. Quirk: hinting
`iw reg set 00` while the kernel is already in its default world
domain makes cfg80211 intersect world-with-world and report the
alias `country 98` (identical rules, confusing label) — the startup
pass therefore hints a region only when one is set, and hints 00
only to revert a live region change. Consequence, reboot-verified:
with the db loaded and no user hint, cfg80211 follows the AP's
802.11d country IE (the bench AP advertises US — fresh boot came up
`country US: DFS-FCC` with the setting unset; no `country=` in the
supplicant conf, wl18xx does not self-hint), a user-set region
overrides the IE (DE applied while associated to the US AP), and
clearing reverts to the 00 hint. The UI labels the default
accordingly ("Automatic — AP country, else World").

## Release acceptance (forgetest, port 8090)

The release acceptance tool - the catalog, campaigns, domain
fingerprints, inheritance, the always-required core, invalidate-all,
the release gate, and the coverage currency rule - is specified in
`docs/ACCEPTANCE.md`; the tool lives in `forgetest/` and ships only on
the dev image (`forgetest` recipe, `/etc/init.d/forgetest`, HTTP :8090).
Status: **code landed 2026-08-15, host-verified and build-verified;
bench validation pending - ships with the next full image flash** (the
image manifest is an image change: `forgefirm-manifest.bbclass` entries
from every component recipe, the kernel and the module through
`do_deploy`, assembled by `forgefirm-image-manifest.bbclass` into
`/etc/forgefirm-manifest.json`, also deployed next to the image as
`*.forgefirm-manifest.json`). Build proof (dev image `20260815191634`,
built with the classes): the manifest carries all eight components
(forgectrl, grblhal-glowforge with the core submodule's files,
forgefirm-app merged from its three recipes, python3-gfhardware,
python3-gfutilities, kernel-module-glowforge and linux-fslc through the
deploy path, forgetest through the file mode), the DTB hashes and the
modules directory, and layer content hashes that are **byte-identical to
what `scripts/manifest-from-tree.py` computes on the workstation** - the
identity is content-defined, independent of the checkout's commit or
dirty state; forgetest is installed at S95 with the bench scripts. Host
proof: 44 unit tests (campaign
rules, fingerprints, artifact build + gate verification incl. the
negative fixtures - tampered artifact, covered-file change, platform
change, core inherited, stale invalidate, catalog change, implementation
change - and the runner + HTTP API end to end with a fake catalog and a
fake bench tool), the tree manifest generated from the recipe pins with
`scripts/manifest-from-tree.py` (submodule recursion verified on the
grblHAL core), the coverage lint reporting on it, and the gate refusing an
empty artifact cleanly; `.github/workflows/forgetest-ci.yml` runs the
same and **enforces the coverage lint** (every manifest path is covered:
0 uncovered on both the built manifest and the tree manifest) - **green
on GitHub for the pushed tree (2026-08-15).** **Catalog
v1 is complete: 24 tests**, every one a port of a proven bench drill or
of a bench-verified check, with the recorded pass criteria: the core
`image.health`, `kernel.latch-locked-idle`, `kernel.k1-k2`,
`kernel.k3-unlock`, `kernel.fire-abu` (GATE A drills as takeover tests;
K3 and fire B/U prompt for the lid when `laser_pgood` reports HV good)
and `laser.emission-witness` (S400 square, emission peak -> 0, HV rise,
M2 job-based disarm, operator confirms the mark); `forgectrl.auth` /
`settings-bounds` / `panel-serves`, `logs.tree-tail-export` (sanitized
bundle carries no panel token); `motion.pacing`, `jog-roundtrip`,
`liveness-probe`, `cancel-abort`, `deadman` (SIGKILL / SIGSTOP->underrun
/ forgectrl restart mid-move, head returned by the kernel counters);
`cooling.flow-verify` (through forgectrl's diag runner) and
`fans-quiet-after-motion`; `laser.disarm-in-hold`, `expected-stop`
(POST /controller/stop mid-burn, then the operator-judged restart),
`kill-mid-fire`; `camera.snapshot`; `update.slots-and-signature`;
`cloud.mode-switch` (gfcloud comes up and records its service probe) and
`cloud.gfhome-homing`. Not in the catalog by design: the stale-origin
refusal after an underrun (config-dependent - GRBL mode permits unhomed
cutting, see the campaign notes above). The bench tab lists every
`scripts/bench` tool; runnable from the page: `check-pwm`,
`pacing-test`, `bench-m2`, `bench-phase2`, `cp-watchdog`, `accel-fast`,
`bump-seek`, `fire-test`, `gate-a-kernel`, `platform-drills`,
`flow-confirm`, `flow-sampler` (takeover tools get forgectrl stopped and
started around the run); the scope tools, the host-side flow
characterization tools, and the live drills stay ssh/host-run for now.
The coverage currency rule is in `CLAUDE.md`
"Working rules". Bench validation and the bench-tab ports are Next work
item 15.

**Bench campaign opened 2026-08-15 on the flashed dev image
`20260815194415` (manifest identity `2d69a61e…`, equal to the release
build's).** The tool came up on `:8090` with all 24 tests required.
Passed that day, driven through the API with the operator present:
`image.health` (kernel options, module + 16 MiB ring, forgectrl holding
`/dev/glowforge`, K80 controllers before K90 forgectrl, 0600 token and
settings, 2.6 GiB free on /data), `kernel.latch-locked-idle` (interlock
`0x2d`, FIRE 0, LASER_ON 0/0, faults 0), `forgectrl.auth`,
`forgectrl.settings-bounds`, `forgectrl.panel-serves`,
`logs.tree-tail-export` (sanitized bundle carries no panel token),
`update.slots-and-signature` - 7 of 24. One finding, on the tool side:
`forgectrl.auth` first failed because it expected `/fuse-identity` to
answer 200 to the token alone; the endpoint is two-factor (token AND the
physical button held) by design, so the test now asserts both refusals
and never fetches the identity (a 200 would have put the fuse password
in the result log). That FAIL closed the first campaign, as the rules
say; the second campaign held the passes.

**2026-08-16, dev image `20260815215332` (26-test catalog), campaign
`c-20260816171010-cd59`: 14 of 26 satisfied** - the always-required core
`image.health`, `kernel.latch-locked-idle`, `kernel.k1-k2` (controlled
stop 0.09 s, no burst; K2 FIRE window replayed after the resume waypoint
with laser_enable/laser_on 0 throughout, counters back to start),
`kernel.k3-unlock` (mid-ramp unlock drives the latch pin, FIRE drive stays
0), `kernel.fire-abu` (A: no FIRE drive under the lock; B: FIRE driven,
LASER_ON off with the chain unarmed, FIRE clear at end-of-data; U: true
underrun, backstop drops FIRE, stop acks) and `cooling.flow-verify`
(flow 9.5 / threshold 14.4 / no-flow 16.4 C, margins 4.9/2.0, not
thin), plus `camera.snapshot` (lid snapshot half/full + a stream, operator
confirmed the bed) and the seven forgectrl/logs/update tests, which
re-passed on this image and then **inherited across two campaign
closures** - the domain-scoped inheritance and the always-required core
behaved as specified. Two campaigns closed by test-side FAILs, both
fixed: forgectrl answers a started diagnostic with 202 (the test asserted
200); and the takeover wrapper returned as soon as `forgectrl start`
succeeded, so the next test found the machine busy under the
supervisor's liveness probe (`409 machine is not idle`).

**The important finding of the day (machine-side symptom, tool-side
cause):** after the kernel takeover tests, forgectrl's supervisor reported
NO MOTION on its liveness probe, ran the rail-off ladder (5/15/30 s), and
once ended in `motion-fault` - the driver-wedge signature. The cause was
`cnc/motor_lock=15` left behind by the takeover drills (they mask every
axis and never restored the mask), and the supervisor's probe does not
reset the mask: its steps were masked, so no motion by construction. Real
probes read head-accel p2p 1779-2857; the masked ones 144-480; the two
"MOTION OK" ladder recoveries seen under the mask (p2p 541 and 718)
were false positives against the fixed `>=500` threshold, plausibly the
rail re-energize jolt. Two consequences: (1) **the rule, from the
operator: every test starts from, and leaves, the fresh-boot idle state
(atomic clean start), and the baseline is taken after a reboot** - the
runner now brackets every test and bench tool with a baseline pass
(`forgetest/baseline.py`, contract in `docs/ACCEPTANCE.md`), takes a
fresh-boot reference once per boot, and takeover runs capture the
controller-owned kernel attributes on entry and write them back before
forgectrl restarts; the fresh-boot dump of this image (uptime 235 s)
confirmed the fixed values (`motor_lock 8`, `x/y_mode 8`, `x/y_decay 1`,
`step_freq 28160` - the controller's tick, not the probe's 10000 -
`ramp_rate 125000`, hold currents 33/5, lamps and button LEDs 0, heater
and TEC off). Proof: k1-k2 / k3 / fire-abu re-run under the baseline -
counters (0,0,0) before and after, the probe verified in 3 s after every
takeover, no ladder, `post: clean` every time. (2) Two forgectrl items
for the operator's decision, not changed: the liveness probe should write
`cnc/motor_lock=0` for its move (a leftover mask from any tool must not
read as a wedge), and the `P2P_MOVING >= 500` threshold has little margin
over the noise floor seen today (~480) against a real-move signature of
~1800+ - a settle after the rail-on before sampling, or a threshold near
1000, would keep a false MOTION OK from starting a controller on a dead
machine. Also noted: at a fresh boot in GRBL mode `pic/lid_led` is 0 and
nothing in the GRBL stack lights the lid lamp; the lit bed the bench was
used to is cloud mode's `LLvl=132`, which persists across the switch back
to GRBL - a resting-lamp setting in forgectrl would be a product
decision. (Later the same day the operator power-cycled the machine and
the fresh-boot reference read `lid_led=132`: the PIC lights the lid lamp
at power-on; the dark lamp after my soft `reboot` was the module's remove
path. The reference is therefore taken after a **power cycle** -
`docs/ACCEPTANCE.md`.)

**Same day, after the power cycle, campaign `c-20260816181534-d07a`:
22 of 26 - everything but the four live-laser tests.** The motion group
under the baseline: `motion.pacing` (idle CPU 2.7 %, moving 34 %, parked
2.7 %, hold/resume exact), `liveness-probe`, `cancel-abort` (jog cancel
16.8 mm short of 40, `^X` abort mid-move into Alarm with position
retained, `$X`, return drift 0.000), `jog-roundtrip` (8 jogs, peak 10500
mm/min, hold parked, drift 0.000, operator confirmed the gantry) and
`deadman` (SIGKILL respawn 1.3 s, SIGSTOP -> kernel underrun 0.21 s with
the latch locked, forgectrl restart mid-move: the busy controller
finished unmanaged and supervision was retaken at idle);
`cooling.fans-quiet-after-motion` (idle profile back 30 s after M9);
`cloud.mode-switch` (session established 2 s after the switch, back to
GRBL Idle) and `cloud.gfhome-homing` (`$H`, homed in 50.5 s, corner
confirmed). Tool findings fixed on the way, each a real bench lesson:
grblHAL's Idle precedes the machine's by the stream depth and the decel
tail, so motion tests now end on forgectrl's idle; a soft reset (`^X`)
flushes the controller's read buffer and eats a `?` that lands in it, so
the Grbl client re-sends `?` until a report arrives; a killed controller
still reads as running until the supervisor reaps it (wait for a
different pid); a forgectrl restart mid-move ends in a **replace-at-idle**
- stop the unmanaged controller, hold the device, re-probe, start a
supervised one - because the old inherited fd cannot be adopted
(SERVICES.md now says so; the test expected the same pid); the cloud
session's evidence is gfcloud's own authenticate/ws-connect lines, not
the optional firmware-probe file; cloud mode's connect zeroes the kernel
counters at the head's start and its hunt homes the head 245/139 mm to
the corner - the test tells the runner and jogs the head back. Two
product observations left visible as baseline leftovers: `$H` (gfhome)
and cloud mode leave the lid lamp at 236 (gfhome should hand the lamp
back; the mode-switch test hands it back itself because it caused the
switch), and a mode switch back to GRBL keeps cloud's lamp level. The
first `Idle`-before-motion race also lived in the fans-quiet test's
second wait (harmless there). **The operator then ran the four live tests
from the page - `laser.emission-witness`, `disarm-in-hold`,
`expected-stop`, `kill-mid-fire`, all PASS - and exported: 26 of 26,
*Release authorized*, and `scripts/acceptance-gate.py` authorizes the
image's own manifest with the artifact. That was an exercise of the
release mechanism, not a release: no `releases/v…` directory was
committed.** Two observations from the live runs, both restored by the
baseline: each live test left the head a few mm +X of its start (11 /
2.8 / 3.3 mm - the tests should end on a return jog), and
`kill-mid-fire` left `cnc/streaming=1` (the supervisor's controller-exit
safing writes `cnc/stop` and the latch, not the streaming flag; the
respawned controller manages the flag per run, so it is hygiene, not a
hazard - noted for the safing sequence).

**Same day, the forgectrl changes decided from the campaign - landed,
built in the forge-yocto tree, hot-deployed on the bench (forgectrl
`ff9a7c9` + `c8f6558`, recipe pin bumped in `1d9b553`):** (1) the lid lamp
has a resting policy - the `lid_lamp_idle` setting (0-255, default 236,
Settings > Lid lamp), asserted at daemon start, on a settings change
(live), and at every controller spawn, so a warm reboot no longer leaves
the bed dark and a cloud session's level does not linger; the camera
engine owns the write (a running lid capture applies it at teardown). (2)
The liveness probe writes `cnc/motor_lock=0` for its move (a leftover
mask from any tool must not read as a wedge), settles 300 ms after the
run-current step before sampling (the current step jolts the head), and
the moving threshold is 800 (live >= 1040, typically 1800-2900; the
rail-on / current-step jolt up to ~700). Proof, through the acceptance
tool: `forgectrl.settings-bounds` (lamp resting at 236, 256 / -1 /
"bright" refused, 100 applied at once, cleared back to 236) and
`motion.liveness-probe` (every axis masked, forgectrl restarted, the
fresh probe MOTION OK on the first try at p2p 2047/1341, mask cleared by
the controller's init). The baseline expects the lamp at the setting now
(the boot capture is the record, not the lamp reference), and its settle
waits for the controller to be running - the post pass had run between
the probe's own writes and the controller's init writes once. **Images
`20260816191838` (forgefirm-image, v0.1.0, 192.7 MB rootfs) and
`20260816191951` (forgefirm-image-dev) are built on that tree - forgectrl
`c8f6558`, the day's forgetest, acceptance identity `c72448c2…` equal on
both - and archived under `images/20260816191838/` with checksums (the
previous pair, `215236`/`215332`, under `images/20260815215236/`).**

**2026-08-16, dev image `20260816191951` flashed: every test came up
`domain-changed`, none inherited - the expectation above ("every domain
forgectrl does not touch inherits") was wrong, and the tool was right.**
The two dev-image manifests differ in exactly one platform field:
`platform.layers.meta-forgefirm.content_sha256` (`b2d13d87…` →
`7ef5555d…`); machine, kernel modules and DTB hashes are equal, and the
only components that moved are forgectrl (7 files) and the dev-only
forgetest. The only non-`.md` change in `meta-forgefirm` between the two
builds is the one-line SRCREV bump in `forgectrl.bb` (`1d9b553`) - the
layer is content-hashed into the platform identity, the platform is
folded into every fingerprint, so the pin bump counted as a platform
change and invalidated the whole catalog. Structural, not a fluke: every
component update that ships in an image rides a pin bump in a
content-hashed layer, so under that rule every image with any component
change was an invalidate-all and the per-domain inheritance the contract
promises could never hold across images (the component entry already
carries the change file by file; the pin double-counted it). Fixed the
same day: component pins live in `<recipe>-pin.inc` (SRCREV + the PV that
moves with it, nothing else) and `forgefirm-image-manifest.bbclass` leaves
`*-pin.inc` out of the layer content (`FORGEFIRM_MANIFEST_PIN_SUFFIX`),
mirrored in `scripts/manifest-from-tree.py` and proven by
`forgetest/tests/test_tree_manifest.py` (pin bump → hash unchanged; recipe
body change or a pin written into the recipe → hash changed, the safe
direction); the six component recipes (forgectrl, grblhal-glowforge,
forgefirm-app in meta-forgefirm; kernel-module-glowforge,
python3-gfhardware, python3-gfutilities in meta-openglow) require their
pin files and resolve the same SRCREV/PV under bitbake. A second, smaller
contributor stays as designed: a test's implementation hash is its suite
module, so the day's edits to `suite/{cloud,cooling,forgectrl,kernel,
motion}.py` alone would have re-required 16 of the 26. **Consequence for
the bench: the fix changes the layer content itself, so the first image
built with it is a platform change against everything recorded so far -
that image's campaign is a full one, unavoidably; from then on a
component pin bump re-requires only the tests covering that component.
Run the full campaign on the first pin-file image, not on `191951`.**

**2026-08-16, bench-tab ports complete (item 15b).** Every tool that can
run against the machine is now runnable from the bench page: the scope
tools (`pwm_sweep`, `pwm_hold` - now a takeover with a locked-state guard:
the latch relocked, refused if FIRE or LASER_ON reads active;
`pwm_stream_test` with a PASS/FAIL exit), the flow characterization
family (`flow_characterize`, `flow_recheck_char`, `flow_warm_validate`,
`flow_matrix` as takeovers - forgectrl owns the thermal hardware, so the
page's takeover replaces the tools' own controller stop/restart, whose
command line predated the supervisor; `flow_sustained`, `fan_test` and
`temp_calibrate` stay dry), the escalation drill (`cool_confirm_max_s`
shortened through forgectrl's settings and restored; the setting's
minimum, 60 s, is the default budget) and the live drills (`<drill> [S]
[F]`, all six, the token from the board). The host tools keep working
from a workstation: `scripts/bench/gfbench.py` resolves `GF_HOST` (host
mode, ssh) or the board itself (local mode; the page runs them that way
with `GF_HOST=127.0.0.1`, `GF_TOKEN`, and their data files under
`/data/forgetest/bench/`). Not ported, by nature: the two null-sink CI
harnesses and the `.puls` decoder. Proof: `forgetest/tests/
test_bench_registry.py` (registry <-> `scripts/bench` consistency, every
ported tool builds its command line, every script compiles, gfbench host
and local modes), the server test (a scope tool runs inside the takeover
wrapper; the bench environment reaches the tool), and a local-mode smoke
run on the bench (`temp_calibrate.py watch`, `gfbench.setting`, the
token) staged in `/tmp` and removed. **The ported tools themselves have
not been exercised from the page on the bench yet - that rides the next
dev image (the confirmation campaign's image).**

## Hardware facts bank (measured)

- **DRV8825 stepper drivers wedge on 40 V rail glitches** (factory board;
  the TMC2130s belong to the upgraded OpenGlow board only). A glitch can
  leave the drivers unserviceable: SDMA playback and the position
  counters run normally while the motors produce nothing. Their reset
  lines are strapped (no kernel pin), `cnc/faults` does not flag the
  state, and whether a given rail power-up wedges them is chance —
  identical settle cycles produce different outcomes. Recovery: a longer
  true power-off (the forgectrl supervisor ladders 5/15/30 s) and, at
  worst, a full machine power cycle. Consequences: **counters, anchors,
  and `H:1` are never proof of motion**; keep the rail up (every
  power-up is a wedge lottery), which is why the pulse-device broker
  exists and why there is no idle-rail-off policy.
- **Motion liveness = the head accelerometer** (`glowforge.dts`
  `head-accel`, i2c-3 @0x1e — resolve iio devices by bus path, never by
  index; lid = i2c-0 @0x1e, board = i2c-3 @0x1d). Bench-characterized on
  an identical commanded 30 mm move: wedged drivers ≤ ~210 counts
  peak-to-peak on X/Y (noise floor at 1 g ≈ 16384); real motion
  ≥ ~1000 p2p. The forgectrl liveness probe gates controller start on
  p2p ≥ 500 (dead ≤ 250); gfhome requires at least one accel-witnessed
  motion window before a quiet service counts as homed. Raw sysfs accel
  reads are slow (~150 ms each) — enough for a binary verdict over a
  multi-second window, not for waveforms (iio buffers exist, no trigger
  devices in this kernel).
- **Any probe/liveness move goes RIGHT (+X) first, then back**: a cable
  lives at the end of LEFT travel and must never be crushed.
- **WL1805 Wi-Fi rides uSDHC1** (mmc0, 4-bit, SD-high-speed at 49.5 MHz,
  `no-1-8-v`; IRQ GPIO6_04, WLAN_EN GPIO5_26). Factory pad control, now
  ours too: CMD/DATA `0x17069`, CLK `0x10069` (SPEED_MED, DSE 48 Ω, fast
  slew, HYS; 47 kΩ pull-up on CMD/DATA only). eMMC (uSDHC3) and the SD
  slot (uSDHC2) use `0x17059`/`0x10059` (80 Ω), SD2_DAT3 `0x13059`. An
  SDIO CRC error surfaces as `sdio write failed (-84)` and costs ~1 s of
  Wi-Fi (wlcore firmware recovery) — see Next work item 13.

- SDMA pulse engine: ring size = the `ring_mb` module parameter
  (default 16 MiB; power of two, must fit the 16 MiB `cnc-pulsebuf` DT
  pool; both were 128 MiB before 2026-08-03 — shrinking returned
  ~112 MB, board now shows 469 MB to Linux). Free = size − 32 KiB gap.
  **Bench-verified at 16 MiB on the flashed image**: 20 MB streamed at
  100 kHz through the wrapping ring, 0 ENOMEM, 0.4 ms max write
  latency, starve → `underrun` per protocol; $H and jogs clamped 0.
  The ring caps legacy cloud-mode job length (whole-file preload:
  ~1 MiB per 100 s of 10 kHz stream); the grblHAL live feed keeps only
  a few KB in flight. Script effective ceiling ~165 kHz; position
  counters (`sdma_context` sc0/1/2 = X/Y/Z steps, sc3 = bytes) match
  grblHAL exactly.
- Byte layout & rules: see the UAPI.md feeder contract (authoritative).
- Z: bit 6 SET = lens UP = +Z (hardware-verified; pulsedata.py was the
  inverted party, fixed). Home = hall trigger at TOP; usable travel ≈ 30
  half-steps ≈ 10.6 mm ≈ 0.417"; 0.3534 mm/half-step. Never blind-drive Z
  — hall-supervised only.
- XY: 0.15 mm per full step; DIR bit set = −X / +Y (Y1/Y2 complementary).
  **+Y physically moves the gantry toward the FRONT** (operator-verified
  2026-08-03). Home corner (convention, for the planned limit-switch
  homing) = back-left (X min, Y min), workspace all-positive from that
  corner.
- Factory motion profile (measured from `_RESOURCES` pulse streams with
  `puls_profile.py`): accel ≈ 700 mm/s² X / 590 mm/s² Y on v2.6.0
  firmware (2018 firmware used ≈1000); header HAxr=132/HAyr=112/HAar=133
  ⇒ ≈5.3 mm/s² per HA unit. Travel moves peak 202 mm/s vector
  (≈ 8 in/s) at STfr=28160 Hz; prints/hunts run STfr=10000. Cut feed in
  the sample print: 145 mm/s. Z cadence ≈ 61–115 ms per half-step
  (≈ 5.7 mm/s max).
- Factory analog config (constant across all captured jobs, 2018→2026):
  PIC currents X 135 run / 33 hold, Y 22 run / 5 hold (axis DAC scales
  differ by design); x/y_decay=1; ×8 microstepping; run currents applied
  only while motion plays, hold otherwise.
- Laser PWM: 39.98 kHz register-verified (divider 13 × 127 counts).
- Switches: truthy = closed/OK for lid/doors/button. **SW_INTERLOCK is
  INVERTED**: the remote interlock (the regulatory 2-pin lockout
  connector) reads ACTIVE only when the loop is OPEN. Basic/Plus —
  including the bench machine — ship the connector factory-jumpered, so
  the bit reads 0 = satisfied/good-to-go; Pro brings it out for an
  external lockout chain. Must NOT gate motion (beam is
  hardware-gated).
  **`hv_enable` (EV_SW bit 4, GPIO4_06) is the readback of the safety
  chain's HV_ENABLE output** through the U24 inverter — not an input.
  Active for the whole duration of any run (the window in which the
  charge pump is fed and HV_ENABLE is alive), inactive at idle, and it
  drops 454 ± 3 ms after the last charge-pump pulse (one-shot t_w measured
  pulse-to-drop 2026-08-15 with `scripts/bench/cp_watchdog_timing.py`:
  451.8 / 455.6 ms; feed period 199.98 ms; the pad-level jog
  characterization dates from 2026-08-07, sampled at 20 ms through X and
  Z jogs, ~70/75 samples). It gates nothing anywhere — it is telemetry (`/status`
  `switches.hv_enable`, control-panel "HV enable"). Naming note: the
  factory design labels this net **E-STOP**, and dated entries below
  written before the rename (through the earlier 2026-08-15 records)
  call it `estop`/`SW_ESTOP` with the pre-rename polarity (the device tree then declared the pin active-high,
  so the bit read HIGH at idle and LOW through a run — the same physical
  behavior, inverted); the DTS now declares it active-low so the bit
  reads as HV_ENABLE itself. The former `estop_halts_motion` /
  `MOTION.ESTOP_HALTS_MOTION` opt-in (gate motion on this line, for a
  hypothetical retrofit) is removed: it only ever made sense while the
  line was misread as an e-stop input, and a real e-stop belongs in the
  lid-switch chain (`docs/SAFETY.md`). Doors/door1/door2 stay stable
  during motion.
- Machine identity from OCOTP nvmem: HW_OCOTP_MAC0 is the serial,
  base-23-encoded to the factory hostname — fuse-verified on the bench
  against the factory label. The bench machine's actual values are
  deliberately not recorded here: this is a public document and a fuse
  identity cannot be rotated.

### eMMC boot & recovery architecture (dumped from the bench board 2026-08-08)

- eMMC (`mmcblk2`): 3.6 GiB user area + two 16 MiB hardware boot
  partitions (`mmcblk2boot0/1`). Factory user-area MBR (per the factory
  `.fw` manifest): p1/p2 = 200 MiB rootfs A/B at blocks 8192/417792,
  p3 = `/data` from block 827392 to end of disk. (The bench board runs
  the legacy ForgeFIRM layout instead: p3 shrunk to ~1.9 GiB plus a
  1.3 GiB p4.)
- **U-Boot lives in boot0** at 1 KiB (IMX IVT header), not in the user
  area — user-area block 2 reads blank on the bench board even though
  the `.fw` `complete` task writes a U-Boot copy there. Any boot0
  rewrite below 0xC0000 risks the bootloader.
- **Saved env**: user area 0x80000 with redundant copy at 0x82000 (the
  area `ffboot`/`fw_setenv` targets; boot0's own 0x80000 region is
  zeros). Slot selection = `mmcdev`/`mmchwpart`/`mmcpart`/`mmcroot`;
  bench board reads `mmcdev=0 mmchwpart=0 mmcpart=1
  mmcroot=/dev/mmcblk1p1` (SD boot). Gap: `ffboot` sets three of the
  four but never `mmchwpart` — it relies on the saved 0.
- **Default (compiled-in) env boots recovery**: `mmcdev=1 mmchwpart=1
  boot_recovery=yes` — a blank/corrupt env lands in recovery mode, not
  a brick. `bootcmd`: select mmc dev+hwpart → load+import
  `/boot/uEnv.txt` from the selected partition → if
  `boot_recovery=yes`, boot kernel+DTB from raw boot0 sectors, else
  load `/boot/zImage` from the slot's rootfs. U-Boot itself polls the
  button at power-on ("Recovery boot requested by user; release button
  to enter" / "Button held too long, booting normally"); it also has
  watchdog-timeout boot-flag strings (semantics untraced).
- **boot0 map**: MBR / U-Boot @1 KiB / zeros @0x80000 / recovery DTB
  @0xC0000 (`fdt_dev_addr=0x600`, 64 KiB slot) / recovery zImage
  @0x100000 (`image_dev_addr=0x800`, 5 MiB slot, kernel 3.14.28) /
  recovery squashfs = `boot0p1` @6 MiB (10 MiB slot, 8.6 MiB used,
  built 2018-03-09).
- **boot1 map**: MBR / squashfs @1 KiB = `boot1p1` (10.6 MiB used),
  mounted as the recovery `/usr` (python runtime) by
  `init.d/recovery-usr`.
- **Recovery userspace** = the factory setup webapp (bottle): WiFi
  setup/AP, log export, `/version`, and `.fw` upload (→ tmpfs →
  `glowforge-updater -f` → fwup signature check against
  `/glowforge/pubkeys` → writes slot A → flips env). It is never
  updated in the field — `.fw` updates don't touch the boot
  partitions, so every machine still runs its as-manufactured
  recovery.
- **Bench slot contents** (probed 2026-08-08, `ffboot -l`): eMMC slot 1
  = factory **20240612194245** (the machine's last cloud update, June
  2024 — the newer slot and the factory-archive candidate), slot 2 =
  factory 20220810204015, legacy p4 = ForgeFIRM v0.1.0 (written during
  the Phase 0 slot-agnostic test). Factory `/etc/version` is a numeric
  datetime stamp — newest-slot selection is integer comparison.
- **Factory `.fw` format** = signed fwup 0.14.2 archive (ZIP:
  `meta.conf` + `meta.conf.ed25519` + payloads). Tasks: `complete`
  (MBR, U-Boot to user area, zero both env copies, rootfs → slot A,
  zero p2/p3 heads) and `upgrade.a`/`upgrade.b` (raw-write
  `rootfs.ext4` into a slot). Factory updater flow: authenticated
  `GET <server>/update/current` → `{version, download_url}` →
  resumable download to `/data/glowforge.fw` → verify → apply to the
  INACTIVE slot → `fw_setenv mmcpart mmcroot` → reboot. Factory
  `rootfs.ext4` is 65 MiB; the ForgeFIRM rootfs is ~141 MB used, so it
  fits a 200 MiB slot with headroom.

## Next work (in rough order)

1. **Backend milestone 2 — motion quality: DONE and human-verified
   2026-08-02.** Operator confirmed motion is "butter smooth" (and near
   silent) on a full observation run — slow/fast/diagonal/zigzag jogs at
   up to 200 mm/s under grblHAL-glowforge with the factory-true analog
   config. The pre-tuning loudness was the 150/150 currents + unset
   decay mode. Milestone closed.
2. **Laser mapping** (gated on the scope session): spindle → power bytes
   (bit 7) + bit 4 laser-enable, M3/M4/$32 semantics, PWM-reset rule per
   the contract. **No live fire before the standing scope gates.** Gate
   status:
   - **GRBL-MODE LASER SOFTWARE: IMPLEMENTED 2026-08-09, bench-verified
     without fire. FIRST LIGHT LANDED 2026-08-11 — first GRBL-mode burn
     completed (operator-run LightBurn job, chain armed, motor-rail
     settle in place).**
     - Architecture: the real spindle lives in
       `grblHAL-glowforge/src/glowforge_laser.c`; per-segment spindle
       updates (the core's laser-mode path, running on the stepper
       producer thread at exact virtual-tick positions) map power/fire
       transitions onto the pulse-byte grid via `gf_stream_laser()`,
       and the shipper emits them: a power byte (0x80 | 7-bit duty,
       raw PWMSAR counts, 127 = 100 %) inserted ahead of the first
       tick byte it covers, FIRE as bit 4 OR'd into tick bytes. The
       spindle PWM is precomputed to a period of exactly 127 so
       computed values ARE power bytes ($30 default 1000 → S1000 =
       127). Contract rules enforced structurally: a power byte leads
       every kernel run before any fire bit (run start resets duty to
       ~100 %), transitions are coalesced per tick so power bytes are
       never consecutive, and power bytes cost no machine tick (the
       SDMA script processes the following byte in the same EPIT
       interrupt), leaving the wall-clock due math untouched. Fire
       only ever rides motion segments of laser blocks - jogs, G0 and
       homing are fire-free by construction, and the end-of-data
       backstop covers every stream end.
     - **Arming - the operator's button press is required.** The first
       laser-on of a job (M3/M4, always planner-synced by the core)
       refuses outright if a coolant fire gate stands, else forces the
       run fan profile on, unlocks the kernel laser latch, lights the
       button white and blocks the gcode stream - pumping real-time
       traffic exactly like the homing session - until the operator
       presses the physical button (EV_SW bit 2), a soft reset aborts,
       or `laser_button_timeout_s` (default 300 s) expires into
       alarm 3. The armed window survives S changes and M5/M3 toggles
       (no re-prompt mid-job) and closes - relocking the latch - after
       `laser_disarm_s` (default 60 s) of spindle-off idle, or
       immediately on alarm/homing/reset/stream fault. Both keys live
       in the shared machine config, re-read per arm.
     - **Underrun policy while armed: fail safe, no retry.** The
       stop/run recovery restarts the kernel run, which resets the
       duty to ~100 % - replaying queued fire bits would fire at full
       power - so an armed underrun acks the kernel and faults (alarm,
       latch relock). Motion-only streams keep the one-shot retry.
     - **Coolant fire gates live** (`gfcool_fire_ok`): flow FAULT or
       over-ceiling coolant temperature (resume-gate hysteresis)
       blocks arming and suppresses fire mid-job with a loud warning.
       While armed the run fan profile + flow interrogation are forced
       on regardless of the sender's M8/M9; a flow SUSPECT/FAULT
       verdict inside an armed window takes the safe posture (feed
       hold + run airflow; laser mode drops the spindle in hold).
       SUSPECT auto-resumes on a clean re-check; FAULT leaves the hold
       and the gate for the operator.
     - **Host verification** (`scripts/bench/laser_stream_test.py`,
       null-sink + `GFSINK_DUMP` stream capture, M4 job S500→S1000
       with a G0 return): power byte leads the stream, no consecutive
       power bytes, first FIRE bit rides nonzero duty, M4 dynamic
       accel scaling visible (duties 44/52 on the ramp), S500 plateau
       63 / S1000 127 exact, 28 354 fire ticks = the cutting time at
       28160 Hz, X peak 533 steps net 0 (steps survive the
       insertions), and 534 dark steps after the last fire bit = the
       entire G0 return.
     - **On-board no-fire verification 15/15 PASS** (chain unarmed,
       nobody at the button; the drill script was a bench one-off and
       is not retained — the arm-window state machine is reproduced
       host-side by `scripts/bench/laser_lifecycle_test.py` and grblHAL's
       `tests/laser_arm_test.c`, and the latch readbacks on hardware by
       `gate_a_kernel_drills.py` and `live_fire_drills.py`): latch locked
       at idle and through jogs (interlock_circuit 13), M4 → prompt +
       latch unlocked (5) + button LED white + run fans forced +
       status served during the wait, soft-reset abort relocks + LED
       off, 3 s timeout drill → warning + ALARM:3 + relock, jogs
       clean after. One transient on the first-ever arm: the
       air-assist run write didn't land (204) - a head-I²C first-write
       blip; deterministic PASS on every rerun, and real jobs re-apply
       run fans with every M8. Note for senders: a disconnecting
       sender leaves a pending arm wait until the button timeout
       clears it (latch relocks then).
     - **Remaining commissioning items** (first light itself landed
       2026-08-11; operator present, coolant flowing, never
       autonomous): verify the hardware button latch persists across
       kernel-run gaps mid-job (if OK_2_FIRE drops between motion
       bursts, the fix is a stream keepalive across armed gaps);
       warm-baseline flow-check behavior under real laser heating;
       then the planned low-temperature gates and TEC handling below.
       Interlock-trip recovery came out of this list on 2026-08-12 —
       exercised in commissioning runs (see the readback cross-check
       below).
     - **2026-08-11: the failed first-light attempts' no-motion root
       cause — fast 40 V motor-rail bounces — found and mitigated.**
       An off→on bounce of the 40 V rail within ~tens to hundreds of
       ms (the gfhome→grbl homing handover measured 38–360 ms in
       dmesg) can leave the supply folded back: SDMA playback and the
       position/byte counters run in exact real time while the X/Y
       motors produce no torque, or stall mid-sweep. Bench matrix:
       raw replay of the captured job stream (bytes verified to carry
       correct steps/fire/power content) reproduced no-motion with
       perfect counters; `disable` → ≥2 s rail-off → `clear_all
       (lseek 0)` → `enable` restores torque; a deliberate 40 ms
       bounce reproduced a mid-sweep stall; one post-heal baseline
       still failed — **the rail is marginal at the hardware level;
       watch it**. Exonerated by bisection (Z-hall stream probes +
       operator-observed 20 mm X sweeps): stream content, kernel
       module and SDMA context, the granular lseek clears, analog
       config values, PIC currents, close/reopen, stop, halt.
       Driver mitigation (grblHAL-glowforge b7264bf): every takeover
       of the pulse device (init and homing-session resume) starts
       with a deliberate rail-off settle, conf key `rail_settle_s`
       (default 2.5 s, 0 disables).
       **SAFETY COROLLARY: advancing position counters are NOT proof
       of physical motion** — an armed job can fire with the gantry
       stalled (dwell burn). The laser milestone needs a physical
       motion-liveness gate (limit switches when they land, or the
       head accelerometer); until then the first-light procedure is:
       operator watches from the first commanded move and stops the
       job on any no-motion.
     - **2026-08-11 (later, same day): root cause corrected and the
       liveness gate landed.** The supply is fine — the **DRV8825
       stepper drivers wedge on rail glitches** (operator diagnosis;
       see the hardware facts bank): whether a given power-up leaves
       them unserviceable is chance, which is why one clean-settle
       baseline still failed. The mitigation stack is now: the
       pulse-device broker (the rail never cycles on handovers), the
       supervisor's **head-accelerometer liveness probe** before each
       session's first controller spawn (+X-first per the cable rule,
       laser latched; rail-off recovery ladder 5/15/30 s on a dead
       verdict; `motion-fault` state when the drivers won't recover),
       and **gfhome's hardened completion** (a run of near-identical
       cloud corrections aborts the session; quiet without an
       accel-witnessed motion window is a failure, not a homing —
       proven the hard way when the service repeated one correction
       eleven times into a motionless gantry, gave up, and the old
       quiet heuristic reported homed). A genuine accel-witnessed
       homing (8 motion windows, head at the corner,
       operator-confirmed) closed the episode.
   - **LASER_PWM waveform: PASSED 2026-08-02** (scope on the physical
     pin). Method: direct PWMSAR duty steps (`scripts/bench/pwm_sweep.py`
     / `pwm_hold.py`) with the controller stopped, cnc `disabled`
     (steppers unpowered), laser latch locked, lid closed;
     `laser_on_sampled` stayed 0 throughout. Measured: 25.0 µs period /
     40 kHz at every duty; 50/25/75 % confirmed visually; low end
     cursor-measured **6.4 % vs 6.3 % commanded** (PWMSAR=8) — clean
     pulse, no runts, carrier stable across the full range. Matches the
     register-level audit numbers (divider 13 × 127 counts, 39.98 kHz).
   - **Stream-path power bytes: PASSED 2026-08-02** (scope on
     LASER_PWM, `scripts/bench/pwm_stream_test.py`: power-bytes-only
     program preloaded and played by the pulse engine; steppers
     energized but motor_lock=15 + zero step bits — position counters
     pinned at 0). Operator observed the full staircase AND both
     contract rules on the pin: **run-start duty reset to 100%**
     (first pulses would fire at full power unless the stream's first
     power byte precedes its first FIRE bit) and **consecutive power
     bytes dropped** (saw 25 % where a 75 % byte rode directly behind;
     75 % applied only after a spacer). Also measured: **duty persists
     after end-of-data** (PWMSAR retains the last value; the end-of-data
     backstop forces FIRE/step lines low, not the power setpoint) — the
     laser-off guarantee rests entirely on FIRE.
   - **Laser latch + safety-chain gating: scope-verified 2026-08-02**
     (`scripts/bench/fire_test.py`, probe on the PSU-connector LASER_ON
     pin; power byte 0 throughout, zero step bytes, HV unpowered,
     operator at the power switch; phase B latch-unlock executed by the
     operator). Phase A (latch LOCKED): 40,000 streamed FIRE bits →
     pin dead flat AND kernel `laser_enable` stayed 0 — the latch
     severs the FIRE drive entirely. Phase B (latch unlocked, chain
     unarmed): kernel `laser_enable=1` mid-window, but the PSU pin
     stayed flat and `laser_on`/`laser_on_sampled` stayed 0 — the
     factory board gates LASER_ON behind OK_2_FIRE exactly like the
     OpenGlow AND design (FIRE ∧ OK_2_FIRE, active high at the PSU
     pin). **Interlock snapshot semantics pinned by experiment**
     (13→7 during the unlocked FIRE window): b0 = SoC-side LASER_ON
     monitor, active LOW (1 = not lasing); b1 = FIRE, active high;
     b3 = latch, 1 = locked/0 = unlocked.
   - **≤1-tick FIRE drop at underrun/end-of-data: PASSED 2026-08-02**
     (scope on GPIO2_IO30, the SoC FIRE drive feeding the safing
     logic; `fire_test.py` B and U, operator-executed, duty 0, chain
     unarmed). Stream: two 2.000 s FIRE windows, the second ending
     exactly at end-of-data so its falling edge IS the SDMA backstop.
     Measured: **both pulses 2.0000 s exactly, clean edges, on BOTH
     termination paths** — normal completion (streaming=0) and true
     underrun (streaming=1, kernel `underrun` state reached and
     acked). The backstop drops FIRE within one tick (≤100 µs at
     10 kHz) regardless of how the stream dies.
     Signal naming (per the OpenGlow LASER SAFING sheet, confirmed to
     match the factory board): FIRE = per-tick request (kernel
     `laser_enable`, GPIO2_IO30); OK_2_FIRE = chain verdict; LASER_ON
     = FIRE∧OK_2_FIRE to the PSU; HV_EN = HV enable, safing-driven
     only.
   - **ALL STANDING SCOPE GATES ARE NOW PASSED.** Live fire remains
     gated on the laser-milestone software itself (power-byte + FIRE
     emission in the stream engine with power-before-fire ordering,
     HV_WDOG retriggering only while genuinely cutting, M3/M4/$32
     mapping) plus a chain-armed first-light procedure; the hardware
     verification prerequisites are complete. Interlock-trip recovery
     (the one non-scope check that was left) was exercised in
     commissioning runs and closed 2026-08-12.
   - **Fan/thermal control (operator-mandated laser-on prerequisite):
     DONE 2026-08-02, bench-verified** (test
     `scripts/bench/fan_test.py`). The policy described in this and the
     following bullets is the cooling engine's; it is now
     forgectrl `cool.c`, serving both controller modes, and the
     `GFCOOL_*` env names carry over as bench overrides (the conf keys
     are the `cool_*` ones — see the cooling-tunables note in the
     forgectrl section). Factory pulse-header
     values throughout: init = pump on / TEC off / purge on / idle
     fans (air assist 204); **M8** (coolant flood — LightBurn's
     per-layer Air Assist) = cut profile (air 1023, exhaust 65535,
     intake 43278); **M9** = 15 s cooldown (`GFCOOL_COOLDOWN_S`) then
     idle. Water temp polled at 1 Hz vs the ~31 °C factory run
     ceiling → one-shot controller warning (laser milestone upgrades
     it to a hard fire gate). Verified via tach readbacks: air tach
     period 4439→699 under M8, exhaust stopped→full, intakes ~3×,
     cooldown hold, clean return to idle; coolant temp visibly
     dropped during the blast. Absolute ceiling 33 °C (job-header
     CMrx).

     **Coolant temperature conversion CORRECTED 2026-08-02** — the
     UAPI "best guess" `raw*-0.09653+94` was wrong (3–5 °C high, wrong
     slope); the real one is the factory B-equation recovered from the
     v2.6.0 binary (10 k B3380 NTC, 10 k divider, ×1.3 gain, 10-bit
     ADC), proven by reproducing this machine's `WT*` cloud settings
     exactly, and thermometer-checked to ~1 °C. Full derivation now in
     `kernel-module-glowforge/UAPI.md`. Consequence: the 33 °C ceiling
     had been firing at a real ~29 °C, and **anything derived from the
     old formula had to be re-derived** — which is how the flow check
     below got rebuilt.

     **Coolant flow verification — REBUILT ON A 60-RUN DESIGN MATRIX
     (2026-08-02 overnight).** Everything below supersedes the earlier
     ΔT-based designs; the tools are `scripts/bench/flow_matrix.py`
     (+`flow_sampler.py` on the board), `flow_sustained.py`,
     `flow_warm_validate.py`, `flow_recheck_char.py`.
     - **Duty is the decisive parameter.** Below ~40 % the stagnant
       loop sheds the heater's output by natural convection well enough
       to **mimic flow**: at 30 %/50 s the five pump-stopped trials read
       8.15, 8.69, 8.78, 12.25, 13.33 °C while flow never exceeded 9.08
       — three of five dead-pump cases looked *healthier* than a working
       pump. At 40 % heat input outruns convection (flow ≤11.46,
       no-flow ≥16.04, d′ 8.4) and it is also the cheapest viable
       option (~0.8 °C of loop heating per check vs ~2.0 °C at 50 %).
     - **Operating point: 40 % duty, 50 s window, threshold 14.4 °C**
       (balanced midpoint of 17 flow observations peaking at 12.75 and
       8 no-flow observations bottoming at 16.04).
     - **Periodic re-checks every 150 s** (`GFCOOL_RECHECK_S`), because
       a stopped pump is undetectable any other way — absolute
       temperature only tracks a *circulating* loop, and "coolant
       should warm while cutting" is ambiguous (a light engrave may add
       no measurable heat). Sustained 40-minute run: zero false faults,
       and **no thermal accumulation** — with cut-profile fans the loop
       *cooled* 2 °C while being interrogated throughout.
     - **Settle gate (safety-critical).** The check measures a rise
       from a baseline; capturing that baseline while the loop is still
       cooling from earlier heat produces garbage and was bench-proven
       to **miss** (reported flow with the pump stopped). Checks are now
       requested, and start only once the sensors agree **and** the
       downstream reading is stationary. Stationarity uses a
       **split-half mean difference**, not peak-to-peak: measured noise
       on a settled loop is 0.52 °C p-p (0.70 worst) but only 0.11 °C
       split-half (0.21 worst), so any p-p threshold tight enough to
       catch drift sits *below the noise floor* and the gate never
       opens.
     - **Record: 25/25 correct classifications at 40 %**, plus all three
       settle cases (settled/flow, settled/no-flow, and the unsettled
       no-flow case that previously missed → now defers, then faults).
     - **NOT YET VALIDATED (first-light commissioning items):** all
       baselines were 19–23 °C (an overnight-cool room; the loop
       equilibrates near ambient and the heater cannot reach a
       cutting-session loop temperature — 100 % duty drives the
       downstream sensor past 50 °C in 30 s while the bulk barely
       moves). Behavior at 27–32 °C baselines, and under real laser
       heating, must be characterized at first light. Physics argues
       the dependence is weak — with forced flow ΔT = P/(ṁ·c), which
       carries no absolute-temperature term — but that is reasoning,
       not measurement.
     - **TRIAGE RESOLVED 2026-08-08 — the 2026-08-03 faults were a
       REAL transient stagnation, not false positives; loop trusted
       again.** The log lines (pass rise 11.4, then FAULT 16.5 / 15.9,
       dT 11.6) postdate the warm-baseline validation session:
       `flow_warm_validate.py`'s controller restart truncates
       `/data/glowforge.log` (single `>`), so they were written by a
       driver M8 session after 23:21 on 2026-08-02 — right after a
       bench session that stopped/started the pump 8+ times with
       ~50 °C heater excursions (classic airlock conditions).
       Signature analysis against the design matrix: the fault rises
       sit at the characterized no-flow floor (16.04), and the
       establish-window dT 11.6 sits in the no-flow band (driver-
       equivalent dT-mean from the matrix: no-flow 11.9–13.2 vs flow
       9.8–10.2) — the checks correctly read stagnant/near-stagnant
       water at that moment. Probable cause: transient pump airlock
       from the bench session's pump cycling, self-cleared (the
       preceding 11.4 pass shows flow was fine minutes earlier).
       **Re-verified 2026-08-08 through the production path** (M8 on
       the flashed v0.1.0 image, pump operator-confirmed, 22 °C
       settled loop): rise 11.3 dT 9.5, and after an M9→M8
       layer-cycle, rise 10.8 dT 9.3 — textbook flow-band values.
       Also measured: **no recirculating heat slug** — each check's
       heat is fully shed within ~60 s (two checks left the loop
       0.4 °C net cooler), and fan-profile transitions inject brief
       ~1.7 °C COLD slugs from the radiator (~20 s), showing the loop
       circulates in tens of seconds. Operational lesson: expect a
       possible legitimate flow SUSPECT on the first checks after
       manual pump stop/start cycling — the confirmation machinery
       below absorbs it.
     - **Suspicion/confirmation state machine — IMPLEMENTED
       2026-08-08, bench-drilled 6/6 + escalation** (now in the
       forgectrl engine). An over-limit check is a SUSPICION,
       not a fault: `COOLANT FLOW SUSPECT` warning + an immediate
       re-check request (no cadence wait). The next completed check
       decides it — "consecutive" means no clean check in between,
       whatever the wall-clock gap: over-limit again →
       `COOLANT FLOW FAULT`; clean → `coolant flow suspicion
       cleared`, episode counted (3 cleared episodes in one job earn
       an aggregated check-your-coolant warning; counter resets when
       cooldown reaches idle). A suspicion that cannot produce any
       verdict within `GFCOOL_CONFIRM_MAX_S` (default 480 s; budget
       restarts per flood session, runs only in Cool_Run) escalates
       to FAULT — a loop that will not settle after a fault-level
       reading has shown no evidence of health. A clean check from
       the FAULT state logs `coolant flow recovered`. Laser
       milestone: safe posture (hold + laser off + forced cooling)
       moves to the SUSPECT edge; FAULT stays the hard fire gate.
       Every threshold in this machinery is a `cool_*` conf key since
       2026-08-08 (forgectrl Machine tab, re-read per flood start;
       verification/calibration tools in the Diagnostics section).
       Bench drill (`scripts/bench/flow_confirm_drill.py`, on-board,
       real pump-off transients through the production path, single
       M8 session): verified 11.6/9.4 → pump off SUSPECT 16.4/12.0 →
       pump on cleared 11.9/9.5 in 92 s (the 2026-08-03 field case,
       now non-fatal) → pump off SUSPECT 18.5 → still-off confirmed
       FAULT 16.1 just 109 s after the suspect → pump on recovered
       11.1/9.4. All six verdicts in order, 6/6. Escalation drilled
       separately (`flow_escalate_drill.py` with
       GFCOOL_CONFIRM_MAX_S=45): suspect → starved settle → "no
       clean re-check within 45 s" FAULT.

     *(Superseded earlier text kept below for context.)*
     **Coolant flow verification (first attempt, live-verified both ways).**
     Continuous 10 % heating was never viable on the corrected curve:
     flow ΔT ≤3.69 vs no-flow ΔT ≥3.74 — a 0.04 °C gap against ~0.9 °C
     of sensor noise. At 30 % the ΔT bands separate (≤9.32 / ≥10.99)
     but a ΔT threshold still **failed a live pump-off drill** (8.8 °C
     vs a 10.2 °C limit), because a check starting from a cold heater
     never reaches the steady-state delta. Final design: a **one-shot
     check at job start (M8)** — heater to 30 % for 50 s — with the
     discriminator being **downstream temperature RISE** (flow ≈10.3 °C
     vs no-flow ≈15.1 °C, ~6 °C separation; threshold 12.7 °C,
     `GFCOOL_FLOW_RISE`). Heater goes off afterwards, so the loop is
     not warmed for the rest of the job, and absolute over-temp
     monitoring carries protection from there (a pump failure mid-cut
     shows as a temperature climb far faster than any heater delta).
     Verified twice each way from a cooled loop. **v2 (same day): heater job-scoped** (M8..M9 only — an
     always-on heater eats headroom below the 31 °C start gate at
     idle; flow faulting arms 30 s after heater-on), **two-phase
     cooldown** (15 s smoke clear at run duty, then half-duty airflow
     until the upstream temp is under the 31 °C resume gate or
     `GFCOOL_COOLDOWN_MAX_S`), and **factory-style over-temp pause**
     using the factory coolant windows (run ceiling 33 °C / resume
     31 °C, env-adjustable: `GFCOOL_TEMP_MAX`/`GFCOOL_TEMP_RESUME`):
     a CYCLE over the ceiling gets a feed hold + forced cooling
     airflow + auto-resume on recovery; a JOG gets a jog-cancel
     (grblHAL refuses HOLD from the jog state by design). Senders see
     the Hold state and [MSG:Warning:…] lines. Drilled live with test
     limits: jog canceled mid-move, cycle held and auto-resumed, fan
     profiles restored on stand-down. TEC control remains for the
     laser milestone; these warnings/holds become hard fire gates
     there.
   - **Low-temperature gates + warm-up: PLANNED (laser-milestone
     scope, operator-directed 2026-08-08).** The factory has a low
     side we do not implement yet, on two layers: the firmware
     coolant-window FLOORS (this machine's settings dump: CMrn/CMwn
     1017 mdeg ≈ 1.0 °C, CMin 4008 ≈ 4.0 °C — freeze/hardware
     protection) and the user-facing ~16 °C / 60 °F operating floor,
     enforced as the factory's "warming up" pause: the machine holds
     the job and warms the coolant with the loop heater until in
     range (the cloud CF* heater-PID keys are that mechanism —
     setpoint/Kp/Ki, zeroed on this unit; the OpenGlow stack uses a
     static 10 %). Plan: two more keys in the Cooling card —
     `cool_temp_min` (hard floor, default ~5 °C; becomes a fire gate)
     and `cool_temp_start` (warm-up gate, default ~16 °C): a job
     starting below the gate holds in a factory-style warm-up phase
     (loop heater on, senders see the Hold + a warming message) and
     releases above it; below the floor nothing fires at all.
     Rationale: cold-tube thermal shock, condensation when the TEC
     pulls below the dew point, frozen coolant. Sequencing with the
     flow check: warm-up first, flow check after (a warm-up that
     raises the bulk temperature is itself circulation evidence).
     Measured physics for the phase (this bench): 50 % duty warms the
     bulk ~0.5-0.8 °C/min and plateaus ~8-9 °C above ambient — the
     same unaided limit the factory has (a cold garage may never
     reach the gate; that is honest, not a bug).
   - **TEC handling: PLANNED (laser-milestone scope,
     operator-directed 2026-08-08).** The control board is common to
     Basic/Plus/Pro; per Glowforge's published specs the TEC ships on
     the Pro (Basic/Plus: same passive closed-loop cooling, 60-75 °F
     operating window; Pro: "solid-state thermoelectric cooler",
     60-81 °F — owners-forum consensus matches), but that is a
     spec-level claim, not teardown-verified per unit, and
     rebuilt/revision units may vary. Moot for the design either
     way: `thermal/tec_on` is a bare on/off output with NO readback —
     presence cannot be detected — so it is a user setting:
     `tec_present` (Machine tab, default off; ForgeFIRM never drives
     tec_on unless set). The setting also covers retrofits. Operation when present: the factory
     regulates coolant toward its ~18 °C setpoints (CMet/CMdt
     18134/18364 mdeg — the same WTub/WTvb raw-754/751 pair that
     proved the thermistor curve); plan is a simple hysteresis while
     a job runs — TEC on above `cool_tec_on_c`, off below
     `cool_tec_off_c`, defaults from the factory setpoints, off at
     idle (factory init state) — with `cool_temp_min` as the chill
     floor so the TEC can never drive the loop toward condensation/
     freeze territory. Exact policy (and whether the /status panel
     shows TEC as absent vs off) lands with the implementation.
   - **Interlock readback semantics cross-check: CLOSED 2026-08-12.**
     The full `interlock_circuit` bitmask is mapped: b0 (SoC-side
     LASER_ON monitor, active low), b1 (FIRE, active high) and b3
     (latch, 1 = locked) were pinned by the 2026-08-02 scope
     experiment recorded in the gate section above; b2 (button latch)
     and b4 (interlock latch reset) come from the factory decode the
     attrs were ported from. The armed kill-mid-FIRE drills exercised
     the mask across armed, firing, idle and disarmed states with
     consistent readings, and interlock-trip recovery is confirmed
     from commissioning runs. Attribute semantics are documented in
     `kernel-module-glowforge/UAPI.md`; note `cnc/laser_latch` is
     write-only, so lock state is read from `interlock_circuit` b3.
   - **Head-IRQ source validation — beam-emission hypothesis: OPEN
     (exploratory feature; NOT a first-light prerequisite).** The
     EV_SW `head` bit (GPIO3_22, factory pad name HEAD_IRQ; the
     panel's "Head sense" row) is the head MCU's attention line —
     idle LOW with a healthy head attached (measured 2026-08-08); it
     pulses on head reboot (hence the 60 ms DT debounce) and floats
     to the SoC pull-up with no head driving it, so the raw level is
     NOT a presence signal (presence = the head answering at I²C
     0x47). The factory app answers this IRQ by reading the head's
     interrupt flags over I²C, and the only flag register is the reg
     0x05 RO group — bit0 hall_sensor, bit1 accel_irq, bit2
     beam_detect_digital (head_private.h) — so there are exactly
     three candidate IRQ sources; working hypothesis (operator): the
     in-cut source is the head's IR beam-emission detector — digital
     flag 0x05 b2 + analog level reg 0x16 (both already head sysfs
     attrs), tunable detection model at regs 0x22–0x2a
     (lambda_k/lambda_t/theta_r/theta_t/e_t = the factory
     BDlk/BDlt/BDtr/BDtt/BDet settings; regs defined in
     head_private.h, not yet exposed as attrs).
     Priority/scope (operator, 2026-08-08): later exploration, not a
     must-have —
     - The bench head is **gen2** (a first-round Kickstarter unit
       already shipped gen2). Gen1 heads are presumed rare to
       nonexistent in the wild, though the factory images still
       support them, so some must be assumed to exist. The gen1
       board-level beam chain (!BEAM_DET GPIO4_15, !BEAM_DET_XOR
       GPIO4_08, !BEAM_DET_TIMEOUT GPIO4_07, BEAM_DET_ERR GPIO4_10 —
       DT-pinmuxed, not driver-requested; BEAM_DET_LATCH_RST GPIO7_13
       pulsed at cut start, boards v13/v14 only) is documented here
       as legacy reference only.
     - Whether the factory actually USES beam detect is unknown. The
       v2.6.0 factory app carries a complete but config-gated
       subsystem (separate printing/idle enables, severities
       failing-abort / pausing-alert / silent-alert, level-vs-edge
       trigger option, beam_detect_irq + irq_override, fault report
       upload; an invalid severity defaults to DISABLED), so the
       plumbing exists but production enablement is an open question.
       Detection at low fire energies is also unverified — the sensor
       may simply not trip on a low-power pulse.
     - Same status for the accelerometer: a promo-touted factory
       feature that was not active in early releases and may not be
       today. Its data path is direct (lis2hh12 on the I²C bus) but
       its INT pin routes to the head MCU as flag 0x05 b1, so it is
       also a head-IRQ source.
     Cheap opportunistic check during live-fire bring-up (no gating):
     log EV_SW head-bit edges + head/beam_detect_digital/_analog
     while firing — if the beam flag level-holds the IRQ, the panel
     row asserts during sustained emission. Later-feature decisions
     if it pans out: beam-absent-while-FIRE as an optional fault
     input, attrs for the calibration regs, panel row relabel (e.g.
     "Head IRQ / emission").
3. **Homing: runtime-selectable, Glowforge web-service mode
   IMPLEMENTED and bench-verified (stub session) 2026-08-07; LIVE
   cloud run still pending operator.** The operator picks the method
   in the forgectrl web UI (`homing_mode` in `/data/forgefirm.conf`,
   REST `GET/POST /settings`): `gfcloud` = factory camera homing via
   the Glowforge web service, `switches` = the future limit-switch
   cycle (falls through to the core, still disabled $22=0), `none` =
   `$H` rejects error 5. The driver re-reads the file on every `$H`.
   - Architecture: `glowforge_homing.c` registers a driver `$H` that
     shadows the core's; for gfcloud it suspends the stream engine
     (only from a fully idle kernel — closing the flock'd fd
     mid-program is an e-stop), spawns `/usr/sbin/gfhome.py` (new
     `gfhome` recipe; config `/data/etc/gfhome.conf`, first-run copy
     from `/etc/gfhome.conf.sample`), pumps the protocol so senders
     keep getting status, then reacquires the device and re-applies
     the analog config + step_freq. `^X` aborts the session (SIGTERM
     → SIGKILL); failure/timeout queues ALARM:18 like a failed core
     cycle (`gfcloud_home_timeout_s`, default 300).
   - The runner drives the GFUIService dispatch itself (the stock
     run() loop can neither stop nor close the socket) and treats
     hunt + ≥1 motion + quiet (10 s) as complete — the modern v2.6.0
     sequence per `_RESOURCES/emulator.log` is settings → hunt →
     lid_image → single corner move → lid_image → silence. It then
     re-homes the lens against the hall for a deterministic Z.
   - Position semantics: factory home = machine origin (back-left
     corner, +Y = FRONT, workspace all-positive 0..495 × 0..279); Z
     top-of-travel = 10.6. `gfcloud_home_x/y/z` in
     `/data/forgefirm.conf` calibrate the post-home coordinates once
     measured (defaults 0 / 0 / Z max).
   - Bench record 2026-08-07: forgectrl `/settings` verified on the
     board; `$H` mode dispatch verified (none → error 5); a stub
     gfcloud session (`gfcloud_home_cmd = /bin/true`) completed the
     full real-device handover — `H:1`, MPos set — and post-resume X
     jogs ran the gantry clean (clamped 0). Host tests covered
     success, calibrated coords, runner-failure and timeout-kill.
   - **LIVE gfcloud homing VERIFIED 2026-08-07 (bench, via `$H`):**
     full sequence in 65 s — hunt (Z hall + hunt puls), lid image,
     corner move (head physically to back-left), confirmation lid
     image, quiet detect, final Z re-reference — `ok` +
     `<Idle|MPos:0,0,10.593|H:1>`, stream resumed clean. The FIRST
     live attempt failed and exposed four real bugs, all fixed the
     same day:
     1. gfhardware `_run_loop` halted every motion ~0.1 s in on a
        false SW_ESTOP trip — the estop sense reads low during any
        motion (facts bank above). Gate is now opt-in
        (`MOTION.ESTOP_HALTS_MOTION`, off in gfhome.conf).
     2. `cnc.halt()` didn't exist → the halt path crashed →
        deadman fd closed mid-run → real kernel e-stop (40V off,
        every later hunt skipped as 'Disabled').
     3. Camera conflict: gfhardware's direct V4L2 grab fails while
        forgectrl serves a stream (LightBurn holds one); the runner
        now captures via forgectrl `/cam/snapshot` (full-res, mux
        borrow, per-shot `lamp=` override — head images torch-off).
     4. Kernel: the deadman e-stop path ran sync SPI (PIC safing)
        inside the ATOMIC dms notifier chain → RCU splat. Chain is
        now blocking (trip point = pulsedev release, process ctx);
        the panic handler keeps only the atomic motion stop.
     Also mapped kernel state 'underrun' in gfhardware (state polls
     raised ValueError on it). Commits: gfhardware 8aa4a49 (+02e66c6
     `_hunt` offset), forgectrl 0b05e48, forgefirm cc838f1,
     kernel-module 5fa558c — board runs all of it (module hot-swapped;
     gfhardware hot-patched over the pinned package). All repos are
     pushed and every recipe pin is bumped to these revisions
     (forgefirm 2dce136, meta-openglow 9e2aa34; recipes
     bitbake-verified from the new pins), so a fresh image build
     carries the whole homing release. Remaining homing polish:
     calibrate `gfcloud_home_x/y` against a jog to a known reference
     if the factory corner offset matters.
   - Limit-switch homing remains the planned second method; the
     accelerometer approach stays retired (implementation and bench
     record in grblHAL-glowforge history before commit 26298a3;
     durable accel/rail-contact measurements below).
   Durable measurements from the accelerometer spike (relevant to any
   future contact/vibration sensing; tools `accel_fast.py`,
   `bump_seek.py` remain in scripts/bench):
   - **Sensors**: the HEAD accel (lis2hh12) is **i2c-3 addr 0x1e**
     (0x1d on the same bus is a static board part; i2c-0 0x1e is the
     lid). st_accel sysfs one-shots are ~6 Hz and the kernel has no
     IIO triggers; direct I2C (unbind st-accel, CTRL1=0x6F = 800 Hz
     ODR) reads ~530 Hz from Python.
   - **Rail-contact signature**: creep baseline ≈0.5–2 k counts;
     contact jumps to 29–42 k within ~4 ms (20–40×). But **slow
     approaches are near-silent** — belt compliance turns slow-speed
     skipping into sub-threshold grinding — so any contact-sensing
     scheme must strike fast.
4. **Controller safety mapping — IMPLEMENTED 2026-08-13; the mid-job
   Door hold described here is superseded by the factory-parity policy of
   item 16 (lid = cancel + return to the job start; Door hold only with
   `lid_policy = hold`) — bench validation
   pending** (`grblHAL-glowforge/src/glowforge_switches.c`). The
   controller reads EV_SW with `EVIOCGSW` from the protocol thread's
   realtime hook (no grab — forgectrl polls the same device) and maps:
   - **doors (bit 3) not closed, or interlock (bit 5) loop open →
     the core's `safety_door_ajar`.** A running job parks in the door
     state and resumes when the condition clears, which is what the
     hardware chain already does to the beam. Bit 3 is the series
     combination the safety chain itself uses, not the individual door
     switches.
   - **hv_enable (bit 4): never gated on.** It is the readback of the
     chain's HV_ENABLE output (facts bank above), telemetry only; the
     core's `e_stop` capability is not advertised. (The `estop_halts_motion`
     opt-in that existed until 2026-08-15 is gone, together with the
     name — see the facts bank.)
   - **interlock latch (bit 6): deliberately not gated on.** Its
     resting state on a healthy machine is not characterized and a
     false assertion would wedge every job; the hardware chain enforces
     it regardless.
   - No switch device (host builds) = no capability advertised, no
     signals.
   **N5 answered: no software latch-reset path is needed.**
   Interlock-trip recovery was exercised in commissioning runs without
   one — the chain recovers when the condition clears. `cnc/laser_latch`
   stays write-only (1 = lock), the driver's arm flow unlocks per job,
   and `interlock_latch_reset` remains a readback. **Amended 2026-08-15:**
   the *interlock* latch never trips at all in ForgeFIRM — see Next work
   item 11; the "recovery" seen in commissioning was the software
   safety-door path, not the hardware latch.
   **Bench items:** open the lid mid-job (expect `Door` at the sender,
   motion parked, cycle start resumes after close); a Pro with an
   unjumpered interlock connector (expect the same door behavior);
   confirm no spurious door events across a full job. Underrun → alarm
   was already covered by the stream-fault path.
   **Changed 2026-08-15 (grblHAL a9446fe, host-tested, pin bumped, bench
   validation pending):** the door signal is now hidden from the core while it is
   IDLE, JOG or HOMING (`gfsw_visible`, applied to both `get_state()` and
   the edge delivery) and delivered the moment it is in any other state.
   Reason: a lid cycle at idle — every material load, and a power-up with
   the lid open — left grblHAL parked in `Door:0` until a cycle start,
   and LightBurn then sat at "Waiting for connection". Consequences: jog
   and `$H` are allowed with the lid open (beam hardware-blocked; upstream
   "ignore when idle" semantics), a job started with the lid open parks on
   the first poll, mid-job opens park exactly as before, and the cloud
   client (own EV_SW reader) is unaffected. Bench check: lid open/close
   at idle → state stays Idle; open mid-job → Door, close, `~` → resumes;
   Start with the lid open → Door immediately. **Partly validated
   2026-08-15 on image 20260815154622: LightBurn now connects after the
   lid has been opened and closed at idle (the original complaint).**
   The mid-job and start-with-lid-open checks are still open, and the
   session surfaced further LightBurn door-open issues — see Next work
   item 12.
4b. **Cloud-mode complete review** (operator-directed 2026-08-03):
   `load_motion` preloads a job's ENTIRE pulse file into the ring with
   no backpressure recovery — with the 16 MiB default ring that caps
   cloud jobs at ~28 min and a too-big job fails mid-download; the
   write path needs rework (stream-during-run or graceful
   too-big rejection). Also: a marked TODO in `load_motion` copies
   every job's full pulse file into the logging directory (disk
   filler), and many cloud actions are not currently handled at all —
   review the action surface end to end (gfutilities service layer).
5. **Camera service: DONE 2026-08-03, bench- and operator-verified**
   (see "The camera service" section above; LightBurn streams it
   directly). Remaining camera work: lens calibration / bed alignment,
   the deferred 5.6 emulator homing-image smoke.
6. **Housekeeping**: ~~pick the controller's remote home~~ **DONE
   2026-08-02** — the controller is now the canonical driver repo
   `github.com/ScottW514/grblHAL-glowforge` (+ `ScottW514/core` fork;
   the settings-write crash fix is upstream PR grblHAL/core#999; repoint
   the submodule to upstream when it merges). ~~Yocto recipe for
   grblHAL-glowforge~~ **DONE 2026-08-03** (`grblhal-glowforge` in
   meta-forgefirm, boot autostart, reboot-verified). ~~Documentation
   sweep (CLAUDE.md charter, README roadmap, INSTALL/BUILD/kas README)~~
   **DONE 2026-08-13.** Remaining: kas flip + first GitHub release per
   kas/README.md once ready to publish.
7. **Install/update system overhaul** (planned 2026-08-08): adopt the
   factory A/B slot scheme end-to-end — fwup-packaged signed `.fw`
   releases, single-stage installer, GUI update manager + boot
   selector in forgectrl, offline factory restore from a `/data`
   archive, legacy-p4 migration, and later a refreshed recovery image
   in boot0. Full phased plan with invariants and decision gates:
   `docs/UPDATE-SYSTEM.md` (builds on the facts-bank eMMC map).
   **Phase 0 COMPLETE, hardware-verified 2026-08-08**: slot-agnostic
   images (`root=${mmcroot}`; the SAME release ext4 boot-verified from
   SD and from eMMC p4, steered by env alone — bench flip test), fwup
   toolchain cross-version proven (modern-packed signed `.fw` applies
   with the factory's 0.14.2; 0.14.2 wants raw 32-byte pubkeys), fwup
   in both images, slot-sized release rootfs + hard size gate + ext4
   artifact + `scripts/mkfw.sh`. GAP found for Phase 1: the image
   ships fw_env tooling but **no `/etc/fw_env.config`** — hand-placed
   on the bench SD system (factory-identical: mmcblk2 0x80000/0x82000,
   0x2000, redundant) — the ffboot-v2 recipe must install it.
   **Phase 1 COMPLETE, hardware-verified 2026-08-08**: ffboot v2 —
   `-l` machine-parsable slot inventory (the shared probe for the
   installer and the forgectrl update manager), verified atomic
   four-variable env flips (one `fw_setenv -s` transaction, read-back
   verify, libubootenv→classic→per-var format fallbacks — works on
   both fw_setenv flavors), content-probe gate on switch targets
   (`-f` overrides), probe-based `-e` newest-factory selection. The
   `ffboot` recipe installs `/usr/sbin/ffboot` + `/etc/fw_env.config`
   in the image (closes the gap above; build 20260808160821, ext4
   still 180.8 MiB). Bench: `-l` classified every slot correctly, and
   ffboot itself drove the SD→p4→SD flip cycle (probe gate, both
   flips, clean returns). Untested edge: empty/unreadable-slot
   classification (no such slot on the bench; exercised naturally
   when Phase 2 overwrites a slot mid-install).
   **Phase 2 COMPLETE — FULL SLOT INSTALL bench-proven end-to-end
   2026-08-08** (operator at the factory console, agent over SSH):
   single-stage installer ran on the FACTORY 2024 firmware — archived
   both factory rootfs versions + boot0/boot1 (~88 MB total, manifest
   with md5s), signature-verified the dev-signed forgefirm.fw, applied
   it to slot 2 with the factory's own fwup (29 s), post-verified,
   verified-flipped, and ForgeFIRM booted from slot 2; slotmigrate
   reclaimed p4 and grew /data to the **byte-exact factory geometry**
   (827392/6725632; 0.7 s at boot, silent no-op thereafter); factory
   round-trip proven (`ffboot -e` → factory 2024 boots → `-e2` back).
   2024-firmware facts learned: no `/factory/imgN` mounts, generic
   fw_env.config points at the WRONG device (use per-device
   `fw_env_mmcblk2.config` — ffboot's selection logic), no SSH (serial
   console only), factory kernel cannot see the SD card (ffboot -s
   needs `-f` from factory). The **bench board now runs ForgeFIRM
   v0.1.0 from eMMC slot 2** (factory 2024 in slot 1, archives in
   /data/forgefirm/archive, dev image still on SD via `ffboot -s`).
   The installer's embedded pubkey is the **production release key**
   (ceremony executed 2026-08-08; `release.sh` enforces the match).
   **Post-test: the bench rests on the SD dev image again** (`ffboot
   -s`; slot 1 = factory 2024, slot 2 = ForgeFIRM v0.1.0, archives in
   /data/forgefirm/archive). Platform fact pinned by experiment while
   chasing a console cosmetic: **busybox mount's auto-type iteration
   against an already-mounted ext4 device prints a kernel
   "`Can't open blockdev`" for each foreign-type (ext3/ext2) exclusive
   claim before the ext4 attempt joins the existing superblock** — the
   image's fstab keeps the factory slots mounted under /factory, so
   any auto-type probe of a slot triggered it. Cosmetic only; ffboot
   and the installer now reuse existing mountpoints from /proc/mounts
   and mount fresh targets with explicit `-t ext4` (verified: dmesg
   count unchanged across `ffboot -l`).
8. **Shared machine services — remaining polish.** The consolidation
   itself is complete and drilled (see "Where the project stands" and
   `forgectrl/docs/SERVICES.md`); these are the deliberate leftovers,
   none of them blocking:
   - **Diagnostics as engine modes.** The Diagnostics flow tools still
     drive the thermal hardware themselves while the cooling engine
     suspends its writes and publishes fire-blocked. The check
     parameters and factory duties are already shared (`cool.h`, one
     definition for both), so what remains is folding the tools into
     the engine as modes and retiring the suspend/resume dance.
   - **Rail policy** (SERVICES.md "Pulse-device ownership", the one
     `[contract]` item left there). `cnc/enable` / `cnc/disable`
     are not forgectrl-only writes yet: under the broker no client
     drops the rail any more, but the GRBL driver still writes
     `cnc/enable` at init and at homing resume — idempotent, since the
     rail is already up and settled, so this is tidiness rather than a
     bounce source. (An idle-rail-off policy is not part of this: the
     rail stays up while the machine is on, per the wedge model in the
     facts bank.)
   - **Busy-state arbitration under one lock.** forgectrl's idle/busy
     gates (`POST /settings`, `/mode`, diagnostics start, upload/apply)
     each cross-check `machine_is_idle()` and `update_job_running()` at
     their own call sites. They fail closed and are drilled, but a
     single arbiter (one lock, one "who owns the machine right now"
     answer) would replace N targeted checks with one and close the
     remaining request-interleaving windows by construction.
   - **HTTP surface caps.** The daemon relies on MHD's default connection
     ceiling (a 500-connection flood plateaued at 379 fds under the raised
     4096 `RLIMIT_NOFILE`, no crash, `cnc/state` readable throughout).
     An explicit `MHD_OPTION_CONNECTION_LIMIT` plus a per-IP cap is the
     right hardening, and the camera `ensure_engine` `popen()`s should
     move out of the HTTP callback so a slow media-ctl can never stall the
     request thread. Changing the MHD start flags touches the streaming
     model, so this waits for a bench slot of its own.
   - **Cloud per-job fan profile.** The cloud client passes the pulse
     header's `AArd`/`EFrd`/`IFrd` duties to the engine as the per-job
     run profile. Homing headers are verified end to end (they carry
     the idle-quiet profile the factory uses — no fans during a hunt);
     a real print header's duties should be confirmed through the same
     round trip at the next cloud print.
   - **`/cool/status` cosmetics.** The endpoint echoes the last
     reported `armed` flag even when that report is stale
     (`report_age_s` tells the truth), and a gfcloud homing session
     reports every motion as a job, so the engine cycles run → smoke →
     idle per motion. Both are silent and safe — the homing profile
     keeps the fans at idle duties — but motion actions reporting
     `idle` would be more honest.
   - **Button edge detection.** The GRBL arm flow reads the button as
     an EV_SW level; edge detection belongs in that reader. It does
     not change where the button is read (per-mode direct evdev, for
     latency) — the switch map itself is contract-documented and
     shared.
9. **Kernel platform hygiene — CODE-COMPLETE and build-verified
   2026-08-13 (kernel-module `6fdc4b2`, meta-openglow `34a0e2e`), bench
   validation pending.** The batch edits the kernel overlay (DTS +
   config fragment), so it **ships with a full image flash, not a module
   hot-swap** — flash the next image before running the checks. What
   changed and what each item needs on the bench:
   - **Panic handler enabled** (`INSTALL_PANIC_HANDLER 1`), reduced to
     what is legal in atomic context: `epit_stop()` plus a direct
     `io_change_pins(cnc_shutdown_pin_changes)` — FIRE parked, charge
     pump low so the hardware watchdog stops being fed, latch reset
     asserted, steppers de-energized. It no longer calls
     `_driver_stop()` (hrtimer cancel, sysfs notify).
     **Bench:** panic mid-motion with motors locked and the laser
     latched; confirm motion stops and the safety lines read safe.
   - **`control_12v` node dropped** along with
     `CONFIG_REGULATOR_USERSPACE_CONSUMER`; the 12 V rail is
     `regulator-always-on` and nothing in userspace referenced the node.
     **Bench:** confirm the rail still comes up and the machine behaves
     identically.
   - **`struct gpio_desc` layout hack removed.** The commanded decay
     mode is tracked per axis and seeded at probe to mixed decay (both
     pins requested `GPIOF_IN`), instead of reading a private kernel
     struct. **Bench:** set each mode per axis and read the attr back.
   - **Module build hygiene:** `-Wno-error` dropped, `.DELETE_ON_ERROR`
     added, and the warnings that surfaced fixed (missing prototypes now
     static or declared in the new `ledtrig_smooth.h`; LED teardown no
     longer flushes the system work queue — the LED work runs on an
     ordered queue the driver owns and destroys). The recipe passes
     `KCFLAGS=-Werror` to hold the zero-warning state without making the
     module's own Makefile unusable against other kernels.
     **Bench:** LED brightness behavior, and a clean module unload.
   - **Platform guards** (not reservations — dmaengine has no channel
     reservation for this path): the SDMA channel number is
     range-checked and its takeover logged; the EPIT clock rate is read
     back at probe, failing probe at zero and warning below the rate
     needed to quantize step frequencies within 1 %; and
     `io_verify_base_address()` checks the GPIO-number→bank math against
     each pin's controller node in the DT, warning rather than failing.
     **Bench:** read the two new probe lines in dmesg and confirm no
     bank warnings.
   - **`head_make_safe` implemented:** measure laser off, UV LED off,
     lens motor de-energized (group-register clear-bits write) — legal
     now that the dead-man chain is blocking. Head fans and the white
     LED are deliberately left alone: `SERVICES.md` gives the fans to
     the cooling engine (whose stand-down keeps airflow after a job
     dies) and the white LED to the camera. **Bench:** trip the dead
     man's switch and read the head registers back.
   - The uniprocessor locking assumption and the panic/dead-man safe
     states are documented in `kernel-module-glowforge/UAPI.md`; no
     bench item.
   - **`hv_enable` rename + polarity flip (2026-08-15) rides the same
     flash.** The gpio-keys node for GPIO4_06 is now `hv_enable`,
     declared active-low, so EV_SW bit 4 reads as the HV_ENABLE output
     itself (inactive at idle, active through a run). forgectrl
     (`/status` key `switches.hv_enable`, panel "HV enable"), the grblHAL
     driver (`SW_BIT_HV_ENABLE`, no gating) and gfhardware
     (`InputSwitch.SW_HV_ENABLE`, no gating) all ship in the same image
     and read the new polarity; the DTS and that userspace must not be
     mixed across the flash (a mismatch only inverts the telemetry — nothing
     gates on the bit — but the dashboard would lie). **Image
     `20260815162923` (forgefirm-image + forgefirm-image-dev) is built on
     these pins** (forgectrl 801f1f3, grblHAL-glowforge b629c18,
     python3-gfhardware c3d1790, kernel module d750784, meta-openglow
     b1ba543): the built DTB carries the `hv_enable` node with
     `gpios = <&gpio4 6 GPIO_ACTIVE_LOW>` and no `estop` string, the rootfs
     forgectrl emits `"hv_enable"` and no `"estop"`, the grblHAL binary has
     no `estop_halts_motion`, `gfhardware/_common.py` carries
     `SW_HV_ENABLE`, and the standard built-image checks pass (root locked,
     no watchdog daemon, K80/K90 order, `glowforge.ko` in `extras/`); the
     only build warning is the usual forced-`do_compile` taint note.
     **Flashed and BENCH-VALIDATED 2026-08-15 (operator flashed; image
     reports `20260815162923 (dev)`, `/proc/device-tree/switches/hv_enable`
     present):** with `/status` and `cnc/charge_pump_alive` sampled together
     at ~10 Hz on the board through a 5 mm X jog (`$J=G91 X-5 F300`, no
     Grbl client attached, laser locked): `hv_enable:false` / pump 0 at
     idle; `true` / 1 in the same sample the state went `running`; still
     `true` / 1 in the first `idle` sample after the run; pump 0 ≈0.4 s
     after that idle sample with `hv_enable` false in the next sample
     (89 ms later); the head returned to `MPos 0.000`. The switch reads as
     HV_ENABLE itself, in lockstep with the watchdog readback.
   - **GATE A kernel fixes added to the same flash (2026-08-14):**
     the controlled-deceleration ramp now floors at the minimum step
     frequency with a saturating decrement, and `epit_hz_to_divisor()`
     can no longer return the degenerate divisor 0 (a 0 Hz request maps
     to the slowest achievable tick); the resume waypoint re-enables
     the FIRE drive only when the laser latch is unlocked; and
     `laser_latch` writes run under `status_lock`, restoring the FIRE
     output drive only when no run or ramp is in flight.
     **Bench (GATE A stays open — no live-fire — until these pass):**
     a controlled-stop drill at the default cloud tick (10 kHz, ramp
     125000) shows a decelerating tail rather than a max-rate burst;
     feed-hold, jog-cancel and `^X` each land in a controlled stop with
     position preserved; a resume waypoint with the latch locked stays
     laser-less; `laser_latch=0` written mid-ramp does not re-arm FIRE
     (probe the PSU-connector LASER_ON line as in `fire_test.py`).
     **The GATE A part of this list is DONE (K1/K2/K3 + `fire_test`
     A/B/U pass on image `20260814223300`, campaign record above); the
     platform-hygiene items themselves are consolidated in item 10.**
10. **Outstanding bench validations (consolidated 2026-08-15).** Every
    safety-critical drill is done: GATE A (K1/K2/K3, `fire_test` A/B/U),
    GATE B (auth/CSRF/loopback/settings-flood probes), dry motion and
    dead-man drills (SIGKILL reap+safing, SIGSTOP → underrun, restart
    mid-move, no stray fd), the X-2 flood, and the live-fire set (A-1
    emission witness, A-5 HV telemetry, X-3 job-based disarm, G-10
    grace-in-Hold, A-2 lid-IR first look). What has **not** been run on
    hardware, none of it gating, in rough priority order:
    - ~~**Lid-IR fire characterization at cutting power**~~ — **DONE
      2026-08-15** (three cutting-power jobs, worst rise +6 counts,
      `cool_fire_ir_delta = 15` set by hand in `/data/forgefirm.conf`).
      **Then disabled again the same day (`cool_fire_ir_delta = 0`)**:
      the channels track the lid LED (0→2, 131→~58, 255→~180 counts),
      so any lamp change during a run — a panel snapshot lights the
      lamp — steps them by tens of counts and a fixed-count gate would
      stop the job on a phantom FIRE. Redesign before re-arming: the
      engine must own or observe the lamp level (suspend the watch and
      re-baseline for a few ticks after any `lid_led` change; forgectrl
      drives it for captures, the cloud client for lid images), and the
      threshold should be relative to the lamp-set level, not a fixed
      count. Even then the signal is weak (a candle reads like a cut);
      the head camera or a real flame sensor is the honest path to fire
      detection that means something.
    - ~~**Kernel platform-hygiene batch (item 9), on the flashed
      image**~~ — **DONE 2026-08-15** (panic mid-motion, decay/microstep
      readback, LED sequence + clean unload, probe lines, dead-man head
      readback, concurrent `cat` during `rmmod` — session record above).
      Still needing a debug kernel build: load/unload under
      `CONFIG_DEBUG_MUTEXES` and a forced `-EPROBE_DEFER` unwind.
    - ~~**Dead-man collateral**~~ — **DONE 2026-08-15**: the trip leaves
      pump and airflow running (readback drill); helper children never
      hold the pulse device (fd-scan during `/update/check` + snapshot);
      the armed kill on the *expected*-stop path failed first (5 s of
      continued fire), the defect is fixed on both sides, and the re-run
      passed. The literal "kill forgectrl mid-download" variant needs a
      published `.fw` to download and was covered by the fd-scan instead.
    - **Physical-evidence negatives:** ~~head absent at power-up~~ **DONE
      2026-08-15** (head group absent → no readings, arm refused, presence
      and motion labels fixed). Still open: a present head answering I²C
      badly (the K-11 runtime case) and a failed head capture leaving the
      measure laser off — both need the head connected and a fault
      injected.
    - **Cloud mode — mostly DONE 2026-08-15:** mode switch clean (GRBL
      controller exit 0x0, gfcloud signed in, connect-time hunt + lid
      image ran); **network/DNS blip** (service peers blackholed + dead
      resolver for 75 s while the session was live): `ping/pong timed
      out - goodbye` → in-process `RECONNECTING`, sign-in retried with
      backoff through the outage, `authenticate_machine SUCCESS` and the
      service's `settings` action answered right after restore, same
      process, supervisor never involved — PASS; **a real print** (22.9 s,
      motion bytes actual = expected, emission peak 91, HV 0..932): the
      header's `AArd 1023 / EFrd 65535 / IFrd 43278` drove air 11.0 k /
      exhaust 11.8 k / intake 4.1 k rpm through the armed window and the
      hunt/Z headers (`204/0/0`) left the fans at idle levels — the
      per-job profile round-trips (directional; duty→rpm not calibrated);
      no false FIRE trip on the job. `$H` witness re-verified (7 windows
      ≥ 500 at ~100 Hz). Still open, not inducible from the bench: the
      cancel-with-a-rejected-`settings`-action case, a malformed frame
      (needs a MITM), the oversize/bad-header job (tracked in `CLOUD.md`).
    - **Opportunistic:** `STATE_FAULT` recovery via `enable` without a
      module reload the next time a DRV8825 fault line actually trips.
    - **Config-dependent, deliberately not gated:** an armed GRBL job
      after an underrun cuts at the stale origin unless homing is
      required (GRBL mode permits unhomed cutting; the underrun itself
      alarms and unlinks the anchor).
11. **Interlock latch has no hardware trip path in ForgeFIRM (found
    2026-08-15, bench-verified).** With the interlock connector unjumpered
    at idle: EV_SW `interlock`=1 (loop open), `interlock_latch`=0 (not
    tripped), `cnc/interlock_circuit`=13 (b4 INTERLOCK_RESET=0),
    `interlock_latch_reset`=0. This matches the safing schematic: the
    interlock latch (U23-2, CD4043B) has RESET = loop-closed and
    SET = INTERLOCK_RESET (GPIO4_05) — an open loop only *releases* the
    reset, and nothing in ForgeFIRM drives INTERLOCK_RESET (the driver
    exposes it as a read-only readback, initialized low; the former
    `interlock_reset` LED node that let userspace drive it is gone). So on
    a machine with a real external lockout (Pro), an open loop does **not**
    cut LASER_ON in hardware; enforcement is the GRBL safety-door hold on
    switch code 5 and the cloud client's motion gate. Basic/Plus ship the
    loop jumpered. **Decision + fix needed:** drive INTERLOCK_RESET high
    whenever the loop is open and hold it until the loop closes, so Q2
    blocks the LASER_ON gate in hardware (the CD4043B is set-dominant, so
    the latch stays blocked until the SoC releases SET *and* the loop is
    closed). **IMPLEMENTED 2026-08-15 (kernel-module, code-complete, bench
    validation pending; kernel-module 015913b, meta-openglow 92d6e20 DTS +
    897c175 pin, forgectrl a451e7c docs, all pushed and pins bumped
    2026-08-15):** `src/cnc_interlock.{c,h}` — an in-kernel input
    handler on the gpio-keys switch device (no DT change, GPIO stays with
    gpio-keys) drives INTERLOCK_RESET high while EV_SW code 5 reads open,
    from probe until the switch device attaches, and if it detaches
    (unobservable = open); low only while an attached device reports the
    loop closed. Pin init changed to `GPIOF_OUT_INIT_HIGH`. Proof so far:
    host test `tests/interlock_test.c` (8 cases, `make -C tests check`,
    new CI job `host-tests`) green; module cross-compiled clean against
    the staged 6.12.20-fslc kernel with `KCFLAGS=-Werror`, MODPOST silent.
    Ships with the next image flash (kernel changes are never hot-swapped);
    bench re-run of this exact reading then expects `interlock_latch`=1 /
    `interlock_circuit` b4=1 with the loop open, both clearing after it is
    closed. **BENCH-VALIDATED 2026-08-15 on image 20260815150546:** loop
    pulled → `interlock`=1, `interlock_latch_reset`=1, `interlock_latch`=1,
    `interlock_circuit` 45→61 (b4 set), all within one 50 ms sample;
    reinserted → all clear the same way. Side effect to know: the pull is
    a grblHAL safety-door hold — the controller sits in `Door:0` after the
    loop closes until a cycle start (`~`) returns it to Idle (a client
    connecting then sees Door, not a dead link). Same batch: the charge-pump
    watchdog readback (`cnc/charge_pump_alive`,
    `interlock_circuit` b5; GPIO1_08 = inverted one-shot Q, new
    `charge-pump-alive-gpio` + GPIO_8 pad in the linux-fslc DTS — kernel
    module and DTB must ship together, the pin is required at probe; DTB
    compile-checked with cpp+dtc against the staged kernel) — **also
    bench-validated 2026-08-15:** two X jogs sampled at 50 Hz: `state`
    running → `charge_pump_alive` 1 and `estop` 0 (pre-rename name and
    polarity of today's `hv_enable`) in the same 20 ms sample;
    after each run `charge_pump_alive` fell 0.325 s / 0.326 s after `idle`,
    which with the 200 ms feed phase (last pulse 0.136 s / 0.118 s before
    the run end) is a one-shot period of **0.46 s / 0.44 s** — matching
    the measured R·C (≈500 kΩ × ≈900 nF = 0.45 s); `estop` re-asserted
    with the drop both times, i.e. HV_ENABLE = DOORS_OK · WDOG_ALIVE
    observed live. Full write-up of the chain: `docs/SAFETY.md`
    (+ `docs/img/safety-chain.svg`).
12. **LightBurn door-open handling — further issues (found 2026-08-15,
    details pending).** With image 20260815154622 (grblHAL a9446fe: door
    signal hidden while idle/jog/homing) LightBurn connects again after
    an idle lid cycle, but the same bench session turned up other
    problems around lid opening in LightBurn that were not characterized
    on the spot. To be detailed and reproduced in a dedicated testing
    session: symptoms, whether they involve the mid-job Door hold /
    Resume path, Start-with-lid-open, or the sender's own handling of the
    `Door` state, and what the controller reports at each step. Until
    then the door change stands as partially validated (item 4).
    **2026-08-16:** the default mid-job lid path is now the factory cancel
    (item 16), so LightBurn no longer lives in `Door` at all; retest the
    symptoms with the item-16 tests, and only chase what remains under
    `lid_policy = hold`.
13. **uSDHC pad strength brought to the factory values (DTS change
    2026-08-15, bench validation pending — ships with the next full image
    flash, per the batched kernel/BSP rule).** Trigger: one
    `wl1271_sdio mmc0:0001:2: sdio write failed (-84)` (`-EILSEQ` = SDIO
    bus CRC error) on the WL1805 Wi-Fi bus at 49.5 MHz SD-high-speed,
    followed by wlcore's designed hardware recovery (firmware reboot +
    reassociation, ~1.0 s of Wi-Fi outage) and one `ipu1_csi0: NFB4EOF`
    160 ms later (a consequence of the recovery/WARN console burst, not a
    co-cause). It happened at idle, 1.7 s after a kernel run ended and
    ~2 s after a button press — no motion, no fire, HV_ENABLE already
    down — so nothing points at laser or stepper EMI. Rate observed:
    1 event in 49 min of uptime. Effect if it lands mid-job: a 1–2 s
    sender stall (planner drains, head pauses; laser off in M4 mode) —
    a cut-quality nuisance, never a safety matter (nothing safety-relevant
    crosses Wi-Fi). Finding: `glowforge.dts` drove all three uSDHC
    controllers with `0x17019` (SPEED_LOW, DSE 80 Ω, 47 kΩ pull-up on
    CLK too), while the factory DTB uses `0x17069`/`0x10069` (SPEED_MED,
    DSE 48 Ω; no pull on CLK) for the Wi-Fi bus and `0x17059`/`0x10059`
    (80 Ω) for eMMC and SD (SD2_DAT3 `0x13059`) — softer edges than the
    factory at the same 50 MHz clock. `openglow_common.dtsi` now carries
    the four factory-exact values (`USDHC_PAD_CTRL`, `USDHC_CLK_PAD_CTRL`,
    `USDHC_SDIO_PAD_CTRL`, `USDHC_SDIO_CLK_PAD_CTRL`) and the compiled
    `fsl,pins` tuples were checked byte-identical to the factory DTB's
    `glowforge_usdhc1/2` and `usdhc3grp`. **Bench:** on the next image
    confirm `pinconf-pins` reads `0x17069`/`0x10069` on SD1, eMMC and
    Wi-Fi come up, then watch `dmesg | grep -c "sdio .* failed"` across
    sessions (baseline: 1 per ~49 min). Only if it still recurs, cap
    the bus with `max-frequency = <25000000>` on `&usdhc1` (halves Wi-Fi
    throughput — last resort; the factory ran 50 MHz on these pads). The
    `WARNING … wlcore/main.c:874 wl12xx_queue_recovery_work` block that
    accompanies the event is upstream noise (an "unintended recovery"
    `WARN_ON`), not a crash — the `-84` line is the signal to watch.
14. **Unified logging — CODE-COMPLETE, host-verified, pushed and pinned
    2026-08-15; bench validation pending — ships with the next full image
    flash (rsyslog replaces busybox syslogd/klogd, so it is an image
    change).** Design and contract: `forgectrl/docs/SERVICES.md`
    "Logging". In brief: rsyslog is the only log writer; forgectrl and
    the grblHAL driver emit through the shared non-blocking `fflog`
    emitter (drops, never waits — a stalled log daemon can never park a
    controller thread), gfcloud/gfhome through `SysLogHandler`, the
    kernel through `imklog`; a controller's stray stdout/stderr rides a
    per-controller `logger` relay under its own name; the daemon's own
    stray output a fifo relay in its init script. Tree:
    `/data/log/forgefirm/{forgectrl,grblhal,gfcloud,gfhome,kernel,system}/`,
    size-capped and rotated (`forgefirm-logging` recipe: renders the
    rsyslog rules from the settings at S19 via `forgectrl
    --render-syslog`, sweeps the pre-syslog files once into
    `/data/forgefirm/legacy-logs/`, logrotate at boot + hourly with a
    `HUP`, never `copytruncate`). Levels: `log_<logger>_disk` /
    `_remote` and `syslog_server/port/proto` in `/data/forgefirm.conf`,
    **applied at reboot** (the panel's Logs tab shows configured vs.
    effective and offers the reboot); a process emits at the more
    verbose of its two levels, rsyslog filters per destination. Export:
    `POST /logs/export` streams a `tar.gz` (tree + system snapshot),
    sanitized by default (`src/sanitize.c`: known values first — serial,
    hostname, cloud credentials, panel token, WiFi SSID/PSK — then
    patterns; stable placeholders; `tests/sanitize_test.c` in CI, 39
    fixtures). Host proof done: forgectrl/grblHAL `-Werror` builds and
    all three CI test sets green (sanitizer, idle fail-closed, switch
    map, arm re-check, laser stream + armed-window harnesses on the
    null-sink build); `tests/fflog_e2e.sh` against a private rsyslogd on
    the shipped `rsyslog.conf` (emitter format, per-logger routing,
    level filtering, `logger` relay routing) and the equivalent Python
    check both pass; `/logs`, `/logs/tail` (full + incremental follow),
    and both export variants exercised over HTTP on a host build and
    the panel's Logs tab driven in a browser (levels table, viewer,
    follow, export). **Bench, on the flashed image (dev image
    `20260815191634`, flashed and booted by the operator 2026-08-15):**
    - ~~boot~~ **DONE 2026-08-15**: `S19forgefirm-logging` → `S20syslog`
      → `S90forgectrl`, `K80`/`K90`/`K95syslog`; `rsyslogd` up, no
      busybox `syslogd`/`klogd`; rules and `/var/run/forgefirm-loglevels`
      rendered (all defaults); six directories under
      `/data/log/forgefirm`; `/var/log/messages` gone; legacy files
      moved to `/data/forgefirm/legacy-logs/` (`forgectrl.log`,
      `forgectrl.log.old`, `gfcloud.log`, `gfcloud/`, `gfhome/`),
      `/data/log/gfcloud` and `/data/log/gfhome` gone, the factory's
      `/data/glowforge.log*` untouched; the forgectrl fifo relay and the
      grblhal relay both running (`logger` ×2, `/var/run/forgectrl.stderr`).
      The swept legacy files (10.6 MB) were deleted from the bench on
      2026-08-15 once the new tree had proven itself; the sweep itself
      stays in the init script for any board upgrading from before the
      syslog tree.
    - ~~routing~~ **DONE 2026-08-15** for GRBL mode: forgectrl lines
      (`super: liveness probe: MOTION OK …`, `NOTICE super: started grbl
      controller`) in `forgectrl/forgectrl.log`; grblHAL's (`gfstream:
      pulse device inherited from the broker`) in `grblhal/grblhal.log`;
      the whole boot ring (350 lines, `glowforge_cnc cnc: 40V on` …) in
      `kernel/kernel.log` with correlated timestamps; sshd/rsyslogd in
      `system/system.log`; `logger -t grblhal` / `-t gfhome` probes land
      in the right files tagged `grblhal[-]` / `gfhome[-]` (the relay
      path). `/logs`, `/logs/tail` and the sanitized export served over
      the LAN: the bundle carried `<SERIAL>` ×2, `<IP-1>` for the LAN
      peer (sshd `Accepted … from <IP-1>`), MACs and e-mails redacted,
      no LAN address anywhere in it. Still open: cloud-mode routing
      (`gfcloud/gfcloud.log` + a Python traceback via the relay) and a
      `$H` for the gfhome lines. Found and fixed the same day: rsyslogd
      warned at start that the fallback rule after the include was
      unreachable (the rendered rules end in `stop`) — the default rules
      now come from the init script when the render leaves none
      (forgefirm 7487f90, next image).
    - ~~levels~~ **DONE 2026-08-15** (three reboots): `forgectrl`/`grblhal`
      → `debug`: `pending_reboot:true` before, effective after; the per-run
      `gfstream: run:` DEBUG stats appear on jogs; `forgectrl` → `warning`
      + `grblhal` → `off`: the new boot wrote zero NOTICE/INFO forgectrl
      lines and kept a WARNING probe, grblhal wrote nothing even for an
      `err` probe, kernel/system unaffected; defaults restored and
      re-verified. ~~Remote~~ **DONE 2026-08-15, real hop to a LAN
      collector (172.16.1.95:5514) over UDP and TCP** (after a first pass
      on a loopback listener): RFC 5424 lines arrive (`<31>1 …
      glowforge grblhal - - - …`), filtered exactly per logger across a
      whole boot (kernel at warning only, forgectrl/grblhal at info,
      sshd from `system`; a gfhome err and a forgectrl debug probe held
      back). Collector down through an entire boot on TCP: `omfwd
      suspended … Connection refused` in `system.log`, the machine
      unaffected (jogs, local logging), and 30 s after the listener came
      up `omfwd resumed` and the queued boot lines were delivered. Note
      for future probes: `busybox nc -u` on the board never sends — use
      `python3 … sendto`; my first "the workstation drops inbound UDP"
      reading was that false negative.
    - ~~rotation~~ **DONE 2026-08-15**: a 30 000-line burst (4.8 MB) into
      `grblhal`, one `logrotate` run → `grblhal.log.1.gz` (all 30 024
      lines), the live file recreated and receiving (rsyslogd's fd on the
      new inode). The imuxsock per-pid rate limit did not engage for
      `logger` bursts (each line is a new pid) — it bounds a single
      runaway process only, as intended.
    - ~~export~~ **DONE 2026-08-15**: both variants downloaded over the LAN;
      the sanitized bundle carries `<SERIAL>`, `<IP-n>`, `<MAC-n>` and no
      LAN address, the full one has them; staging empty afterwards.
    - ~~RT~~ **DONE 2026-08-15**, with a finding that is NOT logging: X
      jogs (F600/F1200, ±5 mm) with `grblhal` at debug: without a camera
      stream `max behind 0–5.8 ms, clamped 0`; with the lid stream running
      steady, `max behind 6–19 ms, clamped 0–11` per run — and the same
      with rsyslogd frozen (SIGSTOP) during the runs (`clamped 0/1/0/10`),
      so the producer clamping under a live stream is the stream's CPU
      load, not the logger (no underrun, the shipper is unaffected). The
      2026-08-03 baseline said `clamped 0` at F1200 with a stream —
      re-check under item 1/10 (VPU stream + cooling engine + telemetry
      polling all landed since).
    - ~~stop/start~~ **DONE 2026-08-15**: `kill -9` of the daemon → the
      wrapper's `forgectrl[-] ERR exited (137) - respawning in 5 s` lands
      through the fifo relay, the respawned daemon stood by, took over the
      unmanaged controller, re-probed motion and restarted it; a mode
      switch to cloud put gfcloud's lines (`ffmachine:_lid_image …`,
      `websocket:img_upload COMPLETE`) in `gfcloud/gfcloud.log` with a
      per-controller relay alive, and back. A `$H` (web-service homing,
      58 s, homed X0 Y0 Z10.60) put gfhome's session lines in
      `gfhome/gfhome.log` under its own pid and grblHAL's `starting
      homing session` / `homed` in `grblhal.log`. **Item closed.** Not
      separately drilled: a Python traceback through the relay — there
      is no external trigger for that; the relay pipe is the same one the
      `logger` probes and the wrapper's `exited (137)` line went through.
      Acceptance catalog: `logs.tree-tail-export` (list, tail, sanitized
      export with the token-leak check), `logs.routing` (one logger
      daemon, rendered rules and effective record consistent with
      `/logs`, the tree, the daemon's own emitter line, `logger` relay
      probes routed by name in the ff_line format, a stray program only
      in system/, kernel lines, relay processes, nothing outside the
      tree) and `logs.level-settings` (bad level/port/proto/server
      refused, a level change configured-not-effective with
      `pending_reboot`, restored) — all three PASS on the bench
      2026-08-15 through the real Runner against an isolated results log
      (the image's forgetest still carries the older catalog until the
      next dev image). Finding from that run, fixed: the sanitized export
      took 13.9 s on the target (0.95 s unsanitized) and tripped the hw
      client's 10 s default — the export call now has its own timeout
      and the sanitizer skips a pattern pass when the line cannot match
      it (4x faster on the host; forgectrl 4d19e9d). **Images
      `20260815215236` (forgefirm-image, 192.7 MB rootfs) and
      `20260815215332` (forgefirm-image-dev) are built on that pin with
      the three logs tests in the dev image's catalog** — the next flash
      carries the fast sanitizer, the init-script default rules, and the
      catalog; nothing else in the logging system is pending.

15. **Release acceptance tool (forgetest) - BENCH-VALIDATED 2026-08-16.**
    Contract: `docs/ACCEPTANCE.md`; catalog v1 (26 tests, coverage lint
    enforced in CI, rule in `CLAUDE.md`). The full catalog ran on the
    dev image `20260815215332` through the tool - takeover, motion,
    cooling, camera, cloud, and the live tests from the page - to 26 of
    26 and an export the gate authorizes against the image's manifest;
    the campaign rules (domain-scoped inheritance, the always-required
    core, FAIL/ERROR closing a campaign, implementation and component
    changes invalidating exactly their domains) behaved as specified
    across the day's closures; the baseline rule was added on the way
    (record in "Release acceptance" above). The flash of `20260816191951`
    exposed the layer-hash over-invalidation (a component pin bump counted
    as a platform change; fixed - pins in `<recipe>-pin.inc`, left out of
    the layer content; record in "Release acceptance" above). Remaining:
    (a) the confirmation campaign - a **full** one, on the **first image
    built with the pin files** (that build is a platform change against
    every result so far; after it, a component pin bump re-requires only
    the tests covering that component) - the tool on the bench is the
    tree, but a hot-patched image is not the image that ships; (b) the
    bench-tab ports are **code-complete 2026-08-16** (every board-runnable
    tool is ported: the scope tools, the flow characterization family,
    the escalation drill, the live drills; record in "Release acceptance"
    above) - their bench validation rides the same next dev image; (c)
    the first release runs the full campaign and commits
    `releases/v<version>/acceptance.json` - **not yet: no release is
    cut.**
16. **Lid / button / interlock parity with the factory firmware — CODE-COMPLETE
    and host-verified 2026-08-16, bench validation pending.** Both controller
    modes now react to the lid, the interlock loop and the button the way the
    factory daemon does (its behavior was decoded and then observed on the
    bench machine booted into factory 2.6.0-2228 the same day: lid open
    mid-print → `cnc/stop` 5 ms after the edge, immediate return to the job
    start with the lid still open, `:cancelled`; app cancel the same path;
    button → pause with a 2000-tick laser-off backtrack, resume with a
    1950-tick laser-off lead; lid while paused → cancel + park).
    - **GRBL mode** (`grblHAL-glowforge/src/glowforge_switches.c`,
      `glowforge_laser.c`): the arm wait aborts on lid or interlock (relock,
      alarm 3, reason reported; a press with the lid open never arms); the
      button is the pause/resume toggle outside the arm wait (feed hold /
      cycle start; the arming press is consumed and never a pause press);
      lid or interlock mid-job → the core parks the job (planned decel) and
      the driver cancels it — armed window closed, reason reported, soft
      reset from the parked state (position kept, no alarm; the sender sees
      the banner), then a driver-enqueued `G53 G0` back to the position the
      job started from with the door hidden and the latch locked; the
      `lid_policy` setting (`cancel` default / `hold` = stock door hold)
      selects it. Job start = machine position at the Idle → Cycle
      transition. Test hook: `GF_SWITCH_FILE` (file-backed EV_SW word for
      null-sink builds).
    - **Cloud mode** (`python3-gfhardware/gfhardware/machine.py`,
      `Glowforge-Utilities` basemachine): interlock joins the lid in every
      gate; the switch thread wakes the run loop on the edge (stop within
      milliseconds, level read as backstop); the park ignores the lid and
      the cancel flag; a hunt ignores the lid; a job refused at start ends
      `:cancelled`; the button pauses/resumes a print exactly as the factory
      (kernel `resume -2000` / `resume 1950`, `print:paused` / `print:resumed`;
      `cloud_pause_backtrack_ticks` / `cloud_resume_lead_ticks` settings);
      hunt honors the cancel flag; every job's terminal event is logged.
    - **Proof so far (host):** `laser_arm_test` (17 new checks),
      `laser_lifecycle_test.py` (button-wait, lid/interlock in the wait,
      button toggle, lid/interlock cancel + return to X=0 without alarm,
      `lid_policy=hold`), `python3-gfhardware/tests/test_machine_lid_button.py`
      (22 cases), gfutilities tests (58), forgetest unit + coverage lint;
      forgectrl builds clean with the three new settings and panel cards.
    - **Bench validation pending (acceptance catalog):** `laser.arm-wait-lid`,
      `motion.button-hold-resume`, `motion.lid-cancel-home`,
      `laser.lid-cancel-mid-fire` (live), `cloud.lid-abort` (live),
      `cloud.lid-during-button-wait`, `cloud.hunt-lid-open`,
      `cloud.pause-resume` (live). Items 4 and 12 above are superseded by
      this policy (the mid-job Door hold is no longer the default path);
      close them with these tests. Still to observe once on the bench: the
      ~90 ms HV_ENABLE re-arm gap on a GRBL resume (whether a dark dwell
      lead is wanted), the app's rendering of `print:paused`, and a lid open
      during the return-to-start motion (should be ignored).
