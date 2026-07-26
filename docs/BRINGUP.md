# ForgeFIRM bring-up status & cold-start runbook

Last updated: **2026-07-26** — the day the machine first moved under grblHAL.
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

## The bench

- **Board**: SSH `root@172.16.1.130`, empty password
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
  (now includes `python3-gfhardware`). Build:
  `cd ~/dev/openglow-forgefirm/forgefirm && kas shell
  kas/forgefirm-glowforge.yml -c 'bitbake forgefirm-image
  forgefirm-image-dev'`. Artifacts:
  `forgefirm/build/tmp/deploy/images/glowforge/`.
- **Shell gotchas** (cost real time): PowerShell mangles embedded double
  quotes in git-commit here-strings (avoid `"` in messages); `wsl -- bash
  -c '...'` eats `$VAR` expansions (use script files run via PowerShell,
  not Git Bash, which MSYS-mangles `/mnt/c` paths).

## Running the step backend (grblHAL on the board)

Source: the ForgeFIRM grblHAL step backend (grblHAL core + the
glowforge pulse-stream sink).

1. Build: cross-compile the backend in the forge-yocto WSL distro (from
   PowerShell). Produces `build-arm/grblHAL_glowforge` in the WSL tree
   (`-O1 -g`, `GLOWFORGE_DEFAULTS=ON` → machine scaling baked in:
   53.333 µsteps/mm XY @ ×8, 2.832 half-steps/mm Z, 0.417" Z travel).
2. Deploy to `/usr/bin/grblHAL_glowforge` on the board.
3. **Analog machine config — required after every module reload/boot; the
   kernel does NOT do this** (the cloud stack normally did):
   ```sh
   echo 150 > /sys/glowforge/pic/x_step_current   # run current; 33 = weak hold.
   echo 150 > /sys/glowforge/pic/y_step_current   # Factory-true values TBD
   echo 8   > /sys/glowforge/cnc/x_mode           # ×8 microstepping to match
   echo 8   > /sys/glowforge/cnc/y_mode           #   the baked steps/mm
   echo 8   > /sys/glowforge/cnc/motor_lock       # Z locked; X/Y free
   echo 1   > /sys/glowforge/cnc/laser_latch      # laser locked out
   ```
4. Start: `cd /data && GFSINK=/dev/glowforge grblHAL_glowforge -p 23 -n -t 1.0`
   (`-t 1.0` is REQUIRED: the real-time throttle is what bounds the
   queue). Env knobs: `GFSINK_RATE` (machine tick, default 10000 Hz),
   `GFSINK_DEPTH_MS` (queue depth = feed-hold latency, default 200).
5. Connect LightBurn/UGS to `172.16.1.130:23`, or jog raw:
   `$J=G91X40F1200`.

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
- Laser PWM: 39.98 kHz register-verified (divider 13 × 127 counts).
- Switches: truthy = closed/OK; SW_INTERLOCK reads False on units without
  the rear plug — must NOT gate motion (beam is hardware-gated).
- Machine identity from OCOTP nvmem: serial 00000000 → hostname XXX-XXX
  (matches the factory label).

## Next work (in rough order)

1. **Backend milestone 2 — motion quality**: motion is loud/jerky at the
   10 kHz tick. Raise `GFSINK_RATE` to 20–50 kHz (finer step-timing
   quantization), find factory-true run currents (puls-file headers carry
   them — see gfutilities settings map XSrc/YSrc) and sane accel/max-rate;
   verify smooth diagonal moves and feed-hold mid-move.
2. **Laser mapping** (gated on the scope session): spindle → power bytes
   (bit 7) + bit 4 laser-enable, M3/M4/$32 semantics, PWM-reset rule per
   the contract. **No live fire before the standing scope gates**: LASER_PWM
   waveform vs factory capture + ≤1-tick laser drop at underrun.
3. **Homing**: X/Y home switch GPIOs exist in the cnc pin map (unused so
   far); wire as grblHAL limits or keep StallGuard-less factory scheme;
   Z homes against the hall sensor (top).
4. **6.5 safety mapping**: door/estop evdev → feed-hold/halt in the
   backend; underrun → grblHAL alarm; interlock-trip recovery check.
5. **6.6 camera service**: persistent MJPEG (ulfius, forgectrl) — also the
   natural time for the deferred 5.6 emulator smoke (homing images).
6. **Housekeeping**: upstream the settings-write crash fix (grblHAL
   crashes on every runtime $-settings write — NULL chained
   `grbl.on_settings_changed` in gcode.c's gc_init); Phase 7 doc sweep
   (CLAUDE.md charter refresh, README roadmap); kas flip + first GitHub
   release per kas/README.md once ready to publish.
