# ForgeFIRM bench tools

Hardware-verification tools for the ForgeFIRM bench. All run ON the
target board (dev image, python3 present) unless noted.

| Tool | Purpose |
|---|---|
| `feeder.c` | Spike-step-3 underrun proof: streams NOP pulse bytes to `/dev/glowforge` with wall-clock pacing, bounded queue depth, deadman flock, SCHED_FIFO. Usage: `feeder <hz> <seconds> <depth_ms>`. Passed 100 kHz × 120 s under full load with 0.2 ms worst write latency. Cross-compile with `build-feeder.sh` (WSL). |
| `bench_phase2.py` | End-of-data protocol bench (audit M2–M5): underrun detection/ack, parked no-replay guard, resume(0), continuous-feed stability, 20× run/underrun cycles. Motion-safe (motors locked, laser latched). 16/16 PASS on 2026-07-26. |
| `check_pwm.py` | Laser PWM register check (audit M8): reads PWM2 PWMCR/PWMPR via /dev/mem, expects divider 13 × ~127 counts ≈ 40 kHz. The scope on LASER_PWM remains the final pre-live-fire gate. |
| `build-glowforge.sh` | Cross-compiles **grblHAL-glowforge** (the canonical driver repo, `../../../grblHAL-glowforge`) in the forge-yocto WSL distro. Run: `wsl -d forge-yocto -- bash <path>/build-glowforge.sh` (from PowerShell; Git Bash mangles /mnt/c paths). This is the production controller build. |
| `build-feeder.sh` | Cross-compiles `feeder.c` the same way. |
| `puls_profile.py` | Decodes factory `.puls` streams (raw or GF1-headered) into velocity/accel profiles: peak speeds, ramp-slope fits, per-move segments, Z cadence. Runs anywhere (stdlib only). Source of the factory-true grblHAL defaults (milestone 2): 700/590 mm/s² accel, 200 mm/s max rate, 28160 Hz travel tick. |
| `bench_m2.py` | Milestone-2 motion bench, runs against the board over TCP:23: bounded round-trip jogs (sanity, max-rate, diagonal) + feed-hold/resume mid-move, reporting peak feed, state transitions, and position drift. All-green 2026-08-02 at factory-true settings. |

The build scripts borrow the Yocto cross toolchain + sysroot from the ulfius
2.7.15 work directory in the WSL build tree; if that path ages out after a
`bitbake -c clean`, point `TC` at any current target recipe workdir (or build
a proper SDK with `bitbake meta-toolchain`).
