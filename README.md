# OpenGlow/ForgeFIRM Firmware for Glowforge

Open-source firmware for Glowforge brand CNC lasers. ForgeFIRM replaces the
cloud-dependent factory software on the **stock control board** — no hardware
modification — and gives the machine a local controller, a local web control
panel, and a standard Grbl interface.

* [Latest Release](https://github.com/ScottW514/forgefirm/releases)
* [Installation Instructions](https://github.com/ScottW514/forgefirm/blob/master/INSTALL.md)
* [Build Instructions](https://github.com/ScottW514/forgefirm/blob/master/BUILD.md)
* [Connecting LightBurn](https://github.com/ScottW514/forgefirm/blob/master/docs/LIGHTBURN.md)
* [How motion and the laser are driven](https://github.com/ScottW514/forgefirm/blob/master/docs/MOTION.md)
* [How cooling and airflow work](https://github.com/ScottW514/forgefirm/blob/master/docs/COOLING.md)
* [The cameras and the video stream](https://github.com/ScottW514/forgefirm/blob/master/docs/VIDEO.md)
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
* **Camera-referenced homing**: `$H` from any sender runs the factory-style
  camera homing cycle through the Glowforge service (a Glowforge account and a
  live service session are required for `$H`; everything else in GRBL mode
  runs without them), and the machine records where it is.
* **Cameras only capture with the lid closed.** The lid camera faces the room
  once the lid is raised, so ForgeFIRM refuses every capture — live view,
  snapshot, and anything the Glowforge service asks for in cloud mode — until
  the enclosure is shut, and stops a running stream the moment the lid opens.
  See [the cameras and the video stream](https://github.com/ScottW514/forgefirm/blob/master/docs/VIDEO.md).

## Hardware

The control board is common to Glowforge Basic, Plus, and Pro. The 5 MP
(OV5648) camera modules are fully supported and hardware-validated. The 8 MP
(OV8856) modules found in "HD" units have a complete capture path — the kernel
patches, device tree and sensor-aware capture profile they need are all in the
build — but it has never run on an 8 MP machine, so treat it as untested; see
the camera note in [kas/README.md](kas/README.md).

## Safety

**These machines contain a CO₂ laser: it burns, blinds, and starts
fires.** Never defeat the lid switches or interlock. Never leave a
running job unattended — keep a fire extinguisher within reach. Read
[Before you cut — safety](docs/LIGHTBURN.md#before-you-cut--safety-read-this-first)
before your first job, and the
[Regulatory and legal](INSTALL.md#regulatory-and-legal) section before
installing. [How the laser safing works](docs/SAFETY.md) describes the hardware
safety chain and the software gates ForgeFIRM stacks on it.

**A very important warning: this is experimental software. Use of this software
could seriously maim or kill you or others, and voids your warranty. It is not
affiliated with or endorsed by Glowforge. Use it at your own risk.**
