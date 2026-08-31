# Motion and laser drive

Everything the machine does physically — every step of the gantry, every lens
move, every laser pulse — comes out of **one stream of bytes** played by
hardware at a fixed rate. This page explains that stream, why the laser is part
of it rather than beside it, and how the two controller modes (GRBL and cloud)
feed it.

You do not need any of this to run a job. It is here so that what the machine
does makes sense, and so the settings you can change mean something.

- To cut from LightBurn, see [LightBurn setup & operation](LIGHTBURN.md).
- For the safety chain that gates the beam, see [Laser safety](SAFETY.md).
- For fans, pump and coolant, see [Cooling and airflow](COOLING.md).

---

## 1. The pulse stream

The control board does not decide, moment by moment, when to move a motor.
Instead a hardware timer (EPIT) fires at a fixed **machine tick**, and a DMA
engine (SDMA) hands the next byte of a prepared stream straight to the GPIO
register that drives the stepper and laser lines. No software runs between the
timer and the pins.

That is what makes motion smooth: step timing cannot be disturbed by a busy
CPU, a camera stream, a network client, or a garbage collector. The worst a
loaded system can do is fail to supply bytes fast enough — and that case is
detected and treated as a fault rather than as silent damage.

### One byte per tick

Each byte covers exactly one tick. If the top bit is clear, the byte commands
steps and fire; if it is set, the byte sets laser power.

| Bit | Meaning |
|---|---|
| 0 | X step |
| 1 | X direction (set = −X) |
| 2 | Y step |
| 3 | Y direction (set = +Y; the two Y motors are driven complementary) |
| 4 | **Laser fire during this tick** |
| 5 | Z step |
| 6 | Z direction (set = lens up, away from the bed = +Z) |
| 7 | 0 = step byte · 1 = power byte (low 7 bits are the power level) |

**Speed is density, not clock.** The tick rate never changes inside a job.
Going faster means setting a step bit in more of the bytes; going slower means
spacing them out. A move is planned in the usual way — acceleration, cruise,
deceleration — and then resampled onto this fixed grid.

Two consequences worth knowing:

- **Resolution is bounded by the tick rate.** At the default GRBL machine tick
  of 28160 Hz, one axis can take at most 28160 steps per second — about
  528 mm/s, comfortably above the machine's 200 mm/s top speed.
- **There is a hardware ceiling.** The playback script needs about 6 µs per
  byte, so beyond roughly 165 kHz the timer outruns it. Ticks are chosen far
  below that.

### The ring, and two ways to fill it

Pulse bytes go into a 32 MiB ring buffer in reserved memory, the same size the factory firmware uses. There are two ways
to use it, and the mode you run decides which:

- **Live streaming (GRBL mode).** The controller keeps only a small window of
  the job in the ring — a fraction of a second — and refills it continuously
  while the job plays. A write that would overflow is refused, and the feeder
  backs off; that is normal flow control, not an error. If the feeder ever
  falls behind far enough to empty the ring, the machine enters an **underrun**
  state: motion stops instantly, and position is no longer trusted.
- **Preloading (cloud mode).** The whole job is written into the ring before it
  starts. Nothing can starve, but the ring size caps job length: roughly
  1 MiB per 100 seconds at the cloud's 10 kHz tick, so about 56 minutes. A job
  larger than the ring is rejected cleanly before it runs.

### Stopping and resuming at the hardware level

The pulse engine itself offers three ways out of a running program, and both
modes are built on them:

- **Controlled stop** — the tick rate ramps down at a set rate (125000 Hz/s by
  default) until motion halts. No steps are lost, so position stays accurate.
  This is what a feed hold, a jog cancel, a lid-open cancel and a soft reset
  all use.
- **Halt** — an immediate stop with no ramp. Steps can be lost; used only for
  emergencies.
- **Resume with a waypoint** — from a controlled stop the program can be
  resumed a chosen number of steps backward (laser forced off) or forward. This
  is how the factory's pause-and-resume works, and cloud mode uses it. It is
  only available for a preloaded job: a live-streamed ring no longer holds the
  bytes to back into, and the kernel refuses the request.

Whenever a stream ends — normally or by starvation — the playback script drives
the fire and step lines low as a hardware backstop.

---

## 2. Laser drive is part of the motion stream

The laser is not a separate subsystem that gets told "on" and "off" while
motion happens elsewhere. **Power and fire ride the same bytes as the steps**,
on the same grid:

- A **power byte** (top bit set) sets the PWM duty of the laser drive: 7 bits
  written straight into the hardware PWM against a 127-count period, at a
  carrier near 40 kHz. 127 is full power.
- The **fire bit** (bit 4) requests emission for that one tick, and only that
  tick.

Because both travel with the steps, power and position cannot drift apart. A
power change lands at exactly the point along the path where it was planned,
regardless of what the rest of the system is doing.

Three rules follow from the hardware, and both controllers obey them:

1. **Power before fire.** Starting a program resets the duty to about 100 %, so
   a stream must set power before its first fire bit — otherwise the first
   pulses would fire at full power.
2. **No two power bytes in a row.** The playback script applies the first of a
   run of power bytes and discards the rest, so power changes are spaced by at
   least one step byte.
3. **End dark.** Every stream ends with fire clear; the end-of-data backstop is
   the safety net, not the mechanism.

Also worth knowing: **the duty setting persists after a program ends.** The
laser-off guarantee rests entirely on the fire bit and the hardware chain, never
on power being zero.

### What actually lets the beam out

The fire bit is a *request*. Emission additionally requires the hardware safety
chain — lid switches, the remote interlock loop, HV good, supply rails, the
charge-pump watchdog the kernel feeds only while a program is playing, and the
physical button latch — to agree. On top of that, ForgeFIRM keeps the kernel's
**laser latch** locked except inside an operator-armed job window (§5.4), and
the kernel relocks it whenever the pulse device is closed.

Fire only ever rides motion segments of laser blocks. Jogs, rapids and homing
are fire-free by construction, not by convention. See [SAFETY.md](SAFETY.md)
for the chain itself.

---

## 3. Geometry, speeds and limits

| Property | Value |
|---|---|
| X/Y resolution | 0.15 mm per full step, ×8 microstepping → 53.333 µsteps/mm |
| Z resolution | 0.3534 mm per half-step → 2.832 half-steps/mm |
| Work area | 495 × 279 mm |
| Z travel | about 10.6 mm (0.417"), hall-referenced at the top |
| Max X/Y rate | 12000 mm/min (200 mm/s) |
| Max Z rate | 300 mm/min |
| Acceleration | 700 mm/s² X, 590 mm/s² Y, 50 mm/s² Z |
| Laser PWM carrier | 39.98 kHz, 7-bit duty |

Origin is the **back-left** corner, and the workspace is all-positive from
there. **+Y moves the gantry toward the front of the machine.** Z counts
positive upward, away from the bed.

Z is never driven blind: the lens carriage is referenced against a hall sensor
at the top of travel, and moves are supervised against it.

The machine has **no limit or home switches** as it ships. What that means in
practice — how each mode establishes an origin, and how the machine behaves
without one — is in §5.7 and §6.3.

---

## 4. Who owns the motion hardware

`forgectrl`, the machine-services daemon, owns the pulse device for as long as
it runs and hands the open connection to whichever controller is active. Only
one controller — GRBL or cloud — runs at a time, and switching between them is
a live operation from the web panel.

Two behaviors follow from this that you will notice:

- **The 40 V motor rail stays up while the machine is on.** Handing the device
  from one controller to another never cycles it. The stepper drivers on this
  board can latch into an unserviceable state on a rail glitch — the position
  counters keep counting while the motors produce nothing — so the rail is left
  alone.
- **The machine proves it can move before the first job of a session.** Before
  the first controller start, forgectrl makes a short test move (always to the
  right first — a cable lives at the left end of travel) and confirms it with
  the accelerometer in the print head. If it sees no motion it powers the rail
  down and retries with progressively longer off periods; if the drivers still
  will not wake, it reports a **motion fault** instead of starting a
  controller, and the panel offers a retry. Position counters advancing are
  never accepted as proof that the machine moved.

---

## 5. GRBL mode

GRBL mode turns the machine into a standard Grbl-speaking laser cutter. It is
the default and the one to use for your own designs.

### 5.1 Connecting

The controller speaks **Grbl 1.1 over TCP port 23**. Point LightBurn, UGS,
cncjs or any Grbl sender at the machine's address on port 23. Setup details and
a first job are in [LIGHTBURN.md](LIGHTBURN.md).

Only one sender at a time is meaningful. Opening a second connection displaces
the first — which is also why the web panel reads position from the machine's
own counters and never from the Grbl socket.

### 5.2 From G-code to pulse bytes

1. Your sender streams G-code over TCP.
2. grblHAL parses it and plans motion in the usual way: look-ahead, junction
   deviation, acceleration ramps.
3. A producer thread runs the planner's step generator against a virtual clock
   a thousand times finer than the machine tick and places each step event on
   the byte grid.
4. A high-priority shipper thread writes due bytes to the pulse device roughly
   every 10 ms, keeping a bounded queue ahead of real time.

The queue depth is the trade: deeper means more immunity to system load,
shallower means a feed hold or a power override takes effect sooner. The
default is 200 ms, and the machine tick defaults to 28160 Hz — the same tick
the factory firmware uses for travel moves.

### 5.3 Laser mapping

- `$32` (laser mode) is **on by default**, so `M3`/`M4` and `S` behave the way
  senders expect. `M4` gives dynamic power scaled with speed through
  acceleration ramps; `M3` gives constant power.
- `$30` is 1000, and S values map linearly onto the 7-bit power byte —
  `S1000` = full power, `S500` ≈ half.
- Power changes are emitted ahead of the tick they apply to, so a power change
  and the motion it belongs to stay together.

### 5.4 Arming: the button press is part of every job

The first laser-on of a job does not fire. Instead the controller:

1. **Checks the coolant verdict.** If a flow fault or an over-temperature
   condition stands, arming is refused outright ([COOLING.md](COOLING.md)).
2. **Checks that a print head is present.** No head, no arming.
3. **Forces the cut airflow profile on**, so every fire window is covered by
   running fans and active flow verification.
4. **Unlocks the kernel laser latch, lights the button white, and pauses the
   job** — the sender keeps getting status reports, so it does not time out —
   until you press the physical button.

A press with the lid open does not arm; the hardware button latch would not
clear on it either. A soft reset, or a lid or interlock open, cancels the job
instead. If nobody presses within `laser_button_timeout_s` (default 300 s), the
job ends in an alarm with the latch relocked. The coolant verdict is re-checked
after the press, so a window can never open against a fault that appeared
during the wait.

**The window is per job, not per fire.** It survives `S` changes and `M5`/`M3`
toggles, so nothing re-prompts mid-job, and it closes — relocking the latch —
when any of these happens:

- program end (`M2`, `M30`, `%`) — the normal case, within the cycle;
- the sender's connection changes (the consent belonged to that session);
- `laser_disarm_s` (default 60 s) of spindle-off idle, counted down in Hold,
  Door and Tool Change as well as Idle;
- immediately on alarm, homing, reset, or a stream fault.

### 5.5 Pausing, stopping and faults

| You do | What happens |
|---|---|
| Feed hold (`!`) | Controlled ramp to a stop, position kept, laser off. The disarm grace keeps counting. |
| Cycle start (`~`) | Resumes from the hold. A live-streamed job cannot back up, so the cut resumes where the deceleration ended. |
| Jog cancel (`0x85`) | Controlled stop, jog abandoned, position kept. |
| Soft reset (`^X`) | Controlled deceleration into Alarm, latch relocked, machine position retained; `$X` clears the alarm. |
| Press the button mid-job | Pause; press again to resume (§5.6). |
| Open the lid or the interlock loop | The job is **canceled**, not paused (§5.6). |
| Ring runs dry (underrun) | Motion stops instantly. While armed this is a hard fault: alarm, latch relocked, position invalidated — re-home before trusting coordinates. A motion-only job gets one sanctioned retry. |
| Coolant fault or over-temp | Feed hold with cut airflow forced on; fire is gated. Over-temp resumes automatically once the loop recovers. |
| Controller crash or hang | The daemon stops motion and relocks the latch, then restarts the controller. |

### 5.6 Lid, interlock and button

ForgeFIRM reproduces the factory machine's behavior:

- **A lid or interlock open during a job cancels it.** Motion stops within
  milliseconds of the switch edge, the job is not resumable, the latch relocks,
  and the head returns to the position the job started from — **with the lid
  still open**, exactly as the factory does. The return-home move always runs
  to completion.
- **The button pauses and resumes.** In GRBL mode a press is a feed hold and
  the next press is a cycle start. A pause is not a cancel: the armed window
  stays open across it.
- **Idle lid cycles are ignored.** Opening the lid to load material, or
  powering up with it open, does not leave the controller parked — senders
  connect normally.
- **Jogs are not lid-gated.** The core is blind to the door signal while it is
  idle, jogging or homing, so a jog both starts and runs with the lid open —
  the beam is blocked in hardware regardless.
- **Homing is lid-gated in practice**, even though the core does not see the
  door during `$H`. With `homing_mode = gfcloud` — the only method that works
  today — the cycle is a cloud homing session (§5.7), and its move to the home
  corner is an ordinary motion action: refused with the lid open, and stopped
  if the lid opens partway through. The camera steps need the lid closed
  anyway. Only the lens/Z **hunt** inside that session ignores the lid (§6.3),
  which is where hunts happen in GRBL mode — there is no hunt outside a cloud
  homing session. Under `homing_mode = switches` a Z reference would just be
  part of the core homing cycle.

The next job re-arms with a fresh button press — the same press the hardware
button latch itself requires, which is why software and hardware cannot
disagree about whether the machine is armed.

If you prefer stock Grbl door behavior, set `lid_policy = hold`: the job parks
in the Door state and a cycle start after the lid closes finishes the move with
its position intact.

### 5.7 Homing, and running unhomed

The homing method is a setting (`homing_mode`), chosen in the web panel:

- **`gfcloud`** — camera homing through the Glowforge web service, the same
  cycle the factory machine runs. `$H` suspends the stream engine, runs the
  session, then hands the machine back. Takes roughly a minute and uses the
  machine's builtin credentials.
- **`switches`** — the future limit-switch cycle. Not enabled yet; brackets for
  the switches are in the project's `3d-models/` directory.
- **`none`** — `$H` is rejected.

**The machine cuts fine unhomed.** Without a reference, coordinates are
relative to wherever the head happened to be, so the panel shows position in
red to say so, and your sender should use a job-start mode that does not depend
on machine coordinates. After a successful home the position is anchored and
shown normally.

Anything that invalidates position — an underrun, a stream fault — drops the
anchor deliberately, so a stale origin cannot be reused.

---

## 6. Cloud mode

Cloud mode runs the factory experience: the Glowforge app and web service, the
camera bed image, the lens hunt, "push the button to print". It is kept and
maintained on purpose. Behavior specific to the service — actions, events,
credentials — is in the cloud-mode documentation (`python3-gfhardware/forgefirm-app/docs/CLOUD.md`).

### 6.1 What is different about the motion path

In cloud mode the machine does not plan anything. The service sends a
**precomputed pulse file** — already resampled to the byte format described in
§1 — which the client downloads, writes into the ring, and plays:

1. The service issues a print action with a URL for the motion data.
2. The client downloads it and validates the header before a byte reaches the
   ring. A job larger than the ring is refused cleanly.
3. The header's own parameters are applied: the machine tick (10 kHz for prints
   and hunts), the acceleration ramp, and the per-job fan duties, which are
   passed to the cooling engine as the run profile.
4. The button wait arms the laser, exactly as in GRBL mode.
5. The ring plays to the end; the client supervises it and reports state.

Because the whole job is preloaded, there is no feeder to starve — but there is
also no live re-planning, and job length is capped by the ring.

### 6.2 Pause, cancel and park

- **The button pauses and resumes a print**, and here it does so exactly as the
  factory does: a press stops motion under control and then backs the stream up
  2000 ticks with the laser off; the next press runs forward and re-enables the
  laser after a 1950-tick lead, so the resumed cut overlaps the material
  already burned instead of starting cold. Both counts are settings
  (`cloud_pause_backtrack_ticks`, `cloud_resume_lead_ticks`). Motions and
  hunts do not pause.
- **A lid or interlock open, or a cancel from the app, ends the job.** Motion
  stops, whatever remains in the ring is dropped so nothing can play later, and
  the head parks back at the job's starting point — ignoring the lid, as the
  factory does. The job is reported as canceled.
- **The service dead-reckons position**, so the park after every print,
  finished or aborted, matters: cutting it short would offset everything until
  the next camera home. That is why the park ignores the lid and the cancel
  flag.

### 6.3 Homing and hunts

Cloud homing is camera-based: the service takes a lid image, moves the head,
takes another, and computes where it is. The lens hunt references Z against the
hall sensor. Hunts are not lid-gated. Connecting zeroes the machine's counters
at the head's current position, so GRBL-mode coordinates do not survive a
switch to cloud mode and back — re-home after switching.

---

## 7. The two modes side by side

| | GRBL mode | Cloud mode |
|---|---|---|
| Who plans motion | grblHAL on the machine | the Glowforge service |
| Input | G-code over TCP:23 | a downloaded pulse file |
| Ring use | live-streamed, small window | whole job preloaded |
| Machine tick | 28160 Hz default | 10 kHz (from the job header) |
| Job length limit | none | ~56 minutes (ring size) |
| Needs internet | no | yes |
| Laser arming | button press per job | button press per job |
| Button mid-job | feed hold / cycle start | pause with backtrack / resume with lead |
| Lid or interlock open | cancel + return to job start | cancel + park at job start |
| Homing | `$H` (camera or, later, switches) | automatic, camera-based |
| Fan control | `M8`/`M9` plus the armed window | per-job duties from the job header |
| Underrun possible | yes (handled as a fault) | no (nothing is streamed) |

Only one mode runs at a time. Switch from the panel's Status tab; the switch is
allowed only when the machine is idle.

---

## 8. Settings that affect motion

Machine settings live in the web panel and are stored on the machine. They can
only be changed while the machine is idle.

| Setting | Default | Effect |
|---|---|---|
| `controller_mode` | `grbl` | Which controller runs: `grbl` or `cloud`. |
| `homing_mode` | `gfcloud` | What `$H` does: `gfcloud`, `switches`, `none`. |
| `gfcloud_home_x/y/z` | 0 / 0 / Z max | Coordinates assigned after a successful camera home. |
| `gfcloud_home_timeout_s` | 300 | How long a homing session may take before it alarms. |
| `lid_policy` | `cancel` | `cancel` = factory behavior; `hold` = stock Grbl door parking. |
| `laser_button_timeout_s` | 300 | How long the machine waits at the button prompt. |
| `laser_disarm_s` | 60 | Spindle-off grace before the armed window closes. |
| `laser_floor_density` | 10 | The S-range floor, percent of full: the lowest pulse density that still marks. Loaded into `$35` at every spindle precompute; `$35` is derived, never typed. |
| `laser_dose_curve` | (bench default) | The measured dose curve as density:light percent pairs; S commands a light fraction and the driver maps it onto the density that delivers it. `off` = identity; a bad value falls back to the default. The panel's recorder measures and applies a machine's own. |
| `laser_corner_gamma` | 2 | The corner rolloff under M4: delivered light follows (v/v_programmed)^gamma, so 1 is plain proportionality and higher values starve the slow spots where heat accumulates. Rides the curve. |
| `laser_pulse_ticks` | 20 | Density base period in machine ticks (35.5 us each). |
| `laser_pulse_min_ticks` | 3 | Shortest density pulse in ticks; below it a period is skipped and its debt carried. |
| `rail_settle_s` | 2.5 | Motor-rail off period when a controller takes the device standalone. |
| `cloud_pause_backtrack_ticks` | 2000 | Cloud pause: laser-off backtrack after the stop. |
| `cloud_resume_lead_ticks` | 1950 | Cloud resume: laser-off lead before firing again. |

Grbl `$` settings (steps/mm, rates, accelerations, laser mode) are set through
your sender in the usual way; the defaults above are baked in from the factory
machine's own measured values. If you change a baked default and it does not
appear to take, remember that stored settings win — `$RST=$` restores the
defaults.

---

## See also

- [LightBurn setup & operation](LIGHTBURN.md) — practical sender setup.
- [Laser safety](SAFETY.md) — the hardware chain and what each interlock does.
- [Cooling and airflow](COOLING.md) — the fire gates referenced above.
- `kernel-module-glowforge/UAPI.md` — the pulse-stream contract in full detail.
- `forgectrl/docs/SERVICES.md` — device ownership, mode supervision, switch map.
