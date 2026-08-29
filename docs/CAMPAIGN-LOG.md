# ForgeFIRM campaign log

The dated record of how ForgeFIRM was brought up: bench campaigns, drills,
scope gates, the audit remediation, and the acceptance campaigns. Entries are
verbatim from the day they were written and are never revised — a correction is
a later entry, not an edit.

**Present state lives in [`BRINGUP.md`](BRINGUP.md)**, which is the runbook and
the authoritative list of open work. Read that first; come here for how a
result was obtained.

Two reading rules for this file:

- **Item numbers refer to the "Next work" list as it stood when the entry was
  written.** That list has since been renumbered around the closed items.
- **"above" and "below" refer to the document as it stood when the entry was
  written**, not to this file's arrangement. Later entries supersede earlier
  ones on the same subject; where an entry was proven wrong, the correction is
  further down.

## Before 2026-08-02 — platform bring-up

### Where the platform stood when the controller work started

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

## 2026-08-02 — motion quality, the scope gates, the cooling design

### First real LightBurn job

**First real LightBurn job: 2026-08-02, operator-verified.** Device
setup per `LIGHTBURN.md` (GRBL over TCP:23); a full design job — rapid
in, M4 dynamic-power cut trace at commanded speed, return rapid — ran
smoothly end to end on grblHAL-glowforge (laser locked, motion only).
Two driver fixes came out of the first attempts: the locked laser
spindle (M4/$32 support without fire capability) and the
continuation-wakeup cursor alignment (back-to-back cycles previously
clamped into step bursts — jerky, step-losing rapids; found via the
per-run `clamped` stat from the operator's own job log).

### Milestone 2 — motion quality

**Milestone 2 (motion quality): bench-verified 2026-08-02.** The factory
motion constants were extracted from captured factory pulse files
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

### Backend milestone 2 closed

**Backend milestone 2 — motion quality: DONE and human-verified
2026-08-02.** Operator confirmed motion is "butter smooth" (and near
silent) on a full observation run — slow/fast/diagonal/zigzag jogs at
up to 200 mm/s under grblHAL-glowforge with the factory-true analog
config. The pre-tuning loudness was the 150/150 currents + unset
decay mode. Milestone closed.

### The standing scope gates

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

### Fan and thermal control

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

### Coolant temperature conversion corrected

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

### Coolant flow verification rebuilt on a 60-run design matrix

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

### Coolant flow verification — the superseded first design

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

## 2026-08-03 — the camera service

### Bench record

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

### LightBurn consumes the stream

**LightBurn consumes the stream directly — operator-verified
2026-08-03** ("without issue", via the mjpg-streamer-compatible
`/?action=stream` alias) while jogging the machine from the same
LightBurn session.

### VPU JPEG offload

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

### NEON demosaic

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

### Cloud-mode complete review (operator-directed)

**Cloud-mode complete review** (operator-directed 2026-08-03):
`load_motion` preloads a job's ENTIRE pulse file into the ring with
no backpressure recovery — with the 16 MiB default ring that caps
cloud jobs at ~28 min and a too-big job fails mid-download; the
write path needs rework (stream-during-run or graceful
too-big rejection). Also: a marked TODO in `load_motion` copies
every job's full pulse file into the logging directory (disk
filler), and many cloud actions are not currently handled at all —
review the action surface end to end (gfutilities service layer).

## 2026-08-07 — pacing, the fortify crash, cached buffers, homing

### Protocol-loop pacing is fd-blocking

**Protocol-loop pacing is fd-blocking (2026-08-07).** `serial_wait()`
drains TX then `ppoll()`s the listen/client fds with the
state-dependent timeout (idle/alarm 10 ms — 1 ms while a delay
callback is pending — motion 200 µs), so traffic wakes the loop
instantly while idle ticks stay coarse. **Bench-verified: idle CPU
7–12% → ~2%** (1.95% with the camera streaming beside it), status
RTT ~1.0 ms median, jogs exact, `clamped 0` with an active stream.
Client RX is armed only while the ring has a full read's worth of
room, so a flow-control-violating sender is paced, not spun on.

### Fortify overflow fixed in the core

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

### Non-coherent (cached) capture buffers + stream FPS cap

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

### Web-service homing: bench record and live verification

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
     motion (facts bank in `BRINGUP.md`). Gate is now opt-in
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

## 2026-08-08 — diagnostics, panel rework, wireless, install/update

### Diagnostics bench record

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

### Units / identity / position panel rework

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

### Wireless regulatory + region setting

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

### Flow-fault triage resolved

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

### Suspicion / confirmation state machine

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

### Install / update system — Phases 0, 1 and 2

**Install/update system overhaul** (planned 2026-08-08): adopt the
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

### SD images 20260808011035

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

## 2026-08-11 … 2026-08-13 — first light, the wedge, shared services

### First light and the no-motion root cause

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
  see the hardware facts bank in `BRINGUP.md`): whether a given power-up leaves
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

### GRBL-mode laser software: implementation record

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

### Interlock readback semantics cross-check

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

### Shared machine services complete and closed out

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

### Shared machine services — the drills

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
counters running normally — see the hardware facts bank in `BRINGUP.md`), so the
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

## 2026-08-13 … 2026-08-15 — audit remediation (159 findings, Phases 0-11)

An independent whole-tree audit dated 2026-08-13 produced 159 findings. The
remediation ran as twelve phases, sequenced behind two gates — **GATE A**
(uncommanded energy) before any further live fire, **GATE B** (control surface
and release) before any published release. Both are bench-closed; the drills
are in the bench-campaign section that follows. The audit's own working files
(the findings list, the remediation plan) were retired when the last phase
landed.

### The images that carried it

Image `20260814223300` (forgefirm-image + forgefirm-image-dev)
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
"Next work" in `BRINGUP.md`, and the runbook is the record.

### Phase 0 and Phase 1 (GATE A, uncommanded energy)

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

### Phase 2 (GATE B, control surface + release)

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

### Phase 3 (broker ownership / dead-man second pass)

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

### Phase 4 (stale-gate cluster)

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

### Phase 5 (physical-evidence instrumentation)

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

### Phase 6 (motion integrity)

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

### Phase 7 (cloud-mode robustness)

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

### Phase 8 (kernel-module hardening)

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

### Phase 9 (build, BSP, and release engineering)

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

### Phase 10 (tests & CI)

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

### Phase 11 (licensing, legal, documentation hygiene)

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

### Kernel platform hygiene batch

**Kernel platform hygiene — CODE-COMPLETE and build-verified
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

## 2026-08-14 … 2026-08-15 — the bench campaign

### Post-flash health, GATE B, GATE A

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

### The live defect the campaign caught

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

### X-2 connection-flood robustness

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

### Idle-CPU diagnosis and the pacing fix

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

### Live-fire drills

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

### Closed by host unit test instead of a bench drill

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

### Lid-IR ambient baseline

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

### Bench session 2026-08-15

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

### Interlock latch, charge-pump watchdog, hv_enable rename

**Interlock latch has no hardware trip path in ForgeFIRM (found
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

### LightBurn door-open handling

**LightBurn door-open handling — CLOSED by item 16.** The lid no
longer parks a job in `Door` on the default policy: it cancels the job,
ends the sender's stream with a clean reset and returns the head to the
job start, so LightBurn never lives in `Door` and the Resume convention
it used to need is gone. The `Door` residency that remains under
`lid_policy = hold` is covered by `motion.lid-policy-hold` (lid parks the
job, cycle start after the lid closes finishes the move with its position
intact), bench-validated 2026-08-17.

### uSDHC pad strength brought to the factory values

**uSDHC pad strength brought to the factory values (DTS change
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

### Unified logging — bench validation

**Unified logging — CODE-COMPLETE, host-verified, pushed and pinned
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

### Outstanding bench validations, as consolidated 2026-08-15

**Outstanding bench validations (consolidated 2026-08-15).** Every
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

## 2026-08-15 … 2026-08-16 — release acceptance (forgetest)

### Campaigns on the bench

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
and TEC off). A reference dumped at uptime 30 s on 2026-08-16 showed the
probe values instead (`motor_lock 0`, `step_freq 10000`, `y_mode 1`): the
dump raced the controller's init writes - `/mode` reports `running` at the
spawn, not at the config - so `boot_reference()` now waits for the
controller's markers (`step_freq`/`motor_lock`/`y_mode` at their fixed
values, bounded 20 s) before dumping, and retakes a pre-config reference
while the boot is still fresh. Proof: k1-k2 / k3 / fire-abu re-run under the baseline -
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

### Tool status record

**Release acceptance tool (forgetest) - BENCH-VALIDATED 2026-08-16.**
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
the layer content; record in "Release acceptance" above). The catalog
has since grown to **35 tests** (item 16's parity work, then a sweep
that merged the tests sharing a setup: `kernel.fire-line` runs A/B/U
and the mid-ramp unlock behind one takeover, `laser.armed-kill` covers
the expected stop and a SIGKILL on one scrap setup,
`laser.pause-resume-lid-cancel` pauses, resumes and then cancels one
armed burn, and `cloud.lid-interlock-abort` runs the lid and the
interlock as two prints; the 17 `auto` tests were left separate, since
merging them buys no operator time and costs failure isolation).
Every board-runnable bench tool is ported to the page, including
`resume_dark_lead.py`. Remaining: the first release runs the campaign
and commits `releases/v<version>/acceptance.json` - **not yet: no
release is cut.**

## 2026-08-16 … 2026-08-17 — lid / button / interlock parity

### The parity record

**Lid / button / interlock parity with the factory firmware — DONE,
bench-validated 2026-08-17 on dev image `20260817124714`.** Both controller
modes react to the lid, the remote-interlock loop and the button the way the
factory daemon does. The factory behavior was decoded and then recorded on
the bench machine booted into factory 2.6.0-2228; that session covered five
prints and its measured numbers are in the facts bank in `BRINGUP.md`.
- **What the machine does, both modes.** Lid or interlock open during a job,
  running or paused: motion stops within milliseconds of the edge, the job is
  **cancelled and not resumable**, the head returns to the position the job
  started from **with the lid still open**, the kernel laser latch relocks and
  the armed window closes. The next job re-arms with a button press — the same
  press the hardware button latch needs, so the software window and the
  hardware latch agree by construction. The return-home park ignores the lid
  and always runs to completion. A lid or interlock open during the pre-run
  button wait cancels the job with the reason named. A lid open during a hunt,
  homing, a jog or at idle is ignored. The button pauses and resumes a job:
  in cloud mode with the factory's laser-off backtrack and resume lead
  (`cloud_pause_backtrack_ticks` 2000 / `cloud_resume_lead_ticks` 1950), in
  GRBL mode as feed hold / cycle start — the kernel refuses a backtrack on a
  live-streamed ring, so a resumed GRBL cut picks up where the deceleration
  ended. A pause is not a cancel: the latch stays unlocked and the armed
  window open across it. `lid_policy = hold` selects stock grblHAL door
  behavior (park in Door, cycle start resumes) instead of the cancel.
- **GRBL** (`grblHAL-glowforge/src/glowforge_switches.c`, `glowforge_laser.c`):
  the arm wait cancels on lid or interlock with a clean soft reset — no alarm,
  reason reported — and a press with the lid open never arms; the button is
  the pause/resume toggle outside that wait, the arming press consumed so it
  is never also a pause; a lid or interlock open mid-job parks the job through
  the core's door state (planned deceleration, spindle off, position kept) and
  the driver then cancels it, resets from the parked state and enqueues a
  `G53 G0` back to the job start with the door hidden and the latch locked.
  The job start is the machine position at the Idle → Cycle transition.
  `GF_SWITCH_FILE` is the file-backed EV_SW word that lets null-sink builds
  drive these edges in CI.
- **Cloud** (`python3-gfhardware/gfhardware/machine.py`, `Glowforge-Utilities`):
  the interlock joins the lid in every gate; the switch thread wakes the run
  loop on the edge, with the level read kept as a backstop; the park ignores
  the lid and the cancel flag and clears the ring before it moves, so nothing
  of the abandoned job plays ahead of it; a hunt ignores the lid; a job refused
  at start ends `:cancelled`, never `:completed`; the button pauses and resumes
  a print exactly as the factory does (`print:paused` / `print:resumed`), and a
  lid, interlock or service cancel while paused cancels from where it stands.
- **No resume dwell.** The GRBL resume was suspected of losing its first ~90 ms
  to the HV_ENABLE re-arm. Measured on the pads instead
  (`scripts/bench/resume_dark_lead.py`, numbers in the facts bank): the chain
  is back within ~3 ms of the resume and motion only restarts ~219 ms later, so
  there is nothing for a dark dwell to cover and none was added.
- **Proof.** Host: `laser_arm_test`, `laser_lifecycle_test.py` (button wait,
  lid and interlock in the wait, button toggle, cancel + return without alarm,
  `lid_policy=hold`), `python3-gfhardware/tests/test_machine_lid_button.py`,
  the gfutilities suite, and the forgetest unit tests + coverage lint. Bench,
  through the acceptance catalog: `motion.button-hold-resume`,
  `motion.lid-cancel-home` (cancel from Run and from a hold),
  `motion.interlock-cancel-home`, `motion.lid-policy-hold`,
  `cloud.lid-interlock-abort`, `cloud.lid-during-button-wait`,
  `cloud.hunt-lid-open`, `cloud.pause-resume`, `cloud.pause-cancel-paths`,
  `cloud.gfhome-homing` and `cloud.mode-switch` all PASS 2026-08-17; the live
  arm-wait, mid-burn lid cancel, expected stop and armed-kill drills passed
  the same day (`laser.arm-wait-lid`, `laser.emission-witness`,
  `laser.disarm-in-hold`, and the mid-burn lid cancel that the stream-engine
  fix below made honest).
- **The stream-engine defect this work found and fixed.** A mid-burn lid
  cancel reported a return the machine never made: the park's `cnc/run` landed
  while the kernel was still playing the hold's queued tail, was refused with
  EPERM, and "refused, kernel running" was taken for a start — the kernel then
  idled with the park bytes stranded, and the next run played them first. Fixed
  in `stepper_stream.c`: a refused run stays *pending* and is re-issued the
  moment the kernel reads idle; a soft reset never stops a kernel that is only
  draining a completed stream; a mid-motion reset clears the unplayed residue
  once the stop has played out, before any new bytes ship or the device changes
  hands; the cancel path waits for the drain before the reset. The lesson is in
  the catalog: the lid tests check the **kernel counters**, not grblHAL's
  belief about them, and the baseline refuses to jog while unplayed ring bytes
  exist.
- Items 4 and 12 above are closed by this policy.

### The controller safety mapping it replaced

**Controller safety mapping — DONE.** The mid-job Door hold described
here is the `lid_policy = hold` path; the default is the factory-parity
cancel of item 16 (lid or interlock = cancel + return to the job start),
bench-validated 2026-08-17 (`grblHAL-glowforge/src/glowforge_switches.c`). The
controller reads EV_SW with `EVIOCGSW` from the protocol thread's
realtime hook (no grab — forgectrl polls the same device) and maps:
- **doors (bit 3) not closed, or interlock (bit 5) loop open →
  the core's `safety_door_ajar`.** A running job parks in the door
  state and resumes when the condition clears, which is what the
  hardware chain already does to the beam. Bit 3 is the series
  combination the safety chain itself uses, not the individual door
  switches.
- **hv_enable (bit 4): never gated on.** It is the readback of the
  chain's HV_ENABLE output (facts bank in `BRINGUP.md`), telemetry only; the
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

## 2026-08-17 — step timing under CPU contention

Opened by an operator report: the `LB-GF-OG-FM` LightBurn job, GRBL mode
at 2000 mm/min and 30 % power, ran jerky and lost many steps.
`cnc/underruns` and `cnc/faults` both read 0 throughout, which is the
whole reason the condition had gone unnoticed — the kernel ring never
runs dry, so the stream stays continuous and only its *timing* is wrong.

### What was wrong

The board runs one core. Of grblHAL's four threads only the shipper held
`SCHED_FIFO`; the producer — which advances virtual time and stamps every
step onto the pulse grid — ran `SCHED_OTHER` at nice 5, the same class and
nice as forgectrl's MHD connection threads. forgectrl was measured at
~41 % of the core serving the panel's MJPEG camera stream, one connection
thread alone at ~35 %.

When the producer's virtual clock falls behind the ship cursor,
`gf_stream_pulse` clamps late events forward and the backlog ships one
step per machine tick: 28 160 steps/s against the 1 778 that 2000 mm/min
asks for, a ~16× velocity burst no motor follows.

The margin absorbing a stall was **2 ms**, not the 200 ms queue depth it
appears to be: the shipper's due index carries the same `+ gf.depth` the
producer's base starts at, so the two cancel and the pacing lead is the
only slack there is.

### What was changed

- Producer on `SCHED_FIFO` one priority below the shipper, and `core_mx`
  given priority inheritance — the producer holds it across the stepper
  callback while the protocol thread also takes it, so promoting without
  PI would have traded jitter for unbounded inversion (grblHAL 026c169).
- Producer lead made tunable (`GFSINK_LEAD_MS`) and defaulted to 10 ms;
  the per-run `LOG_DEBUG` line now reports the **measured** `min margin`
  in ms against it (grblHAL fd059b3).
- Clamp count reported per run at `WARNING`, not only cumulatively at
  process exit.

The lead defaults to 10 rather than higher because of the cycle-churn
path: `gf_stream_wakeup` re-bases production onto the wall cursor only
when the cursor has passed it, so a larger lead survives an idle gap,
skips the re-base and accumulates as dark padding. Measured on the
`laser_stream_test.py` churn harness: 2 ms and 10 ms both give an
identical 64 790-byte stream, 15 ms and above inflate it to ~225 k and
stop being deterministic.

### Bench record

Two `motion.step-timing-under-load` runs 90 s apart on image
20260817210307, same campaign, camera streaming at 2592×1944 in both,
plus the test's own nice-5 CPU hog:

- **PASS** — 20 legs, 26.7 s, 0 clamps. Camera not streaming.
- **FAIL** — 20 legs, 26.7 s, **7 runs clamped, 81 events**, max behind
  3.9–4.4 ms. Camera streaming.

That isolates it: `SCHED_FIFO` covers a userspace CPU competitor and does
not cover the camera, whose per-frame cache maintenance over a 4.8 MB
non-coherent capture buffer is kernel-context work no userspace priority
can preempt.

On image 20260817220126 with the 10 ms lead, same conditions as the
failing run (camera at 2592×1944 **and** the CPU hog): **PASS, 0 clamps**,
worst `min margin` 4.9 ms of 10 across 12 legs.

Then the original `LB-GF-OG-FM` LightBurn job again, operator-run, with
the video stream live (independently corroborated: forgectrl was holding
`video0`/`video4` with four `:8080` connections mid-job):

    run: 686850 callbacks in 62.255 s (90.6 us/call incl. pacing),
    50721 pace sleeps, max behind 4.7 ms, min margin 3.1 ms of 10, clamped 0

Identical callback count and duration to an earlier run of the same job,
so it is the same work. Operator judgment: ran clean. `underruns` 0,
`faults` 0, and no clamp warning from the current controller instance.

### What the numbers say

`max behind` is **not** the instrument — it read 0.0 ms on every leg of
the passing acceptance run while the real margin fell to 4.9 ms, because
the producer never falls behind its own wakeup epoch; the margin is
consumed by the offset between that epoch and the shipper's `ship_t0`.
Only the measured `min margin` shows the condition.

The real job is the harsher adversary: 3.1 ms of 10 remaining, against
the synthetic test's 4.9 ms, at a *lower* callback rate (11 033/s vs
13 784/s). Real cut geometry costs more headroom than uniform jog legs.

So the fix holds on the job that prompted it, with ~31 % of the budget
left at the worst moment. Both remaining levers are unspent: camera
capture resolution (the mainline `ov5648` offers 1280×960 and 640×480
binned modes, 4.1× and 16.4× fewer bytes, which shortens the stall rather
than merely spacing stalls out) and the churn re-base (which is what
would allow a lead beyond 10 ms). Tracked in BRINGUP "Next work" item 16.

## 2026-08-17 — the laser duty threshold ladder

The first owed step of "Next work" item 17: measure where the tube starts
lasing, so `$35` can stop M4's velocity-scaled power falling below it.

### The run

`live_fire_drills.py pthresh 1000 300` on wood scrap, operator-run on dev
image `20260817220126`, machine idle and homed, coolant 23.9/24.1 °C. The
precondition was read off the machine first: `$30`=1000, `$31`=0, `$32`=1,
**`$35`=0.0**, `$36`=100 — no floor in place to lift the rungs.

Thirteen rungs, 2 %…30 % of full, 25 mm each at F300, constant power (M3),
3 mm of `+Y` between them. Before firing, the two conversions were checked
against each other: a rung of *P* % sends `S = 10·P`, which the core maps to
`floor(127·P/100)` counts, and `$35 = P` computes `min_value =
(uint)(127·P/100)` — the same integer, so the rung's percent *is* the `$35`
value exactly, not approximately.

### What came back

Material, counting from the first rung drawn: rung 1 (2 %) nothing at all;
rungs 2–9 (3–14 %) a tiny spot at the start of each line and a dark line
after it; rungs 10–13 (16–30 %) continuous marks.

The `hv_current` trace agrees independently. It holds 0 for 19.5 s (arm
wait), then runs nonzero to 82.8 s, immediately before Idle. Within it the
laser-off `G0` between rungs reads 0, so the current runs count the rungs:
**12 segments of ~4.7 s at a ~5.27 s period, not 13.** The last segment ends
at the job end, so it is rung 13; counting back 12 puts the first current at
rung 2. Rung 1 drew no measurable discharge current — the same rung that
left no mark, from a completely separate witness.

So the tube has **two thresholds, far apart**:

| | rung | duty | witness |
|---|---|---|---|
| Discharge strikes | 2 (3 %) | PWMSAR 3 | current lifts off; spot only |
| Sustained lasing | 10 (16 %) | PWMSAR 20 | first continuous mark |

Between them, 3–14 % is a **dead band**: current flows and climbs (per-rung
means 133 → 289 raw) with essentially no light out. Each line's opening spot
is the strike transient; the tube lights, drops below lasing gain, and coasts
dark for the remaining 25 mm.

This falsifies the drill's own guidance, which said the current "lifts off
baseline at the same rung the material starts marking" — lift-off is rung 2,
marking is rung 10. The docstring and the printed read-the-material text were
corrected to name both thresholds and to tell the operator that a rung
showing only a start-of-line spot is *below* the threshold, not at it.

Raw `hv_current` is a presence/absence witness only. Per-rung means are
non-monotonic at the top (429 at 20 %, then 311 and 302) and the variance
collapses on the top two rungs, which is what an aliased point-sample of a
pulsed current looks like; the signal has no characterized transfer function.

### Ruling out the firmware explanation for the spots

A start-of-line spot is also what a full-power leak would look like: a kernel
run start resets the hardware duty to ~100 %, so a fire bit reaching the
stream ahead of its power byte would burn at full power. The material already
argued against it — rung 1 is the first fire of the run, the likeliest place
for such a leak, and it is blank — but the stream is the record, so
`laser_stream_test.py` gained a fourth session (rule 10): a ladder in the same
shape, full power deliberately absent, asserting that every FIRE tick rides a
commanded duty and that the fire ticks divide evenly across rungs (a rung
opening at its neighbor's duty shows up as a surplus on one and a deficit on
the next).

Result on the native build: duties under FIRE were exactly `[22, 23, 26, 32,
41, 52]`, nothing else, and **28296 fire ticks on every rung, identical to the
tick**. No full-power window, no stale-duty window. The spots are the tube and
supply, not the firmware.

### What landed

- `DEFAULT_SPINDLE_PWM_MIN_VALUE 16.0f` in `boards/glowforge.h` — the
  measured lasing rung. Chosen over the next rung up (20 %) because the floor
  is spent at corners, where velocity and dose per unit length already move
  the wrong way, and because `$35` is a user setting anyone can raise.
- The harness now derives its expectations from that floor (`duty_for()`), so
  the M4 session's S500 plateau moved 63 → 73 and its ramp `[44, 52, 63, 127]`
  → `[57, 64, 73, 127]`, plus a new check that no duty under FIRE falls below
  the floor. All four sessions pass, as do `switch_map_test`, `laser_arm_test`
  and `laser_lifecycle_test`.
- `laser.power-floor`, an auto acceptance test (the suite's only non-firing
  one): reads `$$` and checks the machine actually carries the commissioned
  floor, since stored settings beat freshly baked defaults and a machine with
  an older EEPROM needs `$RST=$` once. Coverage lint clean at 40 tests.

### What it means for the model

The usable analog range is 16–100 %, about 6:1, with the bottom sixth of the
control range physically dead — and the factory's captured pulse files pin the
power byte at 127 and modulate dose by dithering the FIRE bit at 6.5–18.8 %
density. The dead band is why. `$35` is a patch that buys freedom from dropout
by putting its full 16 % into every corner; dose set by pulse density cannot
fall below the lasing threshold by construction. Item 17 is now the density
model itself, with the analog path as the fallback.

## 2026-08-17 — how the factory sets power

Three cloud-mode cuts of the same 1" square, same location, same material,
same speed, changing only the Glowforge UI power setting: Precision Power 1,
Precision Power 100, then Full Power, with the pulse file captured from each.

Pulse-file capture ships off (`LOGGING.SAVE_PULS`), and the machine's copy of
`/data/etc/gfhome.conf` predated the key, so it was enabled for this session
and turned off afterward. A first attempt appended the key past the last
section, where `get_cfg('LOGGING.SAVE_PULS')` would never have found it — it
belongs inside `[LOGGING]`, and was verified through the app's own parser
rather than by eye.

### The measurement

**Analog duty is not a power control.** All three runs carry the power byte
exactly three times, always 127: once as the cut begins, then a refresh every
~27 000 ticks (~2.7 s). Nothing modulates PWMSAR, at any setting.

**Dose is FIRE-bit density on a fixed 7-tick period** — 700 µs at
`STfr` = 10 000, ~1.43 kHz — with the on-count dithered between adjacent
integers:

| Setting | on-runs | mean of 7 | density |
|---|---|---|---|
| Precision Power 1 | 1 (×359), 2 (×212) | 1.371 | 0.1953 |
| Precision Power 100 | 5 (×236), 6 (×334) | 5.576 | 0.7952 |
| Full Power | continuous | 7 | 0.9965 |

The period was exactly 7 in all 570 measured cycles of both dithered runs, and
the mix of adjacent on-counts matches the fractional part exactly: PP 1 wants
1.371 on-ticks, and 2-runs are 212 of 571 = 0.371. That is an error
accumulator, not a repeating pattern.

**The power setting never reaches the machine.** The three headers are
identical — no key differs — so the model lives entirely in the service, which
bakes it into the FIRE bits. The motion is identical too: 5420 steps,
101.62 mm (4 × 25.4), 10.81 s at 9.44 mm/s. Full Power's file is longer only
in the lead-in before the cut.

**Velocity compensation is real but partial.** Density falls as the head slows
into a corner, by the same relative factor at every power setting
(corner/cruise 0.38, 0.38, 0.41). Measured per step interval, though, fire
ticks per step *rise* from 3.89 at 9.44 mm/s to 7.00 at 1.22 mm/s, so dose per
unit length still climbs ~1.8× at a corner — against the ~7.7× it would climb
with no compensation at all. Only ~24 of 5420 step intervals are below cruise
speed, so the direction and rough magnitude are solid and the exact law is
not.

On the UI scale, PP 1→100 is linear in density (~0.006 per unit, intercept
~0.189); Full Power sits off that line, where PP ~134 would land, which fits a
setting the UI presents as outside the normal range.

### Two corrections to earlier readings

The first pass at the dither sampled the mid-point of the cut, which for a
square is a corner, and truncated its distributions — it showed 8-on/4-off
bursts that are corner behavior, not the steady pattern. The first pass at the
dose law counted every tick as a step, because in this encoding bits 1 and 3
are *direction*, held for the whole side, and only bits 0 and 2 are step
pulses; the tell was 2026 mm of travel on a 101.62 mm cut.

### A defect found by using the feature

Deleting the capture directory under a running gfcloud showed that with
capture enabled, a missing directory or a full disk makes `load_motion` raise
on the capture write and kills the print. A debug aid must never cost a job:
the capture open, the per-chunk write and the `.info` write are now each
non-fatal, dropping the capture with a warning and running the job on
(`gfutilities`, with a regression test in `tests/test_lifecycle.py`; verified
in three cases — missing directory still loads the job, a writable directory
still gets the copy, capture off writes nothing). No acceptance-catalog
consequence: the path is an off-by-default debug capture with no bearing on
emission, motion or the release surface.

## 2026-08-17 — the density dose model, phases 1 and 2

Implemented and host-proven; off by default, so nothing about a shipped
machine changes until `laser_power_model = density` is set.

### The change

The whole hot path is one predicate in the shipper:

    if(gf.cur_fire)          ->   if(gf.cur_fire && (!gf.dith_period || dither_tick()))
        b |= 0x10;                    b |= 0x10;

That `&&` is the safety property, structurally: the model masks the core's
fire state and can never be a source of one, so it stays out of the safety
argument entirely — the armed window, the latch, the coolant gates and the
hardware chain are all upstream and untouched.

Around it: a fixed base period of `laser_pulse_ticks` (default 20 = 710 us
at 28160 Hz, the factory's ~1.43 kHz), on-count `level x period / 127` with
the remainder carried across periods so finer densities average out, the
on-ticks leading each period so a level renders as one burst rather than
isolated ticks. The accumulator resets only where the dose itself restarts —
run boundary, fire off, disarm, abort — never per segment. In density mode
the duty is pinned: a power byte still leads every kernel run, because the
run start resets the hardware duty, but it always carries full duty and a
level never reaches PWMSAR. Selected per arm from the shared machine config
and reported as `laser armed (density)`; the arm warns when `$35` is set,
since the floor only clamps the light end of a range that cannot fall into
the dead band anyway.

### What the harness holds (rules 11-13)

- Density renders the commanded level exactly: levels 2, 3, 7, 15, 25, 38
  came back as 0.0158, 0.0237, 0.0551, 0.1182, 0.1969, 0.2993 against
  level/127 of 0.01575, 0.02362, 0.05512, 0.11811, 0.19685, 0.29921.
- S1000 renders density 1.0000 and still ends dark.
- Every power byte carries full duty; a level change inside a run costs no
  stream byte, where analog ships one per level (4 bytes, duties 0/30/52/84,
  against density's 1).
- The mask invariant, measured rather than argued: the same job run under
  both models produced an identical motion grid tick for tick, and all
  20051 density FIRE ticks fell inside the 169776 the analog run fired.
- Churn (planner-starve run boundaries) still terminates dark under the
  model, with no FIRE across a stepless gap.

The analog path is byte-identical to before the change — same byte counts,
duties and fire ticks on every pre-existing session — so the fallback is
intact.

### Two things the work turned up

**Spindle `$`-settings take effect at controller start, not at the write.**
The core precomputes the S -> duty mapping once, when the spindle is
enabled; a settings write does not re-run it. After a runtime `$35=0` the
shipped duties stayed floored at 57/64/73/127. So `$35=16` set on the bench
earlier today persisted immediately and was reported by `$$` immediately,
but only entered force at the next controller restart — which the capture
work then supplied. The harness now models this the way an operator would:
one launch writes the setting, the next runs the job.

**A laser state change made while the stream is idle was lost — found,
root-caused and fixed.** Reproduced in both dose models, so it was not the
density model's doing: with a line-at-a-time sender and moves long enough to
drain the planner, `S100 / G1 X5 / S300 / G1 X5 / S600 / G1 X5` fired only
the first move and shipped duty 30 three times.

It was two faults wearing one symptom, and fixing the first exposed the
second. `gf_stream_laser()` dropped transitions while nothing was streaming,
so nothing re-asserted the state for the next run, which a run end leaves
dark — the stream engine now records the state the core last asked for
whether or not it is streaming, and re-asserts it at the first byte of the
next run, fire only inside an armed window (an abort clears it, so a closed
window can never be resurrected). With that in, all three moves fired, and
all three fired at duty 30: the level had never reached the driver at all,
because `spindleSetState` discarded its `rpm` argument. Per-segment updates
carry the level inside a laser block, but an S executed between blocks
arrives only through that synchronous path. It now publishes the duty, and
only the duty — fire stays where `spindleUpdatePWM` and its gates put it,
so the new path carries no consent to fire.

Rule 14 in the harness is the regression: the same standalone-S job must
show each level firing its own move. It does — 28338 fire ticks each at
duties 30, 52 and 84, where before the fix duty 30 held all 85014 and the
two other levels never appeared.

## 2026-08-17 — the density ladders, and the minimum pulse

Four live ladders on one piece of scrap, 8 rungs each from 5 % to 100 % of
dose at constant power: base period 20, 40 and 10 ticks at F300, then period
20 again at F100. The same six rungs marked every time — 20 % and up. 5 % and
10 % never marked in any of the four.

### Pulse length is not the variable; average power is

Because the same pulse length occurs at different densities across the
periods, the runs contain matched pairs:

| pulse | density | period | marked |
|---|---|---|---|
| 107–142 µs | 20 % | 20 | yes |
| 107–142 µs | 10 % | 40 | no |
| 36–71 µs | 20 % | 10 | yes |
| 36–71 µs | 10 % | 20 | no |

Hold the pulse and halve the density: the mark goes. Hold the density and
vary the pulse 3×: nothing changes. Feed does not move it either — 10 % at
F100 carries 0.0567 dose/mm against 20 % at F300's 0.0394, **44 % more energy
per millimeter than a rung that marks**, and it still left nothing. Two
independent variables moved without shifting the boundary. What sets the
low-end marking limit is average power reaching a quasi-steady surface
temperature; going slower does not help, because the heat conducts away
between pulses.

So the base period can be chosen on other grounds, and stays at 20.

### The trace separates two different failures

The F100 run carried the `hv_current` trace (`pthresh` printed one, `dladder`
did not until this run — the omission cost the three F300 ladders their
per-rung witness). It shows **seven** current segments for eight rungs:
boundaries at 36.6, ~52.0, 67.3, 82.5, 98.0 and 113.2 s, each segment
14.4–14.9 s, one 25 mm rung at F100. The fire window is 106.8 s where eight
rungs would need 121.6 s.

The final segment anchors the count: 113.5–128.4 s reads 943–986 dead flat,
the saturated steady current of continuous fire, which can only be 100 %.
Counting back, the segment means rise monotonically — 182, 320, 330, 390,
450, 540, 967 — for rungs 10 % through 100 %. Rung 1 has no segment at all:
its fifteen seconds are the zeros before 21.6 s, indistinguishable from the
arm wait because nothing happened in them.

| rung | outcome |
|---|---|
| 5 % | **no discharge at all** |
| 10 % | discharge for the full 15 s, no mark |
| 20 %+ | discharge and mark |

Supply current is not light — `pthresh` already showed this tube drawing
current across a whole band while emitting nothing — so "10 % struck" is not
"10 % lased". But 5 % not striking is unambiguous, and it is ours to fix.

### The factory's own numbers, for scale

Precision Power 1 runs the power byte at 127 (PWM duty 100 %) and a **FIRE
duty cycle of 19.53 %** — 1.371 on-ticks of every 7-tick window. Fitting the
three captures, the factory maps its entire 1–100 scale onto density
18.9–79.5 %, with Full Power off that line at ~99.7 %. Its "1 %" is the
bottom of the band that does useful work, not 1 % of the physical range —
which is why no user ever meets the dead zone. Older captured factory
jobs run 6.5–18.8 % density, so 18.9 % is a product
decision about cutting, not a physical floor.

### The fix: a minimum pulse width

At 5 % the model emitted one-tick stubs, 36 µs, and the supply did not
strike. The factory never emits below one 100 us tick and reaches low density
by skipping windows instead. `laser_pulse_min_ticks` (default 3 = 106 µs)
does the same: when the computed on-count falls below the minimum the period
is skipped and the **whole** debt carried, rather than a stub emitted. The
debt is conserved, so the average density is untouched.

Measured on the stream, level 2 (density 0.0159):

| | bursts | density |
|---|---|---|
| minimum 1 tick | 444 × 36 µs | 0.0158 |
| minimum 3 ticks | **147 × 106 µs** | 0.0159 |

147 × 3 = 441 against 444 — the same energy as fewer, longer pulses, and
every level already above the minimum is bit-identical, so the change touches
only what it must. Rule 15 in the stream harness holds both halves: no burst
below the minimum (excepting one clipped by fire going off mid-burst), and
the rendered density still exact.

### The fifth ladder, and a conclusion retracted

Same ladder, period 20, F300, with the 3-tick minimum in place. **The floor
moved down a full rung: only 5 % failed to mark, and 5 % now strikes.**

The trace carries eight current segments where the F100 run had seven.
Segmenting by time rather than by zeros — at 5 % density the sampled current
aliases, so isolated zeros appear mid-rung and cannot serve as boundaries —
the rung period is 5.25 s and lines up end to end: fire begins at 6.2 s,
exactly at rung 1's start, boundaries fall at 11.4, 16.6, 21.9, 27.3, 32.6,
38.1 and 43.3 s, and the span is 42.0 s against 41.4 s for eight rungs. The
final segment reads 937–981 flat and saturated, which can only be full
density. Rung 1 shows peaks of 291, 286 and 204 where the F100 run held a
flat zero for the rung's entire fifteen seconds.

**This retracts the conclusion in the entry above.** Pulse length is not
irrelevant: 10 % moved from no mark at F100 — with three times the dose per
millimeter — to a mark at F300, at the same density, the only change being
its pulses growing from 36–71 µs stubs to 106 µs. The matched-pairs argument
was sound but drawn entirely from comparisons at or above 20 % density, where
every pulse length in play was already sufficient; it generalized from the one
regime where pulse length does not bite. Above ~100 µs dose governs, below it
pulse length does, and below ~36 µs the supply does not strike at all. The
factory's 100 µs quantum sits exactly on that boundary.

Not read into: the low-rung current means (76 and 82 raw for 5 % and 10 %).
At those duties a 3.3 Hz point sample of a pulsed current carries
presence-versus-absence and nothing more. Noted as a confound, though it cuts
against the result rather than for it — this ladder started at MPos 0,0 after
the controller restart, so it may be on different material than the stacked
Y=0/24/48/72 runs.

### The sixth ladder: a longer minimum is worse, and why

`min_ticks = 6` (213 µs), same ladder otherwise. **It broke 5 % striking** —
seven current segments again, boundaries at 14.5, ~19.85, 25.2, 30.4, 35.9
and 41.1 s, segments 4.4–4.9 s with none double-length, fire spanning
9.5 → 46.0 s = 36.5 s against 41.4 s for eight rungs, and the flat saturated
tail anchoring rung 8. Seven rungs marked, matching.

The arithmetic explains it. Below the minimum the model emits `min` ticks
every `min/on` periods, so the interval between pulse starts is

    interval = min_ticks × tick / density

and **the base period cancels** — which retroactively explains why periods
10, 20 and 40 gave identical results in the first three ladders. At 5 %
density that is 2.26 ms at `min_ticks` 3, which struck, against 4.51 ms at 6,
which did not. Doubling the minimum doubles the gap as well as the pulse, and
the gap is what decides: the discharge is re-struck each pulse and past
roughly 2–4 ms it has decayed too far to catch.

That also puts `min_ticks` 3 at the factory's own operating point — its 6.5 %
engrave jobs place 100 µs pulses 1.54 ms apart, against 1.64 ms for
`min_ticks` 3 at that density — and puts 6 outside anything the factory does,
in the direction that fails. The bench is back at 3.

**Measured band for this tube: strikes from ~5 %, marks from ~10 % at F300.**

Which closes the pulse-structure route to a usable 1 %. The interval grows as
1/density, so 1 % implies an 11 ms gap, five times what already failed — no
pulse shape reaches down there. The low end is a scaling problem.

### The seventh ladder: the scale, and the goal met

`$35 = 10` — a density floor under this model, not a duty floor — with the
ladder reweighted to the bottom of the user scale (1, 2, 5, 10, 20, 40, 70,
100 % of S), since with a floor in place what matters is whether the lowest
levels a user can dial in still mark.

The mapping puts S onto 9.4–100 % density, so a commanded 1 % lands at 10.2 %,
just above the ~10 % marking floor the earlier ladders measured. **All eight
rungs marked.** The trace carries eight current segments — boundaries at 14.3,
19.5, ~24.85, 30.2, 35.4, 40.9 and 46.1 s, fire spanning 9.1 → 51.1 s = 42.0 s
against exactly 8 × 5.25 — with means climbing monotonically:

| rung | commanded | density | mean current |
|---|---|---|---|
| 1 | **1 %** | 10.2 % | 136 |
| 2 | 2 % | 11.0 % | 190 |
| 3 | 5 % | 13.4 % | 214 |
| 4 | 10 % | 18.1 % | 262 |
| 5 | 20 % | 27.6 % | 331 |
| 6 | 40 % | 45.7 % | 340 |
| 7 | 70 % | 72.4 % | 444 |
| 8 | 100 % | 100 % | 968 flat |

So the original goal is met: a user's 1 % is a real, visible mark rather than
silence, and 100 % is full power. It took the density model to make every
level real pulses, the minimum pulse to keep them strikeable, and the floor to
put the user's range on the band that works — the same three pieces the
factory uses, arrived at from this bench's own measurements.

### The defaults flipped

`laser_power_model` now defaults to `density` and `$35` to 10, so a stock
machine runs the model and a commanded 1 % marks. The analog path stays as an
explicit `laser_power_model = analog`.

The two settings are coupled and the pairing matters: `$35` is a **density**
floor under the shipped model and a **duty** floor under the fallback, wanting
~10 and ~16 respectively, and the wrong pairing is a dead band in either
direction. The arm warns on both mismatches — a zero floor under density,
where the bottom of the S range asks for pulses too far apart to re-strike,
and a sub-lasing floor under analog.

Test-side consequences worth noting, since the default reaches into the
harness: every analog session in `laser_stream_test.py` now selects its model
explicitly rather than inheriting it, or the flip would have silently turned
them into density runs and taken the analog fallback's coverage with them.
`laser_arm_test` asserts the inverse of what it used to — no config key now
means density — and `laser.power-floor` carries the new floor and its
PWMSAR minimum. All ten stream sessions, both C harnesses and the lifecycle
harness pass on the new defaults; the analog duties shift exactly as the new
floor predicts (min_value 12, gradient 0.115).

Owed: validation at a production feed. Every ladder behind these defaults ran
at F300 or F100 at constant power, so none of them exercised M4's velocity
scaling into corners, a real sender's mid-run level changes, or the raster
path, which has not run at all. The arithmetic says dotting will not be the
problem — at 10 % density the pulse interval is 1.07 ms, 35 µm at
2000 mm/min against a ~200 µm spot — but that is reasoning, not a cut.

## 2026-08-20: how the factory reports progress (F1)

The open question behind cloud-mode progress reporting was which carrier the
factory uses and how often: a `<action>:progress` event, a `progress_bytes`
query on the action endpoint, or the periodic settings report. The strings in
the factory binary named all three and settled none. It was answered by
observing the factory application's own cloud session on the machine, running
the factory slot end to end (a hunt, images, five motions, and a print with a
button pause and resume).

The answer is none of the three as posed, because two of them collapse into
one. Progress rides an **outbound WSS `type:"progress"` frame**, machine to
service, and that frame **is** the periodic settings report: its
`settings.values` block is exactly `periodic_settings_tags`. No
`<action>:progress` event and no `progress_bytes` query appeared in the whole
session. Cadence is `progress_update_interval_ms` = 30000, i.e. one frame every
30 s during a cut, with a burst at each phase transition; during the cut
`current` advances at the 10 kHz print tick.

Two things fell out of the same capture. `CCbp` in the frame reads the byte
position (1009 against a `current` of 994), re-confirming it as telemetry and
not the pause constant an earlier reading had guessed. And the factory's own
progress `total` grew during the cut, 33,291,208 → 33,553,352 → 33,815,496,
256 KiB per interval, because the factory live-appends to its ring: even the
factory's progress bar divides by a denominator that is still growing. Under
ForgeFIRM's streaming feed a progress report must divide by the feeder's own
job total, never the kernel byte counter. That is the F2 work; the carrier,
the frame shape and the cadence are now known.

The decision that came with it: the `type:"progress"` frame is carried as a
deliberate exception to the telemetry exclusion. It is a UI status update, not
the sensor firehose, and it is the operator's only sign a multi-hour print is
advancing. The write-up is in `CLOUD.md` ("Progress reporting" and the scope
exception); the plan's F1/F2 rows are updated. The pause is also reported by
the factory as a ten-event phase machine against the two ForgeFIRM sends, noted
there as optional polish on the F2 work.

## 2026-08-20: the campaign behind a print longer than the ring

The work that made a cloud print independent of the ring size ran from
2026-08-18 to 2026-08-20 and is finished, so the plan it ran from is retired
into this entry and the durable documents. What follows is how the result was
obtained, which is the part that does not belong anywhere else.

**It started from a wrong belief.** The ring was 16 MiB and a job that did not
fit was going to be refused with a clean message, on the reasoning that the
factory must refuse one too. Re-reading the factory application against the
Ghidra project said otherwise on every point. Its ring is 32 MiB, allocated
through `dma_alloc_attrs` out of a 320 MiB CMA area with no device-tree pool
and no module parameter. It models the downloaded body as a pulse data source
with a cursor, gzip or plain behind one vtable, and stages it into the ring in
segments that are checked against free space, refusing with `-ENOMEM` rather
than writing a partial chunk. And it does not stop when the ring is full: it
starts the job and keeps appending for as long as the job lasts.

**The proof was on the machine already.** This board's own factory logs, kept
across slot switches on the shared `/data`, carry a 107 MB job played through a
32 MiB ring. Nothing needed to be induced; the factory had already done it and
written it down. A capture of the factory's own cloud session later showed the
same behavior on the wire, its progress `total` growing 256 KiB per interval as
it appended.

**So ForgeFIRM streams too**, and the shape follows the factory's: hold the
compressed body in memory and inflate only as far as the ring asks, which keeps
a three-hour job to a few MB and off the eMMC entirely; fill the ring before
the button is offered, so a job that cannot be loaded fails before the laser is
ever armed; declare the live feed to the kernel only when the job actually
outran the ring, so a job that fits behaves exactly as it always did; top up on
`-ENOMEM`; clear the live-feed flag after the last byte, so the real
end-of-data is a completion rather than a starved ring. The ring itself moved
to 32 MiB, at factory parity, through a size-aligned no-map device-tree pool.

**Two defects surfaced in the building.** A dry ring used to end the run loop
with `aborted=False`, which reported a job that stopped mid-cut as completed;
it aborts now. And the pause on a streamed job could not retrace, because the
old bound deducted the retained gap from a budget that was zero under a
topped-up feed, counted bytes enqueued rather than bytes played, and set its
dead stop a whole program back instead of one ring back. The retained gap *is*
the backtrack history, which is what the kernel now publishes as
`max_backtrack`, and a request longer than that is refused rather than quietly
shortened.

**What the campaign settled along the way**, each recorded where it belongs:
the factory reports progress on a `type:"progress"` frame that is the periodic
settings report; `CCbp`/`CCbt` are reported progress rather than the pause
constants an earlier reading took them for; and `CFrh`, `CCwp`, `CCrp` and
`CCup` have no consumer in the factory at all, so there is nothing to drive a
warm-up or a rest off. The contract is `kernel-module-glowforge/UAPI.md`, the
client behavior is `CLOUD.md`, and the tag findings are in the firmware
reference alongside the captures.

**What it cost to be sure:** the pulse decoder was 41x too slow to keep a ring
fed (a `sorted()` per byte, 32 kB/s against the 1.33 MB/s it manages now), and
that only showed up when a real 53 MB job was replayed through a fake ring
rather than a synthetic one. The job that hung the bench is kept as the
regression fixture.

## 2026-08-21: a lid cancel that went back to the wrong place

`laser.pause-resume-lid-cancel` failed its first run on the dev image of
2026-08-21 with "head not back at the job start (drift 14.925 mm)", and at the
bench the job had looked right: the button paused the cut, the button resumed
it, the lid stopped it, and the head came back. It came back to the wrong
place. The kernel counters agreed with the controller's own position report:
Y exactly where the job began, X 14.925 mm along the first leg, which at F200
is about four and a half seconds of cutting, the moment the pause landed.

**The controller had told the truth by its own bookkeeping.** The driver takes
the job start as the machine position at the Idle to Cycle transition, and the
grblHAL core restarts a held cycle by passing through Idle: `state_await_resume`
sets Idle and then Cycle back to back, so every resume from a feed hold was
recorded as a new job beginning where the hold had stopped. The lid cancel then
returned the head to the pause point and reported "returned to the job start",
which was exactly what it had written down.

**The fix is a definition.** A job is under way from that first transition
until the core is Idle with the planner empty (the program ran out, a stop, a
reset) or in an alarm. A resume passes through Idle with the planner still
loaded, so it is the same job and keeps its start; a job abandoned in a hold
and reset is over, and the next one starts where it starts. Both sides are
held by the null-sink lifecycle harness now, which reproduced the bench
failure to the millimeter (returned to X=13.088, the pause point) before the
fix and returns to X=0.000 after it.

**Why the acceptance test caught it and the eye did not:** the test measures
the return against the position it recorded before the job, not against the
controller's message. An operator watching the head come back has no such
reference, and fifteen millimeters on a forty millimeter square reads as
"back". The test stays as it is.

## 2026-08-21: the first full campaign on a pin-file image

Completed. Dev image `20260821181036`, the first built on the
`<recipe>-pin.inc` layout: 42 of 42 satisfied (12 run on that image, 30
inherited under the domain model from the day's earlier dev images), all
eight `cloud.*` tests run on that image, and the export reads "Release authorized:
YES" for that image's manifest (campaign `c-20260821182204-dc01`, exported
2026-08-21T18:40:30Z, artifact sha256 `6f17f690...43273055`). No release is
cut from it.

## 2026-08-21: cooling.gate-off, first bench run

PASS on dev image `20260821210903`, campaign `c-20260821213027-0b47`, at
21:47:16Z: the coolant ceiling set to 6 C tripped `OVERTEMP` (hold, fire
blocked) one second into its run session; set to 60 C the next session read
`OK` with `gates_off` `["coolant_max"]` on `/cool/status` and `/status` and the
run-start line in the forgectrl log; restored to 33/31 the third session read
`OK` with nothing off, the settings back verbatim.

The first attempt on the same image (21:18Z) failed in the test, not the
engine: its M9 and the next M8 were 300 ms apart, the GRBL client reports
level-triggered at 1 Hz and the engine samples at 1 Hz, so the engine never
saw the session end and never re-read the ceiling; the restore-on-failure
then rewrote the file without opening a session, which left the bench
holding `OVERTEMP` against the test's ceiling until the next job. The fixed
test (forgefirm f274eb1) waits for the engine's phase to leave `run` after
every M9 and cycles a session after restoring; it was hot-deployed to the
board for this run and is in the next dev image.

## 2026-08-21: the job's limits pass through, seen on a live session

`cloud.pause-resume` PASS on dev image `20260821220926` (campaign
`c-20260821222752-4d93`, 22:30:52Z), the first print under the header
pass-through. The two logs together, from the same session:

- Every hunt and motion file the service sent carried a coolant window of
  10 to 50 C; the client derived `coolant_max_c=50.0 coolant_min_c=10.0`
  from each, and the engine answered `effective limits: coolant ceiling
  33.0 C (local 33.0, header 50.0)` with `header coolant ceiling 50.0 C is
  not stricter than the local 33.0 C; the local one stands`.
- The print carried `air_assist_min_rpm=116 coolant_max_c=33.0
  coolant_min_c=5.0` (the captured cut-job values: `AArx` 64500 us, `CMrx`
  33000, `CMrn` 5000); the engine resolved the ceiling at 33.0 (equal to
  the local one, so the local stands) and published the floors (coolant
  5.0 C, air assist 116 rpm, exhaust and intake 0) for the gates to come.
- At the job's end the limits left with it and the effective set fell
  back to local.

Two refinements from the run, neither a behavior change: the "not
stricter" notice printed twice per job (forgectrl e0b41b3 names it once per
value), and the test quoted the session's first job-limits line, a hunt's,
where the print's is the one worth keeping (it now takes the first line
after the print's action request).

## 2026-08-22: the fan floors measured, and a hunt that would have tripped them

`fan_floor_measure.py spinup` (bench page `fan-floor`, 120 s at the cut
profile from idle, GRBL mode, the exhaust duct's inline booster fan off, so
the exhaust worked against more back pressure than a normal cut):

| fan | steady rpm | min | max | sd | t90 |
|---|---|---|---|---|---|
| exhaust | 11638 | 11444 | 11947 | 103 | 5 s |
| intake 1 | 4157 | 4102 | 4193 | 12 | 7 s |
| intake 2 | 4158 | 4128 | 4173 | 6 | 7 s |
| air assist | 11048 | 11029 | 11061 | 8 | 1 s |

Purge current 627 at idle and 625 at run duty: the engine holds purge air on
continuously, so both are the "on" reading (the off reading, ~1, is from an
earlier observation). The floors shipped from this: exhaust 6400, intake
2290, air assist 6000 rpm (55 percent of steady, bands 50 to 60 percent),
purge current 300, grace 15 s (twice the slowest time to 90 percent). The
provisional floors had come from a snapshot at a lower exhaust speed; the
measured margin is larger.

The run also sent the first `/cool/status` with the limits and the fan rows
through a 512-byte reply buffer, and then a 160-byte limits fragment: twice
a cut-off document, found by the measurement tool refusing to parse it.
Both fixed in forgectrl with a host test that renders the widest legal
document and parses it (`tests/coolfmt_test.c`).

Reading the measurement through cloud mode found a defect in the gates as
first built: the service reports every action as a run, and its hunt and
motion headers command the exhaust and the intakes off and the air assist
at idle, so a hunt longer than the grace would have tripped `AIRFLOW` at
any floor. Decision (operator): a fan is judged only at the operating
point its floor was measured at: always while the laser is armed, when a
job's profile may raise a fan but never lower it below the run duty; and
unarmed when commanded at the run duty. A hunt is measured, published as
`unjudged`, and not judged. `cloud.mode-switch` now watches the connect-time
hunt's gate rows for it.

Both tests ran the same day on a hot-deployed forgectrl (the working tree
cross-built and installed over dev image `20260821230723`; informational,
not acceptance). `cloud.mode-switch` PASS: the hunt reported two run ticks
with the exhaust off and `unjudged`, verdict `OK` throughout.
`cooling.fan-gate-trips` FAIL first, for two reasons worth keeping: the
run-start tick resolved the effective limits before it reloaded the
settings, so for one tick `gates_off` named the exhaust while its row still
carried the old floor (fixed: the session start re-resolves the limits after
the reload, so rows, `gates_off` and the log line agree); and the test's
2 s grace, chosen against the provisional 1800 rpm intake floor, now let
both intakes trip at ~1850 rpm on their 7 s spin-up (the test grace is 8 s).
Rerun PASS in 59 s: only the exhaust tripped in the exhaust leg, only the
purge in the purge leg, the exhaust read `off` with floor 0 in the off leg,
and the restore showed every fan `ok` at the shipped floors (exhaust 11723,
intakes 4157 and 4162, air assist 11078 rpm, purge 628 counts).

## 2026-08-22: the measured floors and the operating-point rule on a pinned image

Dev image `20260822135848` (forgectrl 47e4256 pinned by forgefirm adcd1ad;
release `20260822135751` built alongside), flashed after a fetch-verified
both-image build. Campaign `c-20260822140659-2f25`, every auto test the
pin bump invalidated plus the rest of the non-operator, non-live catalog:
**18 of 18 PASS** (cooling.flow-verify, image.health, kernel.latch-locked-idle,
kernel.k1-k2, kernel.backtrack-bounds, forgectrl.auth,
forgectrl.settings-bounds, forgectrl.panel-serves, logs.tree-tail-export,
logs.level-settings, motion.deadman, cooling.fans-quiet-after-motion,
cooling.gate-off, cooling.fan-gate-trips, camera.sensor-profile,
camera.frame-health, cloud.mode-switch, kernel.fire-line).

The two that carry this change, as recorded: `cooling.fan-gate-trips` in
58 s with only the exhaust `TRIPPED` in its leg, only the purge in its,
the exhaust `off` at floor 0 in the same tick `gates_off` named it, and
the restore reading exhaust 11726, intakes 4160 and 4193, air assist
11095 rpm, purge 627 counts, every gate `ok` at the shipped floors;
`cloud.mode-switch` in 29 s with the connect-time hunt's run tick reading
the exhaust at 0 rpm, `unjudged`, the air assist `unjudged`, verdict `OK`
throughout, and the hunt finishing `:completed`. The hunt's run phase is a
few seconds long and gave one sample at a 1 s poll, so the watcher now
samples twice a second.

## 2026-08-22: the unplugged-exhaust-fan drill

The gate on the real failure path, not a settings override: the operator
unplugged the exhaust fan's whole connector at the Interconnect PCB (fan
dead, tach silent), the machine idle in GRBL mode, lid closed, nothing
armed. One `M8` session from the board, `/cool/status` read once a second
(dev image `20260822135848`):

- 1 to 14 s: every gate `grace` (the shipped 15 s), exhaust reading 0.
- 15 and 16 s: exhaust `under` at 0 rpm; intakes, air assist and purge
  `ok`, up to speed inside the grace.
- 17 s: verdict **`AIRFLOW`**, `fire_ok false`, `hold true`, exhaust
  `TRIPPED`, reason `AIRFLOW: exhaust 0 under the 6400 floor for 3 s -
  hold, no resume this job`; the other four fans held at run duty around
  the dead one. grblHAL relayed the reason on the Grbl port as a
  `[MSG:Warning: ...]`, and forgectrl logged the `WARNING` line.
- `M9` ended the session into the smoke-clear phase with the fault still
  named; the operator replugged the connector.
- The next `M8` session: exhaust 4112 rpm at 1 s, 6623 at 2 s (past the
  floor), 11640 at 7 s (the measured time to 90 percent), `ok` with every
  gate at the end of the grace, verdict `OK`, clean end.

One observation for a decision: between the two sessions the engine sat
at idle with the verdict still `AIRFLOW`, `hold=true`, `fire_ok=false`.
The fan fault latches for the run session and clears at the next session
start, the same shape as the fire alarm; at idle the hold cancels GRBL
jogs and the cloud client's print pre-check refuses a print before a
session could re-prove the fan (a hunt clears it). Decision (operator,
the same day): the fault ends with its session, since every session
judges every fan afresh after the grace before anything can fire;
`cooling.fan-gate-trips` now checks the verdict is `OK` with no hold once
the tripped session is over. The fire alarm keeps its idle hold. Built
and flashed the same day (dev image `20260822145201`, forgectrl d51dbdb):
`cooling.fan-gate-trips` PASS in 60 s, the engine reading `OK`, no hold,
fire allowed in the smoke-clear phase right after the tripped session.

## 2026-08-22: the coolant critical tier, on an image and on a rising loop

Dev image `20260822154257` (forgectrl a1875a8 pinned by forgefirm f51140e):
`cooling.critical-tier` PASS in 23 s. As recorded: the settings API refused
a critical line equal to the ceiling (`400 cool_temp_critical_c must be
above cool_temp_max`) and changed nothing; with the ceiling at 6 C, the
resume gate at 5 C and the critical line at 7 C under 24.3 C coolant the
session read `CRITICAL` (`fire_ok false`, `hold true`, no `resume_ok`,
reason `CRITICAL: coolant 24.3 C at or over the 7 C critical line - hold,
no resume this job`); after the session the ceiling alone held
(`OVERTEMP`); with the critical line at its top of 70 the gate was off
(`gates_off` naming `coolant_critical`, the run-start log line) and the
ceiling alone paused; restored, `OK` with nothing off.

The physical drill, `critical_tier_drill.py`, the same day. The loop heater
reaches the high twenties at most, so the lines were set a few tenths
above the live upstream reading (24.57 C: ceiling 25.0, resume 24.8,
critical 25.3) and the engine's own flow-check heater (100 percent, 300 s
windows, rechecks every 30 s, the suspect threshold at its top) warmed the
loop through them inside one `M8` session. Transitions, as sampled once a
second: `OK` at 24.1 C; `OVERTEMP` at 10 s with the upstream at 25.05 C
(`coolant 25.0 C over 25 C limit - hold until 25 C`); `CRITICAL` at 14 s
at 26.24 C (`fire_ok false`, `hold true`, relayed on the Grbl port as a
`[MSG:Warning: CRITICAL: ...]`). `M9` ended the fault and the ceiling's
`OVERTEMP` stood in the smoke-clear phase (upstream 27.7 C, downstream
49.7 C from the heater, which the session end switched off). Settings
restored and re-read in a short session: `OK`, limits back to 33 / 31 / 38.

One find, cosmetic: after the session the reason text still read the
critical line's message under the ceiling's verdict, because the ceiling
names itself only on its rising edge and the critical fault had overwritten
it. The engine now re-publishes the standing hold's reason when a critical
fault clears (no new log line), and `cooling.critical-tier` checks it.

## 2026-08-22: the board temperatures on an image, and a cross-check that bound too far

Dev image `20260822165832` (forgectrl 76115fd pinned by forgefirm 9fae47c):
`cooling.critical-tier` PASS; `cooling.gate-off` FAIL in its off leg: the
POST that sets the ceiling to its off end (60 C) came back `400
cool_temp_critical_c must be above cool_temp_max`, because the step 3
cross-check compared the default critical line (38 C) against the ceiling
wherever the ceiling stood. Under the settings rule every gate is off by
value on its own, so a ceiling at its off end is no ceiling and the
critical line stands alone as the fail tier: the cross-check now binds
only while the ceiling is a gate (its own table row's off end decides),
`cooling.critical-tier` pins that the off-end POST is accepted with the
default line, and the unit fake mirrors it. The test restored the
settings on its failure path as designed (the trip leg had passed: a 6 C
ceiling read `OVERTEMP` in 1 s). Rebuilt and flashed as dev image
`20260822174523`: `cooling.gate-off` and `cooling.critical-tier` PASS.

## 2026-08-22: the pulse-header envelope closed out

Dev image `20260822182931` (forgectrl b27398a, python3-gfhardware e65cfc2
pinned by meta-openglow 6bfd26e and forgefirm 4e0c90b), the close-out
image of the envelope work. Campaign `c-20260822183742-95a9`, every
unattended test: **18 of 18 PASS**, the same set as the 2026-08-22
morning campaign plus `cooling.critical-tier`.

What the new instrumentation said on the machine: `/status` `temps`
read chassis 29.9 C, SoC die 44.0 C, supply 602 raw, throttle state 0 at
idle; the run-end line after a session read `temps this job: chassis
26.8..26.9 C, soc 36.6..37.1 C, supply raw 549..553`; and the cloud
client's connect-time hunt logged `79 of 101 header keys have no applier
here (30 declared ignored, 49 undecided)`. The 49 are the families the
disposition table calls undecided (the client's network backoff, the air
filter's fans, the camera exposure and gain values, the per-phase idle
variants of the limits), named at debug level by every job; the number is
recorded here so the next decision on them starts from a measurement.

The first build of this image ran on a stale layer: the launch's shell
session closed while the source sync was still copying, rsync took the
hangup, and meta-openglow stayed one commit behind (the old gfhardware
pin). The build was stopped, the tree synced and every moved pin checked
in it, and the build relaunched detached; the image manifest carries all
three components at the intended commits.

## 2026-08-22: the operator's part cut down, and the first campaign with it

Dev image `20260822204234` (forgefirm de324cc packaged forgetest, the
pins unchanged from the envelope close-out), the first image with the
catalog as rebuilt for fewer hands: every attended test asking for its
operator's part by name (Ready prompts before timed steps, standing
notices the test takes down when the machine shows the action done,
one confirm by eye left), `cloud.mode-switch` carrying the lid-open
hunt and the web-service homing, and `kernel.fire-line`,
`camera.snapshot` and `motion.jog-roundtrip` run unattended.

Three bench findings, all in the harness, none in the machine:

- `motion.jog-roundtrip` failed its first run on the accelerometer
  witness: the sysfs read lands two or three samples in a one-second
  leg, and two samples on the constant-velocity stretch read near idle
  with the head in full flight (the accelerometer sees the ramps, not
  the travel); where a ramp was caught the head was plainly moving (p2p
  3019, 1330, 1698, 1663). The verdict became the whole sequence (p2p
  across the eight legs at or above the liveness threshold, motion on at
  least two distinct legs). Rerun: p2p 2897 over 17 samples, motion on
  three legs. forgefirm 9139e92.
- `laser.arm-wait-lid` failed its first run on "the button is still
  lit": the cancel had relocked, disarmed and emitted nothing, but the
  check read the LEDs' `brightness` the instant after, and the smooth
  trigger fades it; the controller writes `target`. The readback is the
  commanded level now, with a few seconds for it to land. forgefirm
  296fd68.
- The operator's campaign showed `cloud.oversize-stream` and
  `cloud.pause-cancel-paths` both cancelling a print from the app. The
  app cancel stays in the oversize test, which has to end that way, and
  is judged in full there; the other became `cloud.paused-lid-cancel`,
  one print instead of two. Same commit.

Those fixes showed the catalog's implementation hash for what it was: a
whole suite file, so a two-line fix in `laser.py` re-required every
laser test and the cloud rename every cloud test. The hash is now the
test's own function plus the module's code outside the `@test`
functions (forgefirm 2547a8e), every recorded fingerprint moved once,
and the campaign was run from nothing on the board's installed copy of
that tree (the six changed files verified identical to the commit).

Campaign `c-20260822220701-a1c0`: **43 of 43 PASS, nothing inherited,
release authorized**; 29 minutes of test time in all, the 16 attended
tests 19 minutes of it (22:16 to 22:46 UTC) against the catalog's own
111-minute estimate for the attended set before this work. No release
cut. What the witnesses read on the machine: the head accelerometer
p2p 4206/2442 over 17 samples across the jogs, motion on four legs; the
beam detector idle 1864, peak 2364 during the emission witness (delta
500 against the 300 the test asks, digital flag seen), 479 during the
pause/resume/lid cut; the lid camera 98.8 kB lit against 49.5 kB with
the lamp off; the cloud round trip's hunt `:completed` with the lid
open and gfhome's `homing complete (service quiet 10s, 6 motion
windows)` 40 s after `$H`. Every one of the 74 machine actions the
campaign asked for was performed by the operator and recorded so in
the evidence; a bench actuator, when there is one, takes the same
calls.

## 2026-08-22: the machine's print behavior without the service

Dev image `20260822232347` (forgefirm 628f2f7; python3-gfutilities 768730e
and python3-gfhardware a3ca36f pinned by meta-openglow a52e68c and the
forgefirm-app pin), the first image with the offline service: gfcloud
restarted under the `/run/gfcloud-offline` marker comes up with no
account and no network, takes the service's action messages on
`/run/gfcloud-offline.sock`, and hands the machine's events back. Four
cloud tests run on it with a job synthesized on the board
(`forgetest/puls.py`: a factory print's header over a square the laser is
never commanded on): the lid and interlock aborts, the button-wait
cancel, a paused print ended by the lid, and a print longer than the ring
ended the way the app ends one. Nothing on the bed; the arm press is the
operator's only hand on a print.

Before the operator's run the plumbing was dry-checked from a shell:
stop, marker, start, the `OFFLINE service` line and the socket, a
`settings` action answered `settings:completed`, then a restart without
the marker and the web session `ready` again. One lesson from the dry
script, not the harness: the marker has to stay until the offline line
is logged, because the supervisor reports the client running seconds
before Python has finished importing and read it.

Campaign `c-20260822233344-08de`: 30 of 43 inherited across the pin bump
(the catalog's covers put every `cloud.*` test on the moved components,
and the core always runs), **13 run, 13 PASS, 43 of 43, release
authorized**; 11 minutes of test time, the four offline tests 5.5 of it.
No release cut. What the machine said under the offline service: the
lid edge to the stop 10 ms; the button-wait cancel with no run started;
the paused print cancelled by the lid, parked to the job start, latch
locked, button dark; the long job (33.4 MiB of ticks in an 87 kB gzip)
live-fed with the kernel's program total climbing 33.29 to 34.60 MB while
the report divided by the job's 35.0 MB, no underrun, the backtrack held
at 164 214 steps, the pause and resume taken, and the cancel's tail the
same as the lid's. Every print's `print:running`,
`print:return_to_home:succeeded` and `print:cancelled` came back over
the socket. The real service was still proven on the same image by
`cloud.mode-switch` and the one real print, `cloud.pause-resume`.

## 2026-08-23: the service protocol proven by the emulator, and the hunt paid only where it is the subject

Three dev images in one day, each a campaign, the last one full and
clean.

**Dev image `20260823002125`** (forgefirm 4c9dcca, python3-gfhardware
12ad3b1 pinned by meta-openglow a4e3abf, the first image with the
`python3-gfutilities-emulator` fixtures) carried a layer change, so every
test was owed. Campaign `c-20260823140444-80ae`: the 27 unattended tests
passed in 10 minutes. Before the operator's part, the emulator path was
dry-checked from a shell the way the offline one had been, and it caught
a defect the host replays could not: the session came up (sign-in, the
firmware check, the WebSocket ready) and the service sent `settings` and
nothing else. The real client's hunt lands 1 to 2 s after `ws_connect
ESTABLISHED`; the emulator waited minutes. `build_emulator` had set
`EMULATOR.BYPASS_HOMING`, which makes gfutilities answer the settings
request with `"settings":{}`, the reconnect form the service answers by
keeping its head position and skipping the hunt. The fix (gfhardware
b7e8035: the report carries the values; a host test proves it red on the
old flag) was hot-patched on the bench for the rest of the dry-check: the
hunt landed 1 s after the settings report and completed; the service was
satisfied after two home frames and one motion (the real client takes
four frames and three motions); the app showed Ready; a Print from the
app reached the emulator 7 s later, behind a pre-print motion pair and a
`lidar_image` request the emulator answered, and downloaded (20 KB
gzip, 643 KB of pulses, a 134-tag header, STfr 10000) and completed. The
shipped file was put back and the real client restarted before anything
else ran.

**The operator's change, before the next image:** a mode switch from GRBL
to cloud costs the service's connect-time hunt, and during cloud
development those add up. gfcloud gained `--no-hunt` and the one-start
marker `/run/gfcloud-nohunt` (gfhardware 351a623): the first settings
report goes out in the reconnect form, which is what the factory client
does on every reconnect within a session. With it, every one-start marker
is now read and taken down by the client itself, first thing, before the
imports that take seconds on this board, so a respawn never inherits one
and a writer can move on once the supervisor reports the client up.
forgetest (forgefirm 969bac6) sets the marker for every cloud client it
starts except where the hunt is the subject: `cloud.mode-switch` and
`cloud.service-protocol` keep theirs, and so does the one real print,
since `enter_cloud` now reuses a running session only when that client
has hunted the machine itself (`session_hunted`: never the emulator's
session, never a no-hunt start) and otherwise restarts the client with
the hunt. The decision, the operator's: all starts skip the hunt but
those three. The hazard it leaves, written into ACCEPTANCE.md: a machine
a campaign leaves in cloud mode may not have hunted since GRBL mode moved
the head, so a lid cycle or a controller restart before printing from
the app.

**Dev image `20260823153019`** (forgefirm 908e0c7, gfhardware 351a623 by
meta-openglow 9e988b5). The pin-file mechanism held across the bump: 21
tests inherited, the 6 always-required core tests ran (76 s), and the
operator took the attended block: the four motion tests, the five laser
tests, `camera.lid-privacy` and `cloud.mode-switch` passed, and
`cloud.service-protocol` ERRORed on its first line, `forgectrl POST /mode:
timed out`. Two defects, one each side. forgectrl's mode switch answers
only after the new controller's first job-state report to the cooling
engine, 15 s without one; the real client reports within seconds of its
machine coming up, and the emulator never reported at all, so the answer
came at the deadline, past forgetest's 10 s client timeout (the dry-check
had used curl, which has none, and so never showed it). The emulator now
runs the same idle, unarmed 1 Hz reporter as the hardware machine
(gfhardware 537d0db), and forgetest gives the supervisor's three levers
(`/mode`, `/controller/start`, `/controller/stop`) a 120 s timeout, above
the daemon's own waits (forgefirm ab0a515).

**Dev image `20260823161333`** (forgefirm 8379aa5, gfhardware 537d0db by
meta-openglow 730db53). Campaign `c-20260823161923-0dd7`: 29 inherited,
the 6 core tests in 74 s, then 9 attended: the emission witness,
`camera.lid-privacy`, `cloud.mode-switch`, `cloud.service-protocol` (68 s:
the session, the hunt, three image uploads, a print from the app
downloaded with its 134-tag header and completed against the real
service with nothing behind it, then the real client back in 14 s under
`NO-HUNT` with no hunt), the four offline tests, and the one real print,
`cloud.pause-resume`, which found the offline client running and started
a fresh one with its own hunt before printing, as the rule requires.
**44 of 44, release authorized**, 868 s of attended test time. No release
cut. The offline client is what a campaign now leaves running in cloud
mode; the next thing that needs the service restarts it.

What this closes: the cloud split of the acceptance plan is complete.
The service protocol is proven by the emulator with only the app to
drive, the machine's print behavior by the offline service with nothing
on the bed, and the two together by one real print. Still open from that
plan: the bench actuator for the lid, interlock and button, and the
finer coverage maps.

## 2026-08-24: the GPU demosaic's first light, and what the probes caught

Dev image 20260824122014 (the first with Mesa etnaviv; release ext4
204,140,544 bytes, ~5 MiB under the slot cap) flashed by the operator;
the drill ran forgectrl builds from `/tmp` against the running image,
each iteration probed over the stream, `FORGECTRL_GPU_CHECK`, and frame
captures diffed against the CPU demosaic on the host.

Five faults found and fixed in one session, each named by a probe log
line or the compare (forgectrl 6614833):

1. `eglChooseConfig` returned nothing: EGL_SURFACE_TYPE defaults to
   WINDOW_BIT and the surfaceless platform has no window configs. Ask
   for surface type 0.
2. Every fourth output byte was 255: the render engine writes an
   XRGB8888 surface's undefined X byte as opaque. Render ARGB8888.
3. The raw import failed etnaviv's stride check (width padded to 16
   texels): 2592 bytes is 1296 GR88 texels exactly, not 656 padded
   XRGB ones. Import GR88, one texel per Bayer pair.
4. The GPU cannot write the CODA's buffers at all: 64-byte render rows
   versus round_up(width,16) strides never meet at these widths. New
   `ipu_copy` module: render into the IPU CSC/scaler's wider source
   (stride align(w,128)) and let the IPU crop into each encoder over
   dmabuf. 14 ms a copy, no CPU touch.
5. The chroma mirror used a quarter-width plane where the plane is
   half-width: the right half of both chroma planes clamped to
   column 0. The three-frame diff-by-transform analysis on the host
   named both this and fault 2.

End state on the bench: `convert: "gpu"` serving MJPEG, the GPU/CPU
compare clean to 2 counts except the bottom row (1296 samples, max
delta 134, unexplained); `/cam/h264` delivering valid fragmented MP4
from the CODA BIT processor (avc1.424020, ~480 kbit/s on the static
bed). Open, measured: the render costs 140 ms a frame against the IPU's
14 (GPU at its full 528 MHz - the suspicion is pre-HALTI linear-texture
sampling), so the GPU path holds ~6 fps until that is run down. The
`getenv` implicit-declaration fix in debayer.c rode along. Bench left
clean; stock service restored.

## 2026-08-24: the render run to ground, and the chroma box paid for

Second session on the flashed fixes (dev 20260824131335, drills from
/tmp, forgectrl 2d59d78). Findings by measurement:

- The GPU has LINEAR_TEXTURE_SUPPORT (minor_features1 bit 22 read from
  debugfs), so Mesa samples the imported buffers directly: no shadow
  copy, and no risk of the seqno-gated shadow going stale under
  external DMA - a hazard that was checked for and does not exist here.
- FORGECTRL_GPU_PASSES decomposed the 140 ms render: 41 ms for luma,
  49 ms per chroma pass. The chroma box filter (four superpixels, 32
  dependent fetches per fragment) was the cost, sixteen times the
  per-fragment price of the luma pass.
- The chroma passes now point-sample the block's top-left superpixel:
  render 64 ms, stream ~9 fps at ~7 % daemon CPU (NEON: 15 fps at
  41 %). Luma stays bit-clean against the CPU path (max delta 1, zero
  samples off by more than 2), and the first session's bottom-row
  artifact went with the old chroma pass. Chroma against the box
  reference reads mean 1.7 on the bench scene: detail, not error.
- CSI hardware frame skip proven with the GPU path:
  FORGECTRL_STREAM_FPS=7 programs keep-1-of-2 in the receiver,
  hw_fps_skip true, steady ~7 fps, the daemon sampling 0.0 % in top.
  The loop split at rest: wait 26, render 64, IPU copy 14, encode 7 -
  15 fps needs the render overlapped with the previous frame's encode,
  recorded as the item-20 remainder.

Bench left clean; stock service restored.

## 2026-08-24: the pipeline goes two frames deep

Third session, on dev 20260824133616 (drills from /tmp, forgectrl
deee6a1). The serialized loop (wait 26, render 64, IPU copy 14,
encode 7) became a two-frame pipeline: a frame's render is kicked
behind an EGL fence and the previous frame's finished render is
cropped, encoded and published while it runs. ipu_copy keeps two
source buffers so the rendering and the copying frame never share one;
the rendering frame's capture buffer stays out of the queue until its
fence clears, and every teardown, failure and frame-health queue cycle
settles the in-flight state first.

Measured: 13.8 fps single-viewer (from 9.2), fence stall 7-9 ms
against the 64 ms render - the render is hidden behind the copies,
the encodes and the frame wait. Daemon ~14 % CPU at that rate with a
WiFi viewer attached (the NEON path: 15 fps at 41 %). MJPEG and H.264
served together run 9.8 fps with the stall at zero (two IPU copies and
two encodes per frame, 33 ms, all still off-CPU). Luma stays bit-clean
against the CPU demosaic; H.264 fragments now carry the delivered
frame's timestamps. Bench left clean; stock service restored.

## 2026-08-24: the browser plays it, and the head moves under it

Fourth session, on dev 20260824140057 (the shipped image runs the
pipelined GPU path stock: convert gpu, 13.6 fps, before any drill
binary). Chrome driven against the panel found what byte-level checks
could not:

- The video element buffered data at t=801 s while playback sat at
  zero: the fragments carried the raw 90 kHz boot clock. Each viewer's
  fragments are now zero-based (the mux context subtracts the first
  frame's clock).
- The live-edge chaser's fixed 0.2 s back-off overshot the one-frame
  buffered window into a gap and the element stalled at readyState 0;
  the seek now clamps inside the newest buffered range, and a paused
  element is kicked back into play after a seek.

With the fixes (forgectrl d97cb35, drill from /tmp): the panel's Live
button plays H.264 over MSE at 1296x972, timeline from zero, no MJPEG
fallback, verified by script and by eye in Chrome.

Coexistence, with the H.264 view live in the browser AND an MJPEG
viewer attached: a jog out (+X 5 mm F600) and back completed at its
commanded feed (mid-status Jog, MPos 3.619, FS 600; end Idle at
origin), the step ring's underrun counter read 0 before and 0 after,
and the planner buffer never left 99-100. The GPU stream path and
motion coexist. The laser latch stayed locked and emission dark
throughout; no armed anything.

What remains of the video offload: the full acceptance campaign on an
image carrying d97cb35 (a platform change: Mesa joined the image), and
first light of all of it on an 8 MP machine when one exists. Bench
left clean; stock service restored.

## 2026-08-24: the kernel built for one board

A read-only review of the running kernel (config, dmesg, bindings,
module tree, image manifests) found the multi-board defconfig doing
what multi-board defconfigs do: USB, Ethernet, CAN, Bluetooth, SATA,
PCIe, NAND, audio, a display stack, touchscreens, ten other i.MX SoCs
and 153 DVB modules, none with a node in the device tree or a driver
bound. Two real defects sat among them: `evbug` autoloading for the
switch block and logging every lid and button transition to the
kernel log, and the fragment's hung-task and soft-lockup panic lines
silently dropped because their detectors were off, so only
`PANIC_ON_OOPS` stood behind the laser-safing notifier. No crash
record existed either: `panic=10` rebooted and the reason left with
it.

The fragment was rewritten as the board's driver set plus the
defconfig's leftovers turned off, and the machine conf names the
modules and firmware the rootfs carries. The first configure pass
taught what the defconfig never says: `PM`, the regulator core and
`EXT4_FS` only ever arrived by selection from suspend, the PMICs and
ext3, so they are pinned by name now. Built into dev 20260824164619:
zImage 9.13 MB to 4.76 MB, kernel-module packages 254 to 31,
`/lib/firmware` down to the WL18xx set and the DualLite VPU blob,
ARMv7-only code, no virtual console, ramoops in the 1 MiB the factory
bootloader already holds back at the top of DRAM, and ecspi2 without
`dmas`, so the pulse ring is the SDMA's only client (the ROM scripts
stay; the RAM firmware never loaded and no client here needs it).

On the bench, fresh boot of that image: every node binds and nothing
defers; `hung_task_panic` and `softlockup_panic` read 1, `panic` 10;
`/sys/fs/pstore` mounts and ramoops registers at 0x2ff00000 with ECC
(the ten "uncorrectable error in header" lines are the never-written
region's first initialization, expected once); `/dev/dri/renderD128`
present and both cameras streamed through the GPU demosaic
(`gpu: GLES2 debayer up` for lid and head, GPU interrupts 0 to 135,
snapshot 200 OK); Wi-Fi associated with the regulatory database
loaded; the switches on `event0`; 31 modules loaded, `evbug` gone; no
DMA channel held by anyone. MemTotal rose by 9.4 MB. Two new dmesg
lines, both cosmetic: spi-imx reports the absent DMA channel at ERR
level and continues in PIO (the PIC probes and reads), and
`consoleblank=0` is now an unknown parameter without a virtual
console. `cannot start cut; no data enqueued` at 31 s is not new (47
earlier occurrences in the kernel log).

The crash record, proven the direct way: `echo c > /proc/sysrq-trigger`
panicked the kernel, the ten-second timeout rebooted it, and the next
boot logged no header errors and mounted `/sys/fs/pstore` holding
`dmesg-ramoops-0` (24 KB, "Panic#1 Part1", the kmsg buffer from
"Booting Linux" to the panic) and `console-ramoops-0` (23 KB, ending
"sysrq: Trigger a crash / Kernel panic - not syncing / Rebooting in
10 seconds.. / ECC: No errors detected"). A panic now leaves its
reason where the next boot can read it.

Still owed: a GRBL job on the image, the acceptance campaign (platform
change), and the `spi_device_id` table for `glowforge,pic`, which
rides the module's next pin bump. Bench left clean.

## 2026-08-24: the second kernel round, on the bench

Dev 20260824200726, cold boot after the flash (the pstore region came up
empty and re-initialized its headers, as a power cycle must). The dmesg
lines the round set out to remove are gone: no spi-imx "can't get the TX
DMA channel", no `consoleblank` in the unknown-parameter list (only
`board=`, which userspace reads), no "cannot start cut; no data enqueued"
(grblHAL treats that run-on-empty-ring race as ordinary; the module now
agrees), no `spi_device_id` warning (the pinned module carries the
table), no "unconfigured mac address in nvs". One line took its place:
with no NVS on the rootfs the firmware loader reports the missing file
at ERR level; patch 0015 asks for the optional file the quiet way and
rides the next build.

The kernel is UP: `nproc` 1, no IPI rows, the TWD still the tick and the
GPT the clocksource. The performance governor is the only one and the
core reads 996 MHz. Wi-Fi associated on `wl18xx-fw-4.bin` with
`wl18xx-conf.bin` beside it and nothing else in `ti-connectivity`; PG 2.2
silicon, firmware 8.9.0.0.83, regulatory database loaded.

IPv6: the kernel took the router advertisement (link-local, a ULA by
SLAAC, the ULA and GUA prefix routes, the default route) and `udhcpc6`
ran from the `wlan0 inet6` stanza. It got no address: the DHCPv6 server
answered every Solicit with an IA_NA carrying only a status option (18
bytes, which busybox reports as "IA_NA option is too short"), which is
NoAddrsAvail; the GUA prefix is advertised on-link without the
autonomous flag. So the board has a routable ULA and no GUA until the
network hands one out; the client side is doing its part. Every service
answered over IPv6 on the ULA from the board itself: sshd (banner),
grblHAL TCP:23, forgectrl :8080 (200), forgetest :8090 (200);
`netstat` shows all four on `:::`. This host sits on another IPv6 LAN,
so cross-network reachability was not testable from here.

The rootfs: nano and `file` present on the dev image, the udev hardware
database gone, `cryptography` not importable while `urllib3` and
`requests` import; `/lib/firmware` down to the WL18xx pair and the
DualLite VPU blob. A sanitized log export ran (200, 1.9 MB) with the
`system/` snapshot in place; the `system/pstore/` directory appears only
when records exist, and after the cold boot there were none. Memory
475 MB total, 325 MB available at idle in GRBL mode.

Owed: the NVS line (patch 0015, next build), the item-16 drill on this
kernel, the campaign. Bench left clean.

## 2026-08-24: the second DHCPv6 responder

Dev 20260824201945 (patch 0015 in): the NVS loader line is gone; the
rest of the second round holds. The missing GUA was not the firewall's
doing. Its DHCPv6 server was enabled, in Managed RA mode, with a pool on
the delegated /64, and a packet capture on the bench VLAN showed it
answering the board's Solicit with an address 1.3 ms later. The board's
Request went to a different server-ID (a UUID) with `NoAddrsAvail`
echoed back. A raw sniff on the board's own link named the other party:
one of the VLAN's three OpenWrt access points still ran its LAN-side
defaults, RA in server mode (its own ULA prefix with SLAAC, M and O
flags, itself as DNS) and a DHCPv6 server with nothing to hand out. Its
unicast Advertise beat the firewall's, and busybox's `udhcpc6` keeps the
first Advertise it sees and keeps Requesting from that server, which is
where the "IA_NA option is too short" line came from (an IA_NA carrying
only a status code). The other two access points have RA, DHCPv6 and
NDP-Proxy disabled, which is the setting that belongs on all three. The
ULA the board carried all along was that access point's. Nothing on the
board needs to change; the network side owns the fix.

With RA and DHCPv6 disabled on that access point, the next Solicit took
the firewall's lease: a global address on wlan0 (a /128 with the lease
as its lifetime, renewed on schedule), sshd, grblHAL TCP:23, forgectrl
and forgetest all answered on it from a host on a different VLAN, and
the board reached the IPv6 WAN gateway. IPv6 is on end to end; the
stale ULA ages out with its own lifetime.

## 2026-08-24: the SDMA clocks, held by nobody

The first campaign on dev 20260824201945 (`c-20260824204310-6b6d`) stalled
on `image.health`: the pre-baseline waited its full 150 s for
`motion=verified`, which forgectrl never reported, and the test then
failed on `cnc/free 35618816 exceeds the ring less its 32 KiB gap`. The
forgectrl log had the shape of it: `liveness probe: ERROR - cannot start
the probe run` at every controller spawn on every boot since the first
kernel-trim image (164619), and `MOTION OK` with a healthy p2p on every
boot before it, the last at 17:47Z on 161618. The kernel log had nothing,
because the one line that would have said so had been demoted to
`dev_dbg` the same afternoon on the belief that it was grblHAL's benign
race.

The ring's own readbacks named the fault. `cnc/position` read X =
0x200000 steps on a machine that had not moved (forgectrl showed 39321.60
mm), the head index sat 2 MiB ahead of the tail on an idle ring, and
scratch6/7 read back the script's constants (the 0x01ffffff index mask
and the PWM sample-register address), which is the start of the channel
context, not its scratch registers. Every context fetch was returning the
bounce page as last written, not SDMA memory. `/sys/kernel/debug/clk/sdma`
confirmed it: `clk_enable_count 0`, prepare 1, the engine unclocked.

The mechanism: imx-sdma enables the engine's `ipg` and `ahb` clocks only
in `sdma_alloc_chan_resources`, for a dmaengine client, and disables them
at the end of probe. glowforge.ko takes channel 26 through the SDMA API
patch's `sdma_get_channel()`, which returned `&sdma->channel[ch]` and
nothing more. Until the trim, spi-imx on ecspi2 held two SDMA channels
and so held the clocks; the pulse engine had run on that accident since
its first image. The round-1 device tree deleted ecspi2's `dmas` on
purpose (the ring as the only SDMA client), and took the last clock holder
with it. With the block gated a channel-0 transfer completes at once and
moves nothing: the script load, the context load, the head sync and the
position fetch all "succeed"; `cnc/run` sees head == tail right after the
tail publish and returns -ENODATA; grblHAL treats that as its ordinary
race and carries on idle; `verify_sdma_script` passes by construction,
because the write copies the script into the same bounce page the read
returns. The "47 earlier occurrences" of `cannot start cut; no data
enqueued` on 164619 and the "no DMA channel held by anyone" observation
were this fault, read as noise. The SDMA RAM firmware is not involved: it
never loaded on any image.

The fix, and what proves it so far: `sdma_get_channel()` enables both
clocks and a new `sdma_put_channel()` releases them (patch 0003 and the
API header); the module calls put in remove and in the probe unwind; the
empty-ring run request logs at ERR level again; `image.health` asserts
`clk_enable_count >= 1` directly, ahead of the 150 s settle it would
otherwise wait out. The ecspi2 `dmas` stay deleted. Host-proven: the
patch round-trips against the kernel tree with 0008 on top, the kernel
object compiles with no new warnings, the module compiles under `-Werror`
(its modpost waits on the rebuilt kernel's export), the module's host
tests and the 270 forgetest tests pass. Owed: the image, then on the
bench `clk_enable_count` reading 1, `MOTION OK` from the probe,
`cnc/free` at 33521664 idle, a GRBL job, and the campaign.

## 2026-08-24: the clocks proven, and the listener that heard nobody

Dev 20260824215906, built with the SDMA clock fix, on the bench: `sdma`
`clk_enable_count` 1, the supervisor's probe `MOTION OK` (p2p x=3390
y=1720), `/mode` verified, `cnc/free` 33521664 at idle, position 0.
Campaign `c-20260824223050-0356` (36 unattended, the fixture in the loop):
`image.health` passed in seconds with its new clock assertion, and every
kernel, forgectrl, logs and motion test passed, `motion.liveness-probe`
and `motion.button-hold-resume` among them. `cooling.flow-verify` passed.
`cooling.fans-quiet-after-motion` failed: `M8 did not raise the fan duty
off idle`.

The engine had heard nothing. `/cool/status` showed `report_age_s` -1 for
the controller the supervisor had just respawned, and a hand-sent
`POST /cool/state?mode=idle` from 127.0.0.1 answered `403 loopback only`.
The listener is dual-stack since the second kernel round (`:::8080`), so
every peer arrives as a `sockaddr_in6`, the IPv4 client as
`::ffff:127.0.0.1`. forgectrl's check handles that spelling; ulfius 2.7.15
does not hand it over: `src/ulfius.c` allocates and copies
`client_address` as `sizeof(struct sockaddr)`, 16 bytes, which holds the
family, the port, the flow label and eight address bytes. The mapped
prefix and the 127 sit at bytes 10 to 12 of the address, past the copy,
in heap the check should never have read. Every report since dev
20260824200726 was refused the same way; nothing ran the cooling tests on
those images until now. The direction was safe: the engine treats silence
as a stand-down, so no run profile, no armed window, no fire.

The fix and its proof so far: the image carries a ulfius patch (a
`sockaddr_storage` allocation, a copy of the family's length, in the
dispatcher and in `ulfius_copy_request`); the recipe builds it clean under
ulfius's own `-Werror -Wconversion`. The peer check moved into
`forgectrl/src/peer.c` unchanged in meaning, with `tests/auth_peer_test.c`
in CI: 127/8, `::1` and mapped 127/8 pass; LAN addresses in both families,
a mapped LAN address, link-local, unspecified, `AF_UNIX`, NULL and a
`::ffff:127.0.0.1` cut to sixteen bytes are refused. forgectrl cross-builds
under `-Werror`. `forgectrl.auth` now asserts the loopback acceptance
(200) next to the LAN refusal (403), so a listener that truncates the
peer fails the catalog on the first forgectrl test rather than the first
cooling one. Owed: the image, the loopback report accepted on the bench,
the campaign.

## 2026-08-24: the listener heard, and the campaign ran through

Dev 20260824230512 (the ulfius peer patch, forgectrl 78efd16 with
`src/peer.c`, the SDMA clock fix underneath) on the bench 54 s after
boot: `POST /cool/state` from 127.0.0.1 answered 200 and the same report
from the board's LAN address with the token answered `403 loopback only`;
`/cool/status` showed `report_age_s` 0.1 from the freshly spawned
controller; the SDMA clock count 1, the probe `MOTION OK` (p2p x=1879
y=1906), `cnc/free` 33521664. Campaign `c-20260824231028-b7ca`, the 36
unattended tests with the fixture in the loop: 36 passed in 13 minutes,
`forgectrl.auth` with its loopback assertion, `motion.liveness-probe`,
`cooling.fans-quiet-after-motion` (the fans up on M8 through the accepted
channel, quiet again within the cooldown), the fan-gate trips, both
unattended laser tests, the cameras, the update slots and the two cloud
tests. Nothing inherited: the image is a platform change twice over. The
nine attended tests (four laser live, five cloud) stand between this
image and an authorized release. The bench was left in cloud mode on the
offline client, as the cloud tests leave it; nothing of the session's on
the board.

## 2026-08-24: the attended nine, and a release authorized

The operator ran the nine attended tests on dev 20260824230512 after the
unattended 36, in one sitting: `laser.emission-witness` (23:25Z, 33 s),
`laser.disarm-in-hold` (83 s), `laser.armed-kill` (66 s),
`laser.pause-resume-lid-cancel` (31 s), `cloud.service-protocol` (65 s),
`cloud.lid-interlock-abort` (66 s), `cloud.pause-resume` (198 s),
`cloud.oversize-stream` (166 s) and `cloud.paused-lid-cancel` (23:37Z,
28 s): every one passed. Campaign `c-20260824231028-b7ca` closed at 45 of
45 from nothing, the whole of it in 27 minutes of test time (36 unattended
in 13, the attended block in 12), and the export authorizes the image.
No release is cut. This is the first campaign on an image carrying the
board-only kernel, the SDMA clock fix and the ulfius peer patch together,
so it is the bench proof of all three, and the first with the bench actuator
doing the operator's door, interlock and button work end to end.

With it, three BRINGUP items close and two working files at the tree root
are merged: item 12's campaign narrative, item 20 (the video offload's bench
validation, `camera.h264-stream` in the campaign), item 21 (the kernel
trim, the campaign being what it owed), the acceptance burden plan (every
step landed, its decisions taken) and the kernel configuration review (its
status section is the record of what changed). Their texts, as they stood,
are in "Superseded status notes" below; what stays open went into BRINGUP
items 12, 13, 16 and the new item 20.

## 2026-08-24: the SoC under a full core, and where it settles

The die read 65.6 C (150 F) with the camera stream running and nothing
else, in a 30 C chassis, which was enough of a number to ask what a full
core does to it. The drill: `openssl speed -seconds 50 sha256` on the one
core for 300 s, on top of the live stream, cloud mode at idle with the
laser locked, a monitor sampling the thermal zone, `cpufreq-cpu0`, both GPU
cooling devices and the load average every 5 s. The die climbed 2.9 C in
the first 30 s and 4.6 C by 2.5 minutes, then sat at **70.8 C (159 F)** from
3.5 minutes to the end, at 0 percent idle and a load average near 3. No
cooling device left state 0, the core stayed at 996 MHz, `/status` read
`soc_throttle 0` throughout, and the driver's grade line in dmesg is the
one the facts bank quotes: `Commercial CPU temperature grade - max:95C
critical:90C passive:85C`. Thirty-five seconds after the load ended the
die was back at 67.9 C.

Read: the bare SoC, no heatsink, holds **14 C of headroom to the passive
trip and 19 C to the poweroff** under the worst load the one core can
produce, in a 30 C chassis. The die-to-chassis delta at full load is about
41 C, so by arithmetic, not measurement, a chassis above roughly 44 C is
what reaches the passive trip; the load alone does not. The facts bank's
open question, whether ForgeFIRM's load wants the heatsink the factory's
never did, closes with this entry: it does not. The per-job SoC range and
the throttle log line stay as the running record.

## 2026-08-25: the performance-curve ladders, and the rapids that fired after M5

The day opened with a new instrument. The head carries a thermopile that
reads scatter off the beam inside the head, upstream of the mirror that turns
it down to the work, so it sees the beam and not the material. A ladder of
100 mm lines at 10 mm/s, one per level, sampled from sysfs at 25 Hz along
with the HV current, is a performance curve for this tube and supply, and the
`pcurve` drill in `scripts/bench/live_fire_drills.py` runs it.

- **Analog ladder (E1), `$35` = 0, 13 rungs from 16 to 100 percent plus a
  repeat of rung 7:** the current is proportional to duty above 30 percent
  (slope 959 counts per 100 percent, r-squared 0.9999) and reaches 990 at
  full, so this PSU's ADC does not clip; below 30 percent the discharge is
  unstable. The thermopile is monotonic to 85 percent and puts the lasing
  knee between 19.7 and 22.8 percent duty, not at 16, with the strike spot
  showing as a first-second spike on the low rungs; its baseline holds within
  50 counts over the ladder and the repeat rung reads 3.5 percent high. It
  does not settle inside a line above about 50 percent (swings of 20 to 30
  percent at constant current), so the top of the analog curve is not yet a
  measurement. Record `pcurve_analog_20260825-195947.json`.
- **Density ladder (E3), `$35` = 0, period 20, minimum 3, 13 rungs from 1 to
  100 percent:** the dose is strongly convex in density at a 710 us period
  (80 percent of density reads 0.53 of full, 60 reads 0.37, 45 reads 0.21,
  30 reads 0.07), while `laser_on_sampled` tracked the commanded on-fraction
  exactly, so the drive delivered what was asked and the light did not
  follow. Whether that is the per-pulse strike deficit or the sensor is the
  next ladder's question. Lines were flat inside to within a few percent.
  Record `pcurve_density_20260825-202317.json`.

**The rapids fired after `M5`.** Seen by the operator on the density block
and confirmed in both traces: the pulsed current ran on through the `G0`
back and the `G0` up after every line, at the rung's level, and through a
bare `G0` sent with no `M3` at all. Under density that is full-power light
where nothing was commanded. `M5` executed with the stream idle only stored
the off state; the stream re-asserts its wanted fire state at the first byte
of every run, and the wanted state was still the last cut's true. Live fire
stopped.

**The first fix made the second job dark.** Pushing `fire=false` on `M5`
darkened the rapids (bench run 1 passed: the current fell from 393 to 0
inside one 40 ms sample) and then every following job in the same controller
process shipped no fire at all (runs 2 and 3, HV 0..0, motion ran). That was
first read as hardware, with the `laser power-good degraded` warning as the
suspect. It was software, and it reproduces on the null sink with two jobs
in one process: the second G1 ships zero FIRE ticks under both models.

**The root cause is a core contract.** grblHAL's per-segment laser update is
edge-triggered on rpm: `set_state(on, rpm)` records the rpm, and a block at
that same rpm gets no `update_pwm`, because the core takes the driver's
`set_state` as having lit the laser. Our `spindleSetState` pushed the duty
only. A process's first job always fired because the parser starts in G0,
where the `M3` and `S` words run at rpm 0 and the first G1 differs; after
`M2` the motion mode is G1 and S is modal, so the next job's `M3` runs at the
old level, the core records it, and nothing lights the G1 except the stale
wanted state. The old build fired job 2 by that accident, the same stale flag
that lit the rapids; removing the accident exposed the hole.

**The fix, and its proof.** `spindleSetState` now computes the pwm for the
state it is given (the off value when off, refused, or rpm 0) and pushes it
through `spindleUpdatePWM`, the whole state through the same armed and
coolant gates; the duty-only stream call is gone. Harness rule 17 and the
`next-job` sessions (two jobs in one process, `M2` between, same S) join
rule 16 and the `m5-idle` sessions; the build that went dark fails the new
session with one fire span, and the fix passes all 14 stream sessions, the
13 lifecycle cases and the arm test. On the bench, with the corrected
controller hot-installed: `m5dark` run 4 (the process's first job) and run 5
(its second, the case that went dark) both passed, 2.00 s of discharge, the
`M5` taking the current to 0 inside one sample, both rapids and every dwell
dark over 11.4 s of sampling, the operator confirming by eye. The catalog
gains `laser.m5-rapid-dark` (46 tests).

**Power-good is not a witness of anything here.** The factory 2.6.0 binary
carries no power-good string at all; ForgeFIRM warns on it once per armed
window and reports it in `/status`, and nothing gates fire on it. On this PSU
it reads not-good at full tube current.

A bench note for the next hot install: a file copied to the board with `scp`
lands without its execute bit, and busybox `cp` keeps that, so the supervisor
loops on exit 127 until a `chmod 755`.

## 2026-08-26: step timing under CPU contention closed

The operator closed BRINGUP "Next work" item 16, step timing under CPU
contention: the video work resolved it. The basis is above (2026-08-24, "the
SoC under a full core"): the kernel runs UP with the performance governor as
the only governor, the hardware frame skip of the video offload halves the
dequeues that the cache maintenance rides on, and the catalog test
`motion.step-timing-under-load` passed on that image with no clamped events.
The stream-live re-measure and the camera gate that the item still listed
are not owed. The item is removed from BRINGUP, and the items after it are
renumbered: 17 to 20 are now 16 to 19. `GFSINK_LEAD_MS` (default 10) and
the per-run margin report stay as shipped.

## 2026-08-29: the flow check under laser load, Tests 1 and 2

The 2026-08-25 flow-check trip (heater rise 15.1 C against the 14.4 C limit,
dT 9.4, while the first `dpatch` patch fired CW through the check window) was
run down with a new drill, `flowload` in `scripts/bench/live_fire_drills.py`.
`flowload t1` puts the three check keys at their defaults for the run and
fires two 30 x 4 mm CW fills (F1500, 0.3 mm pitch, about 35 s lit) on the
press with no dark dwell; `flowload t2 <secs> [pct]` writes
`cool_flow_check_s = 0` for the run and fires one fill sized to the lit
seconds at CW or at a density level; `flowload fit` fits rise against dose
over the t2 records. The sampler is the `dpatch` one plus
`thermal/heater_pwm`, `/cool/status` is polled at 1 Hz with the fan gates,
and every controller reply is kept. Every key the drill writes goes back to
what stood before when the run ends. The pump was never commanded off.
Records: `bench-data/flowload_t1_20260829-*.json` and
`bench-data/flowload_t2_*_20260829-*.json` in the tree.

**Test 1, three runs.** The check starts at the session open (the heater
comes on about one second after the M3, not at the press), so the press must
come at once for the fire to overlap the window. Runs 1 and 2 ended their
windows early (the drill closed the session on M2 before the 50 s were up;
fixed: the drill now holds the window open until the heater trace ends).
Run 3 ran the full window with the tube lit for 70 % of it, and the engine
read `coolant flow verified (heater rise 14.1 C, dT 9.5 C)`: 0.3 C from a
SUSPECT, where the same loop reads 11.7 to 12.1 C dark. The trip is
reproduced in kind, and it is not flow. Two things stack:

- **A common-mode ADC offset while the run airflow profile is on.** One
  sample after the session opens (fans to run duty) both coolant sensors
  drop 1.0 to 1.9 C together; they step back up when the fans return to
  idle; in between the readings toggle between two levels 0.6 to 1.1 C apart,
  both sensors in lockstep, up to 22 times in a run, with every fan steady
  at speed. The one session in which the air-assist fan never left idle
  showed no step and no toggling, the only pointer to a source so far. The
  engine captures `flow_base_down` from one sample at its first tick after
  the heater starts, inside that offset, so every rise carries about +1.1
  to +1.4 C from the offset and about +-0.5 C of single-sample scatter, dark
  or lit.
- **The tube's heat at the sensors.** Test 2 below: about 1.5 C inside a
  fully lit 50 s CW window.

Dark 11.7 plus the tube's 1.5 plus one low base sample reaches 14.1; the
15.1 trip is the tail of the same distribution.

**Test 2, the tube's signature, check off.** CW bursts of 20.8, 40.8, 47.9
and 59.0 s and one 59.4 s burst at 45 % density (S450). With the ADC offset
steps masked (a step is both sensors' half-second mean levels changing by
0.45 C or more the same way, agreeing within 0.4 C, subtracted from all
later samples), the downstream rise at burst end against the `hv_current`
integral is linear through the origin: **k = 3.06e-5 C per raw-second**
(r2 0.981, intercept 0.04 C), 0.030 C per lit second at hv 971, so **a fully
lit 50 s CW check window adds 1.49 C** against the 1.6 C margin; the rise
50 s after fire start read 1.43 to 1.49 C on every burst long enough. The
lag from first emission to the first sensor response is 10 to 20 s, a
smooth ramp on both sensors together, never a step at fire start. At 45 %
density the same window adds 0.46 C, and the heat per raw-second is 0.77 of
CW: the current integral overstates density heat, so a tracer needs one k
per power model.

**Events on the way.** One `t2 40` run held at +7 s on the airflow gate
(`air_assist 1895 under the 6000 floor for 3 s`): the air-assist fan never
left its idle reading inside the 15 s grace, the first air-assist trip on
record; it spun up normally in every other session. The first `t2 60` run
was written to the controller as one 93-line block, about 1270 bytes
against the 1023-byte RX ring, and the serial layer drops bytes on a full
ring, so the fill ran 46 s instead of 60 and the job's M5 and M2 were lost:
the window stayed open (engine phase `run`, `armed` true) until the drill
exited and dropped the connection. The next `t2 60` then ran its whole fill
with no arm, no button wait, no run report and no airflow: the driver's
spindle-state record was still on from the lost M5, and the arm at the
first laser-on is skipped when that record reads on. Fire stayed suppressed
at the stream (no HV, no emission, thermopile flat), so no energy left the
tube, but the head ran a full job without the operator's press. This is
BRINGUP "Next work" item 20 (arm on `state.on && !laser_ok`, clear the
spindle state in `gflaser_disarm`, consume the RX overflow flag), a fix
owed before the next image. The drill now feeds the job against the `Bf:`
free-character count, sends and acknowledges M5 before every run, refuses
to start while `/cool/status` shows the window armed, acknowledges M2 and
waits for the window to close, and prints the controller's replies: the
last three runs show `press the button to start the laser job`,
`laser armed (density)` on the press, and `Pgm End` with
`laser disarmed - latch locked` on the M2.

**Also seen.** `laser power-good degraded during the armed window` is
warned by the engine at every session open, a separate item. The check
window's own baseline and the tube term are the two candidates the fix
chooses between; nothing is built yet.

## Superseded status notes

### Shared machine services — remaining polish, as listed 2026-08-13

**Shared machine services — remaining polish.** The consolidation
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

### Camera service — closed 2026-08-03

**Camera service: DONE 2026-08-03, bench- and operator-verified**
(see "The camera service" section above; LightBurn streams it
directly). Remaining camera work: lens calibration / bed alignment,
the deferred 5.6 emulator homing-image smoke.

### Housekeeping entries

**Housekeeping**: ~~pick the controller's remote home~~ **DONE
2026-08-02** — the controller is now the canonical driver repo
`github.com/ScottW514/grblHAL-glowforge` (+ `ScottW514/core` fork;
the settings-write crash fix is upstream PR grblHAL/core#999; repoint
the submodule to upstream when it merges). ~~Yocto recipe for
grblHAL-glowforge~~ **DONE 2026-08-03** (`grblhal-glowforge` in
meta-forgefirm, boot autostart, reboot-verified). ~~Documentation
sweep (CLAUDE.md charter, README roadmap, INSTALL/BUILD/kas README)~~
**DONE 2026-08-13.** Remaining: kas flip + first GitHub release per
kas/README.md once ready to publish.

### kas/README.md status sections, as listed 2026-08-24

The two status sections of `kas/README.md` (the push/release checklist with its DONE markers, and the Scarthgap migration backlog), verbatim, before the README was cut back to build procedure and present-state facts; outstanding items are in BRINGUP, and the OV8856 reasoning lives in the 0011-0013 patch headers.

#### Push & release order (source-of-truth sequencing)

The build is only reproducible when recipe pins, layer branches, and the kas
config move in the right order. The sequence, with current status:

1. **Source repos pushed & pinned** — **DONE.** Every source repo
   (`kernel-module-glowforge`, `python3-gfhardware`, `Glowforge-Utilities`,
   `grblHAL-glowforge`, `forgectrl`) is on GitHub and its recipe pins an exact
   `SRCREV` — no `AUTOREV` anywhere. Whenever a source repo changes: push it,
   then bump the pin deliberately (BSP recipes in meta-openglow, ForgeFIRM
   components in meta-forgefirm) and re-verify with
   `bitbake -c fetch <recipe>`. A component's `SRCREV` (and the `PV` that
   moves with it) lives in `<recipe>-pin.inc` next to the recipe, nothing
   else goes in that file: the image manifest leaves `*-pin.inc` out of the
   layer content hash, so a pin bump changes the component's fingerprint
   and only that (`docs/ACCEPTANCE.md`) — a pin written into the recipe body
   still builds, but counts as a platform change and forces a full
   acceptance campaign.
2. **meta-openglow pushed** — **DONE.** The Scarthgap port lives on
   the **`scarthgap` branch** (Yocto layer convention; the Dunfell-era `master`
   is untouched). Development continues on the local sibling checkout; push /
   fast-forward `scarthgap` as work lands.
3. **forgefirm pushed** with the kas config and a `kas lock` lockfile pinning
   the upstream layers (poky, meta-openembedded, meta-freescale,
   meta-freescale-distro).
4. **At release time**:
   - flip `meta-openglow` in `forgefirm-glowforge.yml` from the local-sibling
     block to the pinned-remote block (commented FUTURE block in the file);
   - refresh `kas lock`, tag all repos, and prove self-containment by building
     from a **fresh clone**.
5. **GitHub release**: run `scripts/release.sh <version>` on the build
   host. It gates (version single-source, rootfs-vs-slot size,
   installer-embedded pubkey vs the signing key, factory-era fwup
   verification, and the **acceptance gate** - the committed
   `releases/v<version>/acceptance.json` from the bench campaign must
   authorize the built rootfs, `docs/ACCEPTANCE.md`), builds, packs and
   signs `forgefirm.fw`, stages the assets with `sha256sums.txt`, and
   prints the `gh release create` command. Assets and their exact names
   (the installer and the update manager download them verbatim):
   `forgefirm.fw`, `sha256sums.txt`,
   `forgefirm-image-glowforge.rootfs.wic.gz`, plus `acceptance.json` and
   `acceptance.md`. The release tag
   `v<version>` = `FORGEFIRM_RELEASE` = the rootfs `/etc/forgefirm-version`
   = the `.fw` meta-version; `release.sh` enforces the agreement.

All recipes fetch their pinned revision from GitHub, so an image build is
reproducible from the repos alone. For fast iteration on a source repo, bump
its pin per iteration, or add a **local, untracked** `externalsrc` bbappend
pointing at a working checkout — never commit one, or released images stop
matching the pins.

#### Scarthgap migration backlog

The kas scaffold + `LAYERSERIES_COMPAT` bumps let the layers be *selected* under
Scarthgap, but the legacy (Dunfell/Gatesgarth) layers won't build clean until:

1. ~~**Override-syntax migration**~~ — **DONE.** All `_append`/`_prepend`/
   `_remove`/`_${PN}` override syntax converted to the colon form across
   `meta-forgefirm`, `meta-openglow-core`, and `meta-glowforge-bsp` (22
   occurrences).
2. **Kernel forward-port (4.14 to linux-fslc 6.12.20).** The factory NXP vendor
   kernel (linux-imx 4.14.98) carried 7 out-of-tree changes; these are re-derived
   against mainline 6.12 in `meta-glowforge-bsp/recipes-kernel/linux/linux-fslc_%.bbappend`
   (the forward-port landing zone), **not** re-applied as the 4.14 patches.
   - **Foundation: DONE.** `linux-fslc` 6.12.20 builds for `glowforge` with a
     ported device tree (`glowforge.dts` + `openglow_common.dtsi` overlaid into
     `arch/arm/boot/dts/nxp/imx/`, registered via a Makefile patch) and deploys
     `zImage` + `glowforge.dtb`. Boot-core + mainline-bound peripherals only.
   - **Free wins: DONE.** bus-freq disable *dropped* (no mainline busfreq);
     `st,lis2hh12` x3 + `national,lm75b` + `ti,wl1805` + gpio keys/leds bind to
     mainline drivers. The 12 V control rail is a plain always-on fixed
     regulator with no userspace consumer node (nothing in the firmware
     switches it). The PIC SPI delay and the laser PWM prescaler are layer
     patches; see Motion polish below.
   - **Config: the board's kernel.** `glowforge.cfg` names this board's driver
     set and turns off what `imx_v6_v7_defconfig` adds for the other i.MX
     boards, and `conf/machine/glowforge.conf` names the modules and firmware
     the rootfs carries (the `kernel-modules` meta-package is not used). Every
     line of the fragment is expected to land in the built `.config` as
     written; a line that does not means a parent symbol is missing. The
     defconfig never names `PM`, the regulator core or ext4 (it had them by
     selection from suspend, the PMICs and ext3), so the fragment pins them.
     Bench record: BRINGUP item 21, CAMPAIGN-LOG 2026-08-24.
   - **Motion path: DONE and hardware-validated** (live-fed pulse stream,
     real gantry motion, laser fire). The whole chain forward-ports and
     compiles on 6.12:
       - **EPIT API**: `epit_api.c` in `arch/arm/mach-imx` (`CONFIG_MXC_EPIT_API`),
         in vmlinux, symbols exported; `&epit1/&epit2` in the DT.
       - **SDMA-expose**: re-created `dma-imx-sdma.h` + `0003-imx-sdma-*.patch`
         (un-static survivors, re-added the glowforge helpers, custom int-callback
         hook); expose symbols in `Module.symvers`.
       - **`glowforge.ko`**: ported across many 6.12 API changes
         (`tasklet_hrtimer`→soft hrtimer, `timer_setup`, LED-trigger API,
         `pwm_get`, `spi_delay`/`controller`, `filelock.h`, void `.remove`,
         1-arg i2c probe). Compiles + links, 0 undefined symbols; the recipe
         fetches the module by pinned `SRCREV`.
       - **DT**: `glowforge,cnc/thermal/pic/head` re-added with `pwms`/`pwm-names`
         phandles; `glowforge.dtb` compiles with all motion nodes.
     Motion polish, both carried as layer patches in the bbappend: the laser
     PWM prescaler (factory 1001) is patch 0009, `fsl,extra-prescale` on
     `pwm-imx27`, set to 13 on `&pwm2`; the cnc engine programs a ~1925 ns
     period so the SDMA script writes raw 7-bit power levels into PWMSAR, and
     the extra divider stretches the output to ~25 us, the ~40 kHz carrier the
     laser PSU expects (mainline `pwm-imx27` alone would run the laser PWM at
     ~520 kHz, and asking for 25 us directly caps the script's writes at ~8 %
     duty). The PIC inter-word SPI delay (factory 1005) is patch 0004: mainline
     `spi-imx.c` has no `PERIODREG` support, so the patch programs the ECSPI
     sample period from `spi_transfer.delay` (which pic.c sets) and forces
     fixed per-word bursts while a delay is requested, so the wait-states land
     between words; without it the PIC answers 0x0000 to the ID read. Both are
     in every image and hardware-validated (the PIC reads and the laser fires
     on them). The factory `glowforge,imx-pwm-audio` (buzzer) driver is not
     part of ForgeFIRM.
   - **Camera — DONE and hardware-validated.** The factory
     `ov5648_mipi.c` (NXP's removed `v4l2_int_device`/`mxc_v4l2_capture`) is
     replaced by the mainline `ovti,ov5648` subdev + imx6 `imx-media` (IPU CSI)
     + `imx6-mipi-csi2` receiver. The factory CAM_SEL MIPI switch is modeled
     with the mainline `video-mux` (gpio-mux on `gpio7 10`): both sensors →
     video-mux → `mipi_csi` → IPU CSI. Sensor `xvclk` is the board's 24 MHz
     fixed oscillator (matching the factory DTB); avdd/dovdd/dvdd rails are in
     the DT. Both cameras stream live through forgectrl (MJPEG at 15 fps with
     VPU JPEG encode, full-resolution snapshots, mux arbitration).
     **HD units (8 MP OV8856) — code complete, UNTESTED.** The DT lists both
     `ovti,ov5648` (5 MP) and `ovti,ov8856` (8 MP) at 0x36 so one image covers
     both, and the driver matching the chip ID wins. Everything the OV8856
     needs is in the build: patch 0011 gives it the `get_mbus_config` the
     IPU-CSI hard-fails without (the same gap 0006 closes for ov5648), patch
     0012 retunes both PLL multipliers for the board's 24 MHz xvclk (mainline's
     tables are written for 19.2 MHz, which would run the link 25 % above the
     frequency the driver publishes), patch 0013 adds the 2-lane RAW8 modes
     (below), the endpoint's `link-frequencies` list carries the driver's whole
     2-lane menu (it rejects the endpoint outright if any entry is missing —
     the old list omitted 720 MHz, so probe would have failed), and forgectrl
     and gfhardware pick geometry and the sensor's control set from whichever
     driver bound.

     The capture mode is the **full 3264×2448**, reached in RAW8. The
     sensor's stock RAW10 full-resolution 2-lane mode asks for 1.44 Gbps/lane
     and the i.MX6 CSI-2 D-PHY stops at 1 Gbps (`hsfreq_map` in
     `imx6-mipi-csi2.c` ends at 1000 Mbps and `max_mbps_to_hsfreqrange_sel()`
     returns `-EINVAL` above it), so `imx6-mipi-csi2` refuses to program it —
     but 8-bit samples carry the same frame at half the rate, which puts it on
     the 360 MHz link the binned modes already use, at 180 Mpx/s and 15 fps.
     Patch 0013 builds those modes from mainline's own 4-lane 3264×2448 and
     1632×1224 register lists plus a per-mode delta list: `0x3018` for two
     lanes, `0x3031` for 8-bit readout, and double the HTS because half the
     lanes carry half a line in the same time. It also makes the sample depth a
     mode property, so pixel rate, blanking and exposure ranges follow the mode
     instead of a fixed 10. Side effect worth having: the OV8856 path becomes
     byte-identical in shape to the OV5648's (8-bit BGGR, one byte per sample),
     and 3264 is a multiple of 32 so the NEON superpixel converter applies,
     which 1640 did not allow.

     The values are the factory firmware's: its own OV8856 driver is RAW8-only
     and ships exactly these two resolutions over two lanes with the same
     `0x3018`/`0x3031` and the same HTS/VTS pairs. It reaches them through a
     different PLL divider chain (`0x0302=0x1e`, `0x0303=0x03`, `0x030f=0x07`,
     `0x0312=0x05`, `0x4837=0x58`) that halves the link again to 180 MHz and
     the internal SCLK with it — a self-consistent alternative, recorded in the
     patch header as the configuration to fall back to if the D-PHY will not
     lock at 720 Mbps/lane on real hardware.

     Open, and only answerable on an 8 MP machine: whether it streams at all at
     720 Mbps/lane, and exposure/gain/white-balance commissioning — the OV8856
     driver publishes no red/blue balance controls, so white balance is
     uncorrected.
3. **u-boot** — **DONE.** The `glowforge` u-boot is
   a standalone `u-boot_2020.01.bb` (Scarthgap's poky has no u-boot 2020.01
   base recipe to extend). It reuses poky's
   `u-boot-common.inc`/`u-boot.inc`, pins `SRCREV` to the upstream **v2020.01**
   tag with the matching `Licenses/README` md5, and overlays the glowforge board
   support + arch-Kconfig patch. **Builds clean under Scarthgap (GCC 13, no
   source fixes) and deploys `u-boot-glowforge.imx`.** Remaining: move
   `fw_printenv`/`fw_setenv` from `u-boot-fw-utils` to `libubootenv`
   (`PREFERRED_PROVIDER_u-boot-fw-utils` in `glowforge.inc`) when the rootfs needs
   them.
4. **Device tree — DONE.** The `glowforge` `.dts` is validated against the
   linux-fslc 6.12 bindings and against the running board (motion, safety
   readbacks, cameras, sensors all bind and work).
5. **Real-time strategy — decided.** The kernel runs
   `CONFIG_PREEMPT=y` (factory behavior; `imx_v6_v7_defconfig` alone gives only
   `PREEMPT_VOLUNTARY`). **PREEMPT_RT is not selectable on arm32 6.12** (no
   `ARCH_SUPPORTS_RT`) and is **not needed for the pulse feeder**. The
   argument is about queue depth, not ring size: the ring drains at 1 byte
   per EPIT tick (≤200 KB/s even at the 200 kHz ceiling), so the live
   feeder's bounded queue depth of ~150 ms — a few KB in flight — already
   rides out worst-case scheduling latency with orders of magnitude to spare
   (measured: 0.2 ms worst write latency under full CPU + I/O load; the
   underrun bench ran 100 kHz for 120 s with zero underruns). The ring
   itself is 32 MiB (the `ring_mb` module parameter, backed by the 32 MiB
   reserved pool, matching the factory ring): ~168 s of stream at 200 kHz,
   ~56 min at the 10 kHz cloud-mode tick — a capacity that matters for the whole-job preload of
   cloud mode, not for latency. Bounded queue depth + `SCHED_FIFO` for the
   feeder is the design; revisit RT only if the underrun bench ever
   contradicts this arithmetic.

6. **gfui-client → forgectrl — DONE.** The stock `gfui-client` is excluded
   from `forgefirm-image` (`IMAGE_INSTALL:remove = "gfui-client"` in
   `meta-forgefirm/recipes-forgefirm/images/forgefirm-image.bb`). Its slot is
   filled by `forgectrl` (github.com/ScottW514/forgectrl — the machine-services
   daemon: web control panel, cameras, telemetry, settings, diagnostics,
   cooling engine, updates, and controller-mode supervision) plus the two
   controllers it supervises, `grblhal-glowforge` (Grbl over TCP:23) and
   `gfcloud` (the optional Glowforge web-service client, off unless selected).

---

**Image status:** `forgefirm-image` **builds end-to-end** on the forward-ported
stack and deploys `forgefirm-image-glowforge.rootfs.wic.gz` (+ `zImage`,
`glowforge.dtb`, `u-boot-glowforge.imx`) under `build/tmp/deploy/images/glowforge/`.
Build-time prerequisites baked into the config: `ACCEPT_FSL_EULA = "1"` (NXP
firmware-imx — the image also installs `firmware-imx-lic` so the EULA text
ships beside the blobs) and the kernel default in `glowforge.conf`. Every
`LICENSE` string in the layers (`meta-forgefirm`, `meta-glowforge-bsp`,
`meta-openglow-core`) is SPDX, and the recipes for third-party components
that carry more than one license (`wlconf`, `python3-gfhardware`) declare
each of them with a checksum on its license text. The stack
is hardware-validated end to end: motion timing, the laser and safety chain,
the camera pipeline, both controller modes, and the A/B install path.

### Release acceptance follow-through (item 12), as listed 2026-08-24

Closed by campaign `c-20260824231028-b7ca` (45 of 45 on dev 20260824230512, the bench actuator proven in it). The leftovers (bench tools from the page, two unported cooling tests, the armed-kill core question, the websocket.py split) stay in BRINGUP item 12; the first release is item 13.
12. **Release acceptance follow-through.** The full campaign on the first
    image built with the `<recipe>-pin.inc` layout is done: dev image
    `20260821181036`, 42 of 42, release authorized (the export is on the
    board at `/data/forgetest/export/`). From here a component pin bump
    re-requires only the tests covering that component. That image also
    carries the 32 MiB pulse ring (DT pool plus the module default):
    `image.health` reads the pool and `ring_mb` back, and
    `cloud.oversize-stream` fed a print longer than the ring from the live
    service. Still owed: exercising the ported bench tools from the page
    (they are registered and unit-tested, not yet driven from the page), and
    the first release, which commits `releases/v<version>/acceptance.json`.
    Cutting the operator's part of a campaign: the forgetest-only step
    (the operator channel, the merged mode-switch, the sensor witnesses,
    the steps pane, the journal, per-test implementation hashing) is done
    and bench-validated (CAMPAIGN-LOG 2026-08-22). The offline cloud
    service for the machine-behavior tests (gfutilities `OfflineService`,
    `gfcloud --offline`, `forgetest/puls.py`, four tests re-ported) is done
    and bench-validated on dev image `20260822232347` (43 of 43, the four
    offline tests in 5.5 minutes, nothing on the bed). The service-protocol
    test on the emulator (`cloud.service-protocol`, `gfcloud --emulate`, the
    `python3-gfutilities-emulator` fixtures on the dev image; only a Print
    in the app to drive) is done and bench-validated on dev image
    `20260823161333` (44 of 44, CAMPAIGN-LOG 2026-08-23). The service's
    connect-time hunt is paid only where it is the subject: every cloud
    client the tool starts for anything else comes up under
    `/run/gfcloud-nohunt` (`gfcloud --no-hunt`, the first settings report in
    the reconnect form), while the two homing tests and the one real print
    get theirs, the print by never reusing a session that has not hunted
    the machine itself (the contract's cloud split in ACCEPTANCE.md). The
    coverage maps follow the split (a sign-in change re-requires the
    protocol test and the print, a feeder change the offline tests and the
    print, a doc edit nothing), and the bench actuator `forgefixture`
    (`fixture/`: ESP32-S3, three relays, the `ctx.act` seam, an operator
    test it covers routed into the unattended queue) is written and
    host-proven (the firmware builds in the pinned ESP-IDF container, the
    policy and the tool's client have host tests) and **owed its bench
    proof**: the harness at the machine's connectors, then a campaign with
    it up. Catalog
    gaps left from the tool's own plan: `cooling.confirm-escalate` and
    `cooling.fire-gate-blocks-arm` are not ported (both need the pump switched
    by hand mid-run, so they are bench-tab material first), and whether
    `laser.armed-kill` belongs in the always-required core rather than its
    domain is still an open call (the core carries the emission witness).
    Tools that genuinely need a second host (LAN flood, remote auth probes)
    stay host-side by design, and the registry marks them so.

### Video pipeline offload: bench validation (item 20), closed 2026-08-24

Closed: `camera.h264-stream`, `camera.frame-health` and `camera.snapshot` passed in the campaign on the GPU path, and motion ran under the stream. The strip switches and diagnostics named at the end are documented in `forgectrl/docs/SERVICES.md`; 8 MP first light stays with item 6.
20. **Video pipeline offload - bench validation.** First hardware session
    done (2026-08-24, dev image 20260824122014, drill binaries; fixes in
    forgectrl 6614833). Proven: Mesa etnaviv fits the release slot
    (~5 MiB margin); surfaceless EGL and dmabuf import both directions;
    `GL_MAX_TEXTURE_SIZE` 8192 (no tiling even at 8 MP); the full path
    GPU render → IPU stride-fix crop (`src/ipu_copy.c`, the render
    engine's 64-byte rows and the CODA's round_up(width,16) stride never
    meet, so the IPU crops between them, 14 ms, no CPU touch) → VPU
    encode, `convert: "gpu"`, image correct to within 2 counts of the
    scalar demosaic; `/cam/h264` serving valid fragmented MP4 on
    hardware (avc1.424020, ~480 kbit/s on a static bed). Second session
    (2026-08-24 evening, forgectrl 2d59d78): the render decomposed to
    41 ms luma + 49 ms per chroma pass; the chroma passes now
    point-sample instead of box-average (16x fewer per-fragment fetch
    chains), taking the render to 64 ms - **~9 fps at ~7 % CPU**
    against the NEON path's 15 fps at 41 % - with luma measured
    bit-clean against the CPU path (which also retired the bottom-row
    artifact of the first session). The **CSI hardware frame skip is
    live-proven** with the GPU path (`FORGECTRL_STREAM_FPS=7` →
    `hw_fps_skip: true`, steady ~7 fps, daemon sampling 0.0 % in top):
    that is the recommended low-CPU configuration today. Third session
    (2026-08-24 night, forgectrl deee6a1): the render and the encode now
    overlap - a frame renders behind an EGL fence while the previous
    frame is IPU-cropped, encoded and published (two IPU source buffers;
    the rendering frame's capture buffer held until its fence clears) -
    measured **13.8 fps single-viewer at ~14 % CPU** (fence stall
    7-9 ms of the 64 ms render, so it is fully hidden), **9.8 fps with
    MJPEG and H.264 served at once** (stall 0), luma still bit-clean.
    Fourth session (2026-08-24 night, forgectrl d97cb35): MSE playback
    in Chrome found the fragments carrying raw boot-clock timestamps
    and the panel's live-edge seek overshooting the one-frame buffered
    window; each viewer's fragments are now zero-based, the seek clamps
    into the newest range, and a paused element is kicked back into
    play. Verified live: the panel's H.264 view plays at 1296x972 with
    no MJPEG fallback, and with that view plus an MJPEG viewer running,
    a jog out and back completed at its commanded feed with the step
    ring's underrun counter unmoved and the planner buffer full - the
    GPU stream path and motion coexist. Bench validation of the video
    offload is complete. The acceptance campaign is not tracked here:
    it rides the release flow as always (item 12; Mesa joining the
    image makes the next one full, and `camera.h264-stream` rides in
    it). The one piece of video work that needs hardware this bench
    does not have is 8 MP first light (item 6). Switches to strip a suspect layer: `FORGECTRL_NO_GPU`,
    `FORGECTRL_NO_H264`, `FORGECTRL_NO_HW_SKIP`, plus the existing
    `FORGECTRL_NO_VPU` / `FORGECTRL_NO_NEON` /
    `FORGECTRL_NO_CACHED_BUFS`; diagnostics under `FORGECTRL_GPU_CHECK`
    (tight stats cadence, render-versus-copy split, luma/chroma
    compare) plus `FORGECTRL_GPU_PASSES` (limit the draws) and the
    frame-wait column in the stream stats.

### Kernel trim: bench validation (item 21), closed 2026-08-24

Closed: the campaign it owed ran green on dev 20260824230512, after the two faults it uncovered on the way (the SDMA clocks and the truncated peer address, both above) were fixed. The kernel's present shape is in the facts bank ("Reserved memory", "SDMA pulse engine", "The SoC guards itself"); the item-16 drill stays with item 16; the trims not taken are the new item 20.
21. **Kernel trim: bench validation.** The kernel is built for this board
    alone: `glowforge.cfg` names the driver set and turns off what the
    multi-board defconfig adds, and `glowforge.conf` names the modules and
    firmware the rootfs carries. Built into image 20260824164619, not yet
    flashed: zImage 4.8 MB (was 9.1 MB), 31 kernel-module packages (was 254),
    no SDMA, EPDC or Quad-VPU firmware, ARMv7-only code, no virtual console
    (`USE_VT = "0"`), and no `dmas` on ecspi2, so the pulse ring is the SDMA's
    only client. New on the same image: pstore/ramoops in the 1 MiB the
    bootloader holds back at the top of DRAM (`/sys/fs/pstore` mounts from
    fstab), the hung-task and soft-lockup detectors behind the panic
    notifier, `PANIC_TIMEOUT=10` in Kconfig, and `evbug` gone from the kernel
    log. Bench-validated on that image (CAMPAIGN-LOG 2026-08-24): every node
    binds and nothing defers, the panic sysctls read as configured,
    `/sys/fs/pstore` mounts with ramoops registered, `/dev/dri/renderD128`
    is present and both cameras stream through the GPU demosaic, Wi-Fi
    associates with `regulatory.db` loaded, the switches sit on `event0`,
    31 modules load and no DMA channel is held by anyone (which, as the
    campaign later showed, was the problem: see below). Two cosmetic dmesg
    lines came with it: spi-imx reports the absent DMA channel at ERR level
    and runs PIO, and `consoleblank=0` (uEnv) is an unknown parameter without
    a virtual console. The crash record is proven: a forced `sysrq-c`
    panicked, rebooted on the timeout, and the next boot read back
    `dmesg-ramoops-0` and `console-ramoops-0` with no ECC errors (the
    first boot's header-init lines did not repeat). The `spi_device_id`
    table for `glowforge,pic` is pinned into the next build (its boot
    warning goes with it). Still owed: a GRBL job on the image, then the
    acceptance campaign (platform change).

    A second round rides the next image, host-proven and unflashed: the
    kernel is UP (`SMP` off) with performance as its only cpufreq governor;
    spi-imx no longer logs the absent DMA channel (patch 0014);
    `consoleblank=0` is gone from the boot
    arguments; only `wl18xx-fw-4.bin` and `wl18xx-conf.bin` ship for the
    WL1805 (the current factory image's set); IPv6 is on end to end
    (distro feature, `udhcpc6` from the `wlan0 inet6` stanza, forgectrl,
    grblHAL's TCP:23 and forgetest listening dual-stack); the log export
    carries `/sys/fs/pstore`; and the release rootfs drops nano/libmagic,
    the udev hardware database and urllib3's pyOpenSSL chain (~22 MB).
    Bench-validated on dev 20260824200726 (CAMPAIGN-LOG 2026-08-24, second
    round): the three lines are gone, the kernel is UP at 996 MHz on the
    performance governor, Wi-Fi is up on the two-file firmware set, every
    port answers over IPv6 on the board's ULA, the export runs. Dev
    20260824201945 adds patch 0015 (wlcore asks for its optional NVS the
    quiet way) and the last stray dmesg line is gone. The missing GUA is a
    network matter, diagnosed (CAMPAIGN-LOG 2026-08-24, "the second DHCPv6
    responder"): the firewall advertises an address, but an access point on
    the bench VLAN still ran its own RA and DHCPv6 server, its Advertise
    arrived first with nothing to give, and busybox's `udhcpc6` stays with
    the first Advertise it sees. With that access point's RA and DHCPv6
    disabled (as on the other two) the board took the firewall's lease, and
    every service answered on the global address from another VLAN: IPv6 is
    on end to end.

    The campaign on dev 20260824201945 then found what every check above had
    missed: the machine cannot move on any image since the trim. The SDMA
    engine's `ipg`/`ahb` clocks are enabled only while a dmaengine client
    holds a channel; imx-sdma leaves them off after probe, and glowforge.ko
    takes its channel through the SDMA API patch without touching them. The
    ecspi2 `dmas` had been the only clock holder since the first image, by
    accident. With the block gated every channel-0 transfer completes at
    once and moves nothing, so the ring reads back the bounce page: the
    supervisor's probe logs `cannot start the probe run` at every spawn
    (`cnc/run` returns -ENODATA because the head sync reads the tail it just
    published), `cnc/free` exceeds the ring, and `/status` reports a position
    that never moved. `image.health` failed on the free check after the
    150 s settle timeout, which is how it surfaced (CAMPAIGN-LOG 2026-08-24,
    "the SDMA clocks, held by nobody"). The fix, host-proven and unbuilt:
    `sdma_get_channel()` enables the clocks and `sdma_put_channel()`
    releases them (patch 0003, the API header), the module calls put on
    remove and on the probe unwind, the empty-ring run request logs at ERR
    level again (it was the only kernel-log trace of the fault), and
    `image.health` asserts the SDMA clock enable count directly. The ecspi2
    `dmas` stay deleted. Bench-proven on dev 20260824215906: the clock count
    reads 1, the probe reports MOTION OK, `cnc/free` reads the ring less its
    gap, and the campaign ran every kernel, forgectrl, logs and motion test
    green.

    That campaign then stopped on `cooling.fans-quiet-after-motion`: M8
    raised no fan duty because forgectrl had accepted no cooling report
    from the controller at all (`report_age_s` -1). The dual-stack listener
    of the second round reports every peer as a `sockaddr_in6`, and ulfius
    2.7.15 copies the peer into `client_address` as `sizeof(struct
    sockaddr)`, 16 bytes; the mapped-loopback bytes the check reads lie
    beyond the copy, so `POST /cool/state` from 127.0.0.1 got `403 loopback
    only` (fail-safe: the engine treats silence as a stand-down, so nothing
    fired, but no run profile and no armed window either). The fix: the
    image patches ulfius to allocate a `sockaddr_storage` and copy the
    family's length (`meta-forgefirm/recipes-extended/ulfius`), the peer
    check lives in `src/peer.c` with a host unit test (`auth_peer_test`,
    including the truncated-copy case, which fails closed), and
    `forgectrl.auth` asserts that the loopback peer is accepted as well as
    that a LAN peer is refused. Bench-proven on dev 20260824230512: the
    loopback report answers 200 and the LAN peer 403, the controller's
    reports land (`report_age_s` 0.1), and campaign `c-20260824231028-b7ca`
    ran the 36 unattended tests green in 13 minutes, `fans-quiet` among
    them (CAMPAIGN-LOG 2026-08-24, "the listener heard, and the campaign
    ran through"). Left: the item-16 drill and the nine attended tests
    (four laser live, five cloud).

### The acceptance burden plan (tree-root working file), merged 2026-08-24

The working file `ACCEPTANCE_BURDEN_PLAN.md`, verbatim, at the point every step had landed: step 1 (the operator channel and the witnesses), 2a (the offline service), 2b (the protocol test on the emulator), 3 (the bench actuator) and 4 (finer covers) bench-validated, the operator's decisions taken (the fixture built; arm presses human by default with the opt-in; the mode-switch merge done; the protocol test a catalog test). The contract lives in `ACCEPTANCE.md`; the one thing it left open, the `websocket.py` split, is in BRINGUP item 12. The file is deleted.
#### Acceptance campaign: cutting the operator's burden

**Working file, not a repo document.** The tree root is not a git repo. When this
closes, its conclusions merge into `forgefirm/docs/ACCEPTANCE.md` (the catalog
kinds, the action seam, the fixture contract, the cloud split),
`forgefirm/docs/BRINGUP.md` (the open work it leaves behind, and the fixture in
the hardware facts bank if one is built), `forgectrl/docs/SERVICES.md` (the
offline cloud service, if it becomes a setting), and the dated record goes to
`forgefirm/docs/CAMPAIGN-LOG.md`. Then this file is deleted. Same
merge-and-remove convention as the audit and acceptance plans.

**Status: step 1 DONE and bench-validated 2026-08-22** (forgefirm de324cc,
9139e92, 296fd68, 2547a8e, 60db956; dev image `20260822204234`; campaign
`c-20260822220701-a1c0`, 43 of 43 from nothing, the 16 attended tests in 19
minutes of test time against the 111-minute estimate the plan started from).
**Step 2a DONE and bench-validated 2026-08-22** (gfutilities 768730e,
gfhardware a3ca36f, forgefirm 9cc2e4e/628f2f7/0cb9044, meta-openglow a52e68c;
dev image `20260822232347`; campaign `c-20260822233344-08de`, 43 of 43, the
four offline tests in 5.5 minutes with nothing on the bed). **Step 2b
CODE-COMPLETE, BENCH OWED** (gfhardware 12ad3b1 `gfcloud --emulate`,
meta-openglow a4e3abf `python3-gfutilities-emulator`, forgefirm 1c8197f/4c9dcca
`cloud.service-protocol`; dev image `20260823002125` BUILT, NOT FLASHED; it
carries a layer change, so its first campaign is a full one: 28 unattended, 17
attended). 2c (one real print stays) is `cloud.pause-resume` by construction.
Steps 3 to 4 not started.

**Step 2b DONE and bench-validated 2026-08-23** (CAMPAIGN-LOG 2026-08-23,
forgefirm e5fa444): the emulator's hunt bypass found by the dry-check and
fixed (gfhardware b7e8035); the operator's no-hunt change (gfhardware
351a623, forgefirm 969bac6: `--no-hunt`/`/run/gfcloud-nohunt`, markers
consumed by the client first thing, `session_hunted` guarding the real
print; policy in ACCEPTANCE.md); the POST /mode timeout found on the bench
and fixed both sides (gfhardware 537d0db: the emulator reports idle to the
cooling engine; forgefirm ab0a515: 120 s for the supervisor's levers).
Final: dev `20260823161333`, campaign `c-20260823161923-0dd7`, **44 of 44,
release authorized**, 29 inherited, 868 s attended. `cloud.service-protocol`
68 s with one Print in the app; the real client back in 14 s under NO-HUNT.
No release cut. The cloud split (L2) is complete.

**Step 4 (L5, finer covers) DONE 2026-08-23, host-proven, bench re-baseline
owed** (forgefirm 53e4fa2 + 335c6de, pushed, forgetest 241/241, lint clean):
the cloud maps by what each test proves (`_SERVICE_LAYER`, `_MACHINE_RUN`,
`_HOMING_PATH`, the print `_CLOUD_ALL`), two hollow entries of the protocol
test found and fixed (globs anchor at the repository root), the lint now
fails any entry that selects nothing, and non-behavioral paths (docs, CI,
unit tests, licenses: `NON_BEHAVIORAL` in manifest.py) are outside every
fingerprint. Measured on the tree manifest: a sign-in change re-requires
proto + print; a feeder change the 4 offline tests + print; a camera change
mode-switch + print; a doc edit nothing. Cost: 28 fingerprints move once
(the 7 cloud tests by their maps, 21 laser/motion/kernel tests because
their `**` used to hash grblHAL/kernel docs and tests): 16 attended + 12
unattended on the next image. Not done: splitting gfutilities'
websocket.py (transport vs. transfer helpers), which would take
websocket-transport changes off the offline tests; a gfutilities refactor,
not a map.

**Step 3 (L1, the fixture) CODE-COMPLETE 2026-08-23, bench owed**
(forgefirm 8ee4ee3 firmware + b54b94e tool side, pushed, both CI green):
`fixture/` = ESP-IDF v5.5 project for the ESP32-S3 DevKitC-1 (GPIO 4 lid,
5 interlock, 6 button, 7 enable jumper to GND; active-high 3.3 V opto
relay modules; HTTP :80, `X-Fixture-Key`; mDNS `forgefixture.local`;
`fixture.env` baked at build; `fixture.sh env|build|flash|monitor|test`;
builds in `espressif/idf:v5.5.5` via podman from Git Bash, 837 KB).
forgetest: `fixture.py` (config `/data/forgetest/fixture.json`, own mDNS
resolver, client), `hands=` on tests, routing of covered operator tests
into the unattended queue, Ready pass-through, prompt guard, release after
every run, `arm_press` opt-in (`Context.arm_press`, used by the laser
suite). Operator decisions: ESP-IDF native, .env baked, jumper, name.
Settled: the interlock loop is J8 (J6 is the speaker), the 3.3 V rail has
the headroom. 2026-08-23 18:50Z: flashed (COM15), on the air as
forgefixture at 172.16.1.135, found by forgetest (dev 20260823184050) over
mDNS by itself, every API path verified from the board; lid and interlock
relays switch; the button reports disabled until the jumper is in. Left:
the harness, then the campaign.

**Step 3 BENCH-PROVEN 2026-08-24 (harness wired by the operator):** every
channel proven through forgectrl's switch readings (lid 50 ms, interlock
40/200 ms, button pulse seen); forgetest routed 8 operator tests into the
unattended queue. The first fixture campaign (`c-20260824171919-e4f0`)
failed `motion.button-hold-resume` on a harness defect: the second press
was asked while the first 200 ms pulse was still on, the fixture answered
409, the runner fell back to an operator who was not there, and the
post-baseline could not jog a controller left in Hold. Fixed in forgetest
(press spacing in `fixture.py`, unattended fixture refusal = ERROR in
`runner.py`, soft reset out of Hold/Door before the return jog in
`baseline.py`; 5 host tests; ACCEPTANCE.md + fixture/README.md),
hot-installed by the operator, rerun `c-20260824174545-0bdc`: 25/25,
36 unattended satisfied (11 inherited), every fixture action `by:
fixture`, 0.04 to 0.34 s each; the baseline's hold reset proven by a dry
drill the same day (a move held at 7.988 mm reset and jogged back).
Committed and pushed as forgefirm 00ded74. Left:
the 9 attended tests (4 laser live, 5 cloud), the CAMPAIGN-LOG entry,
then the merge of this file.

**COLD PICKUP (next session):** 1. the operator builds the harness and
flashes the DevKit (`fixture/README.md`); settle the interlock connector
first and fix whichever doc is wrong; 2. `/data/forgetest/fixture.json`
on the bench (key from fixture.env, mode 0600); the forgetest change
reaches the bench with the next image (or a hot-install); 3. a campaign
with the fixture up: the 28-test re-baseline of step 4 plus the fixture's
own proof (operator tests in the unattended queue, `by: fixture` in the
evidence, the release leftover); 4. CAMPAIGN-LOG entry, then merge this
file into ACCEPTANCE.md / BRINGUP / SERVICES.md per the header and delete
it. Written 2026-08-22 from a read of the 45-test
catalog, the runner, the page, and the cloud client's seams; the numbers in
§1 and §4 are the catalog's own `est_min` and `steps` declarations, not a
stopwatch; the campaign record is `CAMPAIGN-LOG.md` 2026-08-22.

**What step 1 settled, beyond the plan:**

- **Per-test implementation hashing** (not in the original plan): the
  fingerprint's implementation half was the whole suite file, so a two-line
  witness fix re-required every test of its module. It is now the test's
  function plus the module's shared code. One-time cost paid (every
  fingerprint moved; the 43/43 campaign above).
- **`cloud.pause-cancel-paths` became `cloud.paused-lid-cancel`**: the app
  cancel lives in `cloud.oversize-stream` only, judged in full there. Catalog
  stays 43 (the protocol test of L2c is still to come).
- **Witness facts from the bench:** the head accelerometer lands 2 to 3 sysfs
  samples per one-second jog leg and sees ramps, not travel (judge the
  sequence, never a single leg); the button LEDs fade under the smooth
  trigger (read `target`, the commanded level); the beam detector read delta
  500 and 479 against the 300 threshold at S400 (digital flag seen both
  times); the lid camera's half-res frame is ~2x the bytes lit vs lamp-off.
- **Every action was the operator's** (74 recorded `by: operator`); the
  fixture seam (`runner.fixture`, `covers()`/`act()`) is exercised only by the
  host test until step 3.
- **Step 2a decisions:** the offline lever is a volatile marker
  (`/run/gfcloud-offline`, one start, never a persisted setting: a reboot can
  never come up offline) plus `gfcloud --offline`; no forgectrl change. The
  service is `OfflineService(GFUIService)` in gfutilities (same dispatch
  loop; a UNIX-socket listener stands in for the WsClient; a requests
  Session with a `file://` adapter and an upload sink stands in for the web
  session). Jobs are synthesized on the board from a captured factory print
  header (MCsn 0, so no serial lock) over a laser-free square; a job longer
  than the ring is the whole file gzip-compressed (the client's gzip ISIZE
  is its progress denominator). Lesson: the marker must stay until the
  `OFFLINE service` line is logged (Python import time on the i.MX6 runs
  seconds past the supervisor's "running").

---

##### 0. The problem in one paragraph

A full campaign is 45 tests: 25 `auto` (48 min), 12 `operator` (46 min), 8
`live` (65 min). The attended block is 111 of 159 catalog minutes, and it asks a
human for roughly eighty discrete things: open the lid, press the button, pull
the interlock, set up a job in the Glowforge app, place scrap, look at the
scrap, look at the app, answer a popup before the head finishes its move. The
inheritance model spares most of this on a quiet day, but during development
of the cloud client every change invalidates all eight cloud tests, which means
six real prints and a full-bed raster designed in the app. The goal here is to
take the hands out of the campaign wherever a sensor or a relay can stand in
for them, without moving a single safety line.

##### 1. Where the burden actually is

Counting what the 20 attended tests ask of a person in one full campaign:

| Action | Count | Where |
|---|---|---|
| Lid open or close | ~23 | 9 tests; every one a software-visible EV_SW edge the test already verifies |
| Button press, pause/resume | ~10 | 6 tests |
| Button press, arm consent | 11 | the 8 live tests |
| Interlock unplug/restore | 4 | 2 tests |
| App: set up a job and press Print | 7 jobs (one a full-bed raster), 2 cancels | 5 cloud tests |
| Scrap placement | ~8 | every live test |
| Eyeball confirmation (`ctx.confirm`) | ~16 | 13 tests |

Three facts shape everything that follows.

1. **The switch actions are the majority and the cheapest to remove.** All
   three consumers (grblHAL `glowforge_switches.c`, gfhardware `switches.py`,
   forgectrl `status.c`/`liveness.c`/`auth.c`) read the same gpio-keys device
   (`/dev/input/event0`, EVIOCGSW). There is no software injection path on the
   board; grblHAL's `GF_SWITCH_FILE` hook exists only in the null-sink host
   build. Adding one to three repos' safety paths is the wrong trade when a
   relay exercises the real edge, the real hardware button latch, and the real
   interlock latch drive.
2. **The app operations and the eyeball confirmations are the slow items**, and
   nearly every confirmation duplicates evidence the test already collects
   (log needles, kernel counters, `armed`, the latch bit) or could collect from
   a witness the machine already has: `head/beam_detect_analog` (baseline
   ~1834, 2600 to 2890 during S300/S400 fire, measured 2026-08-12),
   `beam_detect_digital`, the head accelerometer (the supervisor's own
   liveness witness), the button LEDs (`/sys/class/leds/button_led_*`, already
   read by the baseline), `pic/hv_current`.
3. **The cloud tests conflate two mechanisms.** The service protocol (auth,
   WSS, action dispatch, pulse download, lifecycle events, progress) and
   gfhardware's run loop (button wait, lid/interlock abort, park, retrace,
   cancel). Only the first needs the real service; only the second needs the
   real machine. The seam is clean: `GFUIService` feeds
   `dispatch_action(machine, msg)`, and the hardware sits behind `Machine`
   (gfhardware) or `Emulator` (gfutilities, which already completes a homing
   to print cycle against the real service with canned images).

##### 2. The levers, ranked by payoff

###### L1. A bench actuator fixture, and a typed action seam in forgetest

**Hardware.** Three relay channels at the connectors, no board modification:

| Channel | Where | Contact | Why it is fail-safe |
|---|---|---|---|
| Lid | in series with the lid-switch loop (the J4.12/13 net) | normally closed | a series contact can only add an open, never mask a real lid open; the hardware chain sees exactly what it sees today |
| Interlock | in place of the J8 jumper (Basic/Plus), or in the Pro's plug loop | normally closed | same argument |
| Button | from J5's 12 V to J5 BTN | normally open, pulsed by the fixture firmware (max ~500 ms), never held | a parallel contact can only add a press; see the consent question in §5 |

A Pico W or ESP32 with a trivial HTTP API on the LAN; forgetest gets
`FORGETEST_FIXTURE_URL` and the channel inventory from a bench-local file
(`/data/forgetest/fixture.json`). The interposer harness lives with the bench
and is described in the hardware facts bank, never in the public repos.

**Software: `ctx.act()`.** Replace the free-text `ctx.instruct("Open the lid
NOW ...")` calls with typed actions: `ctx.act("lid", "open")`,
`ctx.act("interlock", "open")`, `ctx.act("button", "press")`, with the
existing wording kept as the human fallback text. The runner fulfills an
action through the fixture when the channel is present and then verifies the
resulting EV_SW state through `/status switches` (the tests already make this
check by hand after every prompt), otherwise it falls back to exactly today's
prompt. Tests declare `actions=[...]` next to `steps`. The `kind` stays the
conservative truth for a bench without a fixture; a declared-`operator` test
whose actions the bench's fixture all covers is routed into the unattended
queue at runtime; `live` never downgrades. Every result records, per action,
whether the fixture or a human fulfilled it (`evidence.operator.actions`).

**Payoff.** All 12 operator tests become unattended. The live tests lose every
action except the arm press. About 37 of the 80 actions are gone.

###### L2. Split the cloud tests: service protocol vs. machine behavior

**(a) Offline action injection for the machine-behavior tests.** An
`OfflineService` in `forgefirm-app` with `GFUIService`'s interface: no auth, no
WSS, a local UNIX socket that accepts action messages in the exact WSS shape
(`{"id", "action_type", "motion_url", "settings", ...}`) and writes every
`send_wss_event` as the same `<action> [id]: finished with event ":..."` lines
the tests already needle on. `load_motion` gains a `file://` branch. forgectrl
passes the mode through as a named setting (`cloud_service = offline`), a test
lever like the `cool_*` gates, harmless on a release image because it only
ever runs offline. The connect-time hunt becomes an injected `hunt` when a
test wants one.

Pulse files: this machine's own captured factory files in `_RESOURCES` are
serial-locked to the bench (`MCsn` passes), so a tool that strips the FIRE
bits and zeroes the power bytes turns them into FIRE-less jobs; or a generator
on top of gfutilities' pulse helpers plus a header generator from the decoded
tag table (`_RESOURCES/FW/PULSE-HEADER-TAGS.md`) synthesizes any job, which
gives the oversize test a 40 MiB job in seconds instead of a full-bed raster
designed in the app.

This moves `cloud.lid-interlock-abort`, `cloud.pause-cancel-paths`,
`cloud.lid-during-button-wait`, and `cloud.oversize-stream` off the app and
off the scrap: no job set-up, no Print, no app cancel (an injected `cancel`),
nothing to burn. They still arm (the run loop unlocks the latch on the button
press), so by the contract's definition they stay `live` even FIRE-less; with
L1 their only human input is the arm press. Going fully offline, rather than
injecting into a live session, is deliberate: a half-measure would send events
for invented action ids to the real service.

**(b) One real print stays.** `cloud.pause-resume` is the right one: it is
where progress, warm-up and rest, the header limits reaching the engine, and
the laser-off resume lead all show, and the lead is only observable with FIRE
bits. It keeps the service-to-machine path honest once per cloud change, and
with L1 it costs one app job and one arm press.

**(c) `cloud.service-protocol`, new.** Under `POST /controller/stop` (cloud
standby), run the existing gfutilities `Emulator` on the board with the board's
credentials and the canned images (small JPEGs, shipped with the dev package);
the operator, or an agent with a browser, only presses Print in the app (the
emulator's `_button_wait` is a no-op). Judge the session, the hunt, the image
uploads, the pulse download, and the lifecycle events from the emulator's log;
optionally a cancel from the app. Then stop the emulator and
`POST /controller/start`. No motion, no lid, no button, no scrap. This needs
none of the emulator-parity work declined on 2026-08-21; the emulator already
does what this test needs. Because `POST /answer` exists, an agent can run it
end to end with nobody at the machine.

###### L3. Replace eyeballs with the witnesses the machine already has

| Today's confirmation | Replacement |
|---|---|
| "Did it mark the scrap?" (4 tests) | `beam_detect_analog` delta over baseline plus `beam_detect_digital` asserted during the fire window plus `hv_current`, in the existing 8 Hz sample trail. The human mark confirm stays in `laser.emission-witness` only: one per campaign, the bench's calibration of the sensor witness. |
| "Is the button dark / lit?" (5 tests) | the button LED brightness attrs. |
| "Did the gantry move?" (`motion.jog-roundtrip`) | the head accelerometer sampled per jog against the thresholds already established for the liveness gate. This also frees `motion.step-timing-under-load` (auto, requires jog-roundtrip) and the whole live block's prerequisite chain from the attended queue. |
| "Did the head reach the home corner?" (`cloud.gfhome-homing`) | accelerometer motion seen plus a kernel displacement consistent with the corner; stronger follow-up: a lid snapshot matched against a bench-local "head at home" reference frame under `/data/forgetest/`. |
| "Does the panel show the bed?" (`camera.snapshot`) | toggle `pic/lid_led` between two snapshots and require a luminance change (proves a live capture, not a stale frame), plus an optional correlation against a bench-local reference frame for orientation. |
| "Did both burns end abruptly?", "did the head back up?", "does the app show cancelled?" | already in the evidence: the emission and beam trails, the retrace log lines, the `:cancelled` event sent. |

###### L4. Merges where a setup is shared, and two reclassifications

**`cloud.mode-switch` absorbs `cloud.hunt-lid-open` and `cloud.gfhome-homing`.**
Sequenced, not simultaneous, because the two need opposite lid states (the
reason they were kept apart on 2026-08-17): lid open, switch to cloud, session
established, the connect-time hunt completes with the lid open (no "unsafe to
move" before its terminal line, airflow gates unjudged, exhaust off), lid
closed, the re-hunt waited quiet, switch back to grbl, Idle, `$H` with
`homing_mode = gfcloud`, homed within the session timeout. One test, one lid
open and close, carrying both absorbed tests' `covers` (grblhal `src/**`,
forgectrl `super.c`, `cool.*`, `airflow.*`). The standing merge rule applies:
merge only where a setup is shared, never auto tests. Without a fixture this
saves an operator cycle; with one, all three are free and separate ids give
invalidation finer teeth, so the merge is right now and can be unwound later.

**`kernel.fire-line` to `auto`.** It is in the always-required core, so it
costs a person every campaign, but its only prompt is conditional on HV
reporting good at idle, which the chain holds low. Reclassify with a
"cannot start" precondition (the same outcome as an unmet prerequisite, not a
FAIL that closes the campaign) when `laser_pgood` reads good; with L1 the
fixture opens the lid instead. Check `results.jsonl` first: if `laser_pgood`
was 0 in every recorded run, the prompt has never fired.

**`camera.snapshot` to `auto`** via L3.

Optional, lower value: the four GRBL travel-job tests (`motion.button-hold-resume`,
`motion.lid-cancel-home`, `motion.interlock-cancel-home`, `motion.lid-policy-hold`)
share a trivial setup (bed clear, 40 to 60 mm of +X). A merge saves three
baseline cycles and no hand actions; not worth it once L1 exists.

###### L5 (secondary). Finer `covers` maps

Every cloud test covers all of `forgefirm-app`, `gfhardware`, and
`gfutilities`, so a one-line websocket change invalidates six real prints.
With L2 the natural partition is: the protocol test covers
`gfutilities/service/**`, `basemachine.py`, `emulator.py`; the offline behavior
tests cover `gfhardware/machine.py`, `feeder.py`, `switches.py`, `cnc.py`,
`gfcloud.py`, the offline service; the real print stays coarse as the
integration. A websocket change then reruns the protocol test (agent-runnable)
plus one real print. The coverage lint still requires every path covered; this
is a re-partition, not a relaxation. The laser block's `kernel **` coverage is
honest (the kernel is the emission path) and stays.

###### Usability tweak A: the message area goes to the log

The notes at the top of the Campaign card come from `Runner._note` and two
direct appends (`runner.py` ~341, ~588, ~608), a bounded list rendered as
`state.messages`:

| Source | Already recorded elsewhere? |
|---|---|
| baseline boot-reference failure | nowhere else |
| takeover recovery at start-up | nowhere else |
| queue opened / skipped / stopped / driver errored | the queue card renders the live queue state; a stop-on-FAIL shows in the test row |
| leftovers before and after a run | the run's own log pane and the result's `evidence.baseline.pre/post` |

`state.messages` and the `#msgs` div go away. Every `_note` goes to a runner
journal: a `forgetest` logger under the unified tree
(`/data/log/forgefirm/forgetest/`, so it shows in the panel's Logs tab and the
sanitized export like the other daemons), and, when a run is in progress, into
that run's log as well (the leftovers and baseline lines already do). The
Campaign card keeps only the invalidate note and the transient click feedback
(`actmsg`, `qmsg`). Nothing is lost: leftovers stay in evidence, queue outcomes
stay in the rows and the queue card, the raw log stays the bench's record.

###### Usability tweak B: instructions before the test, not popups during it

Every attended test already declares `steps=[...]`, rendered today only under
each row's *details*; `ctx.instruct()` then appears inline in the run card
(`#prompt`) with no warning, and many of those prompts are timed. Two changes:

**Presentation: a standing "What you will do" pane in the run card.** When a
test is selected or started, the run card shows its steps as a numbered
checklist above the log, for the whole run. For an attended queue, the pane
shows the union for the queue before it starts, then the per-test pane takes
over as each test begins. Prompts advance the checklist in place instead of
opening a new box: the current step highlights, the buttons attach to it, done
steps gray out. With `actions=[...]` the pane is typed: a step the fixture
performs is marked *automatic* so the operator knows what not to do, and a
timed step says so up front ("step 3 is timed: about 8 s").

**Structure: timed steps become Ready-gated.** The surprise is partly how the
tests are written: start the move, then `instruct("press NOW")`. Flip the
order wherever a step is timed: `instruct("When you click Ready, the head
starts a 12 s move; press the button about 2 s in")`, Ready, then the test
starts the move and waits with a generous window. `arm_and_fire` already works
this way ("Ready?" then the stream); the button, lid, and interlock steps in
`motion.*`, `laser.pause-resume-lid-cancel`, and the cloud tests do not. This
changes nothing about what is measured, is replayable host-side, and is the
same seam the fixture plugs into later (the fixture fulfills the step with
exact timing; a human gets the Ready gate).

##### 3. Per-test disposition

| Test | Today (the operator does) | Proposal | Kind: no fixture, then with fixture |
|---|---|---|---|
| camera.snapshot | look at the panel | L3 lamp toggle + reference frame | auto, auto |
| camera.lid-privacy | lid x3 | L1 | operator, auto |
| cloud.mode-switch | (auto) | L4 merge host: lid open for the connect, `$H` after the switch back | operator, auto |
| cloud.gfhome-homing | watch, confirm the corner | merged into mode-switch; L3 evidence | eliminated |
| cloud.hunt-lid-open | lid x2, confirm | merged into mode-switch | eliminated |
| cloud.lid-during-button-wait | app job, Print, lid x2, confirm | L2a offline print + L1 lid; LED for "button dark" | operator (one lid), auto |
| kernel.fire-line (core) | conditional lid | L4 precondition, or fixture lid | auto, auto |
| laser.arm-wait-lid | lid x2 | L1 | operator, auto |
| motion.jog-roundtrip | bed clear, confirm motion | L3 accelerometer | auto, auto |
| motion.button-hold-resume | button x2 | L1 | operator, auto |
| motion.lid-cancel-home | lid x4, button x1 | L1 | operator, auto |
| motion.interlock-cancel-home | interlock x2 | L1 | operator, auto |
| motion.lid-policy-hold | lid x2 | L1 | operator, auto |
| laser.emission-witness (core) | scrap, ack, arm, confirm mark + dark | keep the mark confirm; LED for dark | live, 1 press |
| laser.disarm-in-hold | ack, arm, confirm | L3 (Hold state + armed + LED) | live, 1 press |
| laser.armed-kill | ack, arm x2, judge x2 | L3 trails | live, 2 presses |
| laser.pause-resume-lid-cancel | ack, arm, button x2, lid x2, confirm | L1 + L3 | live, 1 press |
| cloud.lid-interlock-abort | 2 app jobs, 2 Prints, arm x2, lid x4, interlock x2, confirm x2 | L2a offline FIRE-less + L1 | live, 2 presses, no app, no scrap |
| cloud.pause-resume | app job, Print, arm, button x2, confirm x2 | keep real (L2b); L1 for pause/resume; L3 | live, 1 press + 1 app job |
| cloud.oversize-stream | full-bed raster in the app, Print, arm, 2 min burn, button x2, app cancel, confirm | L2a synthesized 40 MiB FIRE-less job + L1; injected cancel | live, 1 press, no app |
| cloud.pause-cancel-paths | 2 app jobs, 2 Prints, arm x2, button, lid x2, app cancel, confirm | L2a + L1 | live, 2 presses, no app |
| cloud.service-protocol (new) | Print in the app | L2c, agent-runnable | operator (app only) |

##### 4. The campaign after

| | Today | L2 + L3 + L4 + tweaks, no fixture | + L1 fixture | + fixture arm press (opt-in) |
|---|---|---|---|---|
| Catalog | 45 | 44 | 44 | 44 |
| Unattended | 25 | 28 | 41 | 41 |
| Operator actions | ~80 | ~45 (app 7 jobs to 1, confirms 16 to 2) | ~16 (11 arm presses, 1 app job, scrap, 1 mark) | ~5 |
| Attended minutes | 111 | ~85 | ~60, sitting through the live block | the same, hands-free |

The floor is by design: the always-required core wants one real emission
witness per campaign, so every campaign needs a person with eye protection in
the room for one burn, and the contract wants the arm press through the
controller's normal path.

##### 5. Lines not crossed, and the one policy question

- A FIRE-less armed run stays `live`. It is "emission possible" by the
  contract's conservative definition, even though it needs no scrap.
- No software switch injection in the three consumers' safety paths on the
  board. The fixture exercises the real edge, the real hardware button latch
  (`laser.pause-resume-lid-cancel` checks it SET), and the real interlock
  latch drive.
- forgetest never touches the laser latch. The offline service never talks to
  the real service. The protocol test never moves the machine.
- The cloud `requires` chains stay minimal (the 2026-08-17 rule), and every
  re-ported test gets its host-side replay (`tests/test_cloud_suite.py` and
  friends) before the operator sees it.
- **The policy question: may the fixture press the button for the arm?** A
  fixture press goes through the controller's normal path (the hardware
  input), so the consent becomes the queue's live acknowledgment with the
  operator present. Recommendation: human by default, since the operator is
  in the room for the fire watch anyway; fixture arm presses as an explicit
  opt-in (a physical enable on the fixture's button channel, plus the page's
  live ack, plus the per-action record in evidence).

##### 6. Decisions that are the operator's

1. Build the fixture? It is the single biggest lever and a small build (three
   relays, an interposer harness at J4/J5/J8, a Pico W). Everything else here
   stands without it.
2. Fixture arm presses: never, or opt-in under the live ack?
3. Merge mode-switch + hunt-lid-open + gfhome-homing now, or keep them
   separate and wait for the fixture?
4. Is `cloud.service-protocol` a catalog test (carries `covers` for the
   service layer, participates in inheritance) or a bench tool? Recommendation:
   a catalog test.

##### 7. Order of work

1. **DONE 2026-08-22. forgetest only, no new hardware:** L3, L4, usability
   tweaks A and B, Ready-gating the timed steps, and per-test implementation
   hashing. Two tests gone, three to `auto`, the confirms down to two, the
   page quiet, the operator reading the whole list once instead of racing
   popups.
2. **The cloud split:** L2a offline service and the pulse-file tooling, the
   four behavior tests re-ported onto it: **DONE 2026-08-22.** L2c, the
   protocol test with the existing emulator: **code-complete 2026-08-23,
   bench owed** (see COLD PICKUP above).
3. **The fixture:** L1 hardware and the `ctx.act()` seam, with the fallback
   wired so a bench without a fixture behaves exactly as today.
4. **L5** once the cloud split exists.

Each step is a catalog change, so each lands with its coverage map kept
current (`python3 -m forgetest.coverage --enforce`) and is proven in the
order the working rules require: host test, then a bench drill logged in
`CAMPAIGN-LOG.md`.

### The kernel configuration review (tree-root working file), merged 2026-08-24

The report `KERNEL_CONFIG_REVIEW.md`, verbatim: its status section is the record of the two rounds that built the board-only kernel (what each finding became, with its proof), and the original report below it is the evidence they were decided on. Its "cannot start cut" row carries the correction the campaign forced. The suggestions it left are BRINGUP item 20; the cosmetic upstream dmesg lines are left by decision. The file is deleted.
#### ForgeFIRM kernel configuration review (2026-08-24)

##### Status (2026-08-24): what was done, what remains

Section numbers below refer to the original report that follows.

###### Done: implemented, built, bench-validated, committed and pushed

Commits: `meta-openglow e1bb4ac` (kernel trim) and `8f8b540` (module pin),
`kernel-module-glowforge 615a36f`, `forgefirm cb9cd53` (BRINGUP item 21, CAMPAIGN-LOG
entry "2026-08-24: the kernel built for one board"). Bench validation ran on dev image
20260824164619 (built from the same tree state before the commits); the post-commit
build that adds the module pin is what the acceptance campaign runs on.

| Report item | What was done | Proof |
|---|---|---|
| 1.1 `evbug` autoload | `# CONFIG_INPUT_EVBUG is not set` | Not in `lsmod`; no `evbug:` lines in dmesg |
| 1.2 dropped lockup-panic lines | `DETECT_HUNG_TASK=y`, `SOFTLOCKUP_DETECTOR=y`; the two `BOOTPARAM_*_PANIC=y` lines now land | `/proc/sys/kernel/hung_task_panic` = 1, `softlockup_panic` = 1 |
| 1.3 `MULTIPLEXER`/`MUX_GPIO` requested `=y`, landed `=m` | Written as `=m` (plus `MUX_MMIO=m`); every fragment line now matches the built `.config` (checked line by line) | Configure-check diff: no unlanded lines |
| 1.4 distro/kernel mismatch | Bluetooth, sound/ASoC, NFS/SUNRPC, PCI/PCIe, ext2/ext3, `IPV6_SIT` off. IPv6 core kept (see Remaining) | dmesg has none of them; `sit0` gone |
| 1.5 DT leftovers | `&asrc`, `&usbphy1/2`, `&usbphynop1/2`, `&usbmisc` disabled | Built DTB shows `status = "disabled"`; the phy/dummy-supply lines are gone from dmesg |
| 1.6 `glowforge_pic` without `spi_device_id` | Table `{ "pic" }` + `MODULE_DEVICE_TABLE(spi)`; pinned at `615a36f` | `alias=spi:pic` in the built module; the boot warning clears on the post-commit image |
| 2.1 no crash record | `PSTORE`, `PSTORE_RAM`, `PSTORE_CONSOLE`; `ramoops@2ff00000` (1 MiB, `no-map`, 32 KiB records, 256 KiB console, 16-byte ECC) in the region the factory bootloader already holds back; `pstore` line in fstab | Forced `sysrq-c`: reboot on the timeout, next boot 0 header errors, `dmesg-ramoops-0` (24 KB, "Panic#1 Part1") and `console-ramoops-0` (ends "Kernel panic - not syncing: sysrq triggered crash / Rebooting in 10 seconds.. / ECC: No errors detected") |
| 2.2 `panic=10` only on the cmdline | `CONFIG_PANIC_TIMEOUT=10` | `/proc/sys/kernel/panic` = 10; the DTS fallback boot now reboots on panic too |
| 2.4 SDMA firmware never loads | Decision (a): ROM scripts stay; `linux-firmware-imx-sdma-imx6q` and `-imx7d` removed from `MACHINE_FIRMWARE`; `dmas`/`dma-names` deleted from `&ecspi2` | `/lib/firmware/imx` gone; dmaengine summary holds no channels; PIC probes and reads in PIO |
| 4.1 built-in dead weight | USB, Ethernet/PHY/PTP/PPS, CAN, BT, SATA/SCSI, PCI, MTD/NAND/UBI, RAM disks, JFFS2/UBIFS/NFS/FUSE/autofs/quota/ISO/UDF/MSDOS/binfmt_misc, DRM_IMX + HDMI/LVDS/panels/bridges/MXSFB, FB/fbcon/logo/VT/backlight, all audio, touchscreens/HID/mouse/serio/beeper/RC, PMICs/expanders/W1/SIOX/other-board sensors and bus glue, ten other i.MX SoCs + Vybrid, PSCI, TEE, `ARCH_MULTI_V6` (ARMv7-only code), suspend/kexec/crash-dump/ATAGs/swap/HIGHMEM, three cpufreq governors, BFQ/Kyber, connector, five initrd decompressors. Kept by decision: `DRM` + `DRM_ETNAVIV`, `IMX_IPUV3_CORE`, `DEBUG_FS`, `DEVMEM`, `MAGIC_SYSRQ`, `KPROBES`, `PERF_EVENTS`, `IKCONFIG_PROC`, `NETFILTER`, `SMP` | `.config` 1634/245 to 819/32 (`=y`/`=m`); zImage 9.13 MB to 4.76 MB; vmlinux text 14.7 MB to 7.8 MB; MemTotal +9.4 MB |
| 4.2 253 modules shipped, 27 needed | `MEDIA_SUPPORT_FILTER=y` + `SUBDRV_AUTOSELECT` (the DVB tree gone), other sensors off; `kernel-modules` replaced by the board's 13-module list in `glowforge.conf` (dependencies follow through modules.dep RDEPENDS; the Wi-Fi ciphers are built in so nothing loads by alias from the rootfs) | 31 `kernel-module-*` packages; built modules 9.7 MB to 2.4 MB; 31 loaded on the bench, all needed |
| 4.3 firmware dead weight | `firmware-imx-epdc`, `firmware-imx-vpu-imx6q`, both SDMA packages removed | `/lib/firmware` 7.7 MB to 2.6 MB |
| 5.1 `DRM_IMX` removal vs the GPU demosaic | Removed; verified | `/dev/dri/renderD128` present, `card1` gone; lid and head streams ran with `gpu: GLES2 debayer up`, GPU IRQs 0 to 135 |
| New: virtual console gone | `USE_VT = "0"` so no tty1 getty respawns against a device that no longer exists | inittab carries only `ttymxc0` |

Also validated on the live image: every node binds, `devices_deferred` empty, Wi-Fi
associated with `regulatory.db` loaded (country US), switches on `event0`, no QA
warnings in the build.

Lessons now written into the fragment's comments: the defconfig never names `PM`,
`REGULATOR`, `EXT4_FS`, `CONFIGFS_FS`; it got them by selection from suspend, the
PMIC drivers, ext3 and the USB gadget, so a trimmed fragment must pin what it keeps.
`KEYBOARD_ATKBD` selects `SERIO`, `I2C_IMX` selects `I2C_SLAVE`, `DRM_MXSFB` selects
`DRM_MXS`, `SOC_VF610` selects `PINCTRL_VF610`.

###### Remaining: issues found and not acted on

State after round 1. Round 2 (below) closes 1.4 (IPv6 is on), 2.5 (firmware set),
2.6 (performance governor), the `consoleblank` and spi-imx lines, and the empty-ring
message; the cosmetic upstream lines stand.

| Report item | Issue | Suggested action |
|---|---|---|
| 1.4 | `IPV6=y` while `DISTRO_FEATURES` removes `ipv6`; `forgectrl/src/auth.c` references `AF_INET6` | Decide once: either put `ipv6` back into the distro (the kernel matches the code) or make `auth.c` IPv4-only and drop `IPV6` from the kernel |
| 2.5 | `wlcore: WARNING Detected unconfigured mac address in nvs` / `This default nvs file can be removed`: `linux-firmware-wl18xx` ships the generic `wl1271-nvs.bin` (and `wl127x-nvs.bin`, three unused `wl18xx-fw*` variants, three `TIInit_*.bts` BT scripts) | Cosmetic. A `linux-firmware` bbappend can drop the NVS and BT files; keep all four `wl18xx-fw*` unless every board is PG 2.2 |
| 2.6 | cpufreq policy is `ondemand` from the defconfig default; nothing sets a governor. A single core with a `SCHED_FIFO` producer (BRINGUP item 16) idles at 396 MHz | Policy, not a defect: `performance` while a job runs (forgectrl) or `CPU_FREQ_DEFAULT_GOV_PERFORMANCE`; measure against item 16 first |
| 3 | `Unknown kernel command line parameters "consoleblank=0 board=glowforge"`: `consoleblank` is a VT parameter and VT is gone; `board=` is for userspace | Drop `consoleblank=0` from the uEnv (forgefirm-uenv); `board=` stays |
| 3 (new) | `spi_imx 200c000.spi: error -ENODEV: can't get the TX DMA channel!` at ERR level at every boot: upstream logs the absent channel with `dev_err_probe` and continues in PIO | Cosmetic. Accept, or a one-line layer patch demoting it (a 14th patch in the bbappend) |
| 3 | `hwmon hwmon1: temp1_input not attached to any thermal zone` (lm75 with `THERMAL_OF`) | Cosmetic; leave |
| 3 | `glowforge_cnc cnc: cannot start cut; no data enqueued` at 31 s after boot | WRONG, corrected 2026-08-24: those occurrences were the SDMA clocks gated by the ecspi2 dmas deletion (CAMPAIGN-LOG 2026-08-24, "the SDMA clocks, held by nobody"); no motion on any image since the trim. Someone issues a run on an empty ring at controller start (forgectrl liveness probe or grblHAL init); worth finding and silencing, in the module's owner's time |
| 3 | fw_devlink "Fixed dependency cycle(s)" (46 lines), "Static allocation of GPIO base is deprecated" (7), the SDIO "voltages below defined range" and "read-only switch" lines | Upstream behavior; leave |
| 5.6 | `kas/README.md` backlog #2 said the PWM prescaler port was obsolete, the PIC SPI delay a bring-up TODO, and `reg-userspace-consumer` enabled by the fragment | Done: the paragraph now describes patches 0009 and 0004 as carried, the 12 V rail without a consumer node, and the config fragment as the board's kernel (uncommitted in `forgefirm`) |

###### Remaining: suggestions not acted on

State after round 1. Round 2 closes 5.2 (`SMP=n`) and the pstore export; 5.5 is
answered (kept, root-only exposure); the firmware split is done as part of 2.5.

| Report item | Suggestion | Why it waits |
|---|---|---|
| 5.2 | `CONFIG_SMP=n` on the single core (no spinlock/IPI overhead, `NR_CPUS=4` gone) | Needs a measurement against BRINGUP item 16 (producer stalls) before it is worth a platform change |
| 5.5 | `KPROBES`, `PERF_EVENTS`, `BPF_SYSCALL`, `DEBUG_FS`, `DEVMEM`, `MAGIC_SYSRQ` off for release | One kernel serves both images; a release-only config needs a second kernel variant or a fragment switch, which is more machinery than the gain |
| 4.3 | Split `linux-firmware-wl18xx` to the one `wl18xx-fw-*` this hardware boots | Only once every board's PG revision is known |
| 2.1 follow-up | Have forgectrl's log export include `/sys/fs/pstore` (and clear records after export) | The records exist now; the consumer is a forgectrl feature |
| 4.2 note | Five helper modules are built and not shipped (`crc7`, `crc-ccitt`, `libcrc32c`, `st-accel-spi`, `st-sensors-spi`; the last two are selected by the accelerometer driver) | 0.1 MB of build output; harmless |

###### Round 2 (2026-08-24, later): implemented, host-proven, committed, built as images/20260824200726 (unflashed)

| Item | What was done | Proof so far |
|---|---|---|
| 1.4 IPv6 | `ipv6` back in `DISTRO_FEATURES` (busybox IPv6 + ifupdown inet6, openssh/ntp/rsyslog IPv6); busybox `udhcpc6` (+RFC 3646) with a hook script (`default6.script`) and a `wlan0 inet6 manual` stanza that starts it; forgectrl listens dual-stack (`ulfius_init_instance_ipv6`, `U_USE_ALL`), grblHAL's TCP:23 is an `AF_INET6` socket with `IPV6_V6ONLY=0`, forgetest binds `::` (dual-stack). The kernel already did SLAAC (the board holds a ULA and the GUA prefix route); the DHCPv6 address is what the client adds | forgectrl `-Werror` build + 11 tests, grblHAL build + 4 CI tests, forgetest 252 tests, bind smoke (`AF_INET6`, v6only 0). Bench (dev 20260824201945): proven end to end. A GUA from pfSense's Kea via `udhcpc6` (lease 7200 s, renew OK); ports 22/23/8080/8090 answer on it from a host on another VLAN; IPv6 egress to the WAN gateway works. The earlier "no GUA" was an OpenWrt access point on the bench VLAN still running RA + DHCPv6 in server mode (its NoAddrsAvail Advertise beat pfSense's, and busybox keeps the first Advertise); disabled by the operator, the other two were already off |
| 2.5 firmware files | `linux-firmware_%.bbappend`: only `wl18xx-fw-4.bin` stays (the current factory image ships exactly that plus `wl18xx-conf.bin`); the `wlcommon` package (NVS files, BT `.bts`) is no longer pulled | Factory `/factory/img1/lib/firmware/ti-connectivity` = `wl18xx-conf.bin` + `wl18xx-fw-4.bin`. Bench: Wi-Fi up, no NVS warning |
| 2.6 / BRINGUP 16 | `CPU_FREQ_DEFAULT_GOV_PERFORMANCE=y`, ondemand and the other governors off: 996 MHz always. Item 16 carries the re-measure plan | Bench: `scaling_governor` = performance; the item-16 drill (clamps, min margin) on this image |
| 3 `consoleblank=0` | Dropped from `uEnv.txt` and the U-Boot default env (`glowforge.h`) | Bench: no "Unknown kernel command line parameters" line |
| 3 spi-imx ERR line | Patch 0014: `dev_err_probe` only when the failure is not `-ENODEV` (no DMA described = PIO by design) | Bench: no `can't get the TX DMA channel` line |
| 3 `cannot start cut` | Found: grblHAL's `issue_run` already treats a run on an empty ring as an ordinary race (`idle` + `ENODATA`, "already consumed"); only the module logged it at ERR. `cnc.c` now `dev_dbg`s it | Module compiles; bench: line gone from dmesg |
| 5.2 `SMP=n` | `# CONFIG_SMP is not set` (UP kernel: GPT tick, no IPIs, no spinlock cost) | Configure check + bench boot owed |
| 2.1 follow-up | forgectrl's log export stages `/sys/fs/pstore/*` under `system/pstore/` (README lists it) | forgectrl build + tests; bench: export after the sysrq record |
| Fluff | `nano` (+`file`/libmagic, 8.7 MB) release-image only via `IMAGE_INSTALL:remove`, kept on dev; `BAD_RECOMMENDATIONS += eudev-hwdb` (7.7 MB of USB/PCI IDs); `python3-urllib3` bbappend drops its pyOpenSSL/cryptography recommendation (~6 MB: cryptography, pyopenssl, cffi, pycparser, ply; nothing imports them) | Build + campaign |

Fluff found and not acted on: the `python3` meta-package installs `python3-modules` (tkinter, idle, 2to3, pydoc, ensurepip, venv, debugger, doctest, asyncio, multiprocessing, xmlrpc: ~10 MB) where the apps declare only `python3-core` + a few modules; replacing `python3` with the explicit module set needs an import audit of gfcloud/gfhome/gfhardware/gfutilities (the campaign's cloud tests are the check). `libgnutls30`, `libunistring5`, `nettle`, `libgmp10` (~4.9 MB) are installed with no package depending on them and no binary on the rootfs linking them; a `PACKAGE_EXCLUDE` experiment on a build would name the holder if there is one. `v4l-utils` (1.8 MB) is a declared runtime dependency of forgectrl and gfhardware (media-ctl); `shadow` is pulled by openssh/ntp/dbus; `curl` is the update downloader; `openssl-bin` serves `ca-certificates`.

Debug features in release (5.5): no runtime cost when unused; the exposure is root-only (`/dev/mem`, debugfs, sysrq over a physically attached console, kprobes/perf/BPF with unprivileged BPF already off) and root can load modules anyway, so a compromise of root is the actual boundary. Kept.

###### Owed, in the operator's hands

A GRBL job on the image, then the full acceptance campaign (platform change) on the
post-commit build, which also confirms the `spi_device_id` warning is gone at boot.

##### Original report

Report only at the time of writing. Nothing was changed on the bench, in any repo, or in the build tree.

##### Scope and evidence

| Source | What was examined |
|---|---|
| `meta-openglow/.../linux-fslc/glowforge.cfg` + `linux-fslc_%.bbappend` | The config fragment and the 13 patches |
| `arch/arm/boot/dts/nxp/imx/glowforge.dts` + `imx6qdl.dtsi`/`imx6dl.dtsi` defaults | Which peripherals the board actually enables |
| Bench board, fresh boot (9 min uptime) | `dmesg`, `/proc/config.gz`, `lsmod`, platform/i2c/spi/sdio driver bindings, `/proc/interrupts`, `/proc/iomem`, debugfs gpio + clk tree, cpuidle/cpufreq, sysctl, `/lib/modules`, `/lib/firmware` |
| WSL `forge-yocto` build tree (`linux-fslc/6.12.20+git`) | Built `.config`, `imx_v6_v7_defconfig`, module sizes, `imx-base.inc`, the image manifests |
| `forgectrl/src`, `python3-gfhardware`, `Glowforge-Utilities`, `kernel-module-glowforge/src` | Which kernel interfaces userspace consumes |

The running kernel config is byte-identical to the built `.config` (the board runs the
current build). Kernel: `6.12.20-fslc`, `SMP PREEMPT`, zImage 9.1 MB, vmlinux text
14.7 MB; 1634 `=y` and 245 `=m` symbols against a defconfig of 403 + 63.

##### 1. Misconfigurations (wrong today)

###### 1.1 `evbug` autoloads and logs every switch event to the kernel log
`CONFIG_INPUT_EVBUG=m` (inherited from the defconfig). `evbug` carries a catch-all
`MODULE_DEVICE_TABLE(input, ...)`, so udev loads it for the `switches` gpio-keys device on
every boot (`lsmod` shows it; `dmesg` shows `evbug: Connected device: input0` and
`evbug: Event. Dev: input0, Type: 5, Code: 4, Value: 1` for the HV-enable readback).
Every lid, button, interlock, and HV-enable transition lands in `dmesg`/rsyslog for the
life of the machine. It is a kernel debugging aid, nothing consumes it.
Fix: `# CONFIG_INPUT_EVBUG is not set` in `glowforge.cfg`.

###### 1.2 Two safety lines of the fragment were silently dropped
`glowforge.cfg` requests `CONFIG_BOOTPARAM_HUNG_TASK_PANIC=y` and
`CONFIG_BOOTPARAM_SOFTLOCKUP_PANIC=y` with the comment "Hung-task and softlockup also
panic on the same reasoning". Neither symbol exists in the built `.config`, because their
parents are off: `# CONFIG_DETECT_HUNG_TASK is not set`, `# CONFIG_SOFTLOCKUP_DETECTOR is
not set`. On the board `/proc/sys/kernel/hung_task_panic` and `softlockup_panic` do not
exist. Only `PANIC_ON_OOPS` is live; a hard lockup or a hung feeder does not reach the
laser-safing panic notifier the fragment describes.
Fix: add `CONFIG_DETECT_HUNG_TASK=y` and `CONFIG_SOFTLOCKUP_DETECTOR=y` (which pulls
`LOCKUP_DETECTOR`) ahead of the two `BOOTPARAM_*` lines; consider
`CONFIG_HARDLOCKUP_DETECTOR=y` (the buddy detector is available: `HAVE_HARDLOCKUP_DETECTOR_BUDDY=y`,
though on one core it has no buddy, so the perf-based NMI detector is the only real one and
arm32 lacks it; softlockup is the practical ceiling). Verify after the build with
`ls /proc/sys/kernel/{hung_task,softlockup}_panic`.

###### 1.3 Two more fragment lines are not what landed
`CONFIG_MULTIPLEXER=y` and `CONFIG_MUX_GPIO=y` are requested, `=m` is what the build
produced (both load fine as modules; `mux_gpio`, `mux_mmio`, `mux_core` are in `lsmod`).
Functionally harmless, but the fragment does not describe the kernel. Either write `=m`
(and `CONFIG_MUX_MMIO=m`, which the IPU CSI muxes need and which nothing pins) or find out
why the merge demoted them.

###### 1.4 Distro features and the kernel disagree
`forgefirm.conf` removes `bluetooth bluez5 alsa nfs pci ipv6 ext2` from `DISTRO_FEATURES`,
but the kernel is built from the multi-board `imx_v6_v7_defconfig`, which does not follow
distro features. The kernel therefore still carries, built in:

| Feature removed from the distro | Still in the kernel |
|---|---|
| bluetooth | `BT=y`, `BT_HCIUART=y` (+LL, serdev), `BT_BNEP=m`; `Bluetooth: Core ver 2.22` in dmesg. The WL1805 is Wi-Fi only (no BT core, no serdev node). |
| alsa | `SOUND/SND/SND_SOC=y` with the whole i.MX ASoC stack and ten codec drivers; `fsl-asrc` binds to the SoC's ASRC (16 clocks + an IRQ) because `imx6qdl.dtsi` leaves `&asrc` `okay`. "No soundcards found." Audio/buzzer is not a planned feature. |
| nfs | `NFS_FS=y` (v3, v4, v4.1, v4.2) + SUNRPC; `rpciod`, `xprtiod`, `nfsiod` kthreads at boot. |
| pci | `PCI=y`, `PCIE_DW_HOST=y`, `PCI_IMX6=y`, MSI, ASPM. No PCIe node is enabled. |
| ipv6 | `IPV6=y`, `IPV6_SIT=y` (creates the `sit0` device seen in `/sys/class/net`). `forgectrl/src/auth.c` references `AF_INET6`, so keep IPv6 core unless that is resolved; `IPV6_SIT` has no consumer. |
| ext2 | `EXT2_FS=y`, `EXT3_FS=y` as separate drivers; ext4 mounts both formats. |

###### 1.5 Device-tree leftovers enabled by the SoC defaults
`imx6qdl.dtsi` enables these without a `status`, and the board has no consumer:
- `usbphy1`/`usbphy2` (mxs_phy), `usbphynop1`/`usbphynop2`, `usbmisc`: no USB controller
  node is enabled (`usbotg`, `usbh1` are `disabled`, as in the factory tree). They produce
  `supply phy-3p0 not found, using dummy regulator` and `dummy supplies not allowed for
  exclusive requests (id=vbus)` at every boot.
- `asrc`: `status = "okay"` by default; binds `fsl-asrc` as above.
Fix (DTS): `status = "disabled"` on `&asrc`, `&usbphy1`, `&usbphy2`, `&usbphynop1`,
`&usbphynop2`, `&usbmisc`.

###### 1.6 `glowforge_pic` has no `spi_device_id` table
`SPI driver glowforge_pic has no spi_device_id for glowforge,pic` at every boot. The SPI
core wants an `spi_device_id` table alongside `of_device_id` (module alias generation and
the non-OF match path). `kernel-module-glowforge/src/glowforge.c` has `pic_dt_ids` only.
Hygiene, no functional effect while the device comes from the DT.

##### 2. Incomplete configuration

###### 2.1 No crash record survives a panic
`# CONFIG_PSTORE is not set`; no ramoops. The design is `PANIC_ON_OOPS` + `panic=10`, so
the machine reboots ten seconds after any oops and the reason is gone unless a serial
console happens to be attached. The factory environment carried
`ramoops.mem_address/mem_size/record_size/console_size` on the command line for exactly
this reason (visible in the U-Boot `mmcargs`). Recommend `CONFIG_PSTORE=y`,
`CONFIG_PSTORE_RAM=y`, `CONFIG_PSTORE_CONSOLE=y` (and `PSTORE_PMSG` if forgectrl wants to
leave breadcrumbs), backed by a `ramoops` node under `reserved-memory` in `glowforge.dts`
so it does not depend on the bootloader environment. The record is then readable from
`/sys/fs/pstore` after the reboot, and forgectrl's log export can pick it up.

###### 2.2 `panic=10` lives only in the boot arguments
`CONFIG_PANIC_TIMEOUT=0`. The DTS fallback `bootargs` has no `panic=`, so a boot that falls
through to the DTS (the documented recovery ladder) hangs on panic instead of rebooting.
`CONFIG_PANIC_TIMEOUT=10` makes the behavior independent of the environment. (Keep the
cmdline value too; the cmdline wins when present.)

###### 2.3 Lockup detectors (see 1.2).

###### 2.4 SDMA RAM firmware never loads (decided: keep the ROM scripts, drop the packages)
`imx-sdma 20ec000.dma-controller: external firmware not found, using ROM firmware`.
`IMX_SDMA=y` probes at 0.42 s, before the rootfs, so `sdma-imx6q.bin` (installed by
`linux-firmware-imx-sdma-imx6q`) is never used; the ROM scripts run. The pulse script is
loaded by glowforge.ko itself (halfword 7680), not by the firmware.

Decision: the ROM-script behavior stays, and the two SDMA firmware packages
(`linux-firmware-imx-sdma-imx6q`, plus `linux-firmware-imx-sdma-imx7d`, which the
`imx-mainline-bsp` override also pulls) leave `MACHINE_FIRMWARE`. This is a runtime no-op:
nothing on the board runs on the RAM firmware. Loading it deliberately was rejected because
no client gains from it and it would let a PIC SPI burst run through SDMA channel 0 next to
the pulse channel during a job (channel 0 has the highest priority).

SDMA client inventory behind that decision (running board + DT + driver source):

| Client | `dmas` in the SoC dtsi | Use today | Scripts needed |
|---|---|---|---|
| glowforge.ko pulse ring | n/a (driven directly, channel 26, priority 6, EPIT1 event 16) | The only real user | Its own script, loaded by the module |
| ecspi2 (PIC) | yes | Two dmaengine channels held since probe, 0 bytes transferred; `spi-imx` uses DMA only for transfers of 64 bytes or more, PIC transactions are 3 bytes and the largest observed bucket is 32-63 bytes (full register-map reads). Only the sysfs `raw` write can cross 64 bytes; today that path logs `sdma firmware not ready!` once, and the SPI core retries in PIO and disables DMA for the controller for good. | RX ROM; TX `mcu_2_ecspi` is a RAM script on i.MX6Q/DL (ERR009165 path) |
| uart1 (console) | yes | Never; the console port is excluded from DMA | n/a |
| uart2 | yes | Enabled in the DTS, nothing opens `ttymxc1` | ROM |
| asrc | yes | Enabled only by the dtsi default, never opened (removal list) | RAM |
| i2c1/2/4 | none | PIO | n/a |
| uSDHC x3, IPU/CSI, VPU, GPU, CAAM | own DMA masters | not SDMA | n/a |
| mxs-dma (`110000`) | separate APBH engine | no client | n/a |

`/sys/kernel/debug/dmaengine/summary` lists exactly the two ecspi2 channels; the SDMA IRQ
count is static at idle (all 170 came from boot: script load and verify, device open, 40 V on).
The firmware layout in the binary checks out against the DTS comment: v3.6,
`ram_code_size` 2754 bytes = 1377 halfwords at 6144, so RAM code spans 6144-7520 and the
highest script entry is 7419; the pulse script at 7680-7819 is clear.

Companion change (DTS): drop `dmas`/`dma-names` from `&ecspi2`. That releases the two held
channels, makes the PIC's PIO behavior explicit instead of relying on the 64-byte threshold
and the fallback path, and leaves the pulse ring as the SDMA's only client, which is what the
timing argument in BRINGUP item 16 assumes.

###### 2.5 Wi-Fi NVS
`wlcore: WARNING Detected unconfigured mac address in nvs, derive from fuse instead` and
`This default nvs file can be removed from the file system`: the generic
`wl1271-nvs.bin` from linux-firmware is installed. The MAC comes from the chip fuse anyway,
so this is cosmetic. Removing the file (or shipping a real NVS) silences it.

###### 2.6 cpufreq policy is the defconfig default
`CONFIG_CPU_FREQ_DEFAULT_GOV_ONDEMAND`, OPPs 396/792/996 MHz, `ondemand` at runtime,
nothing in forgectrl sets a governor. On a single core with a `SCHED_FIFO` step producer
(BRINGUP item 16), the 396 MHz idle floor plus ondemand's sampling delay is a latency
source at job start and between moves. Not a defect; a policy to decide. `performance`
while a job runs (forgectrl) or `CONFIG_CPU_FREQ_DEFAULT_GOV_PERFORMANCE` (mains-powered
machine, SoC at 47 C with 85 C passive trip) are the two levers. Drop
`CONSERVATIVE`/`POWERSAVE`/`USERSPACE` governors either way.

##### 3. dmesg review (fresh boot)

No driver probe failed; `/sys/kernel/debug/devices_deferred` is empty; every DTS node
binds (`cnc`, `thermal`, `pic`, `head`, both cameras, 3 accelerometers, lm75, wl18xx,
watchdog, 3 PWMs, EPIT1/2). The SDIO CRC watch (BRINGUP item 11) shows 0 events this boot.

| Line | Cause | Action |
|---|---|---|
| `evbug: Event. Dev: input0 ...` (every switch transition) | `INPUT_EVBUG=m` autoloaded | Remove (1.1) |
| `SPI driver glowforge_pic has no spi_device_id for glowforge,pic` | Missing id table in glowforge.ko | Add table (1.6) |
| `imx-sdma: external firmware not found, using ROM firmware` | Built-in driver, firmware on rootfs | Decided: ROM scripts stay, packages go (2.4) |
| `mxs_phy 20c9000.usbphy: supply phy-3p0 not found` x2, `usb_phy_generic usbphynop1/2: dummy supplies not allowed for exclusive requests` | USB PHY nodes enabled with no USB controller | Disable in DTS (1.5) |
| `imx-drm display-subsystem: [drm] Cannot find any crtc or sizes` + 4 `card1-crtcN` kthreads | `DRM_IMX=y` with no display | Remove DRM_IMX (4.1) |
| `Bluetooth: Core ver 2.22 ...`, `HCI UART protocol H4/LL registered` | `BT=y` | Remove (1.4) |
| `ALSA device list: No soundcards found.` | `SND=y` | Remove (1.4) |
| `usbcore: registered new interface driver r8152/lan78xx/asix/...` (13 lines) | USB net drivers built in, no USB | Remove (4.1) |
| `CAN device driver interface`, `can: raw/bcm/gw` | `CAN=y`, `CAN_FLEXCAN=y` | Remove (4.1) |
| `SCSI subsystem initialized`, `libata version 3.00 loaded`, `kworker/R-ata_sff` | `SCSI=y`, `ATA=y` | Remove (4.1) |
| `PCI: CLS 0 bytes, default 64`, `vgaarb: loaded` | `PCI=y`, `VGA_ARB=y` | Remove (4.1) |
| `jffs2: version 2.2. (NAND)`, `fuse: init`, `NFS: Registering the id_resolver`, `RPC: Registered ...` | JFFS2/FUSE/NFS built in | Remove (4.1) |
| `brd: module loaded` + 16 `ram0..15` in `/proc/partitions` | `BLK_DEV_RAM=y`, 16 x 64 MiB | Remove |
| `mxs-dma 110000.dma-controller: initialized` | APBH DMA (GPMI NAND) | Remove `MXS_DMA` |
| `hwmon hwmon1: temp1_input not attached to any thermal zone` | `THERMAL_OF` + lm75 without a zone | Cosmetic |
| `Unknown kernel command line parameters "board=glowforge"` | uEnv passes it for userspace | Cosmetic |
| `No ATAGs?` | `ATAGS=y` on a DT boot | Drop `ATAGS`/`ATAGS_PROC` |
| `snvs_rtc: setting system clock to 1970-01-01` | No RTC battery | Expected; ntpd sets time |
| `Fixed dependency cycle(s) with ...` (about 40 lines) | fw_devlink over the video-mux graph and the CSI muxes | Upstream noise, harmless |
| `gpio gpiochipN: Static allocation of GPIO base is deprecated` x7 | Upstream `gpio-mxc` | Harmless |
| `sdhci-esdhc-imx 2190000.mmc: card claims to support voltages below defined range` | WL18xx advertises 1.8 V, host is `no-1-8-v` | Harmless |
| `mmc1: host does not support reading read-only switch` | `broken-cd` SD slot | Harmless |
| `imx_media_common/imx6_media/...: module is from the staging directory` | imx-media lives in staging | Expected |
| `glowforge: loading out-of-tree module taints kernel` | Expected | None |

##### 4. Drivers that are configured and unnecessary

Evidence for "unnecessary": no node in `glowforge.dts` (and none in the factory 4.14 tree
either), no driver bound on the running board, and no consumer in forgectrl, gfhardware,
gfutilities, or grblHAL. The board's peripheral set is: UART1/2, eCSPI2 (PIC), I2C1/2/4,
uSDHC1 (WL1805 SDIO) / 2 (SD) / 3 (eMMC), PWM1/2/4, EPIT1/2, SDMA, MIPI CSI-2 + IPU CSI,
VPU (coda), GPU (etnaviv, used by forgectrl's surfaceless-EGL demosaic), CAAM (RNG),
OCOTP, SNVS RTC, WDOG1, tempmon, GPIO switches/leds, the glowforge nodes.

###### 4.1 Built in (`=y`), removable from `glowforge.cfg`
These are what the 9.1 MB zImage is made of. Grouped; each group is one `# CONFIG_X is not
set` cluster in the fragment (the defconfig sets them, the fragment must unset them).

| Group | Symbols (parents; children fall with them) | Note |
|---|---|---|
| USB (all) | `USB_SUPPORT`, `USB`, `USB_CHIPIDEA*`, `USB_EHCI_HCD`, `USB_GADGET` + `USB_CONFIGFS*`/`USB_F_*`, `USB_USBNET` + `USB_NET_*`, `USB_RTL8152`, `USB_LAN78XX`, `USB_STORAGE`, `USB_HID`, `USB_MXS_PHY`, `USB_ULPI_BUS`, `USB_ONBOARD_DEV`, `USB_ROLE_SWITCH`, `EXTCON_USB_GPIO`, `USB_PCI` | No USB controller on the board |
| Wired/other networking | `FEC`, `PHYLIB`/`MDIO_*`, `PTP_1588_CLOCK`, `PPS`, `NET_VENDOR_*` (58 gates), `CAN` + `CAN_FLEXCAN/RAW/BCM/GW`, `BT` + `BT_HCIUART*`, `SERIAL_DEV_BUS`, `CFG80211_WEXT`, `IPV6_SIT`, `IP_PNP` | No Ethernet, CAN, or BT |
| Storage buses | `SCSI` (+`SCSI_LOWLEVEL`), `ATA` (+`ATA_SFF`, `ATA_BMDMA`), `PCI` + `PCIE_DW_HOST` + `PCI_IMX6` + `PCI_MSI` + `PCIEASPM`, `MTD` (+`MTD_CFI*`, `MTD_RAW_NAND`, `MTD_NAND_GPMI_NAND`, `MTD_NAND_MXC`, `MTD_SPI_NOR`, `MTD_UBI`, `MTD_DATAFLASH`, `MTD_PHYSMAP`), `MXS_DMA`, `FSL_EDMA`, `IMX_WEIM`, `BLK_DEV_RAM` | eMMC/SD only; EIM pads are plain GPIOs here |
| Filesystems | `JFFS2_FS`, `UBIFS_FS`, `NFS_FS` (+SUNRPC), `FUSE_FS`, `AUTOFS_FS`, `EXT2_FS`, `EXT3_FS`, `QUOTA`, `ISO9660_FS`/`UDF_FS`/`MSDOS_FS` (modules), `BINFMT_MISC` | Keep `EXT4_FS`, `VFAT_FS` + `NLS_*` (SD cards), `TMPFS`, `CONFIGFS_FS` |
| Display | `DRM_IMX` (+`DRM_IMX_HDMI/LDB/PARALLEL_DISPLAY/TVE`), `DRM_DW_HDMI` (+CEC, AHB audio), `DRM_MSM` (Qualcomm; the whole `DRM_MSM_*` block), `DRM_MXSFB`, `DRM_PANEL_*`, `DRM_SII902X`, `DRM_TI_TFP410`, `DRM_I2C_NXP_TDA998X`, `DRM_LVDS_CODEC`, `DRM_FBDEV_EMULATION`, `FB`, `FRAMEBUFFER_CONSOLE`, `LOGO`, `VT` + `DUMMY_CONSOLE` + `CONSOLE_TRANSLATIONS`, `VGA_ARB`, `BACKLIGHT_CLASS_DEVICE`/`BACKLIGHT_GPIO`/`BACKLIGHT_PWM`, `LCD_CLASS_DEVICE`, `CEC_CORE`, `MEDIA_CEC_SUPPORT` | **Keep `DRM`, `DRM_ETNAVIV`, `DRM_ETNAVIV_THERMAL`, `IMX_IPUV3_CORE`** (GPU demosaic needs the etnaviv render node; the IPU core drives CSI capture). See 5.1 for the verification this needs. |
| Audio | `SOUND`, `SND`, `SND_SOC`, `SND_IMX_SOC`, `SND_SOC_FSL_SSI/SAI/ESAI/SPDIF/ASRC/AUDMUX/UTILS`, `SND_SOC_IMX_PCM_DMA/FIQ`, all codec drivers (`SGTL5000`, `WM8960`, `WM8962`, `WM8994`, `TLV320AIC23/31XX/3X`, `CS42XX8`, `ES8328`), `SND_SIMPLE_CARD`, `SND_SOC_HDMI_CODEC`, `SND_AC97_CODEC`, `SND_USB_AUDIO` | Plus `&asrc` disabled in the DTS |
| Input | `INPUT_TOUCHSCREEN` + 19 `TOUCHSCREEN_*`, `HID`/`HID_GENERIC`/`HID_MULTITOUCH`/`HID_WACOM`/`I2C_HID*`, `INPUT_MOUSE` (psmouse), `SERIO`/serport, `INPUT_MISC` + `INPUT_GPIO_BEEPER`, `INPUT_EVBUG`, `INPUT_LEDS`, `INPUT_MATRIXKMAP`, `RC_CORE`/`RC_DEVICES`/`IR_GPIO_CIR`/`VIDEO_IR_I2C` | **Keep `INPUT`, `INPUT_EVDEV`, `KEYBOARD_GPIO`** (`/dev/input/event0` = the switches) |
| PMIC / board-support for other boards | `MFD_DA9052_I2C`, `MFD_DA9062`, `MFD_DA9063` (+`da9063_wdt`), `MFD_MC13XXX*` (+`SENSORS_MC13783_ADC`, `TOUCHSCREEN_MC13783`), `MFD_RN5T618` (+`rn5t618_power`), `MFD_ROHM_BD71828` + `GPIO_BD71815` + `REGULATOR_ROHM`, `MFD_STMPE` (+gpio, ts), `MFD_SY7636A` (+`SENSORS_SY7636A`), `MFD_WM8994`, `GPIO_74X164`, `GPIO_MAX732X`, `GPIO_PCA953X`, `GPIO_PCF857X`, `GPIO_VF610`, `GPIO_SIOX`/`SIOX`, `REGULATOR_GPIO`, `POWER_SUPPLY`, `W1` (+`ds2482`, `w1_therm`), `I2C_GPIO`, `I2C_MUX_GPIO`, `I2C_ALGOPCA/PCF`, `I2C_SLAVE`, `SPI_GPIO`/`SPI_BITBANG`, `SPI_FSL_DSPI`, `SPI_FSL_QUADSPI`, `PWM_FSL_FTM`, `PWM_IMX_TPM`, `RTC_DRV_MXC`, `SENSORS_GPIO_FAN`, `SENSORS_PWM_FAN`, `SENSORS_IIO_HWMON`, `SENSORS_ISL29018`, `IIO_ST_SENSORS_SPI` (+`st_accel_spi`), `LEDS_PWM`, `LEDS_TRIGGER_*`, `IMX_IRQSTEER`, `IMX_GPCV2*`, `SERIAL_FSL_LPUART*`, `DMATEST`, `IRQ_IMX_MU_MSI`, `HW_RANDOM_IMX_RNGC`, `HW_RANDOM_MXC_RNGA`, `HW_RANDOM_OPTEE`, `HW_RANDOM_ARM_SMCCC_TRNG`, `CRYPTO_DEV_MXS_DCP`, `CRYPTO_DEV_SAHARA`, `TEE`/`OPTEE`, `ARM_PSCI*` | **Keep `REGULATOR_FIXED_VOLTAGE`, `REGULATOR_ANATOP`, `GPIO_MXC`, `GPIO_CDEV`, `GPIO_SYSFS`, `LEDS_GPIO`, `LEDS_CLASS`, `I2C_IMX`, `I2C_CHARDEV`, `SPI_IMX`, `PWM_IMX27`, `RTC_DRV_SNVS`, `NVMEM_IMX_OCOTP`, `NVMEM_SNVS_LPGPR`, `CRYPTO_DEV_FSL_CAAM*`, `SENSORS_LM75`, `IIO_ST_SENSORS_CORE`/`I2C`, `IMX_THERMAL`, `CPU_THERMAL`** |
| Other SoCs | `SOC_IMX31/35/50/51/53/6SL/6SLL/6SX/6UL/7D/7ULP/8M`, `PINCTRL_IMX35/50/51/53/6SL/6SLL/6SX/6UL/7D/7ULP/8MM/8MN/8MP/8MQ`, `PINCTRL_VF610` | **Keep `SOC_IMX6Q`, `PINCTRL_IMX6Q`, `MXC_CLK`, `CLKSRC_IMX_GPT`, `IMX2_WDT`, `ARM_IMX6Q_CPUFREQ`** |
| Media (non-camera) | `MEDIA_ANALOG_TV_SUPPORT`, `MEDIA_DIGITAL_TV_SUPPORT`, `MEDIA_RADIO_SUPPORT`, `MEDIA_SDR_SUPPORT`, `MEDIA_TEST_SUPPORT`, `MEDIA_USB_SUPPORT`, `DVB_CORE`, `VIDEO_IMX_PXP` (the 6DL PXP node's compatible is not one this driver matches; unbound), `VIDEO_OV2680`/`OV5640`/`OV5645`/`ADV7180`, `USB_VIDEO_CLASS` | **Keep `MEDIA_SUPPORT`, `MEDIA_CAMERA_SUPPORT`, `MEDIA_PLATFORM_SUPPORT`, `MEDIA_CONTROLLER`, `VIDEO_DEV`, `VIDEO_V4L2_SUBDEV_API`, `V4L_PLATFORM_DRIVERS`, `V4L_MEM2MEM_DRIVERS`, `VIDEO_CODA`, `VIDEO_IMX_VDOA`, `VIDEO_IMX_MEDIA`, `VIDEO_MUX`, `VIDEO_OV5648`, `VIDEO_OV8856`, `STAGING_MEDIA`**. The single switch `CONFIG_MEDIA_SUPPORT_FILTER=y` (then enable only CAMERA + PLATFORM) is what removes the DVB/tuner tree (4.2). |
| Debug / misc | `KEXEC`, `CRASH_DUMP`, `PROC_VMCORE`, `ATAGS` + `ATAGS_PROC`, `SUSPEND`/`PM_SLEEP`/`PM_TEST_SUSPEND`/`PM_DEBUG` (no suspend use on a laser), `SWAP`, `CPU_FREQ_GOV_CONSERVATIVE/POWERSAVE/USERSPACE`, `IOSCHED_BFQ`, `MQ_IOSCHED_KYBER`, `CONNECTOR`/`PROC_EVENTS`, `RD_BZIP2/LZ4/LZMA/LZO/XZ/ZSTD` (no initrd), `HIGHMEM` (512 MB fits lowmem; dmesg: `HighMem empty`) | `DEBUG_FS`, `DEVMEM`, `MAGIC_SYSRQ`, `KPROBES`, `PERF_EVENTS`, `IKCONFIG_PROC` are bench tools; keep on the dev image at least |

###### 4.2 Modules shipped and never used
`imx-base.inc` sets `MACHINE_EXTRA_RRECOMMENDS = "kernel-modules"`, so every module built
lands on the rootfs: 253 modules, 9.7 MB, in the release image as well (its manifest lists
254 `kernel-module-*` packages). The board loads 28; 27 are needed (`wl12xx` is not).
Breakdown of the dead weight on the board:

| Group | Modules | Size | Why they exist |
|---|---|---|---|
| DVB frontends + tuners | 153 | 3.1 MB | `MEDIA_SUPPORT_FILTER` off + `MEDIA_SUBDRV_AUTOSELECT` off makes every frontend `default m` |
| Non-TI Wi-Fi (`ath10k`, `brcmfmac`, `mwifiex`, `wl12xx`) | 13 | 1.4 MB | `WLAN_VENDOR_*` gates + defconfig |
| USB (gadget legacy, serial, `cdc-acm`, `usbtest`, `ehset`, `uvcvideo`, `snd-usb-audio`, USB net) | 20 | 1.2 MB | No USB |
| Other (`psmouse`, `serport`, `gpio-beeper`, `w1`, `siox`, `dmatest`, `evbug`, `bnep`, `udf`/`isofs`/`msdos`, `binfmt_misc`, `da9063_wdt`, `rn5t618_power`, `lvds-codec`, `dw-hdmi-ahb-audio`, `qcaspi`, `ov2680/ov5640/ov5645/adv7180`, `cxd2880-spi`, `irq-imx-mu-msi`, `st_accel_spi`, `i2c-algo-pca/pcf`, `nls_iso8859-15`) | ~40 | 1.3 MB | Defconfig |

Two independent fixes: (1) unset the symbols so the modules are not built (4.1 plus
`MEDIA_SUPPORT_FILTER=y`); (2) replace the blanket `kernel-modules` recommendation in
`glowforge.conf` with the explicit list (`kernel-module-glowforge`, the `wlcore`/`wl18xx`/
`mac80211`/`cfg80211`/`ccm`/`ctr`/`gcm`/`ghash`/`libarc4` set, `ov5648`, `ov8856`,
`video-mux`, `mux-core/gpio/mmio`, `imx-media-common`, `imx6-media`, `imx6-media-csi`,
`imx6-mipi-csi2`, `coda-vpu`, `v4l2-jpeg`, `imx-vdoa`, `lm75`, `st-accel`/`st-accel-i2c`/
`st-sensors`/`st-sensors-i2c`). (2) alone already shrinks the release rootfs by about
8 MB against the 200 MiB slot; (1) is what shrinks the kernel and the build.

###### 4.3 Firmware packages (adjacent, same mechanism)
`MACHINE_FIRMWARE` in `imx-base.inc` adds, for `mx6dl-generic-bsp` and `imx-mainline-bsp`:
`firmware-imx-epdc` (5.0 MB of e-paper controller firmware; no EPDC on this board),
`firmware-imx-vpu-imx6q` (the 6DL uses `vpu_fw_imx6d.bin`), `linux-firmware-imx-sdma-imx7d`
(wrong SoC), plus `linux-firmware-imx-sdma-imx6q` (never loads; both SDMA packages are
decided out, 2.4). `/lib/firmware` is 7.7 MB; about 5.5 MB of it has no consumer. `linux-firmware-wl18xx` carries four `wl18xx-fw*`
variants; this board (PG 2.2) boots `wl18xx-fw-4.bin`. Keep all four unless every board
is known to be PG 2.2. The `TIInit_*.bts` files are BT init scripts (no BT).

##### 5. Considerations (not defects; decide, then measure)

###### 5.1 `DRM_IMX` removal must be verified against the GPU demosaic
forgectrl's `gpu_debayer.c` opens EGL through `EGL_PLATFORM_SURFACELESS_MESA`, which
enumerates render nodes (`/dev/dri/renderD128`, etnaviv). It does not need `card1`
(imx-drm). After removing `DRM_IMX`, confirm on the bench that `/dev/dri/renderD128` still
exists and forgectrl logs the GPU path as active (the `gpu:` lines) rather than falling back
to NEON. Mesa's `PACKAGECONFIG:pn-mesa = "... gallium etnaviv"` is unaffected.

###### 5.2 `SMP=y` on a single core
`CONFIG_SMP=y`, `NR_CPUS=4`, one CPU brought up. Every spinlock and per-CPU path pays the
SMP cost for nothing. `CONFIG_SMP=n` (the multi-platform build allows it) removes that and
the seven IPI vectors. Worth measuring against BRINGUP item 16 (producer stalls); it is
not a correctness issue.

###### 5.3 Kernel-side latency knobs that are already right
`PREEMPT=y`, `HZ=100` with `NO_HZ_IDLE` and `HIGH_RES_TIMERS`, `imx6q_cpuidle` (WFI + WAIT,
50 us exit), `RCU_PREEMPT`, no `DEBUG_PREEMPT`/lock debugging, `DEBUG_INFO_NONE`,
`INIT_STACK_ALL_ZERO` (small cost, fine). `sched_rt_runtime_us=950000` is the default RT
throttle; a `SCHED_FIFO` feeder that ever runs a full 950 ms without sleeping is throttled
for 50 ms. The feeder sleeps, so this is a note, not a finding.

###### 5.4 Watchdog
`IMX2_WDT=y` + `WATCHDOG_HANDLE_BOOT_ENABLED=y`: the kernel adopts U-Boot's 60 s watchdog
and keeps it fed while `/dev/watchdog` stays closed (nothing opens it, by design per the
image recipe). Consistent with the fragment. A hung userspace does not reset the machine;
that is the documented decision.

###### 5.5 Tracing and BPF
`FTRACE`-family symbols are absent from the config (no function tracer), but `BPF_SYSCALL`,
`KPROBES`, `RCU_TRACE`, `TASKS_TRACE_RCU`, `PERF_EVENTS` are on. Keep on the dev image
(latency work), consider off for release.

###### 5.6 Documentation drift noticed on the way (kas/README.md #2)
The README says the PWM prescaler port is "obsolete", that the PIC SPI delay is a
"hardware-bring-up TODO", and that `reg-userspace-consumer` is enabled via `glowforge.cfg`.
The bbappend carries patch 0009 (`fsl,extra-prescale = <13>` on `&pwm2`) and patch 0004
(the PERIODREG delay), and the fragment has no userspace-consumer line (the DTS dropped
the node). The bbappend header is current; the README paragraph is not.

##### 6. What to keep (the board's real driver set)

Built in: `IMX_SDMA`, `MXC_EPIT_API`, `PREEMPT`, `PANIC_ON_OOPS`, `IMX2_WDT`, `CMA`/`DMA_CMA`,
`SERIAL_IMX` (+console), `MMC_SDHCI_ESDHC_IMX`, `MMC_BLOCK`, `I2C_IMX`, `I2C_CHARDEV`,
`SPI_IMX`, `PWM_IMX27`, `GPIO_MXC`, `GPIO_CDEV`, `GPIO_SYSFS`, `PINCTRL_IMX6Q`, `SOC_IMX6Q`,
`KEYBOARD_GPIO`, `INPUT_EVDEV`, `LEDS_GPIO`, `REGULATOR_FIXED_VOLTAGE`, `REGULATOR_ANATOP`,
`IMX_THERMAL`, `CPU_THERMAL`, `ARM_IMX6Q_CPUFREQ` (+`ondemand`, `performance`), `CPU_IDLE`,
`RTC_DRV_SNVS`, `NVMEM_IMX_OCOTP`, `IMX_IPUV3_CORE`, `DRM` + `DRM_ETNAVIV`,
`CRYPTO_DEV_FSL_CAAM` (RNG, `hwrng` thread), `IIO` + triggered buffer, `HWMON`, `WATCHDOG`,
`EXT4_FS`, `VFAT_FS` + `NLS_*`, `TMPFS`, `DEVTMPFS`, `CONFIGFS_FS`, `IKCONFIG_PROC`,
`INET`/`UNIX`/`PACKET`, `IPV6` (until `auth.c` says otherwise), `RFKILL` (wpa_supplicant),
`WIRELESS`/`WLAN`/`WLAN_VENDOR_TI`, `MEDIA_SUPPORT` + camera/platform, `STAGING_MEDIA`,
`SRAM`, `MXC_CLK`, `CLKSRC_IMX_GPT`, `HAVE_ARM_TWD`, `IMX_GPC` + PM domains (`vddpu`).

Modules (27): `glowforge`, `wl18xx`, `wlcore`, `wlcore_sdio`, `mac80211`, `cfg80211`,
`libarc4`, `ccm`, `ctr` (+`gcm`, `ghash` for WPA3/GCMP), `ov5648`, `ov8856`, `video_mux`,
`mux_core`, `mux_gpio`, `mux_mmio`, `imx_media_common`, `imx6_media`, `imx6_media_csi`,
`imx6_mipi_csi2`, `coda_vpu`, `v4l2_jpeg`, `imx_vdoa`, `lm75`, `st_accel`, `st_accel_i2c`,
`st_sensors`, `st_sensors_i2c`.

##### 7. Suggested order, if acted on

1. `glowforge.cfg`: unset `INPUT_EVBUG`; add `DETECT_HUNG_TASK` + `SOFTLOCKUP_DETECTOR`;
   add `PSTORE`/`PSTORE_RAM`/`PSTORE_CONSOLE` (+ ramoops node in the DTS); set
   `PANIC_TIMEOUT=10`; write `MULTIPLEXER`/`MUX_GPIO`/`MUX_MMIO` as `=m`. (Safety and
   diagnostics first.)
2. `glowforge.conf`: replace the `kernel-modules` recommendation with the explicit module
   list; drop `firmware-imx-epdc`, `firmware-imx-vpu-imx6q`, `linux-firmware-imx-sdma-imx6q`,
   and `linux-firmware-imx-sdma-imx7d` from `MACHINE_FIRMWARE` (2.4, decided).
3. `glowforge.cfg`: the removal clusters in 4.1 with `MEDIA_SUPPORT_FILTER=y`; `glowforge.dts`:
   disable `&asrc` and the USB PHY nodes, and drop `dmas`/`dma-names` from `&ecspi2` (2.4).
4. `kernel-module-glowforge`: `spi_device_id` table for `glowforge,pic`.
5. Bench: fresh-boot `dmesg` diff, `/proc/sys/kernel/*_panic` present, `/sys/fs/pstore`
   mounts, `renderD128` present and forgectrl on the GPU path, cameras stream, Wi-Fi up,
   then the acceptance catalog.

All of 1 through 4 ride one image flash (kernel/BSP changes batch), and every item here is
a platform change under the acceptance model.


## Reference notes

### Head-IRQ source validation — the beam-emission hypothesis

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

### Homing: limit switches planned, the accelerometer approach retired

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
