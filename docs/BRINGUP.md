# ForgeFIRM bring-up status & cold-start runbook

Last updated: **2026-08-08** — **SD images 20260808011035 built**
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
Read together with `AUDIT_ACTION_PLAN.md` in the project root (sibling of
this repo; per-finding status of the 2026-07-03 audit) and
`kernel-module-glowforge/UAPI.md` (the pulse-stream feeder contract).

## Where the project stands

**Audit phases 0–5: complete and hardware-verified.** Both motion blockers
fixed (cnc probe / 40v-supply; SDMA script relocated to `<26 0xF00>` with a
pre-run integrity guard); the end-of-data protocol reworked and bench-proven
(underrun is a first-class `underrun` state behind the `streaming` attr;
16/16 protocol bench); laser PWM verified at 39.98 kHz (register level);
`CONFIG_PREEMPT=y`; uEnv/u-boot/ulfius build integrity restored; legacy
cloud mode repaired (nvmem identity → fuse hostname verified;
deadman/safety loop; camera error paths).

**Phase 6 spike: achieved.**
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

## The bench

- **Board**: SSH `root@172.16.1.97` (fixed DHCP lease since 2026-08-02;
  was .130), empty password
  (`ssh -o PreferredAuthentications=none` logs straight in). The bench
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
  Batch kernel-overlay edits accordingly. Queued for the next batch:
  `vs-supply = <&reg_3p3v>` on the lm75 node (the last cosmetic
  "dummy regulator" probe line besides the two SoC USB PHYs).
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
  2017-05-001.pub). The production release key does not exist yet —
  generation/custody is an operator ceremony (UPDATE-SYSTEM.md gate 8).
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
constants in `src/boards/glowforge.h`. **The controller autostarts at boot** since
2026-08-03: the `grblhal-glowforge` recipe (meta-forgefirm; gitsm pin +
sysvinit script `grblhal`, defaults 92) is installed in both images, and
the same init script is installed on the current bench rootfs
(reboot-verified: controller + forgectrl both up unattended, Grbl
answering on :23). The manual start below remains the bench/debug path. Architecture: a wall-paced producer thread runs
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
2. Deploy to `/usr/bin/grblHAL_glowforge` on the board (kill the running
   instance first — the binary can't be overwritten while executing).
3. Start: `cd /data && GFSINK=/dev/glowforge grblHAL_glowforge -p 23 -e
   /data/EEPROM-glowforge.DAT` (no `-t` — real-time pacing is intrinsic
   now). Env knobs: `GFSINK_RATE` (machine tick, default 28160 Hz =
   factory travel tick), `GFSINK_DEPTH_MS` (queue depth = feed-hold
   latency, default 200). The driver applies the full analog machine
   config itself at init (×8 modes, decay 1, motor_lock 8, laser latched,
   PIC hold currents) and swaps PIC run/hold currents around motion. If
   the baked $-defaults changed since the last run, `$RST=$` once (stored
   settings win). Each motion run logs a producer-stats line to stderr
   (callbacks, µs/call, max-behind, clamped) — clamped should stay 0.
4. Connect LightBurn/UGS to `172.16.1.97:23`, or jog raw:
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

## The camera service (forgectrl, port 8080)

Source: `C:\dev\openglow-forgefirm\forgectrl` — the **canonical repo**
(github.com/ScottW514/forgectrl, branch `main`, MIT). forgectrl is the
ForgeFIRM control daemon: camera service today; realtime hardware
status/settings, hardware control, and GRBL-vs-cloud mode selection are
its planned scope. The meta-forgefirm recipe pins its SRCREV (bump
deliberately after pushing) and installs the sysvinit script from the
repo's `init/`; bench builds cross-compile with
`forgefirm/scripts/bench/build-forgectrl.sh` (same toolchain-borrow
pattern as build-glowforge.sh). One ulfius daemon exposes both OV5648
cameras as MJPEG over the mainline imx-media pipeline:

- `GET /` — the tabbed machine control panel (Status / Machine /
  GF Cloud / GRBL / Diagnostics; ui.c): status page with the
  controller-mode selector (GRBL active; factory cloud disabled until
  implemented), the operational dashboard, a scaled lid snapshot +
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
runner (forgectrl diag.c, one slot) stops the `grblhal` service
(launch is gated on cnc idle + no diagnostic), drives the loop
directly through sysfs — the same model as the bench characterization
scripts — and restarts the service on every exit path (completion,
tool error, operator abort via `POST /diag/abort`, safety ceiling).
`/run/forgefirm-diag.active` marks the ownership; forgectrl startup
recovers a stale marker (stand-down + controller start), covering a
daemon crash mid-diagnostic. The laser is untouched throughout (latch
stays locked). While a diagnostic runs: settings POSTs 409, `/status`
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

**Cooling tunables are conf-backed since 2026-08-08**: the nine
`cool_*` keys (flow_rise, flow_heater_pct, flow_check_s, recheck_s,
confirm_max_s, temp_max, temp_resume, cooldown_s, cooldown_max_s) live
in `/data/forgefirm.conf` (forgectrl Machine tab, validated ranges),
the driver re-reads them at **every flood start** (env `GFCOOL_*` >
conf > compiled default; env stays the bench-override path — it wins
for the process lifetime), and the conf parser now lives in
`glowforge_io.c` shared with homing.

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

## Hardware facts bank (measured)

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
     behavior remains to be exercised (non-scope check).
   - **Fan/thermal control (operator-mandated laser-on prerequisite):
     DONE 2026-08-02, bench-verified** (`glowforge_cooling.c` in the
     driver; test `scripts/bench/fan_test.py`). Factory pulse-header
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
       2026-08-08, bench-drilled 6/6 + escalation** (driver
       `glowforge_cooling.c`). An over-limit check is a SUSPICION,
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
   - **Interlock readback semantics cross-check: OPEN** (see
     factory-laser-safety-readbacks notes).
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
4. **6.5 safety mapping**: door/estop evdev → feed-hold/halt in the
   backend; underrun → grblHAL alarm; interlock-trip recovery check.
4b. **Cloud-mode complete review** (operator-directed 2026-08-03):
   `load_motion` preloads a job's ENTIRE pulse file into the ring with
   no backpressure recovery — with the 16 MiB default ring that caps
   cloud jobs at ~28 min and a too-big job fails mid-download; the
   write path needs rework (stream-during-run or graceful
   too-big rejection). Also: a marked TODO in `load_motion` copies
   every job's full pulse file into the logging directory (disk
   filler), and many cloud actions are not currently handled at all —
   review the action surface end to end (gfutilities service layer).
5. **6.6 camera service: DONE 2026-08-03, bench- and operator-verified**
   (see "The camera service" section above; LightBurn streams it
   directly). Remaining camera work: lens calibration / bed alignment,
   the deferred 5.6 emulator homing-image smoke.
6. **Housekeeping**: ~~pick the controller's remote home~~ **DONE
   2026-08-02** — the controller is now the canonical driver repo
   `github.com/ScottW514/grblHAL-glowforge` (+ `ScottW514/core` fork;
   the settings-write crash fix is upstream PR grblHAL/core#999; repoint
   the submodule to upstream when it merges). ~~Yocto recipe for
   grblHAL-glowforge~~ **DONE 2026-08-03** (`grblhal-glowforge` in
   meta-forgefirm, boot autostart, reboot-verified). Remaining: Phase 7
   doc sweep (CLAUDE.md charter refresh, README roadmap), kas flip +
   first GitHub release per kas/README.md once ready to publish.
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
   Remaining Phase 2 nicety: the installer's embedded pubkey is the
   DEV key until the production ceremony.
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
