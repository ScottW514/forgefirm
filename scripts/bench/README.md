# ForgeFIRM bench tools

Hardware-verification tools for the ForgeFIRM bench. All run ON the
target board (dev image, python3 present) unless noted.

| Tool | Purpose |
|---|---|
| `feeder.c` | Underrun proof: streams NOP pulse bytes to `/dev/glowforge` with wall-clock pacing, bounded queue depth, deadman flock, SCHED_FIFO. Usage: `feeder <hz> <seconds> <depth_ms>`. Proven envelope: 100 kHz × 120 s under full load, 0.2 ms worst write latency. Cross-compile with `build-feeder.sh` (WSL). |
| `bench_phase2.py` | End-of-data protocol bench: underrun detection/ack, parked no-replay guard, resume(0), continuous-feed stability, 20× run/underrun cycles. Motion-safe (motors locked, laser latched). |
| `check_pwm.py` | Laser PWM register check: reads PWM2 PWMCR/PWMPR via /dev/mem, expects divider 13 × ~127 counts ≈ 40 kHz. |
| `pwm_sweep.py` | LASER_PWM scope test (runs on the board): `check` = read-only safety readbacks + PWM2 dump; `sweep` = steps PWMSAR through 50/25/75/6/100 % duty with 4 s holds, then restores. Run only in the locked state (controller stopped, cnc disabled, latch locked). |
| `pwm_hold.py` | Holds one PWMSAR value for a scope-measurement window (`pwm_hold.py <sar> <seconds>`), then restores. Same locked-state rule. |
| `fire_test.py` | FIRE drop-timing scope test (runs on the board): A = latch locked (expects nothing on FIRE/LASER_ON), B = latch unlocked / normal end-of-data, U = true underrun. Duty 0 throughout; refuses to unlock if HV reports good. |
| `fan_test.py` | Fan/coolant bench (Windows-side): snapshots fan PWMs/tachs/temps, drives M8 → cut fans, M9 → cooldown → idle, verifying via tach readbacks. |
| `flow_characterize.py` | Coolant flow characterization using the factory temperature curve: baseline → flow → no-flow → recovery, printing the ΔT bands and their separation. Takes the heater duty as an argument (`flow_characterize.py 30`); aborts if downstream passes 45 °C. |
| `flow_matrix.py` | **The flow-detection design matrix** (with `flow_sampler.py`, which lives on the board at `/data/`): duty × duration × flow/no-flow, every run from a common cooled baseline, interleaved repeats. One heating trace yields the metric at every candidate duration, so cost and precision come from the same 60 runs. Prints a cost table, a precision table (mean±sd, worst-case margin, d′) and a ranked shortlist. Env: `FM_DUTIES`, `FM_REPEATS`, `FM_RESULTS`. |
| `flow_sustained.py` | Long-run test of the real re-check cadence via M8: counts verdicts/false faults and tracks whether the loop accumulates heat. |
| `flow_warm_validate.py` | Runs the real check from a heater-warmed baseline. Note the ceiling: 100 % duty pushes the downstream sensor past 50 °C in 30 s while the bulk barely moves, so warm-loop validation above ~23 °C needs the laser, not the heater. |
| `flow_recheck_char.py` | Characterizes short in-run re-checks and the differential metric; shows why over-temp cannot see a stopped pump and why passive warming trends are ambiguous. |
| `temp_calibrate.py` | Coolant temperature spot-check helper (`watch` / `point <measured_C>` / `fit`) — pairs a measured temperature with averaged raw ADC readings and fits a per-machine line to sanity-check the factory curve against a thermometer. |
| `build-glowforge.sh` | Cross-compiles **grblHAL-glowforge** (the canonical driver repo, `../../../grblHAL-glowforge`) in the forge-yocto WSL distro. Run: `wsl -d forge-yocto -- bash <path>/build-glowforge.sh` (from PowerShell; Git Bash mangles /mnt/c paths). This is the production controller build. |
| `build-forgectrl.sh` | Cross-compiles **forgectrl** (the canonical control-daemon repo, `../../../forgectrl`) the same way, borrowing the toolchain from the forgectrl recipe workdir (regenerate with `bitbake forgectrl` after a clean). |
| `build-feeder.sh` | Cross-compiles `feeder.c` the same way. |
| `puls_profile.py` | Decodes factory `.puls` streams (raw or GF1-headered) into velocity/accel profiles: peak speeds, ramp-slope fits, per-move segments, Z cadence. Runs anywhere (stdlib only). Source of the factory-true grblHAL defaults: 700/590 mm/s² accel, 200 mm/s max rate, 28160 Hz travel tick. |
| `bench_m2.py` | Motion-quality bench, runs against the board over TCP:23: bounded round-trip jogs (sanity, max-rate, diagonal) + feed-hold/resume mid-move, reporting peak feed, state transitions, and position drift. |

The build scripts borrow the Yocto cross toolchain + sysroot from the ulfius
2.7.15 work directory in the WSL build tree; if that path ages out after a
`bitbake -c clean`, point `TC` at any current target recipe workdir (or build
a proper SDK with `bitbake meta-toolchain`).
