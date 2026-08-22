# ForgeFIRM bench tools

Hardware-verification tools for the ForgeFIRM bench. All run ON the
target board (dev image, python3 present) unless noted. The dev image
installs them under `/usr/share/forgetest/bench/`, and the acceptance
tool's **Bench diagnostics** tab (`http://<machine>:8090/#bench`,
`docs/ACCEPTANCE.md`) runs them with their arguments and the output on
the page - takeover and scope tools get forgectrl and the controller
stopped and started around the run, live tools need the operator
acknowledgment; the acceptance catalog itself is built from ports of
these drills. The tools that also run from a LAN host use `gfbench.py`:
`GF_HOST` names the machine (sysfs through ssh - the `ssh` on `PATH`, or
the client named by `GF_SSH`, for example `GF_SSH='wsl -d <distro> --
ssh'` from Windows - Grbl and forgectrl over the LAN); with `GF_HOST`
unset they run on the board itself (sysfs directly, everything on
127.0.0.1), which is how the bench page runs them, with their data files
under `/data/forgetest/bench/` (`FORGETEST_BENCH_DATA`; next to the tool
otherwise) and the panel token in `GF_TOKEN`. Tools that drive the
thermal hardware directly (the flow characterization family) run with
forgectrl - the thermal-hardware owner - and the controller stopped: the
page's takeover does that; from a host, stop them first.

| Tool | Purpose |
|---|---|
| `feeder.c` | Underrun proof: streams NOP pulse bytes to `/dev/glowforge` with wall-clock pacing, bounded queue depth, deadman flock, SCHED_FIFO. Usage: `feeder <hz> <seconds> <depth_ms>`. Proven envelope: 100 kHz × 120 s under full load, 0.2 ms worst write latency. Cross-compile with `build-feeder.sh` (WSL). |
| `bench_phase2.py` | End-of-data protocol bench: underrun detection/ack, parked no-replay guard, resume(0), continuous-feed stability, 20× run/underrun cycles. Motion-safe (motors locked, laser latched). |
| `check_pwm.py` | Laser PWM register check: reads PWM2 PWMCR/PWMPR via /dev/mem, expects divider 13 × ~127 counts ≈ 40 kHz. |
| `pwm_sweep.py` | LASER_PWM scope test (runs on the board): `check` = read-only safety readbacks + PWM2 dump; `sweep` = steps PWMSAR through 50/25/75/6/100 % duty with 4 s holds, then restores. Locked state only (controller and forgectrl stopped, the pulse device closed - the page's takeover): the sweep relocks the latch itself and refuses to write if FIRE reads driven or LASER_ON reads active. |
| `pwm_hold.py` | Holds one PWMSAR value for a scope-measurement window (`pwm_hold.py <sar> <seconds>`), then restores. Same locked-state rule and guard. |
| `fire_test.py` | FIRE drop-timing scope test (runs on the board): A = latch locked (expects nothing on FIRE/LASER_ON), B = latch unlocked / normal end-of-data, U = true underrun. Duty 0 throughout; refuses to unlock if HV reports good. |
| `pwm_stream_test.py` | LASER_PWM stream-path scope test (runs on the board, controller and forgectrl stopped): streams power bytes only (no step bytes, no FIRE bits, `motor_lock=15`, latch locked) through `/dev/glowforge` so the scope verifies the real power path, including the run-start duty reset and the consecutive-power-byte drop; position counters compared before/after. Exit 0 = counters unmoved, idle at the end, no FIRE/emission read back. |
| `gate_a_kernel_drills.py` | Kernel laser-safety drills (run on the board with forgectrl stopped so the pulse device is free): `K1` controlled-stop deceleration floor, `K2` resume waypoint honors the locked latch, `K3` a mid-ramp latch unlock never re-arms the FIRE drive. Software witnesses (`cnc/state`, `laser_enable`, `laser_on`, `laser_on_sampled`, interlock bit 3) plus the PSU-connector LASER_ON scope point; K3 refuses to run if HV reports good. |
| `laser_stream_test.py` | Host-side laser pulse-stream emission harness: runs the native null-sink controller with `GFSINK_DUMP`, drives small laser jobs over TCP, and checks the dumped bytes against the kernel feeder contract (leading power byte, no back-to-back power bytes, FIRE only inside cutting moves, every stream ends FIRE-clear, no FIRE on a stepless gap, no FIRE leak across cycle churn). Runs in the grblHAL repo's CI. |
| `laser_lifecycle_test.py` | Host-side operator-armed-window lifecycle harness (null-sink controller): arm once per job with M5/M3 persistence, the M2 close, sender-change re-consent, the disarm grace counting down in Hold, and arm refusal under a blocking cooling verdict. Runs in the grblHAL repo's CI. |
| `live_fire_drills.py` | **LIVE LASER** drills, on the board (the bench page) or from a LAN host (`GF_HOST`): `live_fire_drills.py <drill> [S] [F]` - `witness` (emission witness, lid-IR peaks vs the ambient baseline, HV current, job-based disarm on M2), `hold` (disarm grace in Hold), `faultpos` (armed job refuses a stale origin after an underrun), `ircut` (lid-IR characterization cut at S/F), `pthresh` (laser power-threshold ladder: 13 constant-power rungs from 2 % to 30 % of full on scrap; the lowest rung that marks is the tube's striking threshold and reads directly as the `$35` value - requires `$35` = 0 for the run), `expstop` (armed kill on the expected-stop path; needs the panel token - `GF_TOKEN`, or the board's token file) and `ctrlstart` (the separate controller restart after it). Every drill waits for the operator's physical arm press; eye protection, fire watch, extinguisher, and exhaust are mandatory. |
| `pacing_test.py` | Protocol-loop pacing check (runs on the board, dry motion): idle and parked-in-Hold states are coarse-paced, active motion is tight-paced, and a feed-hold/resume mid-move preserves position with no feeder starve. |
| `gfbench.py` | Not a tool: the helper the board/host tools share - `HOST`/`LOCAL` from `GF_HOST`, `board(cmd)` (local `sh -c` or ssh), the factory coolant conversion `degc()`, `data_path()` (`FORGETEST_BENCH_DATA` or next to the tool), forgectrl's HTTP API with the panel token, `setting(key)` (from forgectrl, or from `/data/forgefirm.conf` on the board while forgectrl is stopped). |
| `fan_test.py` | Fan/coolant bench (board or host; controller running): snapshots fan PWMs/tachs/temps, drives M8 → cut fans, M9 → cooldown → idle, verifying via tach readbacks. |
| `fan_floor_measure.py` | The numbers the airflow gates ship with (board or host): `spinup` opens a run session with M8 from idle and samples the four tachs and the purge current at 1 Hz, reporting per fan the steady speed, the time to 90 percent and the spread over the steady window, plus the purge current at idle and at run duty (the pump is always on; a dead one reads about 1), and candidate floors at 55 percent; `cut` samples only, during a real cut, for the spread under load. Results as JSON in the bench data directory. |
| `flow_characterize.py` | Coolant flow characterization using the factory temperature curve (board or host; forgectrl and controller stopped): baseline → flow → no-flow → recovery, printing the ΔT bands and their separation. Takes the heater duty as an argument (`flow_characterize.py 30`); aborts if downstream passes 45 °C. |
| `flow_matrix.py` | **The flow-detection design matrix** (board or host; forgectrl and controller stopped; with `flow_sampler.py` from `/usr/share/forgetest/bench/`): duty × duration × flow/no-flow, every run from a common cooled baseline, interleaved repeats. One heating trace yields the metric at every candidate duration, so cost and precision come from the same 60 runs. Prints a cost table, a precision table (mean±sd, worst-case margin, d′) and a ranked shortlist. `flow_matrix.py [duties] [repeats]` (or env `FM_DUTIES`, `FM_REPEATS`, `FM_RESULTS`); results/log in the bench data directory, resumable. |
| `flow_sustained.py` | Long-run test of the real re-check cadence via M8 (board or host; controller running): counts verdicts/false faults against the configured `cool_flow_rise` and tracks whether the loop accumulates heat. `flow_sustained.py [minutes]`. |
| `flow_warm_validate.py` | Runs the real check from a heater-warmed baseline (board or host; forgectrl and controller stopped; `flow_warm_validate.py [cycles_per_case]`; results/log in the bench data directory; exit 1 if any run is misclassified). Note the ceiling: 100 % duty pushes the downstream sensor past 50 °C in 30 s while the bulk barely moves, so warm-loop validation above ~23 °C needs the laser, not the heater. |
| `flow_recheck_char.py` | Characterizes short in-run re-checks and the differential metric (board or host; forgectrl and controller stopped; `flow_recheck_char.py [heater_pct] [window_s]`); shows why over-temp cannot see a stopped pump and why passive warming trends are ambiguous. |
| `flow_confirm_drill.py` | Coolant flow suspicion/confirmation drill (runs on the board): one continuous M8 session walks the verdict state machine through real pump-off transients — verified → SUSPECT (+ immediate re-check) → cleared → SUSPECT → FAULT (consecutive) → recovered — printing PASS/FAIL per transition. Leaves the machine idle (M9, pump on, heater off). |
| `flow_escalate_drill.py` | Coolant starved-re-check escalation drill (runs on the board, controller running): sets the engine's confirmation budget `cool_confirm_max_s` to a short value through forgectrl's settings (`flow_escalate_drill.py [budget_s]`, default 60, the setting's minimum) and restores it after; with the pump off the job-start check reads SUSPECT, the stagnant loop cannot pass the settle gate inside the budget, and the engine must escalate to FAULT. PASS/FAIL (exit status), leaves the machine idle. |
| `flow_sampler.py` | Board-side coolant sampler used by the flow tools (`flow_sampler.py <duration_s> <interval_s>`, prints `elapsed,raw_down,raw_up`); run on the board (dev image: `/usr/share/forgetest/bench/`) so cadence does not depend on ssh latency. |
| `temp_calibrate.py` | Coolant temperature spot-check helper (board or host): `watch [seconds]` / `point <measured_C> [note]` / `fit` — pairs a measured temperature with averaged raw ADC readings and fits a per-machine line to sanity-check the factory curve against a thermometer. Points accumulate in `temp_calibration.json` in the bench data directory. |
| `build-glowforge.sh` | Cross-compiles **grblHAL-glowforge** (the canonical driver repo) in the Yocto build environment, borrowing the recipe toolchain. Run: `bash <path>/build-glowforge.sh` (from Windows, launch it through the WSL distro from PowerShell; Git Bash mangles /mnt/c paths). Env: `FF_SRC_TOP`, `FF_BUILD_TOP`. This is the production controller build. |
| `build-forgectrl.sh` | Cross-compiles **forgectrl** (the canonical control-daemon repo) the same way, borrowing the toolchain from the forgectrl recipe workdir (regenerate with `bitbake forgectrl` after a clean). |
| `accel_fast.py` | Direct-I2C sampler for the two head-bus LIS2HH12s (runs on the board; unbinds/rebinds st-accel around the capture, 800 Hz ODR, ~270 Hz per device polled): optional mid-capture jogs via local grblHAL TCP. CSV to /tmp/accel.csv. The head accel is i2c-3 0x1e. |
| `bump_seek.py` | Accelerometer bump-seek homing prototype (runs on the board): creeps toward a rail in bounded jog segments via grblHAL TCP, learns the moving-noise baseline per segment, detects the contact jolt (~530 Hz sampling, 2-sample confirm), jog-cancels (0x85) and backs off. CSV to /tmp/bump.csv. |
| `build-feeder.sh` | Cross-compiles `feeder.c` the same way. |
| `puls_profile.py` | Decodes factory `.puls` streams (raw or GF1-headered) into velocity/accel profiles: peak speeds, ramp-slope fits, per-move segments, Z cadence. Runs anywhere (stdlib only). Source of the factory-true grblHAL defaults: 700/590 mm/s² accel, 200 mm/s max rate, 28160 Hz travel tick. |
| `cp_watchdog_timing.py` | HV charge-pump watchdog one-shot timing (runs on the board): latches every CHG_PUMP feed pulse in GPIO3's edge detector (pin 24 only, IMR untouched, ICR2 restored on exit) and polls the `!Q` (`charge_pump_alive`) and `!HV_ENABLE` (`hv_enable`) pads through /dev/mem in a tight loop while it commands short local jogs; prints per-run t_w (last pulse → Q fall), Q → HV_ENABLE delay, priming latency and the feed period, with the loop's worst gap as the resolution. Motion only, laser locked, no other Grbl client attached. |
| `resume_dark_lead.py` | Pause/resume safety-chain timing (runs on the board, as root): samples LASER_ON, FIRE, HV_ENABLE, the charge-pump watchdog, the button and the doors straight off the SoC pads through /dev/mem at ~2 kHz, with motion dated from the kernel step counters, across a pause and a resume driven by the operator's button presses. Reports how long HV_ENABLE survives the stream stopping, how fast the chain re-arms on the resume, and - on `--run live` - the dark lead between FIRE going back on and LASER_ON following it, in milliseconds and in millimeters at the job's feed. `--run dry` (default) commands no laser at all and `--auto P,R` drives the pause and resume with `!`/`~` for an unattended rehearsal; `--run live` needs the arm press, eye protection, fire watch, extinguisher and exhaust. GRBL mode, no other Grbl client attached. |
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

To reproduce on another machine: boot the dev image and run the
**flow-matrix** tool from the bench page (`#bench`; a takeover, ~1.6 h for
the full matrix; the results land under `/data/forgetest/bench/`), or from a
host with `GF_HOST` (and `GF_SSH` if ssh needs a wrapper), forgectrl and the
controller stopped, `flow_matrix.py [duties] [repeats]`. The same
derivation is also built into forgectrl as the panel's Diagnostics →
**flow-calibrate** tool (3 trials per case at the operating point, reports
both bands and a recommended threshold; the bench value it recommends
lands within a few tenths of a degree of 14.4). Apply a per-machine value
through the `cool_flow_rise` setting rather than editing the constant.
