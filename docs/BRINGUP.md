# ForgeFIRM bring-up status & cold-start runbook

Last updated: **2026-08-26**.

This is the present state of the machine, the bench runbook, the measured
hardware facts, and the authoritative list of open work. **The dated record —
bench campaigns, drills, scope gates, the audit remediation, the acceptance
campaigns — is [`CAMPAIGN-LOG.md`](CAMPAIGN-LOG.md)**; come here for what is
true now, go there for how it was proven.

Read together with:

| Document | What it settles |
|---|---|
| `kernel-module-glowforge/UAPI.md` | the pulse-stream feeder contract, sysfs attributes, sensor conversions |
| `forgectrl/docs/SERVICES.md` | the machine-services contract: switch map, hardware ownership, cooling channels, mode supervision, pulse-device ownership, logging |
| `docs/SAFETY.md` | the hardware safing chain, decoded |
| `docs/VIDEO.md` | the cameras as users meet them: endpoints, delivered geometry, and what the sensors can do that ForgeFIRM does not send |
| `docs/LIGHTBURN.md`, `docs/UPDATE-SYSTEM.md`, `INSTALL.md` | sender setup, A/B update system, install |
| [docs.forgefirm.org/developers](https://docs.forgefirm.org/developers/) | build, release flow, tests, the bench runbook |
| `python3-gfhardware/forgefirm-app/docs/CLOUD.md` | cloud mode, including its own open items |

## Where the project stands

**The machine works, in both controller modes, and the whole stack is
hardware-validated.**

- **Platform bring-up: complete and hardware-verified.** SDMA + EPIT pulse
  playback out of a reserved DMA pool, live-fed during a run; laser PWM at
  39.98 kHz; `CONFIG_PREEMPT=y`; both OV5648 cameras on the mainline
  imx-media pipeline with VPU JPEG encode; A/B slot install, signed `.fw`
  releases and factory restore.
- **GRBL mode cuts real jobs.** grblHAL (the stock core plus one local fix, and
  the ForgeFIRM driver) speaks Grbl 1.1f over TCP:23; LightBurn drives motion, the laser and the
  camera stream. First light landed 2026-08-11.
- **Cloud mode runs the factory experience end to end**, deliberately kept
  and maintained: sign-in, camera homing, prints, pause/resume, cancel.
- **forgectrl is the one machine-services daemon** behind both modes —
  cooling engine, controller supervision, pulse-device broker, motion-liveness
  gate, cameras, telemetry, settings, diagnostics, logging, updates, web panel.
- **Laser safety is hardware-first and bench-proven.** The chain
  (`LID_SW1 & LID_SW2 & INTERLOCK & HV_OK & supplies-OK → OK_2_FIRE`,
  `FIRE & OK_2_FIRE → LASER_ON`) gates the beam; the kernel latch, the
  operator-armed window, the coolant fire gates and the dead-man chain sit on
  top. GATE A (uncommanded energy) and GATE B (control surface + release) are
  both closed.
- **Lid, interlock and button behave like the factory firmware** in both
  modes (cancel-and-return on a lid or interlock open, button pause/resume),
  bench-validated 2026-08-17.
- **Releases are gated by the acceptance tool** (`forgetest`, dev image only):
  a 46-test catalog, domain-scoped inheritance, an always-required safety core,
  a bench actuator that works the lid, the interlock and the button so most of
  the operator's part runs unattended, and a release gate that reads the
  exported artifact. The latest full campaign, on dev image `20260824230512`,
  satisfied 45 of 45 from nothing in 27 minutes (36 tests unattended) and
  authorizes a release; **no release is cut yet.**

Current bench state: dev image `20260824230512`, the board resting on the SD
dev image (eMMC slot 1 = factory 2024, slot 2 = ForgeFIRM v0.1.0, archives in
`/data/forgefirm/archive`).

## The bench

- **Board**: SSH `root@<machine-ip>` (dev images permit passwordless root
  login). The bench machine is a **Basic/Plus** (the control board is common to
  Basic/Plus/Pro). Dev image (`forgefirm-image-dev`) on SD; BusyBox userland +
  python3 + gdb/strace. Serial console on ttymxc0 available at the bench.
- **Deploying kernels**: re-burn the SD with the freshly built
  `forgefirm-image-dev-glowforge.rootfs.wic.gz` (deploy dir below). Why this
  works: U-Boot (in eMMC boot0) reads the saved env at eMMC user-area 0x80000,
  which selects the boot device (bench board: `mmcdev=0
  mmcroot=/dev/mmcblk1p1` = SD), then loads `/boot/uEnv.txt` and `/boot/zImage`
  from that rootfs partition — so the kernel always comes from the burned SD.
  Full map: "eMMC boot & recovery architecture" in the facts bank below.
  **Module-only changes hot-swap**: scp `glowforge.ko` over
  `/lib/modules/<kver>/extras/`, then `rmmod glowforge && modprobe glowforge`.
  NOTE: a module reload turns off the lid LED (relight via
  `/sys/class/leds/lid_led*/target`) and resets the analog configuration, and
  the first liveness probe after a reload can read NO MOTION until the ladder
  re-probes.
- **Module hot-swap vs kernel re-stamps**: the hot-swap only loads if the
  module was built against the FLASHED kernel's patch state. Any edit under the
  kernel recipe's overlay (e.g. `glowforge.dts`) re-stamps
  `CONFIG_LOCALVERSION_AUTO` — and the stamp does NOT reproduce by reverting
  the edit (the kernel patch tree is a fresh git commit each `do_patch`, not
  sstate-restored), so after any overlay edit the module can only ship with a
  full image flash. **Kernel/BSP changes therefore ride one image flash,
  batched**, and a `.ko` or overlay change is validated on the image that ships
  it, never hot-swapped onto a board about to be reflashed.
- **Build host**: a Linux build environment (a WSL2 distro works) holding the
  `forgefirm` + `meta-openglow` sibling checkout (the site, Developers,
  "Build"); the ForgeFIRM
  source repos are fetched by pinned `SRCREV`. Build:
  `cd forgefirm && kas shell kas/forgefirm-glowforge.yml -c 'bitbake
  forgefirm-image forgefirm-image-dev'`. Artifacts:
  `forgefirm/build/tmp/deploy/images/glowforge/`.
- **fwup lab (host)**: a host directory (`<fwup-lab>`) holds host-built
  `fwup-0.14.2` (factory-era) and `fwup-v1.16.0` under `bin/` and the DEV
  signing keypair `devkeys/fwup-key.{priv,pub}` (`fwup-key-raw.pub` = raw
  32-byte form — what fwup 0.14.2 expects; 1.x reads both). Cross-version
  compatibility is proven both ways (modern-packed signed archives apply with
  0.14.2; modern fwup verifies and applies the factory `.fw` — signer key
  2017-05-001.pub). **The production release key is held offline by the
  operator** — the installer embeds its public key, so releases sign with that
  key only. Pack releases with `scripts/mkfw.sh`; the full pipeline is
  `scripts/release.sh`, invoked as:
  `FWUP=<fwup-lab>/bin/fwup-v1.16.0 FWUP_COMPAT=<fwup-lab>/bin/fwup-0.14.2
  FORGEFIRM_DEV_KEY=<fwup-lab>/devkeys/fwup-key.priv
  FORGEFIRM_SIGNING_KEY=<release key> RELEASE_STAGING_DIR=<dir>
  ./scripts/release.sh <version>` (the publish step needs an authenticated
  `gh`; release.sh prints the exact command).
- **Bench hygiene**: stage test files in `/tmp`; anything that must survive a
  reboot goes in `/data/bench-scratch/` and that directory is deleted whole at
  the end of the session. Bench tools worth keeping live in
  `forgefirm/scripts/bench/` and ship on the dev image under
  `/usr/share/forgetest/bench/`.
- **Shell gotchas** (cost real time): PowerShell mangles embedded double quotes
  in git-commit here-strings (avoid `"` in messages); `wsl -- bash -c '...'`
  eats `$VAR` expansions (use script files run via PowerShell, not Git Bash,
  which MSYS-mangles `/mnt/c` paths).

## Running the controller (grblHAL-glowforge on the board)

Source: the `grblHAL-glowforge` sibling repo — the **canonical grblHAL driver
repo** (github.com/ScottW514/grblHAL-glowforge, branch `main`): core as a
submodule at `src/grbl` (→ ScottW514/core fork, branch `forgefirm` = upstream
master plus one local commit, the `step_us_min` buffer sizing that keeps a
fortified build from aborting in `settings_init`; the settings-write crash fix
merged upstream 2026-08-04 as grblHAL/core PR #999). `driver.c` implements the
HAL; machine constants live in `src/boards/glowforge.h`.

**The controller is spawned and supervised by forgectrl**: the supervisor
starts the controller selected by `controller_mode` (grbl | cloud) as a direct
child, respawns it on a crash (after safing the machine), and switches modes
live via `POST /mode` / the Status-tab selector. The `grblhal` and `gfcloud`
init scripts defer to it (they remain as manual emergency levers, routed
through `POST /controller/stop|start`). The pulse device arrives as a
broker-inherited fd (`GF_PULSE_FD`) — the device never closes across mode
switches, homing handovers or respawns, so the 40 V rail never cycles as a side
effect — and the supervisor verifies **physical motion** (head-accelerometer
liveness probe) before the first controller spawn of each session.

Architecture: a wall-paced producer thread runs the core stepper ISR against a
virtual step clock (1000× machine tick) and maps step events to pulse bytes; a
SCHED_FIFO shipper feeds `/dev/glowforge` through a bounded queue; a recursive
core mutex stands in for interrupt masking. `GFSINK` unset = null-sink mode
(full engine, no hardware I/O — host testing and CI).

1. Build: `bash <repo>/forgefirm/scripts/bench/build-glowforge.sh` in the build
   environment (from Windows, launch it through the WSL distro from PowerShell
   — Git Bash mangles `/mnt/c` paths). Produces `build-arm/grblHAL_glowforge`
   in the checkout (`-O1 -g`; machine constants force-included into the core:
   53.333 µsteps/mm XY @ ×8, 2.832 half-steps/mm Z, 0.417" Z travel,
   12000 mm/min max, 700/590 mm/s² accel — factory-derived, see
   `puls_profile.py`).
2. Deploy: move the new binary over `/usr/bin/grblHAL_glowforge` (mv replaces
   the inode, so the running instance is untouched), then kill the running
   controller — the supervisor respawns it on the new binary within about a
   second.
3. Standalone start (bench/debug only — requires forgectrl stopped, since the
   broker's exclusive hold on `/dev/glowforge` makes any self-open fail EBUSY):
   `cd /data && GFSINK=/dev/glowforge grblHAL_glowforge -p 23 -e
   /data/EEPROM-glowforge.DAT`. Env knobs: `GFSINK_RATE` (machine tick, default
   28160 Hz = factory travel tick), `GFSINK_DEPTH_MS` (queue depth = feed-hold
   latency, default 200). Standalone, the driver opens the device itself and
   every takeover runs the `rail_settle_s` off-period; under the broker it
   inherits the fd and skips the settle (the rail never dropped). The driver
   applies the full analog machine config at init either way (×8 modes, decay 1,
   motor_lock 8, laser latched, PIC hold currents) and swaps PIC run/hold
   currents around motion. Each motion run logs a producer-stats line
   (callbacks, µs/call, max-behind, clamped) — `clamped` should stay 0.
4. Connect LightBurn/UGS to `<machine-ip>:23`, or jog raw: `$J=G91X40F1200`.
   `^X` mid-motion aborts via kernel `cnc/stop` (controlled decel) and raises an
   alarm; TCP disconnects never kill the process (the dead-man fd stays held).

**Spindle `$`-settings take effect at controller start.** The core
precomputes the S -> duty mapping once, when the spindle is enabled, and a
settings write does not re-run it: `$35=16` persists to the eeprom
immediately and `$$` reports it immediately, but the mapping in force is
still the one loaded at start until the controller restarts (a mode switch,
a `POST /controller/stop` + `start`, or a boot). Verified host-side: after a
runtime `$35=0` the shipped duties stay floored.

**Stored `$`-settings beat freshly baked defaults** — after changing
`GLOWFORGE_DEFAULTS` values, run `$RST=$` once on the board (settings persist
in the eeprom file in `/data`).

**Protocol-loop pacing is fd-blocking.** `serial_wait()` drains TX then
`ppoll()`s the listen/client fds with a state-dependent timeout: idle and alarm
at 10 ms (1 ms while a delay callback is pending), motion at 200 µs, and the
parked states — a completed feed hold, a parked door ajar or closed, and sleep
— at the coarse idle poll, while the motion sub-phases (`Hold_Pending` decel,
`Parking_Retracting`/`Resuming`) keep the tight pace. Measured on the bench:
idle 2.7 %, active move 34–35 %, parked 2.7–3.0 %. Client RX is armed only
while the ring has a full read's worth of room, so a flow-control-violating
sender is paced, not spun on.

## Laser control (GRBL mode)

The real spindle lives in `grblHAL-glowforge/src/glowforge_laser.c`.
Per-segment spindle updates (the core's laser-mode path, on the stepper
producer thread at exact virtual-tick positions) map power and fire transitions
onto the pulse-byte grid via `gf_stream_laser()`, and the shipper emits them: a
power byte (`0x80 | 7-bit duty`, raw PWMSAR counts, 127 = 100 %) inserted ahead
of the first tick byte it covers, FIRE as bit 4 OR'd into tick bytes. The
spindle PWM is precomputed to a period of exactly 127, so computed values ARE
power bytes (`$30` default 1000 → S1000 = 127).

**Dose model: density, the only one.** The shipper renders the
per-segment value the core computes by pinning the duty at full and
modulating the FIRE bit on a base period of `laser_pulse_ticks` (default
20 = 710 us at 28160 Hz, the factory's ~1.43 kHz) whose on-count is
dithered between adjacent integers with the remainder carried, so
densities finer than one tick per period average out. Every pulse is
full-power, so no commanded level can land in the tube's dead band, and
no beam-on ever dwells: the analog alternative (duty as the power byte,
continuous FIRE) fires the strike transient as a visible spot at every
turn-on whatever the power, and was removed as a product mode for it -
the rendering survives only as the host harness's conservatism
reference, selectable solely in the null-sink build.
`laser_pulse_min_ticks` (default 3 = 106 us) is the shortest pulse the
model emits: below it a period is skipped and its debt carried, so a
faint level arrives as fewer full-width pulses instead of stubs the
supply cannot strike - measured on the bench, a 36 us stub draws no
discharge at all, and the factory never emits below one of its 100 us
ticks. The debt is conserved, so the average density is unchanged: at
level 2 the stream goes from 444 one-tick bursts to 147 three-tick
bursts, same density to four decimals. Structurally the model is a mask
on the core's fire state and never a source of one, so emission stays
exactly where the core commanded it.

**The floor is derived, never typed.** `laser_floor_density` (default 10,
the lowest density that still marks, putting a commanded 1 % at 10.2 %
density) is loaded into `$35` at every spindle precompute - boot
included - in RAM only: the stored `$35` is never written, `$$` reports
the floor in force, and a `$35` typed by a sender is overwritten on the
spot. The arm report names it (`laser armed (density, floor 10 %)`), and
a floor of 0 is honored with a note (the ladders run that way). The
cooling report carries the model with the job state.

**S commands light, through the measured curve.** The tube's output is
convex in pulse density (this bench, 2026-08-30, by the head thermopile,
the tube current and the operator's eye: 80 % density delivers about
half the CW light, 60 % a third, 45 % a fifth, 30 % a fourteenth - the
same physics behind the factory's 18.9 to 79.5 % mapping with Full
Power kept apart). So the driver maps the commanded fraction through
the measured curve's inverse onto the density that delivers it:
`laser_dose_curve` in the machine config holds density:light percent
pairs, ships with the bench-measured default compiled in, accepts
`off` for the identity, falls back loudly on a bad value, and is
reloaded at every precompute with the arm naming it (`laser armed
(density, floor 10 %, curve bench-default)`). `$35`/`$36` still floor
and ceil the result. Under M4 the curve makes delivered light exactly
proportional to velocity - and heat still accumulates where the head
slows, so corners over-burned on the bench; `laser_corner_gamma`
(default 2, range 0.25 to 4) bends the rolloff to light proportional to
(v/v_programmed)^gamma, starving the slow spots the way the raw convex
mapping used to by accident, while the programmed level at speed stays
exactly the curve's. The knob is per machine and per taste: this bench
runs 1.5, and the commissioning side-by-side chooser (the "Initial
commissioning" item under Next work) is how a machine finds its own. An owner measures their own curve from the panel:
the dose-curve recorder streams the ladder job itself from one Record
press (absolute from X0 Y0, refused while a sender is connected; the
operator's button press starts the fire with every arm gate standing),
records the tube current and the head thermopile, fits the rungs, and
Apply writes the result (`forgectrl/docs/SERVICES.md`). Rasters hold their tonality down
to ~14 pulse slots per pixel (508 DPI at 6000 mm/min): the dither
accumulator's cross-pixel averaging recovers the levels, with no
visible dither pattern.

An S word takes effect whether or not motion is in progress. Per-segment
updates carry the level inside a laser block, but an S executed between
blocks - with the planner drained, so nothing is streaming - arrives only
through the synchronous spindle path, which publishes the duty without
touching the fire state; and the next run re-asserts the laser state the
core last asked for at its first byte, fire only inside an armed window.
Without those two a standalone S from a sender slow enough to drain the
planner left the following moves cutting at a stale duty, or dark.

Contract rules enforced structurally: a power byte leads every kernel run
before any fire bit (a run start resets duty to ~100 %), transitions are
coalesced per tick so power bytes are never consecutive, and power bytes cost
no machine tick. Fire only ever rides motion segments of laser blocks — jogs,
G0 and homing are fire-free by construction — and the end-of-data backstop
covers every stream end. **Duty persists after end-of-data** (PWMSAR retains
its last value): the laser-off guarantee rests entirely on FIRE.

**Arming — the operator's button press is required.** The first laser-on of a
job (M3/M4, planner-synced) refuses outright if a coolant fire gate stands or
if no head is detected (`ALARM:3`, "laser fire blocked: no head detected"),
else forces the run fan profile on, unlocks the kernel laser latch, lights the
button white and blocks the gcode stream — pumping real-time traffic — until
the operator presses the physical button (EV_SW bit 2), a soft reset aborts, a
lid or interlock open cancels, or `laser_button_timeout_s` (default 300 s)
expires into alarm 3. The coolant verdict is re-checked immediately after the
wait, before the window opens. The armed window survives S changes and M5/M3
toggles (no re-prompt mid-job) and closes — relocking the latch — at program
end (`M2`/`M30`/`%`), when the sender connection changes, after
`laser_disarm_s` (default 60 s) of spindle-off idle, or immediately on
alarm/homing/reset/stream fault. The disarm grace counts down in Hold, Door and
Tool Change too. Both keys live in the shared machine config, re-read per arm.

**Underrun policy while armed: fail safe, no retry.** The stop/run recovery
restarts the kernel run, which resets duty to ~100 %, so replaying queued fire
bits would fire at full power: an armed underrun acks the kernel and faults
(alarm, latch relock, homing anchor unlinked). Motion-only streams keep the
one-shot retry.

**Coolant fire gates live** (`gfcool_fire_ok`): a flow FAULT or an over-ceiling
coolant temperature blocks arming and suppresses fire mid-job with a loud
warning. While armed, the run fan profile and flow interrogation are forced on
regardless of the sender's M8/M9; a SUSPECT/FAULT verdict inside an armed
window takes the safe posture (feed hold + run airflow). SUSPECT auto-resumes
on a clean re-check; FAULT leaves the hold and the gate for the operator.

**The controller publishes its state for the daemon.** forgectrl can
never open the Grbl socket (a connection displaces the sender), so the
controller writes two files under `/run/forgefirm`, atomically, on
edges: `grbl.settings` (the `$$` view, rewritten on every setting
change and whenever the derived floor moves) and `grbl.state` (JSON: machine state
and alarm, the sender session with peer and generation, the laser's
armed window and dose model with its floor, the exact `[GC:...]` modal
report, overrides, driver version, `ts_mono` for age; on change plus a
5 s heartbeat). forgectrl echoes the state file in `GET /status` as the
`grbl` block only while it supervises a live GRBL controller, serves
the settings file at `GET /grbl/settings`, and the panel's GRBL card
renders it. Position stays out: it changes per segment and is served
from the kernel counters. Contract: `forgectrl/docs/SERVICES.md`.

**Emission evidence.** `cnc/laser_on_sampled` (surfaced as `/status`
`laser.emission_samples`) is the reliable live-emission witness; emission
sensed with no armed window relocks the latch and stops motion. `pic/hv_current`
is the only live HV telemetry on this PSU. `cnc/laser_pgood_sampled` is **not**
a usable witness here — it reads 0 through real cutting.

## Lid, interlock and button policy

Both controller modes react the way the factory daemon does (decoded from a
factory 2.6.0-2228 session; measured numbers in the facts bank).

- **Lid or interlock open during a job, running or paused:** motion stops
  within milliseconds of the edge, the job is **canceled and not resumable**,
  the head returns to the position the job started from **with the lid still
  open**, the kernel latch relocks and the armed window closes. The
  return-home park ignores the lid and always runs to completion. The next job
  re-arms with a button press — the same press the hardware button latch needs,
  so software and hardware agree by construction.
- **During the pre-run button wait:** a lid or interlock open cancels the job
  with the reason named (clean soft reset, no alarm); a press with the lid open
  never arms.
- **Ignored:** a lid open during a hunt, homing, a jog, or at idle.
- **The button pauses and resumes a job.** Cloud mode uses the factory's
  laser-off backtrack and resume lead (`cloud_pause_backtrack_ticks` 2000 /
  `cloud_resume_lead_ticks` 1950), on a preloaded job and a live-fed one
  alike: the retrace is sized to `cnc/max_backtrack` and the lead follows it,
  so a pause with little history behind it shortens both rather than failing.
  GRBL mode uses feed hold / cycle start, so a resumed GRBL cut picks up where
  the deceleration ended (item 11). A pause is not a cancel: the latch
  stays unlocked and the window open across it. There is no resume dwell: the
  safing chain re-arms ~216 ms before the first step (facts bank).
- **`lid_policy = hold`** selects stock grblHAL door behavior instead (park in
  Door, cycle start after the lid closes resumes with position intact).

Switch mapping (`grblHAL-glowforge/src/glowforge_switches.c`; the controller
reads EV_SW with `EVIOCGSW` from the protocol thread's realtime hook, no grab):
doors = bit 3 (the series combination the safety chain itself uses), remote
interlock = bit 5 (inverted sense), button = bit 2. The door signal is hidden
from the core while it is IDLE, JOG or HOMING (`gfsw_visible`) so a lid cycle at
idle cannot park the controller in `Door:0` and leave a sender waiting.
**hv_enable (bit 4) is never gated on** — it is the readback of the chain's
HV_ENABLE output, telemetry only. **The interlock latch (bit 6) is not gated on
either** — the hardware chain enforces it. No switch device (host builds) = no
capability advertised. `GF_SWITCH_FILE` is the file-backed EV_SW word that lets
null-sink builds drive these edges in CI.

## Homing

Runtime-selectable through `homing_mode` in `/data/forgefirm.conf` (forgectrl
`GET/POST /settings`, panel selector); the driver re-reads the file on every
`$H`:

- `gfcloud` — factory camera homing via the Glowforge web service. **Live
  verified**; a full cycle runs in 50–65 s.
- `switches` — the planned limit-switch cycle (falls through to the core, still
  disabled `$22=0`).
- `none` — `$H` rejects with error 5.

Architecture: `glowforge_homing.c` registers a driver `$H` that shadows the
core's; for gfcloud it suspends the stream engine (only from a fully idle
kernel — closing the flock'd fd mid-program is an e-stop), spawns
`/usr/sbin/gfhome.py` (config `/data/etc/gfhome.conf`, first-run copy from
`/etc/gfhome.conf.sample`), pumps the protocol so senders keep getting status,
then reacquires the device and re-applies the analog config and `step_freq`.
`^X` aborts the session (SIGTERM → SIGKILL); failure or timeout queues
`ALARM:18` like a failed core cycle (`gfcloud_home_timeout_s`, default 300).
The runner drives the GFUIService dispatch itself (the stock `run()` loop can
neither stop nor close the socket) and treats hunt + ≥1
accelerometer-witnessed motion window + quiet (10 s) as complete — the modern
v2.6.0 sequence, captured from a live service session, is settings → hunt → lid_image
→ single corner move → lid_image → silence. It then re-homes
the lens against the hall for a deterministic Z. **A quiet service without an
accel-witnessed motion window is a failure, not a homing.**

Position semantics: factory home = machine origin (back-left corner, +Y =
FRONT, workspace all-positive 0..495 × 0..279); Z top-of-travel = 10.6.
`gfcloud_home_x/y/z` calibrate the post-home coordinates once measured
(defaults 0 / 0 / Z max). GRBL mode permits unhomed cutting — position shows
counters-only and painted red until anchored.

## The machine-services daemon (forgectrl, port 8080)

Source: the `forgectrl` sibling repo (github.com/ScottW514/forgectrl, branch
`main`, MIT). It is the ForgeFIRM machine-services daemon: **controller-mode
supervision**, the **pulse-device broker**, the **motion-liveness gate**, the
**cooling engine** (single owner of fans/pump/TEC/heater for both modes), plus
cameras, telemetry, settings, diagnostics, the web panel, updates and the
**logging tree**. It runs under a respawn wrapper (its init script); a
restarted daemon retakes supervision once the machine is idle — an unmanaged
controller left running mid-move is replaced at idle, not adopted (the old
inherited fd cannot be taken over). The meta-forgefirm recipe pins its SRCREV
in `forgectrl-pin.inc` (bump deliberately after pushing) and installs the
sysvinit script from the repo's `init/`; bench builds cross-compile with
`forgefirm/scripts/bench/build-forgectrl.sh`. The **machine-services
contract** — EV_SW switch map, sensor conversions, hardware single-writer
ownership, cooling channels, mode supervision, pulse-device ownership, logging
— is `forgectrl/docs/SERVICES.md`.

Every state-changing endpoint requires the first-boot bearer token in `/data`
(embedded in the panel), a Host address-literal check, and
`Sec-Fetch-Site`/`Origin` validation (CSRF and DNS-rebinding refusal).
`/cool/state` is loopback-only. `/fuse-identity` and unsigned-firmware installs
additionally require the physical button held.

One ulfius daemon serves it all:

- `GET /` — the tabbed control panel (**Status / Machine / GF Cloud / GRBL /
  Diagnostics / Logs / System**; sources in `forgectrl/src/ui/`,
  `index.html` + `panel.css` + `panel.js`, bundled into the binary by
  `embed.cmake`; `tools/devserver.py` and the repo's `.devcontainer/` serve the
  same panel on a workstation against a live board or a mock). Status carries
  the controller-mode selector, the operational dashboard, a scaled lid
  snapshot and an on-demand live stream; System carries A/B slot selection,
  ForgeFIRM updates, image install/restore, the wireless regulatory region and
  reboot. All settings controls disable (with a banner) while the machine is not
  idle **or a diagnostic is running**. `/?action=stream|snapshot` remain the
  mjpg-streamer-compatible aliases (lid camera; LightBurn uses the stream one).
- `GET /status` — motion state and true machine position (kernel step counters
  anchored at homing via `/run/grblhal.homed` — the Grbl socket is never polled,
  a connection there displaces the sender), coolant temps, pump/TEC, all four
  fan tachs, the sensed laser evidence (emission samples, HV current, lid IR),
  faults, the safety switches via `EVIOCGSW` (head = real presence, i.e. the
  head sysfs group exists), and a `diag` flag for the UI lock.
- `GET/POST /settings` — the shared machine settings store
  (`/data/forgefirm.conf`, 0600, validated keys, empty-value-clears via query
  params; `gf_password` write-only). **Writes 409 unless `cnc/state` is idle**
  and 409 while a diagnostic owns the hardware; a multi-key POST lands as one
  atomic replace. Keys: `controller_mode`, `homing_mode`, `gfcloud_home_x/y/z`,
  `gfcloud_home_timeout_s`, `gf_serial`, `gf_password`, `ui_units`,
  `wifi_country`, the nine `cool_*` tunables, `laser_button_timeout_s`,
  `laser_disarm_s`, `rail_settle_s`, `lid_lamp_idle`, `lid_policy`,
  `cloud_pause_backtrack_ticks`, `cloud_resume_lead_ticks`, the twelve
  `log_<logger>_disk|_remote` levels and `syslog_server|port|proto`.
  `cool_fire_ir_delta` is a hand-edited conf key, not a panel setting.
- `GET /mode`, `POST /mode?controller=grbl|cloud` — the supervisor: current
  mode, controller state (`running | stopped | standby | motion-fault`), pid,
  and the motion-liveness verdict (`verified | unverified | fault`); the POST is
  the live idle-gated mode switch and the retry lever after a motion fault.
- `POST /controller/stop|start` — the routed emergency levers the init scripts
  use. Stop writes `cnc/stop` + `cnc/laser_latch=1` **before** the SIGTERM
  (kernel-level, instantaneous) and holds supervision suspended.
- `POST /cool/state` (job-state reports from the active controller, level-
  triggered ~1 Hz) and `GET /cool/status` (engine phase, verdict, temps, report
  age). The verdict the controllers enforce is the
  `/run/forgefirm/cooling.state` file.
- `POST /diag/flow-verify|flow-calibrate|abort`, `GET /diag/status` — the
  diagnostics runner (below).
- `GET /cam/stream?cam=lid|head` — multipart MJPEG at half the sensor's frame
  in each axis, 1296×972 on a 5 MP machine (2×2 Bayer-superpixel demosaic,
  JPEG q75; `FORGECTRL_STREAM_Q` overrides, `FORGECTRL_STREAM_FPS` caps the
  frame rate, unset/0 = sensor max).
- `GET /cam/snapshot?cam=lid|head&res=full|half&q=1..100` — single JPEG,
  default the sensor's full frame, 2592×1944 on a 5 MP machine (own MIT
  bilinear demosaic).
- `GET /cam/status` — JSON (running/cam/clients/frames/fps/fps_cap/encoder/
  buffers/sensor, the stream + snapshot geometry the fitted sensor implies,
  and the privacy gate's `capture_allowed` / `stopped_by_lid`). Stream and
  snapshot answer 409 while the lid is open.
- `GET /slots`, `POST /boot`, `POST /update/check|download|apply|upload`,
  `GET /update/status`, `POST /restore/factory`, `POST /system/reboot` — the
  A/B update manager (`docs/UPDATE-SYSTEM.md`). Upload is auth + idle + job
  gated; a booted-slot write is refused under any `root=` spelling.
- `GET /logs`, `GET /logs/tail`, `POST /logs/export` — the logging tree
  (below).
- `GET /fuse-identity` — serial, derived hostname and the SRK password, behind
  the token AND the physical button; fetched on demand only.

**Panel conventions:** the header identifies the machine by its **fuse
identity** (the factory hostname derived from the OCOTP serial), regardless of
any cloud identity override. **Units** are a display-only preference
(`ui_units`): the backend stores metric, and saves post only fields whose
display string changed. **Position always shows** — counters-only and painted
red while unreferenced, normal once anchored.

**Camera engine.** One worker owns the V4L2 node persistently (media-ctl /
v4l2-ctl sequences identical to `gfhardware/cam.py`, factory exposure/gain/WB,
software hflip in the demosaic); it starts on demand and tears down fully after
10 s idle so gfhardware one-shot grabs still work. **Privacy gate: neither
camera captures unless the lid is closed** — `machine_lid_closed()` (EV_SW
bit 3, fail-closed) is checked at every entry point and once per frame, so an
open lid refuses stream and snapshot with HTTP 409 and a lid opened mid-capture
tears the pipeline down; `gfhardware.cam.capture()` enforces the same rule for
the cloud client's direct-V4L2 fallback and raises `LidOpen`. No setting
disables it, and the factory's lid-open focus hunt now fails as a result
(`docs/VIDEO.md` §2, `forgectrl/docs/SERVICES.md`). Geometry, Bayer depth and
the manual control set come from a **sensor profile** chosen by whichever
driver bound on that camera's I2C bus, so one image serves both the 5 MP
OV5648 (2592×1944) and the 8 MP OV8856 (3264×2448) — both 8-bit BGGR, so the
capture word and the demosaic are the same and only the geometry changes;
`/cam/status` reports the model and the frame sizes that follow from it.
A frame the capture queue flags errored is dropped rather than demosaiced,
four in a row cycle the queue, and three cycles with no usable frame stop the
engine; `/cam/status` carries the running `health` counts (`src/camhealth.c`,
host test `camhealth_test`). The cameras share the
hardware video-mux and the NEWEST request wins it: **streams preempt** (the
current stream's clients end cleanly), **snapshots borrow** (pause, switch,
grab one frame, switch back — a ~1–2 s freeze). The per-camera lamp
(`pic/lid_led` / `head/white_led`) is raised to `FORGECTRL_LAMP` (default 132)
while capturing and restored to the resting level on idle. The resting lid lamp
is the `lid_lamp_idle` setting (0–255, default 236), asserted at daemon start,
on a live settings change, and at every controller spawn.

Measured performance (bench): **15.0 fps sustained** at 1296×972, sensor-
limited — NEON superpixel→YUV420 convert (18–20 ms) plus CODA960 VPU JPEG
encode (7 ms) on cached (non-coherent) V4L2 capture buffers, so there is no
bounce copy; daemon ~41 % CPU with one viewer. Full-res snapshot 2.4 s warm /
2.7 s cold. Fallbacks, each bench-verified: `FORGECTRL_NO_CACHED_BUFS` (bounce
copy, needed on a kernel without the `allow_cache_hints` patch — detected via
the `MMAP_CACHE_HINTS` capability bit), `FORGECTRL_NO_NEON` (scalar convert,
bit-identical), `FORGECTRL_NO_VPU` (libjpeg; also the snapshot path).
The default path is newer and bench-proven: the GC880 GPU demosaic feeding the
`/cam/h264` CODA960 H.264 stream (render, IPU stride-fix crop, VPU encode;
~14 fps for one viewer at ~14 % CPU, luma bit-clean against the CPU path) with
CSI hardware frame skip as the low-CPU setting; `camera.h264-stream` covers
it in the acceptance catalog. `FORGECTRL_NO_GPU` / `FORGECTRL_NO_H264` /
`FORGECTRL_NO_HW_SKIP` strip them individually, each falling back to the
measured paths above.
`/cam/status` reports `encoder` and `buffers`. A CSI glitch frame can out-size
the coda driver's default JPEG capture buffer, so forgectrl requests 3 B/px and
drops error-flagged dequeues as single bad frames. **LightBurn consumes the
stream directly** while jogging from the same session; motion coexistence is
proven (`clamped 0`, max behind 4.5–7.2 ms of the 200 ms queue at 15 fps).

Run by hand: `/usr/bin/forgectrl &` after `/etc/init.d/forgectrl stop` (kill
before scp when redeploying — text-file-busy). It logs through syslog
(`/data/log/forgefirm/forgectrl/forgectrl.log`; a terminal, or `FFLOG_STDERR=1`,
echoes the lines).

**Wireless region.** `wifi_country` (System tab, full ISO 3166-1 alpha-2
dropdown, default 00 = world) is applied with `iw reg reload` + `iw reg set`
at daemon startup and on every change; the same pass pins `wlan0 power_save
off`. With the regulatory db loaded and no user hint, cfg80211 follows the AP's
802.11d country IE; a user-set region overrides it. The startup pass hints a
region only when one is set (hinting `00` into the default world domain makes
cfg80211 report the confusing `country 98` alias).

## Diagnostics (forgectrl-owned hardware tests)

The Diagnostics tab runs tools that **take the hardware over**: the runner
(`diag.c`, one slot) suspends the active controller through the supervisor
(launch is gated on cnc idle + no diagnostic), drives the loop directly through
sysfs, and resumes the controller on every exit path (completion, tool error,
operator abort via `POST /diag/abort`, safety ceiling). The cooling engine
suspends its own writes for the duration and publishes fire-blocked.
`/run/forgefirm-diag.active` marks the ownership, and forgectrl startup recovers
a stale marker. The laser is untouched throughout (latch stays locked). While a
diagnostic runs, settings POSTs 409, `/status` reports `diag:true`, and the
panel locks with a banner. Live progress streams through `GET /diag/status`.

Both cooling tools run at the *configured* duty/window/threshold, with
cut-profile chassis fans (the characterization condition); pump-off windows
hard-abort at 48 °C downstream:

- **flow-verify** (~3 min): one check with the pump on, one with it commanded
  off, judged against `cool_flow_rise`. PASS = the threshold separates the
  readings; margins under 1.5 °C add a run-calibration warning.
- **flow-calibrate** (~15–25 min): 3 trials per case, alternating, with settle
  gates between; reports both bands and recommends threshold = (flow max +
  no-flow min)/2 with an Apply button, or refuses when the gap is under 3 °C.

**Cooling tunables are conf-backed**: the nine `cool_*` keys (`flow_rise`,
`flow_heater_pct`, `flow_check_s`, `recheck_s`, `confirm_max_s`, `temp_max`,
`temp_resume`, `cooldown_s`, `cooldown_max_s`) live in `/data/forgefirm.conf`
(Machine tab, validated ranges), and the cooling engine re-reads them at **every
run start** (env `GFCOOL_*` > conf > compiled default; env stays the bench
override and wins for the process lifetime).

**Flow verification, as it runs:** a one-shot check at flood start (M8) heats
the loop at `cool_flow_heater_pct` for `cool_flow_check_s` and discriminates on
downstream temperature RISE, with periodic re-checks every `cool_recheck_s` —
a stopped pump is undetectable any other way. A check starts only once the
sensors agree and the downstream reading is stationary (split-half mean
difference, not peak-to-peak). An over-limit check is a **suspicion**, not a
fault: the next completed check decides it (over-limit again → FAULT, clean →
cleared, three cleared episodes in one job → aggregated warning), and a
suspicion that produces no verdict within `cool_confirm_max_s` escalates to
FAULT. Over-temp policy is the factory's: a CYCLE over `cool_temp_max` gets a
feed hold plus forced cooling airflow and auto-resumes under `cool_temp_resume`;
a JOG gets a jog-cancel.

## Logging

rsyslog is the system logger and the only log writer. forgectrl and the grblHAL
driver emit through the shared non-blocking `fflog` emitter (drops, never waits
— a stalled log daemon can never park a controller thread), gfcloud/gfhome
through `SysLogHandler`, the kernel through `imklog`; a controller's stray
stdout/stderr rides a per-controller `logger` relay under its own name. Tree:
`/data/log/forgefirm/{forgectrl,grblhal,gfcloud,gfhome,kernel,system}/`,
size-capped and rotated at boot and hourly (the `forgefirm-logging` recipe
renders the rsyslog rules from the settings at S19 via
`forgectrl --render-syslog`). Levels (`log_<logger>_disk` /
`_remote`) and the remote target (`syslog_server/port/proto`) are machine
settings **applied at reboot** — the panel's Logs tab shows configured vs.
effective and offers the reboot, plus a live viewer and a sanitized `tar.gz`
export for issue reports (`POST /logs/export`; `src/sanitize.c` replaces
serial, hostname, cloud credentials, panel token, SSID/PSK, IPs, MACs and
e-mails with stable placeholders). Design and contract: `SERVICES.md`
"Logging".

## Release acceptance (forgetest, port 8090)

The release acceptance tool — catalog, campaigns, domain fingerprints,
inheritance, the always-required core, invalidate-all, the release gate and the
coverage currency rule — is specified on the site (Developers, "Acceptance"); the tool lives in
`forgetest/` and ships only on the dev image (`/etc/init.d/forgetest`, HTTP
:8090). It is **bench-validated**: the full campaign on dev image
`20260824230512` (`c-20260824231028-b7ca`) satisfied 45 of 45 from nothing,
36 of them unattended with the bench actuator in the loop, in 27 minutes, and
the export reads "Release authorized: YES" for that image's manifest. That
authorizes a release; it is not one until `releases/v<version>/acceptance.json`
is committed.

- **Catalog: 46 tests** in `forgetest/forgetest/suite/`, every one a port of a
  proven bench drill or a bench-verified check: the always-required core
  (`image.health`, `kernel.latch-locked-idle`, `kernel.k1-k2`,
  `kernel.fire-line`), `forgectrl.*`, `logs.*`, `update.*`, `motion.*`
  (pacing, jog round-trip, liveness probe, cancel/abort, dead-man, the lid,
  interlock and button parity tests), `cooling.*` (flow verification, fans
  quiet after motion, a gate setting tripping and off by value, a fan under
  its floor), `camera.*`,
  `laser.*` (emission witness, arm-wait lid, disarm-in-hold, armed kill,
  pause/resume/lid-cancel, the rapids after an M5 shipping dark) and `cloud.*` (the service protocol answered by
  the emulator in this machine's identity, with only the app to drive; the
  mode round trip with the lid-open hunt and the web-service homing on it;
  one real print; and the job-behavior tests under the offline service:
  the cloud client driven from a local socket with a synthesized
  laser-free job, no account, no network, nothing on the bed). Tests that
  share a setup are merged; the `auto` tests stay separate for failure
  isolation. 28 are `auto`, 9 `operator`, 9 `live`; with the bench actuator up,
  eight of the operator tests run in the unattended queue.
- **The operator's part is asked for by name, not by popup**
  (the site, Developers, "Acceptance", "The operator's part"): a Ready prompt before a
  timed step, a standing notice the test takes down when the machine shows
  the action done (`ctx.act("lid", "open")` and its kin, the seam a bench
  actuator will plug into), and one confirm by eye left in the catalog (the
  emission witness's mark). The head accelerometer, the beam detector, the
  button LEDs, and a lid-lamp toggle between two snapshots replaced the
  other eyeball confirmations; `kernel.fire-line` and `camera.snapshot` are
  `auto`. With the bench actuator up the attended block is the ten tests
  that need a person (five laser live, five cloud): 12 minutes on dev image
  `20260824230512`. A test's implementation hash is its own function plus its
  module's shared code, so a fix inside one test re-requires that test
  alone.
- **Machine identity is content-defined.** Every component recipe contributes
  `forgefirm-manifest.bbclass` entries (the kernel and the module through
  `do_deploy`), `forgefirm-image-manifest.bbclass` assembles them plus the layer
  content hashes into `/etc/forgefirm-manifest.json` (also deployed beside the
  image as `*.forgefirm-manifest.json`), and `scripts/manifest-from-tree.py`
  computes the byte-identical thing on a workstation — the identity is
  content-defined, independent of the checkout's commit or dirty state.
  **Component pins live in `<recipe>-pin.inc`** (SRCREV + the PV that moves
  with it, nothing else) and
  are left out of the layer content hash, so a pin bump invalidates only the
  tests covering that component; a pin written into a recipe body counts as a
  platform change and invalidates everything.
- **Baseline rule:** every test and bench tool is bracketed by a baseline pass
  (`forgetest/baseline.py`), against a fresh-boot reference taken once per boot
  **after a power cycle** (a soft reboot leaves the lid lamp dark — the PIC
  lights it at power-on). Takeover runs capture the controller-owned kernel
  attributes on entry and write them back before forgectrl restarts, so a
  leftover `motor_lock` mask can never read as a wedged driver.
- **Coverage currency is enforced in CI** (`python3 -m forgetest.coverage
  --enforce` in `forgetest-ci.yml`, over the tree manifest): an uncovered
  manifest path fails the build, because it would let an inherited PASS survive
  a change that should have invalidated it.
- **Bench tab:** every board-runnable tool in `scripts/bench` is runnable from
  the page (scope tools, the flow characterization family, the escalation
  drill, the live drills, `resume_dark_lead.py`), with takeover tools bracketed
  by a forgectrl stop/start. `scripts/bench/gfbench.py` resolves `GF_HOST`
  (host mode, ssh) or the board itself (local mode). Not ported by nature: the
  two null-sink CI harnesses and the `.puls` decoder.
- Releases are signed only when `releases/v<version>/acceptance.json`
  authorizes the built rootfs (`scripts/release.sh`).

## Hardware facts bank (measured)

- **The bench actuator's wiring** (`fixture/README.md` for the box itself).
  Three 3.3 V optocoupler relay modules, high-level trigger, coils from the
  machine's 3.3 V (about 100 mA each), inputs from the ESP32-S3 DevKitC-1's
  GPIO 4 (lid), 5 (interlock), 6 (button), the button's enable jumper on
  GPIO 7 to GND. The lid contact (NC) goes in series with the lid-switch
  loop at J4.12/13; the button contact (NO) across the front button input
  at J5 (BTN and its 12 V); the interlock contact (NC) in the remote
  interlock loop at J8 (SAFETY.md; J6 is the speaker). The machine's 3.3 V
  rail carries the three coils with room to spare. The DevKit and the
  machine share a ground through the modules, so the DevKit is powered from
  a USB wall adapter. The interposer harness itself is bench-local and is
  not described in any repository.

- **The factory's envelope, decoded** (firmware 2.6.0-2228, the 23 captured
  headers, this board's own factory logs). The pulse header is the job's
  operating envelope and the factory refuses to cut without it: 29 tags are
  mandatory, 346 are header-legal, an unknown tag is logged and skipped. The
  service fills the fan duties, the coolant window, the per-sensor temperature
  ceilings, the lid IR thresholds, the accelerometer thresholds and an HV
  current cap per job; a cut job carries the real fan duties (air assist
  1023, exhaust 65535, intake 43278, equal to ForgeFIRM's run profile) and a
  hunt or motion file carries air assist 204 with the extraction fans off.
  Every tach window is zero in every capture except `AArx` 64500 on cuts, and
  the factory's intake and exhaust tach monitors treat zero as not configured,
  so a stalled extraction fan is caught there by the temperature it causes;
  when a fan alert does fire during a cut the factory pauses the print on the
  same transition as a user pause. Temperature runs two tiers there: a plain
  alert pauses, a `*_temp_critical` fails the machine; the units are per
  sensor (the coolant family is carried twice, raw counts with the NTC's hot
  end as "min", and millidegrees), and a stock machine's live coolant window
  is 10 to 30 C idle and 5 to 35 C warm-up and run, `CMrx` 33000 on a cut
  being exactly the shipped 33 C ceiling. The factory does not verify coolant
  flow: the calorimetric `CF` controller in its firmware is never armed and
  its heater is written only at phase changes. ForgeFIRM's answer, all of it
  landed and bench-proven in the catalog (`cooling.gate-off`,
  `cooling.fan-gate-trips`, `cooling.critical-tier`, the hunt leg of
  `cloud.mode-switch`) and in the CAMPAIGN-LOG drills: every gate a plain
  setting with an off end; a header value only ever tightening a local one;
  every fan held to a measured floor with a fault, not a pause, for the
  session; a coolant critical line above the ceiling's pause; the board
  temperatures watched per job; and the rest of the envelope declared, tag by
  tag, in `CLOUD.md` "The pulse header".
- **Board temperatures at idle** (room ~22 C, machine on for hours): the
  chassis LM75 reads **29.0 C**, `pic/pwr_temp` reads **589 raw** (the
  unverified guess `raw * 0.08715 - 21` would make that 30.3 C), the SoC die
  **42.8 C**. Ranged per job by the engine from here on. The supply stays a
  raw count by decision: its heatsink cannot be reached with a thermometer
  while the machine runs, so the conversion is not going to be verified on
  this bench, and a number nobody has checked is not published as degrees.
  The per-job range in raw counts is the record, and a ceiling, if one is
  ever wanted, is set in raw counts from it (`temp_calibrate.py supply-*`
  stays for a machine where the heatsink is reachable).
- **The SoC guards itself.** The i.MX6DL (rev 1.3) on-die monitor is
  `thermal_zone0` (`imx_thermal_zone`, the same node as `hwmon0`), governor
  `step_wise`, trips at **85 C passive** and **90 C critical** (the
  consumer-grade points the driver derives from the fuses: hot point 95,
  critical at hot minus 5, passive at hot minus 10). The passive trip is
  bound to `cpufreq-cpu0` (996 / 792 / 396 MHz OPPs; `performance` is the only
  governor built, so the core sits at 996 MHz until the trip lowers it) and
  both GPU cooling devices; the critical trip is the kernel's orderly
  poweroff. A throttle slows the engine, the camera and the protocol thread
  before the step stream (the ring is in hand). The factory board carries
  **no heatsink or fan on the SoC**, only the mounting holes for one, and
  needs none: under a full core for five minutes on top of the live camera
  stream, in a 30 C chassis, the bare die plateaus at **70.8 C**, 14 C under
  the passive trip, with the core at 996 MHz and no cooling device off
  state 0. The die-to-chassis delta at full load is about 41 C, so the
  passive trip is a hot-chassis case (above roughly 44 C), not a load case.
  The per-job SoC range and the throttle log line are the running record.
- **Fan speeds at the cut profile** (exhaust duty 65535, intake 43278, air
  assist 1023; sampled at 1 Hz over 120 s from idle, the exhaust duct's
  inline booster fan off): exhaust **11640 rpm** steady (spread 11444 to
  11947, 90 percent of steady in 5 s), intakes **4157 / 4158 rpm** (spread
  under 100, 7 s), air assist **11050 rpm** (spread 30, 1 s); at idle the
  exhaust and intakes read 0 / ~745 rpm and the air assist ~1900 rpm
  (idle duty 204). The purge-air fan is always on and reads **~625 counts**
  of `head/purge_air_current` (~1 when off). The airflow floors are 55
  percent of these (bands 50 to 60 percent); an inline booster fan changes
  the exhaust's back pressure and can move its reading by a few percent
  either way, well inside the margin.

- **DRV8825 stepper drivers wedge on 40 V rail glitches** (factory board; the
  TMC2130s belong to the upgraded OpenGlow board only). A glitch can leave the
  drivers unserviceable: SDMA playback and the position counters run normally
  while the motors produce nothing. The supply itself is fine — this is a
  driver failure mode, not a marginal rail. Their reset lines are strapped (no
  kernel pin), `cnc/faults` does not flag the state, and whether a given rail
  power-up wedges them is chance. Recovery: a longer true power-off (the
  forgectrl supervisor ladders 5/15/30 s) and, at worst, a full machine power
  cycle. Consequences: **counters, anchors and `H:1` are never proof of
  motion**; keep the rail up (every power-up is a wedge lottery), which is why
  the pulse-device broker exists and why there is no idle-rail-off policy.
- **Motion liveness = the head accelerometer** (`glowforge.dts` `head-accel`,
  i2c-3 @0x1e — resolve iio devices by bus path, never by index; lid = i2c-0
  @0x1e, board = i2c-3 @0x1d). Signatures on an identical commanded move: real
  motion **1800–2900 counts peak-to-peak** on X/Y (noise floor at 1 g ≈ 16384),
  a genuinely dead/wedged axis ≤ ~250, and the rail-on / current-step jolt up to
  ~700 — which is why the forgectrl probe gates controller start at
  **p2p ≥ 800** (`P2P_MOVING`), writes `cnc/motor_lock=0` for its own move (a
  leftover mask from any tool must not read as a wedge) and settles 300 ms
  after the run-current step before sampling. A masked axis reads 144–480.
  gfhome requires at least one accel-witnessed motion window before a quiet
  service counts as homed. Raw sysfs accel reads are slow (~150 ms each) —
  enough for a binary verdict over a multi-second window, not for waveforms.
- **Any probe/liveness move goes RIGHT (+X) first, then back**: a cable lives
  at the end of LEFT travel and must never be crushed.
- **Rail-contact signature** (from the retired accelerometer-homing spike,
  relevant to any future contact sensing; tools `accel_fast.py`,
  `bump_seek.py`): creep baseline ≈0.5–2 k counts, contact jumps to 29–42 k
  within ~4 ms (20–40×). But **slow approaches are near-silent** — belt
  compliance turns slow-speed skipping into sub-threshold grinding — so any
  contact-sensing scheme must strike fast. Direct I²C (unbind st-accel,
  CTRL1=0x6F = 800 Hz ODR) reads ~530 Hz from Python; st_accel sysfs one-shots
  are ~6 Hz and the kernel has no IIO triggers.
- **WL1805 Wi-Fi rides uSDHC1** (mmc0, 4-bit, SD-high-speed at 49.5 MHz,
  `no-1-8-v`; IRQ GPIO6_04, WLAN_EN GPIO5_26). Factory pad control, now ours
  too: CMD/DATA `0x17069`, CLK `0x10069` (SPEED_MED, DSE 48 Ω, fast slew, HYS;
  47 kΩ pull-up on CMD/DATA only). eMMC (uSDHC3) and the SD slot (uSDHC2) use
  `0x17059`/`0x10059` (80 Ω), SD2_DAT3 `0x13059`. An SDIO CRC error surfaces as
  `sdio write failed (-84)` and costs ~1 s of Wi-Fi (wlcore firmware recovery)
  — see "Wi-Fi SDIO CRC watch" under Next work.
- **SDMA pulse engine**: ring size = the `ring_mb` module parameter (default
  32 MiB, the factory ring size; power of two, must fit the 32 MiB
  `cnc-pulsebuf` no-map DT pool). Free = size − 32 KiB gap, so 33,521,664 bytes.
  Bench-verified on the 16 MiB ring the earlier images shipped, and the
  mechanism is size-independent: 20 MB streamed at 100 kHz through the wrapping
  ring, 0 ENOMEM, 0.4 ms max write latency, starve → `underrun` per protocol.
  The ring holds ~1 MiB per 100 s of 10 kHz stream, so ~56 min of a cloud
  print at a time; a longer job is fed live as it plays, and the grblHAL feed
  keeps only a few KB in flight. The 32 KiB gap is retained history: the
  writer stops that far short of the play head, so any fill leaves 3.2 s of
  played program (at the print tick) to back a pause into, which is what
  `cnc/max_backtrack` reports less the deceleration tail. The engine's `ipg`
  and `ahb` clocks are enabled only by a channel holder: imx-sdma leaves them
  off after probe, and glowforge.ko holds them itself through
  `sdma_get_channel()` in the SDMA API patch for as long as it is loaded;
  nothing else on this board holds an SDMA channel (ecspi2 runs PIO). With the
  block gated every channel-0 transfer completes at once and moves nothing:
  the ring reads back its bounce page, the probe cannot start and `cnc/free`
  exceeds the ring, which is why `image.health` asserts the clock enable
  count directly.
- **Reserved memory**: 511 MiB usable DRAM (`0x10000000`–`0x2fefffff`), of which
  96 MiB is reserved for DMA: the 32 MiB `cnc-pulsebuf` no-map pool (dynamically
  placed, `alignment = size`, so it lands at `0x2c000000`) plus 64 MiB of
  reusable CMA for camera/IPU/VPU buffers. no-map means the pulse pool is gone
  from the kernel's map whether a job uses it or not, which is what makes
  `dma_alloc_coherent()` deterministic for a late-probing out-of-tree module.
  The 1 MiB above the memory node (`0x2ff00000`, held back by the bootloader)
  is pstore/ramoops: 32 KiB dump records, a 256 KiB console record, 16-byte
  ECC, mounted at `/sys/fs/pstore` from fstab and staged by the log export.
  MemTotal ~464 MiB on the board-only kernel (`linux-fslc` 6.12, `SMP` off,
  `CONFIG_PREEMPT=y`, zImage 4.8 MB, 31 module packages, ROM SDMA scripts);
  measured idle use in GRBL mode with the daemon and
  controller up is ~100 MiB. The playback script is
  relocated to SDMA channel 26 at `<26 0xF00>` (halfword 7680) with a pre-run
  integrity guard; the probe lines to look for are `EPIT clock 66000000 Hz` and
  `SDMA channel 26 reserved for pulse playback (script at halfword 7680)`.
  Measured script ceiling **~165 kHz effective** (~6 µs/byte); position
  counters (`sdma_context`
  sc0/1/2 = X/Y/Z steps, sc3 = bytes) match grblHAL exactly. Underrun proof:
  100 kHz × 120 s under full load, 150 ms queue, 0.2 ms worst write latency,
  zero underruns. Real time: the kernel runs `CONFIG_PREEMPT=y` (the factory
  behavior; `imx_v6_v7_defconfig` alone gives `PREEMPT_VOLUNTARY`).
  PREEMPT_RT is not selectable on arm32 6.12 (no `ARCH_SUPPORTS_RT`) and is
  not needed: the ring drains at 1 byte per EPIT tick, at most 200 KB/s even at
  the 200 kHz ceiling, so the feeder's bounded queue depth of ~150 ms (a few
  KB in flight) rides out worst-case scheduling latency with orders of
  magnitude to spare. Bounded queue depth plus `SCHED_FIFO` for the feeder is
  the design; RT is worth revisiting only if the underrun bench ever
  contradicts this arithmetic.
- Byte layout and stream rules: see the UAPI.md feeder contract
  (authoritative).
- **Z**: bit 6 SET = lens UP = +Z (hardware-verified). Home = hall trigger at
  TOP; usable travel ≈ 30 half-steps ≈ 10.6 mm ≈ 0.417"; 0.3534 mm/half-step.
  Never blind-drive Z — hall-supervised only.
- **XY**: 0.15 mm per full step; DIR bit set = −X / +Y (Y1/Y2 complementary).
  **+Y physically moves the gantry toward the FRONT.** Home corner (convention,
  for the planned limit-switch homing) = back-left (X min, Y min), workspace
  all-positive from that corner.
- **Factory motion profile** (measured from captured factory pulse streams
  with `puls_profile.py`): accel ≈ 700 mm/s² X / 590 mm/s² Y on v2.6.0 firmware
  (2018 firmware used ≈1000); header HAxr=132/HAyr=112/HAar=133 ⇒ ≈5.3 mm/s²
  per HA unit. Travel moves peak 202 mm/s vector (≈ 8 in/s) at STfr=28160 Hz;
  prints and hunts run STfr=10000. Cut feed in the sample print: 145 mm/s. Z
  cadence ≈ 61–115 ms per half-step (≈ 5.7 mm/s max).
- **Factory analog config** (constant across all captured jobs, 2018→2026):
  PIC currents X 135 run / 33 hold, Y 22 run / 5 hold (axis DAC scales differ by
  design); x/y_decay=1; ×8 microstepping; run currents applied only while
  motion plays, hold otherwise.
- **Laser PWM**: 39.98 kHz register-verified (divider 13 × 127 counts), scope-
  confirmed at 25.0 µs period across the full duty range, clean at the low end
  (6.4 % measured vs 6.3 % commanded at PWMSAR=8).
- **Laser duty thresholds** (ladder on scrap at F300, constant power): the
  tube has two thresholds, far apart. The discharge **strikes between 2 % and
  3 %** duty — 2 % (PWMSAR 2) draws no measurable `hv_current` and leaves
  nothing at all, 3 % (PWMSAR 3) draws current — but it does **not lase
  usefully until 16 %** (PWMSAR 20), the lowest duty leaving a continuous
  mark. Between them (3–14 %) is a **dead band**: current flows and climbs,
  and each line shows only a spot at its start (the strike transient) with a
  dark line after it. So the usable analog range is ~16–100 %, and `$35`
  (`DEFAULT_SPINDLE_PWM_MIN_VALUE`) ships at **16** to hold every nonzero S
  above it. Raw `hv_current` counts are a presence/absence witness only: the
  per-rung means are non-monotonic at the top of the ladder and the signal
  has no characterized transfer function.
- **Factory power model** (three cloud cuts of one 1" square, same location,
  material and speed, only the UI power setting changed, pulse files captured
  from each): the **power byte is pinned at 127**
  in all three runs — three occurrences each, one as the cut begins and a
  refresh every ~27 000 ticks (~2.7 s). Analog duty is never a power control.
  **Dose is FIRE-bit density on a fixed 7-tick period** (700 µs at
  `STfr` = 10 000, ~1.43 kHz), the on-count dithered between adjacent integers
  to reach a fractional duty: Precision Power 1 = 1.371 of 7 (density 0.1953,
  runs of 1 and 2), PP 100 = 5.576 of 7 (0.7952, runs of 5 and 6), Full Power
  = 7 of 7 (0.9965, continuous). The period was exactly 7 in all 570 measured
  cycles of both dithered runs, and the mix of adjacent on-counts matches the
  fractional part exactly (PP 1 wants 1.371; 2-runs are 212 of 571 = 0.371).
  The three **headers are identical** — the power setting never reaches the
  machine, so the whole model is service-side. Motion is identical too: 5420
  steps, 101.62 mm, 10.81 s at 9.44 mm/s. **Density tracks velocity through
  corners**, by the same relative factor at every power setting (corner/cruise
  0.38, 0.38, 0.41), but only partly: fire ticks per step rise 3.89 → 7.00 as
  speed falls 9.44 → 1.22 mm/s, so dose per unit length rises ~1.8× at a
  corner instead of the ~7.7× it would rise with no compensation. On the UI
  scale, PP 1→100 is linear in density (~0.006 per unit, intercept ~0.189) and
  Full Power sits off that line, where PP ~134 would land.
- **Density dose limits** (measured on five ladders, `dladder`): under the
  FIRE-density model the interval between pulses at a level below the
  minimum is `min_ticks x tick / density` - **the base period cancels**,
  which is why periods 10, 20 and 40 gave identical results. The tube
  **strikes down to ~5 % density at a 2.26 ms interval** (`min_ticks` 3,
  106 us pulses) and **fails to strike at 4.51 ms** (`min_ticks` 6, 213 us):
  lengthening the pulse at fixed density lengthens the gap in proportion,
  and the gap is what kills re-striking. It **marks from ~10 %** at F300 on
  scrap. `min_ticks` 3 is essentially the factory's own structure - its
  6.5 % engrave jobs put 100 us pulses 1.54 ms apart, against 1.64 ms for
  `min_ticks` 3 at that density - and 6 is outside anything the factory
  does. Below ~5 % no pulse shape reaches the tube: the interval grows as
  1/density, so 1 % implies an 11 ms gap, five times what already failed.
  **The scale closes that gap instead:** `$35` = 10 maps S onto 9.4-100 %
  density, putting a commanded 1 % at 10.2 %, and a ladder weighted to the
  bottom (1, 2, 5, 10, 20, 40, 70, 100 % of S) then marked on **all eight
  rungs**, with eight current segments and means rising 136 -> 968. So a
  user's 1 % is a real, visible mark rather than silence.
- **Cooling operating point**: 40 % heater duty, 50 s window, flow-rise
  threshold 14.4 °C, re-checks every 150 s. Below ~40 % duty the stagnant loop
  sheds the heater's output by convection well enough to mimic flow (at 30 %,
  three of five dead-pump trials looked healthier than a working pump). Record
  at 40 %: 25/25 correct classifications, plus all three settle cases. Settled-
  loop noise is 0.52 °C peak-to-peak but only 0.11 °C split-half, which is why
  the stationarity gate uses split-half means. Coolant windows: run ceiling
  33 °C, resume 31 °C (factory job-header CMrx/…); the factory's low side
  (floors ≈1.0/4.0 °C, ~16 °C warm-up gate) is not implemented yet. The
  coolant thermistor conversion is the factory B-equation recovered from the
  v2.6.0 binary — derivation in `kernel-module-glowforge/UAPI.md`; the old
  UAPI "best guess" linear formula was 3–5 °C high and everything derived from
  it had to be re-derived. The flow check's bands hold from 19 to 27 C, the
  loop heater's ceiling in a 20 C room, with the margin widening warm; above
  that only a running tube warms the loop, and the check takes the tube's
  share off. With the pump on, a heater slug reaches the upstream sensor
  within seconds and inflates the instant reading by a degree; the warm-up
  release therefore judges a one-minute rolling minimum of that reading.
- **The four `pic/lid_ir_*` channels are first of all a photometer for the lid
  lamp.** Measured against `lid_led` (sysfs brightness, 0 to 1023): all four
  channels follow it as a straight line, 2 counts dark, 32 to 35 at 128, 54 to
  61 at 256, 96 to 105 at 512, 131 to 143 at 768 and 161 to 177 at 1023;
  channels 3 and 4 read about 7 percent above 1 and 2. Against that lamp-set level, a
  full-power cut raises them only +4 to +6 counts and a candle burning on the
  bed +3 to +6, with ±3 counts of ambient noise and ~+22 counts of day-to-day
  drift. forgectrl's camera engine drives `pic/lid_led` for every lid capture,
  and the resting level varies (131, 8 after a reboot, cloud mode sets its own).
  The armed fire-watch thresholds sit above the fully lit lamp (alert 275
  against a 177 ceiling plus drift), so no lamp change can trip them; each
  job still logs baseline and peaks.
- **Emission and HV witnesses**: `cnc/laser_on_sampled` goes to its full 255
  count on a commanded fire window and returns to 0 at Idle — the reliable
  witness. `pic/hv_current` tracks the cut (0 idle → hundreds/1023 raw while
  firing) and is the only live HV telemetry on this PSU (`hv_voltage` is
  grounded). `cnc/laser_pgood_sampled` stays 0 through real cutting: not usable
  here.
- **Switches**: truthy = closed/OK for lid/doors/button. **SW_INTERLOCK is
  INVERTED**: the remote interlock (the regulatory 2-pin lockout connector)
  reads ACTIVE only when the loop is OPEN. Basic/Plus — including the bench
  machine — ship the connector factory-jumpered, so the bit reads 0 =
  satisfied; Pro brings it out for an external lockout chain. It must NOT gate
  motion (the beam is hardware-gated), but ForgeFIRM's kernel module does drive
  INTERLOCK_RESET high whenever the loop reads open, so the CD4043B latch
  blocks the LASER_ON gate in hardware until the loop is closed again
  (bench-verified: loop pulled → `interlock_latch`=1, `interlock_circuit` b4
  set, all within one 50 ms sample; reinserted → all clear).
- **`hv_enable` (EV_SW bit 4, GPIO4_06) is the readback of the safety chain's
  HV_ENABLE output** through the U24 inverter — not an input. Active for the
  whole duration of any run, inactive at idle, and it drops 454 ± 3 ms after
  the last charge-pump pulse (one-shot t_w measured pulse-to-drop with
  `scripts/bench/cp_watchdog_timing.py`: 451.8 / 455.6 ms; feed period
  199.98 ms; matching the measured R·C ≈ 500 kΩ × ≈900 nF). It gates nothing —
  it is telemetry (`/status` `switches.hv_enable`, panel "HV enable"), read
  alongside `cnc/charge_pump_alive` (`interlock_circuit` b5). **Across a pause
  and a resume** (measured at the pads with `scripts/bench/resume_dark_lead.py`,
  ~2 kHz through /dev/mem): a pause stops motion 317 ms after the command and
  HV_ENABLE drops with the watchdog 550 ms after it, so a pause shorter than
  about half a second never drops HV at all; on the resume HV_ENABLE and the
  watchdog are back within ~3 ms while motion only restarts at ~219 ms — the
  chain re-arms ~216 ms **before** the first step, so a resumed cut loses
  nothing and no dark dwell is warranted. Naming note: the factory design
  labels this net **E-STOP**; entries in `CAMPAIGN-LOG.md` written before the
  2026-08-15 rename call it `estop`/`SW_ESTOP` with the pre-rename polarity
  (the DTS then declared the pin active-high, so the bit read HIGH at idle and
  LOW through a run — the same physical behavior, inverted). The DTS now
  declares it active-low, and the former `estop_halts_motion` /
  `MOTION.ESTOP_HALTS_MOTION` opt-in is gone: a real e-stop belongs in the
  lid-switch chain (`docs/SAFETY.md`). Doors/door1/door2 stay stable during
  motion.
- **Factory job behavior on the lid and the button, measured on 2.6.0-2228**
  (bench session 2026-08-16; this is what ForgeFIRM's parity policy
  reproduces). Lid open mid-print: `cnc/stop` 5–6 ms after the edge, decel to
  idle in 86–91 ms, the return-home park starting ~300–340 ms after the edge and
  running to completion **with the lid still open**, the job reported
  `:cancelled`. A cancel from the app takes the same path. The button pauses a
  print — controlled stop, then a 2000-tick laser-off backtrack — and resumes it
  with a 1950-tick laser-off lead; the button **flashes white while paused**. A
  lid open while paused cancels the job and parks from where it stands. The lens
  hunt is not lid-gated.
- **The hardware button latch is what makes the armed window honest.** A lid
  open SETs it (set-dominant), and it stays SET until the lid is closed, the SoC
  lock is released **and the button is pressed** (`docs/SAFETY.md`). So a policy
  that cancels the job on a lid open and re-arms only through a fresh button
  press keeps software and hardware in agreement by construction; one that
  resumes a job after a lid open leaves the beam blocked in hardware while
  software believes it is armed.
- **`interlock_circuit` bitmask**: b0 = SoC-side LASER_ON monitor, active LOW
  (1 = not lasing); b1 = FIRE, active high; b2 = button latch; b3 = latch,
  1 = locked; b4 = interlock latch reset; b5 = charge-pump watchdog readback.
  b0/b1/b3 were pinned by scope experiment, b2/b4 come from the factory decode.
  `cnc/laser_latch` is write-only, so lock state is read from b3.
- **Machine identity from OCOTP nvmem**: HW_OCOTP_MAC0 is the serial,
  base-23-encoded to the factory hostname (`BCDFGHJKMQRTVWXY2346789`, XXX-YYY)
  — fuse-verified against the factory label, and the C implementation matches
  gfhardware `id.py` over 200 k random serials. The bench machine's actual
  values are deliberately not recorded here: this is a public document and a
  fuse identity cannot be rotated.

### eMMC boot & recovery architecture

- eMMC (`mmcblk2`): 3.6 GiB user area + two 16 MiB hardware boot partitions
  (`mmcblk2boot0/1`). Factory user-area MBR (per the factory `.fw` manifest):
  p1/p2 = 200 MiB rootfs A/B at blocks 8192/417792, p3 = `/data` from block
  827392 to end of disk. (The bench board ran the legacy ForgeFIRM layout —
  p3 shrunk plus a p4 — until `slotmigrate` reclaimed it to the byte-exact
  factory geometry.)
- **U-Boot lives in boot0** at 1 KiB (IMX IVT header), not in the user area.
  Any boot0 rewrite below 0xC0000 risks the bootloader.
- **Saved env**: user area 0x80000 with a redundant copy at 0x82000 (what
  `ffboot`/`fw_setenv` target; boot0's own 0x80000 region is zeros). Slot
  selection = `mmcdev`/`mmchwpart`/`mmcpart`/`mmcroot`. Gap: `ffboot` sets
  three of the four but never `mmchwpart` — it relies on the saved 0.
- **Default (compiled-in) env boots recovery**: `mmcdev=1 mmchwpart=1
  boot_recovery=yes` — a blank or corrupt env lands in recovery mode, not a
  brick. `bootcmd`: select mmc dev+hwpart → load and import `/boot/uEnv.txt`
  from the selected partition → if `boot_recovery=yes`, boot kernel+DTB from
  raw boot0 sectors, else load `/boot/zImage` from the slot's rootfs. U-Boot
  polls the button at power-on for a recovery request.
- **boot0 map**: MBR / U-Boot @1 KiB / zeros @0x80000 / recovery DTB @0xC0000
  (`fdt_dev_addr=0x600`, 64 KiB slot) / recovery zImage @0x100000
  (`image_dev_addr=0x800`, 5 MiB slot, kernel 3.14.28) / recovery squashfs =
  `boot0p1` @6 MiB (10 MiB slot). **boot1 map**: MBR / squashfs @1 KiB =
  `boot1p1`, mounted as the recovery `/usr` (python runtime) by
  `init.d/recovery-usr`.
- **Recovery userspace** = the factory setup webapp (bottle): WiFi setup/AP,
  log export, `/version`, and `.fw` upload (→ tmpfs → `glowforge-updater -f` →
  fwup signature check → writes slot A → flips env). It is never updated in the
  field, so every machine still runs its as-manufactured recovery.
- **Factory `.fw` format** = signed fwup 0.14.2 archive (ZIP: `meta.conf` +
  `meta.conf.ed25519` + payloads). Tasks: `complete` (MBR, U-Boot to user area,
  zero both env copies, rootfs → slot A, zero p2/p3 heads) and
  `upgrade.a`/`upgrade.b` (raw-write `rootfs.ext4` into a slot). Factory
  updater flow: authenticated `GET <server>/update/current` →
  `{version, download_url}` → resumable download to `/data/glowforge.fw` →
  verify against `/glowforge/pubkeys` → apply to the INACTIVE slot →
  `fw_setenv mmcpart mmcroot` → reboot. Factory `rootfs.ext4` is 65 MiB; the
  ForgeFIRM release rootfs uses about 89 MiB, so it fits a 200 MiB slot with
  headroom.
- **Facts about the factory 2024 firmware** (learned during the slot install):
  no `/factory/imgN` mounts, the generic `fw_env.config` points at the WRONG
  device (use the per-device `fw_env_mmcblk2.config` — ffboot's selection
  logic), no SSH (serial console only), and the factory kernel cannot see the
  SD card (`ffboot -s` needs `-f` from factory). Factory `/etc/version` is a
  numeric datetime stamp, so newest-slot selection is integer comparison.
- **Platform quirk**: busybox `mount`'s auto-type iteration against an
  already-mounted ext4 device prints a kernel "`Can't open blockdev`" for each
  foreign-type (ext3/ext2) exclusive claim before the ext4 attempt joins the
  existing superblock. Cosmetic only; ffboot and the installer reuse existing
  mountpoints from `/proc/mounts` and mount fresh targets with explicit
  `-t ext4`.

## Next work

Open items only. Anything closed is in `CAMPAIGN-LOG.md`.

1. **Limit-switch homing.** The planned second homing method (`$22` stays 0
   until it lands).
2. **Cameras.** **First light on an 8 MP (OV8856) machine**: the
   whole path is written but nothing has run on one, and only that hardware can
   answer whether the 2-lane RAW8 full-resolution mode locks the D-PHY at
   720 Mbps/lane and what exposure/gain the sensor wants; the details, the
   reachable-mode reasoning and the factory fallback configuration are in
   the headers of kernel patches 0011-0013 (`meta-glowforge-bsp`,
   `recipes-kernel/linux/`).
3. **Shared machine services — remaining polish.** None of it blocking:
   - **Diagnostics as engine modes.** The flow tools still drive the thermal
     hardware themselves while the engine suspends its writes; the check
     parameters are already shared (`cool.h`), so what remains is folding the
     tools into the engine and retiring the suspend/resume dance.
   - **Busy-state arbitration under one lock.** The idle/busy gates (`POST
     /settings`, `/mode`, diagnostics start, upload/apply) each cross-check
     `machine_is_idle()` and `update_job_running()` at their own call sites.
     They fail closed and are drilled, but a single arbiter would close the
     remaining request-interleaving windows by construction.
   - **HTTP surface caps.** An explicit `MHD_OPTION_CONNECTION_LIMIT` plus a
     per-IP cap is the right hardening (a 500-connection flood plateaued at 379
     fds under the raised 4096 `RLIMIT_NOFILE`, no crash), and the camera
     `ensure_engine` `popen()`s should move out of the HTTP callback so a slow
     media-ctl cannot stall the request thread. Changing the MHD start flags
     touches the streaming model, so this wants a bench slot of its own.
4. **Physical-evidence negatives still open.** A present head answering I²C
   badly (the K-11 runtime case) and a failed head capture leaving the measure
   laser off — both need the head connected and a fault injected. Opportunistic:
   `STATE_FAULT` recovery via `enable` the next time a DRV8825 fault line
   actually trips.
5. **Debug-kernel checks.** Module load/unload under `CONFIG_DEBUG_MUTEXES`
    and a forced `-EPROBE_DEFER` unwind still need a debug kernel build. Both
    drills cycle what the rail policy avoids: a module unload powers the 40 V
    rail off (a stepper driver can come out of the power-up unserviceable),
    and a forced defer needs the 40 V regulator or the SDMA device unbound
    under the module's probe. This is a bench slot with the rail-cycle gamble
    accepted, not a quick check.
6. **Wi-Fi SDIO CRC watch.** The uSDHC pads now carry the factory-exact values
    and ship in every image. Watch `dmesg | grep -c "sdio .* failed"` across
    sessions (baseline: 1 event in 49 min of uptime). Effect if one lands
    mid-job: a 1–2 s sender stall — a cut-quality nuisance, never a safety
    matter. Only if it still recurs, cap the bus with
    `max-frequency = <25000000>` on `&usdhc1` (halves Wi-Fi throughput — last
    resort; the factory ran 50 MHz on these pads).
7. **Release acceptance follow-through.** The campaign is the release gate
    and runs as designed: dev image `20260824230512`, 45 of 45 from nothing,
    36 of them unattended with the bench actuator in the loop, release
    authorized (the export is on the board at `/data/forgetest/export/`).
    What is left is small. The ported bench tools are registered and
    unit-tested but not yet driven from the page. Two catalog gaps from the
    tool's own plan, `cooling.confirm-escalate` and
    `cooling.fire-gate-blocks-arm`, are not ported (both need the pump
    switched by hand mid-run, so they are bench-tab material first). From
    the coverage maps: splitting gfutilities' `websocket.py`
    into transport and transfer helpers would take websocket-transport
    changes off the offline tests (a gfutilities refactor, not a map).
    Tools that genuinely need a second host (LAN flood, remote auth probes)
    stay host-side by design, and the registry marks them so. The deferred
    emulator homing-image smoke is tool work here too, now that the
    emulator can be pointed at live snapshots. The first
    release is item 8.
8. **Publish.** The first release: `releases/v<version>/acceptance.json`
    from the authorized export, `scripts/release.sh`, the kas flip and the
    first GitHub release, per the site (Developers, "Release flow"), once
    ready to publish. Repoint the core submodule to
    upstream if the `step_us_min` sizing fix merges.
9. **Update system Phase 5 — recovery refresh.** The remaining phase of
    `docs/UPDATE-SYSTEM.md` (a refreshed recovery image in boot0); Phases 0–4
    are done.
10. **Head-IRQ source validation — beam-emission hypothesis (exploratory, not
    gating).** The EV_SW `head` bit (GPIO3_22, factory pad HEAD_IRQ) is the head
    MCU's attention line — idle LOW with a healthy head, pulsing on head reboot,
    floating to the SoC pull-up with no head — so the raw level is not a
    presence signal (presence = the head answering at I²C 0x47). The factory app
    answers the IRQ by reading the head's flag register (reg 0x05: b0
    hall_sensor, b1 accel_irq, b2 beam_detect_digital), so there are exactly
    three candidate sources; the working hypothesis is the head's IR
    beam-emission detector (digital flag + analog level reg 0x16, both already
    head sysfs attrs; the tunable detection model at regs 0x22–0x2a is not
    exposed). Whether the factory actually uses beam detect is unknown — the
    v2.6.0 app carries a complete but config-gated subsystem — and detection at
    low fire energies is unverified. Cheap opportunistic check during live fire:
    log EV_SW head-bit edges plus `head/beam_detect_digital|_analog` while
    firing.

11. **Gapless pause and resume in GRBL mode (planned).** A pause leaves a mark
    in the cut. With laser mode on, the core stops the beam at the start of the
    hold (`disable_laser_during_hold`, on by default), so the head travels the
    whole deceleration dark, and the resume re-accelerates from a standstill at
    the point the decel ended — an unburned length, then a restart that dwells
    through the accel. At constant power (`M3`) that restart is a deeper spot
    you can see; `M4` scales power with velocity and mostly hides it, but
    neither closes the gap. GRBL mode should pause and resume with no
    discontinuity in the cut, the way the factory does.

    Cloud mode already does, on the kernel's waypoint resume: controlled stop,
    laser-off backtrack (`cloud_pause_backtrack_ticks` 2000), then a laser-off
    lead back up to speed on the next press (`cloud_resume_lead_ticks` 1950),
    so the beam returns only once the head is retracing ground it already cut
    and is back at feed. The kernel offers that mechanism to a live feed as
    well: what bounds a backward run is the ring's retained history, not how
    the ring was filled, and the 32 KiB the writer must leave clear is 3.2 s of
    history at the print tick (`cnc/max_backtrack`, `UAPI.md`). What is not
    settled is the bookkeeping above it: a backward run moves the head and the
    kernel's counters while grblHAL's planner still holds a partly executed
    block, so borrowing the mechanism means reconciling the two, and a GRBL
    cut runs a much shorter queue than a cloud print does.

    So the equivalent likely belongs above the ring, where grblHAL still holds
    what the kernel does not: the planned path. Shape to evaluate: capture the
    point where the beam went off at the hold; on the resume plan a laser-off
    retrace back along the path and a laser-off accelerate-in, and unmask FIRE
    only once the head is at feed and has passed the captured point. Open: how
    far back is enough (2000/1950 ticks is a reference, not a transferable
    number — the tick rates differ), whether the retrace can reuse planner
    blocks or needs a synthesized one, what a hold inside an arc or a raster
    line does to it, and how it composes with the armed window's disarm grace
    across a long hold.

12. **Head crash and rail-contact detector (planned).** The head
    accelerometer is the motion-liveness probe and nothing more; the
    factory runs two tiers off the same sensor (a per-axis alert that
    pauses, a per-axis abort), and its thresholds arrive in every pulse
    header in a unit and behind a filter that are not known. A detector
    here is bench-measured from scratch, not adopted from the header: the
    rail-contact signature in the facts bank (a 20 to 40 times jump within
    4 ms on a fast strike, near-silent on a slow one) is the starting
    point, and the header values are only a cross-check once the units
    are established. A pause on contact, on the factory's shape, would be
    the first use.

13. **A sender change while a job runs: discussion.** Today a sender that
    disconnects mid-job leaves the motion running to the end of what the
    controller holds, with the window closed and fire suppressed (the
    consent belonged to the displaced session), so the job finishes dark
    and the material is left with an unfinished cut. This is the stock
    Grbl and grblHAL expectation for the motion: the controller has no
    notion of sender presence, executes what its planner and RX ring hold,
    and then waits; the core's stream code (`stream.c`,
    `stream_disconnect`) only switches streams, with no hold and no
    alarm, and senders treat a lost connection as a failed job (LightBurn
    stops its own side and resumes nothing). ForgeFIRM adds only the
    disarm on top. The open question is whether the disarm should also
    feed-hold the job, so a reconnecting sender can press and resume where
    the cut stopped instead of finding the head at the end of a dark pass:
    a hold parks the head over hot material with the assist air on the run
    profile, and the grace then closes the window in Hold as it does today;
    running on leaves a clean stop position but wastes the piece. Decide
    with the gapless pause and resume item (11), which owns the resume
    mechanics.
14. **The flow check while the tube is lit.** The arm-time heater check
    starts at the session open, so with a prompt press the tube is lit
    for most of its window, and a lit CW window adds about 1.5 C to the
    rise (0.5 C at 45 % density) against a 1.6 C margin; on top of that the
    engine takes its baseline from one sample while the coolant ADC
    carries a common-mode offset of about 1 C that steps in when the
    airflow goes to the run profile, steps out when it returns to idle,
    and toggles between two levels in between. Together they put an
    ordinary job's check within a few tenths of the limit. The engine now
    reads means and takes the tube's share off (`cool_laser_heat_cw`,
    `cool_laser_heat_density`), and `cooling.flow-under-load` is the
    catalog's case. Owed: a re-measure of the two coefficients once a
    second machine is on the bench (one tube, one supply so far); and if a
    lit check still trips, the void-on-emission design with the tube as
    its own flow tracer.
    The offset's source is the air-assist fan's return current on a ground
    path the thermistor reference shares (about 1.2 C at the run duty,
    proportional to the fan's current, both sensors alike; not crosstalk
    on the sensor cable and not HV). The check cancels it now that its
    baseline is taken under the run profile, but the over-temperature
    gates read the coolant about 1.2 C cooler than it is while the air
    assist runs unless `cool_aa_offset_counts` carries the machine's value
    (the `aa-offset-calibrate` diagnostic measures it, the panel's Apply
    writes it; zero is the factory's uncorrected reading; the bench
    machine carries 16). Owed: a second machine's value when one is on
    the bench; and the mid-run
    toggling between two levels (0.6 to 1.1 C, both sensors together),
    which comes only with the tube lit: not with the fans alone, not under
    motion, not in an armed dark window. The HV supply's input current on
    a return the thermistor reference shares, or its switching, is what
    remains; a scope on the two sensor lines during a cut is the next
    instrument. It sits inside the ceiling's 2 C hysteresis and the flow
    check reads means, so it is a measurement item, not a gate item.
15. **Laser power-good: what the line means.** `cnc/laser_pgood` and its
    sampled count are defined in the UAPI (active low, one sample every
    ~3.9 ms), the facts bank records that the sampled count reads 0 through
    real cutting, and the cooling engine warns
    `laser power-good degraded during the armed window` whenever fewer
    than half the samples read low, so the warning fires at every session
    open and carries no information. Nobody knows what the line reports
    on this PSU: whether it is the supply's own power-good, an HV-present
    flag, a polarity we have inverted, or unconnected. Owed: the line on a
    scope against `hv_current` through an armed cut, its meaning written
    into the facts bank and the UAPI, and then either a warning that means
    something or no warning.
16. **Initial commissioning: measure and set the machine's own numbers
    methodically.** Every tunable that was measured on the bench machine
    and shipped as a default varies from machine to machine: the flow
    check's bands and `cool_flow_rise`, the tube's heat coefficients
    (`cool_laser_heat_cw`, `cool_laser_heat_density`), the air-assist
    ground offset on the coolant readings, the laser's striking and lasing
    thresholds and the duty floor, the fan floors, the thermistor curve
    itself. Owed: one commissioning procedure, run once on a new machine
    from the panel or the bench page, that measures each of these in
    order with the tube dark wherever it can be, fires only where it
    must, and writes the results as that machine's settings with a
    record; and a reading of what the cloud sets for the same machine,
    taken from cloud cuts (the pulse header carries the factory's
    per-machine values), so the commissioning can start from the
    factory's own numbers where they exist and note where they differ
    from the measured ones. The dose-curve recorder (the panel's one-press
    ladder, fit and apply) is the first piece of this tool family and the
    template for the rest. Next piece, from the corner work: a
    **side-by-side chooser** - the tool cuts the same corner-heavy pattern
    at several settings of a knob (the corner rolloff first: a row of
    passes at, say, 1.0 / 1.25 / 1.5 / 1.75 / 2.0), labels them, and the
    operator picks the best by eye; Apply writes the winner. The rolloff
    is the proof case (this bench settled at 1.5 and may go lower, so the
    shipped default of 2 is a starting point, not a truth), and the same
    shape fits any by-eye tunable the commissioning flow meets.

**Deliberately not gated:** an armed GRBL job after an underrun cuts at the
stale origin unless homing is required (GRBL mode permits unhomed cutting; the
underrun itself alarms and unlinks the anchor). Not in the acceptance catalog
by design, for the same reason. From the pulse-header envelope, each by
decision and each declared in the cloud client so every job's log counts it
as decided rather than missed: the warm-up fan profile (the run profile
covers the warm-up hold), the supply temperature window (the service sends
the whole ADC range and the factory binds it to nothing; the supply is
watched per job instead), the head, lid, interconnect and fused temperature
ceilings (no sensor at those locations; the chassis is watched per job), the
head accelerometer thresholds (item 12), the lid IR thresholds (the fire
watch runs on local knobs; the header values stay ignored), the
HV current caps (the sampled emission witness covers the idle case, and HV
current is ranged per job), the thermal report upload conditions and the
pump flag. Beam detect stays with item 10.
