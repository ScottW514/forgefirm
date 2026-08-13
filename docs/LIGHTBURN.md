# LightBurn setup & operation (ForgeFIRM)

The laser fires only inside an operator-armed window:

- **Starting a job that fires: press the button.** At the first
  laser-on command of a job the machine unlocks its laser latch,
  lights the big button **white**, and pauses the incoming gcode until
  you **press the button** (the same press the factory firmware
  requires). LightBurn simply waits; press the button and the job
  runs. If nobody presses within `laser_button_timeout_s` (default
  300 s) the job aborts with alarm 3. Stop in LightBurn (soft reset)
  cancels the wait at any time.
- One press covers the whole job — power changes and M5/M3 toggles do
  not re-prompt. The window relocks after `laser_disarm_s` (default
  60 s) of idle with the spindle off; the next job prompts again.
- S-value scale: `$30` defaults to 1000, so set LightBurn's S-max to
  1000. 100 % power = S1000. Use M4 (variable/dynamic) mode for cuts
  and engraves.
- The machine forces the cut fan profile on while armed and
  continuously verifies coolant flow; a flow fault or over-temperature
  pauses/blocks firing (messages appear in LightBurn's console).
- The hardware safety chain stands above all of this: lid open,
  interlock open, or power faults make firing physically impossible
  regardless of software state.

## One-time device setup

Prerequisite: the controller is running on the board (see BRINGUP.md;
`grblHAL_glowforge` on TCP port 23 at 172.16.1.97).

1. **Laser window → Devices → Create Manually** (skip auto-find; it
   scans serial ports).
2. Device type: **grblHAL** if your LightBurn version lists it,
   otherwise **GRBL** — both speak the right protocol.
3. Connection: **Ethernet/TCP**. IP address: **172.16.1.97** (LightBurn
   uses TCP port 23 for GRBL devices, which is exactly where the
   controller listens).
4. Name: e.g. `Glowforge ForgeFIRM`. Work area: **X 495 mm, Y 279 mm**.
5. **Origin**: pick the corner where the head sits after parking at
   home — **rear-left as you face the machine** (the top-left dot in
   the selector). This is what keeps jobs un-mirrored: machine +X runs
   right, +Y runs from the rear rail toward you.
6. **Auto-home on startup: NO.** Homing is not wired yet; `$H` errors.
7. Finish. If a stale device profile already exists, edit its IP
   instead of creating a new one.
8. Device Settings (wrench icon): **S-Value Max = 1000** (matches $30).
9. Optional backup: File → Export Devices → saves a `.lbdev` you can
   re-import later (the format is not editable text; export is the way
   to make one).

## Job start mode (important on an unhomed machine)

In the Laser window set **Start From: Current Position**, and set the
**Job Origin** dot to the same corner as the machine origin (top-left
dot). The job then runs into the bed from wherever the head currently
sits — absolute machine zero never matters, which is the forgiving mode
while the machine has no homing switches.

(`Absolute Coords` also works, but only if the head was parked at the
home corner when the controller started; after any Stop/alarm the
absolute frame is stale until the controller is restarted with the head
re-parked.)

## Operating basics

- **Frame** traces the job's bounding box at travel speed — do it
  before every Start. There are **no limit switches**: framing is your
  crash protection.
- **Start** runs the job. Travels run up to 200 mm/s; anything faster
  in a layer is clamped by the controller ($110/$111 = 12000 mm/min).
- **Pause** = grbl feed hold: motion parks within ~0.4 s (0.2 s stream
  queue + deceleration); Resume continues exactly.
- **Stop** = soft reset: motion aborts with a controlled deceleration
  and grblHAL raises an alarm with **position declared lost** (the
  stream queue means up to ~40 mm of in-flight difference). Recovery:
  unlock (`$X` in Console or LightBurn's prompt), jog the head clear,
  and carry on in Current Position mode. Restart the controller with
  the head re-parked if you want a clean absolute frame.
- **Move tab**: jogging (set a sane speed, e.g. 6000 mm/min), Get
  Position, distance buttons.
- **Console tab**: raw grbl — `?` status, `$$` settings, `$X` unlock,
  `$J=G91X10F1200` jog.

## Air assist / fans

Each cut/engrave layer has an **Air Assist** toggle (in the layer's cut
settings). Turning it on makes LightBurn emit M8/M9 around that layer,
which drives the machine's full cut-profile ventilation: air assist to
full, exhaust and intake fans to factory run speeds, then a ~15 s
cooldown after the layer before returning to idle. Leave it ON for
anything that will eventually involve the beam; expect real fan noise.

## A good first job

1. Draw a rectangle (~100 × 60 mm) with a circle inside.
2. Double-click the layer color bar (bottom): mode **Line**, speed
   **50 mm/s** (= 3000 mm/min; check Edit → Settings for your speed
   units), power anything (ignored — nothing fires).
3. Park the head where the job's rear-left corner should be (or leave
   it at home), **Frame**, watch the perimeter trace, then **Start**.

Expected behavior: darting travels at up to 200 mm/s, smooth 50 mm/s
tracing of the shapes, silky and near-silent motion (factory currents +
decay mode), and the head finishing per the job's return setting.
