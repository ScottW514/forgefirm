# ForgeFIRM bench tools

Hardware-verification tools for the ForgeFIRM bench. All run ON the
target board (dev image, python3 present) unless noted. Host-side tools
take the machine address from `GF_HOST` (or `argv`, where stated); the
ones that shell into the board over ssh use the `ssh` on `PATH`, or the
client named by `GF_SSH` (for example `GF_SSH='wsl -d <distro> -- ssh'`
to go through a WSL distro from Windows).

| Tool | Purpose |
|---|---|
| `feeder.c` | Underrun proof: streams NOP pulse bytes to `/dev/glowforge` with wall-clock pacing, bounded queue depth, deadman flock, SCHED_FIFO. Usage: `feeder <hz> <seconds> <depth_ms>`. Proven envelope: 100 kHz × 120 s under full load, 0.2 ms worst write latency. Cross-compile with `build-feeder.sh` (WSL). |
| `bench_phase2.py` | End-of-data protocol bench: underrun detection/ack, parked no-replay guard, resume(0), continuous-feed stability, 20× run/underrun cycles. Motion-safe (motors locked, laser latched). |
| `check_pwm.py` | Laser PWM register check: reads PWM2 PWMCR/PWMPR via /dev/mem, expects divider 13 × ~127 counts ≈ 40 kHz. |
| `pwm_sweep.py` | LASER_PWM scope test (runs on the board): `check` = read-only safety readbacks + PWM2 dump; `sweep` = steps PWMSAR through 50/25/75/6/100 % duty with 4 s holds, then restores. Run only in the locked state (controller stopped, cnc disabled, latch locked). |
| `pwm_hold.py` | Holds one PWMSAR value for a scope-measurement window (`pwm_hold.py <sar> <seconds>`), then restores. Same locked-state rule. |
| `fire_test.py` | FIRE drop-timing scope test (runs on the board): A = latch locked (expects nothing on FIRE/LASER_ON), B = latch unlocked / normal end-of-data, U = true underrun. Duty 0 throughout; refuses to unlock if HV reports good. |
| `pwm_stream_test.py` | LASER_PWM stream-path scope test (runs on the board): streams power bytes only (no step bytes, no FIRE bits, `motor_lock=15`, latch locked) through `/dev/glowforge` so the scope verifies the real power path, including the run-start duty reset and the consecutive-power-byte drop; position counters compared before/after. |
| `gate_a_kernel_drills.py` | Kernel laser-safety drills (run on the board with forgectrl stopped so the pulse device is free): `K1` controlled-stop deceleration floor, `K2` resume waypoint honors the locked latch, `K3` a mid-ramp latch unlock never re-arms the FIRE drive. Software witnesses (`cnc/state`, `laser_enable`, `laser_on`, `laser_on_sampled`, interlock bit 3) plus the PSU-connector LASER_ON scope point; K3 refuses to run if HV reports good. |
| `laser_stream_test.py` | Host-side laser pulse-stream emission harness: runs the native null-sink controller with `GFSINK_DUMP`, drives small laser jobs over TCP, and checks the dumped bytes against the kernel feeder contract (leading power byte, no back-to-back power bytes, FIRE only inside cutting moves, every stream ends FIRE-clear, no FIRE on a stepless gap, no FIRE leak across cycle churn). Runs in the grblHAL repo's CI. |
| `laser_lifecycle_test.py` | Host-side operator-armed-window lifecycle harness (null-sink controller): arm once per job with M5/M3 persistence, the M2 close, sender-change re-consent, the disarm grace counting down in Hold, and arm refusal under a blocking cooling verdict. Runs in the grblHAL repo's CI. |
| `live_fire_drills.py` | **LIVE LASER** drills from a LAN host (`live_fire_drills.py <drill> [host]`, or `GF_HOST`): `witness` (emission witness, lid-IR peaks vs the ambient baseline, HV current, job-based disarm on M2), `hold` (disarm grace in Hold), `faultpos` (armed job refuses a stale origin after an underrun). Every drill waits for the operator's physical arm press; eye protection, fire watch, extinguisher, and exhaust are mandatory. |
| `pacing_test.py` | Protocol-loop pacing check (runs on the board, dry motion): idle and parked-in-Hold states are coarse-paced, active motion is tight-paced, and a feed-hold/resume mid-move preserves position with no feeder starve. |
| `fan_test.py` | Fan/coolant bench (Windows-side): snapshots fan PWMs/tachs/temps, drives M8 → cut fans, M9 → cooldown → idle, verifying via tach readbacks. |
| `flow_characterize.py` | Coolant flow characterization using the factory temperature curve: baseline → flow → no-flow → recovery, printing the ΔT bands and their separation. Takes the heater duty as an argument (`flow_characterize.py 30`); aborts if downstream passes 45 °C. |
| `flow_matrix.py` | **The flow-detection design matrix** (with `flow_sampler.py`, which lives on the board at `/data/`): duty × duration × flow/no-flow, every run from a common cooled baseline, interleaved repeats. One heating trace yields the metric at every candidate duration, so cost and precision come from the same 60 runs. Prints a cost table, a precision table (mean±sd, worst-case margin, d′) and a ranked shortlist. Env: `FM_DUTIES`, `FM_REPEATS`, `FM_RESULTS`. |
| `flow_sustained.py` | Long-run test of the real re-check cadence via M8: counts verdicts/false faults and tracks whether the loop accumulates heat. |
| `flow_warm_validate.py` | Runs the real check from a heater-warmed baseline. Note the ceiling: 100 % duty pushes the downstream sensor past 50 °C in 30 s while the bulk barely moves, so warm-loop validation above ~23 °C needs the laser, not the heater. |
| `flow_recheck_char.py` | Characterizes short in-run re-checks and the differential metric; shows why over-temp cannot see a stopped pump and why passive warming trends are ambiguous. |
| `flow_confirm_drill.py` | Coolant flow suspicion/confirmation drill (runs on the board): one continuous M8 session walks the verdict state machine through real pump-off transients — verified → SUSPECT (+ immediate re-check) → cleared → SUSPECT → FAULT (consecutive) → recovered — printing PASS/FAIL per transition. Leaves the machine idle (M9, pump on, heater off). |
| `flow_escalate_drill.py` | Coolant starved-re-check escalation drill (runs on the board against a controller started with a short confirmation budget): with the pump off the job-start check reads SUSPECT, the stagnant loop cannot pass the settle gate inside the budget, and the driver must escalate to FAULT. PASS/FAIL, leaves the machine idle. |
| `flow_sampler.py` | Board-side coolant sampler used by the flow tools (`flow_sampler.py <duration_s> <interval_s>`, prints `elapsed,raw_down,raw_up`); kept on the board at `/data/` so cadence does not depend on ssh latency. |
| `temp_calibrate.py` | Coolant temperature spot-check helper (`watch` / `point <measured_C>` / `fit`) — pairs a measured temperature with averaged raw ADC readings and fits a per-machine line to sanity-check the factory curve against a thermometer. |
| `build-glowforge.sh` | Cross-compiles **grblHAL-glowforge** (the canonical driver repo, `../../../grblHAL-glowforge`) in the Yocto build environment, borrowing the recipe toolchain. Run: `bash <path>/build-glowforge.sh` (from Windows, launch it through the WSL distro from PowerShell; Git Bash mangles /mnt/c paths). Env: `FF_SRC_TOP`, `FF_BUILD_TOP`. This is the production controller build. |
| `build-forgectrl.sh` | Cross-compiles **forgectrl** (the canonical control-daemon repo, `../../../forgectrl`) the same way, borrowing the toolchain from the forgectrl recipe workdir (regenerate with `bitbake forgectrl` after a clean). |
| `accel_fast.py` | Direct-I2C sampler for the two head-bus LIS2HH12s (runs on the board; unbinds/rebinds st-accel around the capture, 800 Hz ODR, ~270 Hz per device polled): optional mid-capture jogs via local grblHAL TCP. CSV to /tmp/accel.csv. The head accel is i2c-3 0x1e. |
| `bump_seek.py` | Accelerometer bump-seek homing prototype (runs on the board): creeps toward a rail in bounded jog segments via grblHAL TCP, learns the moving-noise baseline per segment, detects the contact jolt (~530 Hz sampling, 2-sample confirm), jog-cancels (0x85) and backs off. CSV to /tmp/bump.csv. |
| `build-feeder.sh` | Cross-compiles `feeder.c` the same way. |
| `puls_profile.py` | Decodes factory `.puls` streams (raw or GF1-headered) into velocity/accel profiles: peak speeds, ramp-slope fits, per-move segments, Z cadence. Runs anywhere (stdlib only). Source of the factory-true grblHAL defaults: 700/590 mm/s² accel, 200 mm/s max rate, 28160 Hz travel tick. |
| `cp_watchdog_timing.py` | HV charge-pump watchdog one-shot timing (runs on the board): latches every CHG_PUMP feed pulse in GPIO3's edge detector (pin 24 only, IMR untouched, ICR2 restored on exit) and polls the `!Q` (`charge_pump_alive`) and `!HV_ENABLE` (`hv_enable`) pads through /dev/mem in a tight loop while it commands short local jogs; prints per-run t_w (last pulse → Q fall), Q → HV_ENABLE delay, priming latency and the feed period, with the loop's worst gap as the resolution. Motion only, laser locked, no other Grbl client attached. |
| `bench_m2.py` | Motion-quality bench, runs against the board over TCP:23: bounded round-trip jogs (sanity, max-rate, diagonal) + feed-hold/resume mid-move, reporting peak feed, state transitions, and position drift. |

Data files kept beside the tools: `flow_matrix_results.json` /
`flow_matrix_log.txt` (the 60-run flow-detection matrix),
`flow_warm_results.json` / `flow_warm_log.txt` (warm-baseline validation),
`temp_calibration.json` (coolant sensor spot-checks), and
`lid_ir_ambient_baseline.csv` (lid-IR ambient, lid closed, idle).

The build scripts borrow the Yocto cross toolchain + sysroot from a target
recipe work directory in the build tree (`FF_BUILD_TOP`, default
`../forgefirm/build`); if that path ages out after a `bitbake -c clean`,
rebuild the named recipe or point `TC` at any current target recipe workdir
(or build a proper SDK with `bitbake meta-toolchain`).

## How the coolant-flow fire-gate threshold was derived

forgectrl's cooling engine refuses to let the laser fire unless a
heater-based flow check passes: with the pump commanded on, the loop heater
runs at `COOL_FLOW_HEATER_PCT` (40 %) for `COOL_FLOW_CHECK_S` (50 s) and the
downstream sensor's rise over its settled baseline must stay below
`COOL_FLOW_RISE_C` (14.4 °C) — a stopped pump lets the heater's output pool
at the downstream sensor instead of being carried away. The three constants
live in `forgectrl/src/cool.h` and are the compiled defaults behind the
`cool_flow_*` settings.

The 14.4 °C threshold and the 40 %/50 s operating point come from
`flow_matrix.py`: 6 duties × 2 flow states × 5 interleaved repeats = 60
heating runs, every run started from a common cooled baseline, both sensors
sampled at 1 Hz by `flow_sampler.py`, and one heating trace scored at every
candidate check duration. The committed `flow_matrix_results.json` and
`flow_matrix_log.txt` are that data set. The selection rule: the cheapest
duty at which every observed no-flow rise exceeded every observed flow rise
with a comfortable d′ (40 % / 50 s: flow ≤ 12.75 °C over 17 observations,
no-flow ≥ 16.04 °C over 8, d′ 8.4, ~0.8 °C of loop heating per check), with
the threshold set at the balanced midpoint of the two bands (14.4 °C).
`flow_warm_validate.py` then re-ran the real check from heater-warmed
baselines (`flow_warm_results.json`).

To reproduce on another machine: set `GF_HOST` (and `GF_SSH` if ssh needs a
wrapper), copy `flow_sampler.py` to `/data/` on the board, and run
`flow_matrix.py` (env `FM_DUTIES`, `FM_REPEATS`, `FM_RESULTS`; ~1.6 h for
the full matrix, the controller is stopped for the duration). The same
derivation is also built into forgectrl as the panel's Diagnostics →
**flow-calibrate** tool (3 trials per case at the operating point, reports
both bands and a recommended threshold; the bench value it recommends
lands within a few tenths of a degree of 14.4). Apply a per-machine value
through the `cool_flow_rise` setting rather than editing the constant.
