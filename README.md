# OpenGlow/ForgeFIRM Firmware for Glowforge

Open-source firmware for Glowforge brand CNC lasers. ForgeFIRM replaces the
cloud-dependent factory software on the **stock control board** — no hardware
modification — and gives the machine a local controller, a local web control
panel, and a standard Grbl interface.

* [Latest Release](https://github.com/ScottW514/forgefirm/releases)
* [Installation Instructions](https://github.com/ScottW514/forgefirm/blob/master/INSTALL.md)
* [Build Instructions](https://github.com/ScottW514/forgefirm/blob/master/BUILD.md)
* [Connecting LightBurn](https://github.com/ScottW514/forgefirm/blob/master/docs/LIGHTBURN.md)
* [How the laser safing works](https://github.com/ScottW514/forgefirm/blob/master/docs/SAFETY.md)
* [How a release is accepted](https://github.com/ScottW514/forgefirm/blob/master/docs/ACCEPTANCE.md)
* [Community Support](https://community.openglow.org)

## What it does

**Two controller modes, selected in the web panel and switchable while the
machine is idle:**

* **GRBL mode** — [grblHAL](https://github.com/grblHAL) runs on the machine and
  speaks Grbl 1.1 over TCP port 23, so LightBurn, UGS, and cncjs drive the
  laser directly. Motion runs on the board's own hardware step engine (SDMA +
  EPIT), fed live by the planner. M3/M4 dynamic laser power, coolant-flow
  verification, over-temp holds, and an operator button press to arm the laser
  for each job.
* **Cloud mode** — the machine presents itself as a stock Glowforge to the
  Glowforge web service, so the phone and web apps work as they always did.
  Optional, and off by default. GRBL mode jogs and cuts without it; the one
  GRBL-mode function that still reaches the Glowforge service is
  camera-referenced homing (below), until limit-switch homing lands.

**Around both modes:**

* A **web control panel** on port 8080: machine status and position, coolant
  and fan telemetry, safety-switch states, camera view, machine settings,
  hardware diagnostics, firmware updates, and boot-slot management.
* **Unified logging**: every ForgeFIRM component logs through syslog into its
  own directory under `/data/log/forgefirm`, with per-logger levels for the
  device and for an optional remote syslog server, a live viewer in the
  panel, and a one-click log bundle — sanitized of identifying details — for
  attaching to an issue report.
* Both **cameras** as MJPEG streams and full-resolution snapshots — the lid
  camera feeds LightBurn's camera overlay directly.
* **Camera-referenced homing**: `$H` from any sender runs the factory-style
  camera homing cycle through the Glowforge service (a Glowforge account and a
  live service session are required for `$H`; everything else in GRBL mode
  runs without them), and the machine records where it is.
* **Installs alongside the factory firmware** in the unused A/B rootfs slot,
  archiving every factory version first, so the machine can be switched back
  to stock at any time without the Glowforge cloud.

## Hardware

The control board is common to Glowforge Basic, Plus, and Pro. The 5 MP
(OV5648) camera modules are fully supported; the 8 MP (OV8856) modules found in
"HD" units bind but do not capture yet — see the camera note in
[kas/README.md](kas/README.md).

## Roadmap

* Limit-switch homing as an alternative to camera-referenced homing.
* Camera lens calibration and bed alignment for the LightBurn overlay.
* Capture support for the 8 MP (OV8856) camera modules.
* Cloud mode: stream jobs into the motion ring during the run, lifting the
  job-length cap that buffering the whole job imposes.

## Safety

**This machine contains a Class 4 CO₂ laser: it burns, blinds, and starts
fires.** Never defeat the lid switches or interlock, always vent the exhaust
outdoors, and never cut PVC or other chlorinated plastics. Never leave a
running job unattended — keep a fire extinguisher within reach. Read
[Before you cut — safety](docs/LIGHTBURN.md#before-you-cut--safety-read-this-first)
before your first job, and the
[Regulatory and legal](INSTALL.md#regulatory-and-legal) section before
installing. [How the laser safing works](docs/SAFETY.md) describes the hardware
safety chain and the software gates ForgeFIRM stacks on it.

**A very important warning: this is experimental software. Use of this software
could seriously maim or kill you or others, and voids your warranty. It is not
affiliated with or endorsed by Glowforge. Use it at your own risk.**
