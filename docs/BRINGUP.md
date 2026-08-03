# ForgeFIRM bring-up status & cold-start runbook

Last updated: **2026-08-02** — milestone 2 (factory-true motion tuning)
bench-verified, and the controller promoted to a canonical grblHAL driver
repo (**grblHAL-glowforge**) with bench parity re-proven on hardware.
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
cloud mode repaired (nvmem identity → hostname XXX-XXX verified on fuses;
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
  (`ssh -o PreferredAuthentications=none` logs straight in). Dev image
  (`forgefirm-image-dev`) on SD; BusyBox userland + python3 + gdb/strace.
  Serial console on ttymxc0 available at the bench.
- **Deploying kernels**: re-burn the SD with the freshly built
  `forgefirm-image-dev-glowforge.rootfs.wic.gz` (deploy dir below). Where
  the boot flow loads the kernel from was never fully traced (the wic has
  no boot partition; the eMMC env area reads empty) — re-burning works and
  is the procedure. **Module-only changes hot-swap**: scp `glowforge.ko`
  over `/lib/modules/<kver>/extras/`, then `rmmod glowforge && modprobe
  glowforge`. NOTE: a module reload turns off the lid LED (relight via
  `/sys/class/leds/lid_led*/target`) and resets analog config (below).
- **Build host**: WSL2 distro `forge-yocto`, tree at
  `~/dev/openglow-forgefirm`. `~/src-sync.sh` rsyncs the Windows repos in
  (includes `python3-gfhardware` and `grblHAL-glowforge`). Build:
  `cd ~/dev/openglow-forgefirm/forgefirm && kas shell
  kas/forgefirm-glowforge.yml -c 'bitbake forgefirm-image
  forgefirm-image-dev'`. Artifacts:
  `forgefirm/build/tmp/deploy/images/glowforge/`.
- **Shell gotchas** (cost real time): PowerShell mangles embedded double
  quotes in git-commit here-strings (avoid `"` in messages); `wsl -- bash
  -c '...'` eats `$VAR` expansions (use script files run via PowerShell,
  not Git Bash, which MSYS-mangles `/mnt/c` paths).

## Running the controller (grblHAL-glowforge on the board)

Source: `C:\dev\openglow-forgefirm\grblHAL-glowforge` — the **canonical
grblHAL driver repo** (github.com/ScottW514/grblHAL-glowforge, branch
`main`): core as a submodule at `src/grbl` (→ ScottW514/core fork, branch
`forgefirm`, carrying the settings-write crash fix, PR'd upstream as
grblHAL/core#999), `driver.c` implementing the HAL, machine constants in
`src/boards/glowforge.h`. Architecture: a wall-paced producer thread runs
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

## Hardware facts bank (measured)

- SDMA pulse engine: ring free = 128 MiB − 32 KiB gap; script effective
  ceiling ~165 kHz; position counters (`sdma_context` sc0/1/2 = X/Y/Z
  steps, sc3 = bytes) match grblHAL exactly.
- Byte layout & rules: see the UAPI.md feeder contract (authoritative).
- Z: bit 6 SET = lens UP = +Z (hardware-verified; pulsedata.py was the
  inverted party, fixed). Home = hall trigger at TOP; usable travel ≈ 30
  half-steps ≈ 10.6 mm ≈ 0.417"; 0.3534 mm/half-step. Never blind-drive Z
  — hall-supervised only.
- XY: 0.15 mm per full step; DIR bit set = −X / +Y (Y1/Y2 complementary).
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
- Switches: truthy = closed/OK; SW_INTERLOCK reads False on units without
  the rear plug — must NOT gate motion (beam is hardware-gated).
- Machine identity from OCOTP nvmem: serial 00000000 → hostname XXX-XXX
  (matches the factory label).

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
   - **Interlock readback semantics cross-check: OPEN** (see
     factory-laser-safety-readbacks notes).
3. **Homing (design decided 2026-08-02)**: the factory machine has NO
   X/Y home switches (only an unpopulated IO header — hardware project
   for another day). Current-spike stall sensing is a dead end (the PIC
   current attrs are setpoints, not measurements, and chopper-driven
   steppers don't draw more current when stalled). Plan, simple first:
   1. **Primary: accelerometer bump-detect** — the head lis2hh12 (in
      the DT, `head/accel_irq` readback) senses the contact jolt while
      creeping toward the corner; stop, back off, zero. Needs IIO
      bring-up on the dev image.
   2. **Fallback: soft-bump** — PIC current dropped to a weak value,
      slow constant-velocity stream past full travel, harmless step
      skipping against the hard stop, back off, zero counters, restore
      run current. Zero new sensing; ~±1 full step (0.15 mm)
      repeatability; brief grind during the skip. Y "weak" value needs
      empirical tuning (factory run is already only 22).
   Camera homing (the factory's actual method) is a future option once
   the camera service exists. Z homes against the hall sensor (top),
   hall-supervised only.
4. **6.5 safety mapping**: door/estop evdev → feed-hold/halt in the
   backend; underrun → grblHAL alarm; interlock-trip recovery check.
5. **6.6 camera service**: persistent MJPEG (ulfius, forgectrl) — also the
   natural time for the deferred 5.6 emulator smoke (homing images).
6. **Housekeeping**: ~~pick the controller's remote home~~ **DONE
   2026-08-02** — the controller is now the canonical driver repo
   `github.com/ScottW514/grblHAL-glowforge` (+ `ScottW514/core` fork;
   the settings-write crash fix is upstream PR grblHAL/core#999; repoint
   the submodule to upstream when it merges). Remaining: a Yocto recipe
   for grblHAL-glowforge in meta-forgefirm (pin SRCREV; fills the
   `forgectrl` slot per kas/README.md), Phase 7 doc sweep (CLAUDE.md
   charter refresh, README roadmap), kas flip + first GitHub release per
   kas/README.md once ready to publish.
