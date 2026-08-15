# ForgeFIRM bring-up status & cold-start runbook

Last updated: **2026-08-14** — **audit remediation Phases 0 through 9
landed** (from an independent whole-tree audit dated 2026-08-13; the
remediation is sequenced behind two gates — GATE A, uncommanded energy,
before any further live-fire; GATE B, control surface + release, before
any published release). **Every kernel/image row across all phases —
including Phase 9's BSP rows — is now code-complete, and the image
carrying all of it is built: `20260814223300` (forgefirm-image +
forgefirm-image-dev), all source pins pushed, bumped, and
fetch-verified.** Built-image checks pass: the release rootfs has root
locked (`*` in `/etc/shadow`), no watchdog daemon, forgefirm-logrotate
installed, and `K80grblhal`/`K80gfcloud` ahead of `K90forgectrl` at
runlevel 6; the kernel config carries `CONFIG_IMX2_WDT`,
`CONFIG_PANIC_ON_OOPS`, and `CONFIG_PREEMPT`; the DTB fallback
bootargs is console-only; `glowforge.ko` (the full hardening batch) is
in `/lib/modules`. One cosmetic QA warning (a buildpaths reference in
the grblHAL binary from the debug-info prefix maps) is noted for the
Phase 11 sweep. **Flash this image, then run the consolidated bench
campaign** — the GATE A drills, GATE B probes, and every phase's bench
list above validate against it.

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
0644 (B-16); the panel token is stored 0600. Deferred to Phase 11: the
settings file is still 0644 (F-23). **GATE A dry motion drills pass
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
(`machine_is_idle()` returns busy on any `rd_attr` failure) is present
in `status.c` and covered by the `-Werror` CI build; distinctly
exercising the EMFILE→busy path wants a host unit test that injects the
read failure (the clean X-2 closure — the runtime flood cannot reach it
while MHD caps connections below the fd limit). Note for F-15/X-6: the
absence of an explicit `MHD_OPTION_CONNECTION_LIMIT` + per-IP cap is
still the deferred half; the default ceiling held here but a per-IP cap
remains the right hardening.

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
MOTION OK (p2p x=3919, y=1636).

**Deferred (fiddly or config-dependent, not blocking):** G-4 (arm
re-checks the coolant fire gate after the button wait) wants the pump
killed in the instant after the press — cleanest as a host unit test;
the code re-check is in place. Phase 6's "armed job refuses at the stale
origin after an underrun" is config-dependent (GRBL mode permits
unhomed cutting), and the core underrun behavior — `pulse data
underrun; position no longer trusted` with the homing anchor unlinked —
is already logged in the dry dead-man drills above. Live fire only with
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
- **Build host**: WSL2 distro `forge-yocto`, tree at
  `~/dev/openglow-forgefirm`. `~/src-sync.sh` rsyncs the Windows repos in
  (includes `python3-gfhardware` and `grblHAL-glowforge`). Build:
  `cd ~/dev/openglow-forgefirm/forgefirm && kas shell
  kas/forgefirm-glowforge.yml -c 'bitbake forgefirm-image
  forgefirm-image-dev'`. Artifacts:
  `forgefirm/build/tmp/deploy/images/glowforge/`.
- **fwup lab (host)**: `~/fwup-lab/bin/` holds host-built `fwup-0.14.2`
  (factory-era) and `fwup-v1.16.0`; `~/fwup-lab/devkeys/fwup-key.{priv,pub}`
  is the DEV signing keypair (`fwup-key-raw.pub` = raw 32-byte form —
  what fwup 0.14.2 expects; 1.x reads both). Cross-version compat is
  proven both ways (modern-packed signed archives apply with 0.14.2;
  modern fwup verifies+applies the factory .fw — signer key
  2017-05-001.pub). The production signing-key ceremony
  (UPDATE-SYSTEM.md gate 8) was executed 2026-08-08. **The production
  release key is held offline by the operator** — the installer embeds
  its public key, so releases sign with that key only.
  Pack releases with `scripts/mkfw.sh`; the full pipeline is
  `scripts/release.sh`, invoked on this host as:
  `FWUP=~/fwup-lab/bin/fwup-v1.16.0 FWUP_COMPAT=~/fwup-lab/bin/fwup-0.14.2
  FORGEFIRM_DEV_KEY=~/fwup-lab/devkeys/fwup-key.priv
  FORGEFIRM_SIGNING_KEY=<release key> RELEASE_STAGING_DIR=<dir>
  ./scripts/release.sh <version>` (gh for the publish step lives on the
  Windows side; release.sh prints the exact command).
- **Shell gotchas** (cost real time): PowerShell mangles embedded double
  quotes in git-commit here-strings (avoid `"` in messages); `wsl -- bash
  -c '...'` eats `$VAR` expansions (use script files run via PowerShell,
  not Git Bash, which MSYS-mangles `/mnt/c` paths).

## Running the controller (grblHAL-glowforge on the board)

Source: `C:\dev\openglow-forgefirm\grblHAL-glowforge` — the **canonical
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

1. Build: `wsl -d forge-yocto -- bash <repo>/forgefirm/scripts/bench/build-glowforge.sh`
   (from PowerShell). Produces `build-arm/grblHAL_glowforge` in the WSL
   tree (`-O1 -g`; machine constants live in `src/boards/glowforge.h`,
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

Source: `C:\dev\openglow-forgefirm\forgectrl` — the **canonical repo**
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
web panel, and updates. It runs under a respawn wrapper (its init
script) and a restarted daemon retakes supervision automatically once
the machine is idle. The meta-forgefirm recipe pins its SRCREV (bump
deliberately after pushing) and installs the sysvinit script from the
repo's `init/`; bench builds cross-compile with
`forgefirm/scripts/bench/build-forgectrl.sh` (same toolchain-borrow
pattern as build-glowforge.sh). The **machine-services contract** —
the EV_SW switch map, the authoritative sensor conversions, the
hardware single-writer ownership matrix, the cooling channels, mode
supervision, and pulse-device ownership — is
`forgectrl/docs/SERVICES.md` in the forgectrl repo. One ulfius daemon
serves it all, including both OV5648 cameras as MJPEG over the
mainline imx-media pipeline:

- `GET /` — the tabbed machine control panel (Status / Machine /
  GF Cloud / GRBL / Diagnostics; ui.c): status page with the
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
core). Run by hand: `/usr/bin/forgectrl >> /data/forgectrl.log 2>&1 &`
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
  **SW_ESTOP reads LOW during ANY motion** (measured 2026-08-07:
  polled at 20 ms through X and Z jogs — low for the whole run, ~70/75
  samples, recovers instantly at idle; True at idle) — must NOT gate
  motion on the factory board either (it false-tripped every legacy
  cloud motion ~0.1 s in). Doors/door1/door2 stay stable during motion.
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
       nobody at the button; `laser_arm_test.py` drill): latch locked
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
       moves). Behaviour at 27–32 °C baselines, and under real laser
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
4. **Controller safety mapping — IMPLEMENTED 2026-08-13, bench validation
   pending** (`grblHAL-glowforge/src/glowforge_switches.c`). The
   controller reads EV_SW with `EVIOCGSW` from the protocol thread's
   realtime hook (no grab — forgectrl polls the same device) and maps:
   - **doors (bit 3) not closed, or interlock (bit 5) loop open →
     the core's `safety_door_ajar`.** A running job parks in the door
     state and resumes when the condition clears, which is what the
     hardware chain already does to the beam. Bit 3 is the series
     combination the safety chain itself uses, not the individual door
     switches.
   - **e-stop (bit 4): opt-in only.** The line rests ACTIVE on a
     healthy machine and drops for the duration of any stepper motion
     on this board, so gating on it would abort every job. Set
     `estop_halts_motion` in `/data/forgefirm.conf` (hand-edited; it is
     not in forgectrl's settings whitelist, and unknown keys survive
     forgectrl's writes) for a machine retrofitted with a real e-stop
     circuit. Same escape hatch as the cloud client's
     `MOTION.ESTOP_HALTS_MOTION`.
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
   and `interlock_latch_reset` remains a readback.
   **Bench items:** open the lid mid-job (expect `Door` at the sender,
   motion parked, resume on close); jog and `$H` with the lid open
   (refused); a Pro with an unjumpered interlock connector (expect the
   same door behavior); confirm no spurious door events across a full
   job. Underrun → alarm was already covered by the stream-fault path.
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
     `[contract, pending]` item left). `cnc/enable` / `cnc/disable`
     are not forgectrl-only writes yet: under the broker no client
     drops the rail any more, but the GRBL driver still writes
     `cnc/enable` at init and at homing resume — idempotent, since the
     rail is already up and settled, so this is tidiness rather than a
     bounce source. (An idle-rail-off policy is not part of this: the
     rail stays up while the machine is on, per the wedge model in the
     facts bank.)
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
