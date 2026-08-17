# ForgeFIRM bring-up status & cold-start runbook

Last updated: **2026-08-17**.

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
| `docs/ACCEPTANCE.md` | the release acceptance contract |
| `docs/VIDEO.md` | the cameras as users meet them: endpoints, delivered geometry, and what the sensors can do that ForgeFIRM does not send |
| `docs/LIGHTBURN.md`, `docs/UPDATE-SYSTEM.md`, `INSTALL.md`, `BUILD.md`, `kas/README.md` | sender setup, A/B update system, install, build |
| `python3-gfhardware/forgefirm-app/docs/CLOUD.md` | cloud mode, including its own open items |

## Where the project stands

**The machine works, in both controller modes, and the whole stack is
hardware-validated.**

- **Platform bring-up: complete and hardware-verified.** SDMA + EPIT pulse
  playback out of a 16 MiB reserved pool, live-fed during a run; laser PWM at
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
  a 35-test catalog, domain-scoped inheritance, an always-required safety core,
  and a release gate that reads the exported artifact. The last full campaign
  reached 26 of 26 on the then-current catalog; **no release is cut yet.**

Current bench state: dev image `20260817124714`, the board resting on the SD
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
  `forgefirm` + `meta-openglow` sibling checkout (`BUILD.md`); the ForgeFIRM
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

**Emission evidence.** `cnc/laser_on_sampled` (surfaced as `/status`
`laser.emission_samples`) is the reliable live-emission witness; emission
sensed with no armed window relocks the latch and stops motion. `pic/hv_current`
is the only live HV telemetry on this PSU. `cnc/laser_pgood_sampled` is **not**
a usable witness here — it reads 0 through real cutting.

## Lid, interlock and button policy

Both controller modes react the way the factory daemon does (decoded from a
factory 2.6.0-2228 session; log archived under
`_RESOURCES/factory-session-20260816/`, measured numbers in the facts bank).

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
  `cloud_resume_lead_ticks` 1950); GRBL mode uses feed hold / cycle start — the
  kernel refuses a backtrack on a live-streamed ring, so a resumed GRBL cut
  picks up where the deceleration ended. A pause is not a cancel: the latch
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
v2.6.0 sequence, per `_RESOURCES/emulator.log`, is settings → hunt → lid_image
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
coverage currency rule — is specified in `docs/ACCEPTANCE.md`; the tool lives in
`forgetest/` and ships only on the dev image (`/etc/init.d/forgetest`, HTTP
:8090). It is **bench-validated**: a full catalog run reached 26 of 26 on the
then-current catalog, and `scripts/acceptance-gate.py` authorized that image's
own manifest from the export. That was an exercise of the release mechanism,
not a release.

- **Catalog: 35 tests** in `forgetest/forgetest/suite/`, every one a port of a
  proven bench drill or a bench-verified check — the always-required core
  (`image.health`, `kernel.latch-locked-idle`, `kernel.k1-k2`,
  `kernel.fire-line`), `forgectrl.*`, `logs.*`, `update.*`, `motion.*`
  (pacing, jog round-trip, liveness probe, cancel/abort, dead-man, the lid,
  interlock and button parity tests), `cooling.*`, `camera.snapshot`,
  `laser.*` (emission witness, arm-wait lid, disarm-in-hold, armed kill,
  pause/resume/lid-cancel) and `cloud.*`. Tests that share a setup are merged;
  the `auto` tests stay separate for failure isolation.
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
  16 MiB; power of two, must fit the 16 MiB `cnc-pulsebuf` no-map DT pool).
  Free = size − 32 KiB gap. Bench-verified at 16 MiB: 20 MB streamed at 100 kHz
  through the wrapping ring, 0 ENOMEM, 0.4 ms max write latency, starve →
  `underrun` per protocol. The ring caps legacy cloud-mode job length
  (whole-file preload: ~1 MiB per 100 s of 10 kHz stream, so ~28 min); the
  grblHAL live feed keeps only a few KB in flight. The playback script is
  relocated to SDMA channel 26 at `<26 0xF00>` (halfword 7680) with a pre-run
  integrity guard; the probe lines to look for are `EPIT clock 66000000 Hz` and
  `SDMA channel 26 reserved for pulse playback (script at halfword 7680)`.
  Measured script ceiling **~165 kHz effective** (~6 µs/byte); position
  counters (`sdma_context`
  sc0/1/2 = X/Y/Z steps, sc3 = bytes) match grblHAL exactly. Underrun proof:
  100 kHz × 120 s under full load, 150 ms queue, 0.2 ms worst write latency,
  zero underruns.
- Byte layout and stream rules: see the UAPI.md feeder contract
  (authoritative).
- **Z**: bit 6 SET = lens UP = +Z (hardware-verified). Home = hall trigger at
  TOP; usable travel ≈ 30 half-steps ≈ 10.6 mm ≈ 0.417"; 0.3534 mm/half-step.
  Never blind-drive Z — hall-supervised only.
- **XY**: 0.15 mm per full step; DIR bit set = −X / +Y (Y1/Y2 complementary).
  **+Y physically moves the gantry toward the FRONT.** Home corner (convention,
  for the planned limit-switch homing) = back-left (X min, Y min), workspace
  all-positive from that corner.
- **Factory motion profile** (measured from `_RESOURCES` pulse streams with
  `puls_profile.py`): accel ≈ 700 mm/s² X / 590 mm/s² Y on v2.6.0 firmware
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
  it had to be re-derived.
- **The four `pic/lid_ir_*` channels are first of all a photometer for the lid
  lamp.** Measured against `lid_led`: 0 → `2 2 1 2`, 8 → `2 2 3 2`, 131 →
  `54 55 61 62`, 255 → `172 171 190 188`. Against that lamp-set level, a
  full-power cut raises them only +4 to +6 counts and a candle burning on the
  bed +3 to +6, with ±3 counts of ambient noise and ~+22 counts of day-to-day
  drift. forgectrl's camera engine drives `pic/lid_led` for every lid capture,
  and the resting level varies (131, 8 after a reboot, cloud mode sets its own),
  so a fixed-count gate fires a phantom FIRE stop on any lamp change.
  `cool_fire_ir_delta` therefore ships **0 = watch-only**; each job still logs
  baseline and peaks.
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
  (bench session 2026-08-16, log archived at
  `_RESOURCES/factory-session-20260816/`; this is what ForgeFIRM's parity policy
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
  ForgeFIRM rootfs is ~141 MB used, so it fits a 200 MiB slot with headroom.
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

1. **Laser commissioning leftovers.** Verify the hardware button latch persists
   across kernel-run gaps mid-job (if OK_2_FIRE drops between motion bursts, the
   fix is a stream keepalive across armed gaps); characterize warm-baseline
   flow-check behavior under real laser heating (all flow characterization used
   19–23 °C baselines; physics argues the dependence is weak — ΔT = P/(ṁ·c)
   carries no absolute-temperature term — but that is reasoning, not
   measurement).
2. **Low-temperature gates and warm-up (planned).** Two keys in the Cooling
   card: `cool_temp_min` (hard floor, default ~5 °C, a fire gate) and
   `cool_temp_start` (warm-up gate, default ~16 °C) — a job starting below the
   gate holds in a factory-style warm-up phase with the loop heater on and
   releases above it; below the floor nothing fires. Rationale: cold-tube
   thermal shock, condensation when the TEC pulls below the dew point, frozen
   coolant. Sequencing: warm-up first, flow check after. Measured physics on
   this bench: 50 % duty warms the bulk ~0.5–0.8 °C/min and plateaus ~8–9 °C
   above ambient — the same unaided limit the factory has.
3. **TEC handling (planned).** `thermal/tec_on` is a bare on/off output with no
   readback, so presence cannot be detected: it becomes a `tec_present` user
   setting (Machine tab, default off; ForgeFIRM never drives `tec_on` unless
   set), which also covers retrofits. Operation when present: simple hysteresis
   while a job runs — TEC on above `cool_tec_on_c`, off below `cool_tec_off_c`,
   defaults from the factory setpoints (CMet/CMdt 18134/18364 mdeg — the same
   WTub/WTvb raw-754/751 pair that proved the thermistor curve), off at idle —
   with `cool_temp_min` as the chill floor, so the TEC can never drive the loop
   toward condensation or freeze territory. Whether a given unit has a TEC at
   all is a spec-level claim (Glowforge ships it on the Pro; Basic/Plus use the
   same passive closed-loop cooling), not teardown-verified per unit — another
   reason it is a setting.
4. **Fire watch (lid IR) redesign.** The gate stays disabled
   (`cool_fire_ir_delta = 0`) until it is lamp-aware: the engine must own or
   observe the lamp level (suspend the watch and re-baseline for a few ticks
   after any `lid_led` change) and the threshold must be relative to the
   lamp-set level, not a fixed count. Even then the signal is weak — a candle
   reads like a cut — so the head camera or a real flame sensor is the honest
   path to fire detection that means something.
5. **Limit-switch homing.** The planned second homing method (`$22` stays 0
   until it lands); printable brackets are in `3d-models/`. Also: calibrate
   `gfcloud_home_x/y` against a jog to a known reference if the factory corner
   offset matters.
6. **Cameras.** Lens calibration / bed alignment (the fisheye needs LightBurn's
   camera calibration pass); **first light on an 8 MP (OV8856) machine** — the
   whole path is written but nothing has run on one, and only that hardware can
   answer whether the 2-lane RAW8 full-resolution mode locks the D-PHY at
   720 Mbps/lane and what exposure/gain the sensor wants; the details, the
   reachable-mode reasoning and the factory fallback configuration are in
   `kas/README.md` §2. Also unapplied: the factory's **per-unit lens-shading
   calibration**, an OmniVision LENC register file the factory pushes into the
   sensor at every stream start (`load_cam_regs.sh` → a `regs` sysfs attribute
   its driver adds; OV8858 `0x58xx` addresses remapped to the OV8856's
   `0x59xx`). The files are per-machine data, not in the factory rootfs — look
   for them under `/data` on a machine booted into the factory slot before
   deciding whether to reimplement the mechanism. Finally the deferred emulator
   homing-image smoke, now that the emulator can be pointed at live snapshots.
7. **Cloud mode.** The remaining gaps are tracked in
   `python3-gfhardware/forgefirm-app/docs/CLOUD.md` "Outstanding items":
   streaming-during-run (would lift the ring-size cap on job length),
   oversize-job rejection against a real too-big job, packaged-path boot with
   `controller_mode = cloud`, the three unobserved actions, the lid-flash LED,
   and taking the pause constants from the pulse header (`CCbp`/`CCbt`) once a
   capture confirms them. Not inducible from the bench: the
   cancel-with-a-rejected-`settings`-action case and a malformed frame (needs a
   MITM).
8. **Shared machine services — remaining polish.** None of it blocking:
   - **Diagnostics as engine modes.** The flow tools still drive the thermal
     hardware themselves while the engine suspends its writes; the check
     parameters are already shared (`cool.h`), so what remains is folding the
     tools into the engine and retiring the suspend/resume dance.
   - **Rail policy** (the one `[contract]` item left in SERVICES.md). The GRBL
     driver still writes `cnc/enable` at init and at homing resume —
     idempotent, since the rail is already up, so this is tidiness rather than
     a bounce source.
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
   - **`/cool/status` cosmetics.** The endpoint echoes the last reported `armed`
     flag even when that report is stale (`report_age_s` tells the truth), and a
     gfcloud homing session reports every motion as a job, so the engine cycles
     run → smoke → idle per motion. Both are silent and safe.
9. **Physical-evidence negatives still open.** A present head answering I²C
   badly (the K-11 runtime case) and a failed head capture leaving the measure
   laser off — both need the head connected and a fault injected. Opportunistic:
   `STATE_FAULT` recovery via `enable` the next time a DRV8825 fault line
   actually trips.
10. **Debug-kernel checks.** Module load/unload under `CONFIG_DEBUG_MUTEXES`
    and a forced `-EPROBE_DEFER` unwind still need a debug kernel build.
11. **Wi-Fi SDIO CRC watch.** The uSDHC pads now carry the factory-exact values
    and ship in every image. Watch `dmesg | grep -c "sdio .* failed"` across
    sessions (baseline: 1 event in 49 min of uptime). Effect if one lands
    mid-job: a 1–2 s sender stall — a cut-quality nuisance, never a safety
    matter. Only if it still recurs, cap the bus with
    `max-frequency = <25000000>` on `&usdhc1` (halves Wi-Fi throughput — last
    resort; the factory ran 50 MHz on these pads).
12. **Release acceptance follow-through.** A full campaign is owed on the first
    image built with the `<recipe>-pin.inc` layout: that image is a platform
    change against everything recorded so far, unavoidably, and only from then
    on does a component pin bump re-require just the tests covering that
    component. `20260817124714` was built after the pin files landed and the
    parity tests were driven on it, but no full-campaign export is recorded for
    it — confirm on the bench and write the record here. Also still owed:
    exercising the ported bench tools from the page (they are registered and
    unit-tested, not yet driven from the page), and the first release, which
    runs the campaign and commits `releases/v<version>/acceptance.json`.
    Catalog gaps left from the tool's own plan: `cooling.confirm-escalate` and
    `cooling.fire-gate-blocks-arm` are not ported (both need the pump switched
    by hand mid-run, so they are bench-tab material first), and whether
    `laser.armed-kill` belongs in the always-required core rather than its
    domain is still an open call (the core carries the emission witness).
    Tools that genuinely need a second host (LAN flood, remote auth probes)
    stay host-side by design, and the registry marks them so.
13. **Publish.** The kas flip and the first GitHub release, per
    `kas/README.md`, once ready to publish. Repoint the core submodule to
    upstream if the `step_us_min` sizing fix merges.
14. **Update system Phase 5 — recovery refresh.** The remaining phase of
    `docs/UPDATE-SYSTEM.md` (a refreshed recovery image in boot0); Phases 0–4
    are done.
15. **Head-IRQ source validation — beam-emission hypothesis (exploratory, not
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

16. **Step timing under CPU contention.** The board runs one core, and of
    grblHAL's four threads only the shipper is `SCHED_FIFO`. The producer —
    the thread that emulates the stepper timer and stamps every step onto the
    virtual time grid — is `SCHED_OTHER` at nice 5, the same class and nice as
    forgectrl's MHD connection threads, so a camera stream viewer (~35 % of the
    core on its own) competes with step generation on equal terms. When the
    producer's virtual clock falls behind wall clock by more than the ring
    depth (200 ms), `gf_stream_pulse` clamps late events forward and the
    backlog ships one step per machine tick: 28 160 steps/s against the 1 778
    that 2000 mm/min asks for, a ~16× velocity burst the motors cannot follow.
    `cnc/underruns` stays 0 through all of it, because the ring never goes
    dry — the stream is continuous and only its timing is wrong, which is
    exactly what the present counters cannot see. Owed: put the producer on
    `SCHED_FIFO` just below the shipper; gate or throttle the camera stream
    while a job runs (forgectrl already holds the run state, so this shares the
    bench slot with the HTTP surface caps in item 8); and report the clamp
    count per run instead of only cumulatively at process exit. The per-run
    `LOG_DEBUG` line is the instrument — a clean 2000 mm/min run with no camera
    consumer reports `max behind 1.5 ms, clamped 0`.
17. **Laser power model and the missing duty floor.** grblHAL maps S onto the
    analog PWM duty (`$30`/`$31` → `$35`/`$36`, written raw into PWMSAR against
    the 127-count period), and ForgeFIRM overrides only `$32`, so a shipped
    machine has `$35` = 0: duty runs linearly to zero with S and nothing stops
    it falling below the tube's striking threshold. Under M4 the core scales S
    by velocity, so every corner, every reversal, and every segment shorter
    than the accelerate-in-and-out distance (~1.6 mm at 2000 mm/min with the
    default 700 mm/s²) is commanded below the striking point and does not burn
    at all.

    The factory does not use duty as a power control. All five firing jobs in
    the captured pulse files pin the power byte at 127 (one also uses 102) and
    modulate dose entirely by dithering the FIRE bit at the 10 kHz tick, at
    6.5–18.8 % density. Two consequences: the captures cannot supply a `$35`
    default, because nothing in them runs anywhere near the threshold; and the
    duty → optical-power transfer function of this HV supply is unmeasured,
    because nothing has ever depended on it.

    Owed, in order: run `live_fire_drills.py pthresh` on scrap with `$35` = 0
    to find the striking threshold, set `DEFAULT_SPINDLE_PWM_MIN_VALUE` (a
    percent) in `grblHAL-glowforge/src/boards/glowforge.h` from it — the
    marking rung's percent is the value — and record the number here. Then the
    design question behind it: whether to follow the factory and modulate dose
    by FIRE-bit density at a fixed high duty rather than by analog duty. That
    is what the per-tick FIRE bit exists for, it cannot fall below the striking
    threshold by construction, and it is the only power model this tube and
    supply are known to work well with.

    What that model means for image engraving, since it decides the design as
    much as cutting does. LightBurn has two image paths. Its 1-bit modes
    (Dither, Stucki, Jarvis, Halftone, Ordered) dither in the image domain and
    emit only `Smax` or 0, so density is solid whenever a dot is on. Grayscale
    mode emits a level per pixel, and that is the path the present duty model
    breaks worst: dark pixels map below the striking threshold and mark
    nothing, so shadows do not fade, they drop out. FIRE-bit density fixes that
    by construction — a low level becomes sparse full-power pulses, every one
    of which marks. Three consequences to design around:
    - **Tonal resolution is set by ticks per pixel**, `rate × pixel_mm ÷
      speed_mm_s`: 56 ticks at 254 DPI and 3000 mm/min, 14 at 508 DPI and
      6000 mm/min. Fine, fast rasters have few pulse slots per pixel and lose
      levels. The factory works at 10 kHz with ~20 ticks per pixel at 254 DPI,
      so this envelope is livable, not comfortable.
    - **The dither accumulator must carry across pixels**, so a level too fine
      to express inside one pixel still averages over a run of them — that
      spatial averaging is what recovers the levels the arithmetic above
      loses. It follows that the accumulator resets only on fire-off, run
      boundaries, disarm and abort, never per pixel.
    - **A 1-bit image run below full layer power stacks two dithers**, and a
      plain integer carry repeats on a short period, so it can beat against
      LightBurn's own pattern as moiré. Perturbing the accumulator removes the
      short period; the workflow answer is that 1-bit modes belong at 100 %
      power with darkness set by speed, where density is solid and no second
      dither exists.

    Rasters also gain from the model directly: a level change costs a power
    byte in the stream today, and the feeder contract forbids back-to-back
    power bytes, while under FIRE dithering the duty is a constant sent once
    per run and a per-pixel level change costs no stream byte at all.

**Deliberately not gated:** an armed GRBL job after an underrun cuts at the
stale origin unless homing is required (GRBL mode permits unhomed cutting; the
underrun itself alarms and unlinks the anchor). Not in the acceptance catalog
by design, for the same reason.
