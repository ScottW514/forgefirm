# LightBurn setup & operation (ForgeFIRM)

## Before you cut — safety (read this first)

ForgeFIRM replaces the factory software, **not** the factory safety rules. The
machine contains a Class 4 CO₂ laser emitting invisible 10.6 µm infrared at
roughly 45 W. **Jobs sent from LightBurn fire the laser.**

- **Eyes.** The enclosure and lid glass are the eye-safety barrier. Never
  defeat the lid switches or the Pro's remote-interlock plug, and never
  operate with any cover removed. Direct or reflected 10.6 µm radiation
  blinds and burns.
- **Fumes.** Vent the exhaust to the outdoors, always. Laser-cutting fumes
  are toxic and flammable.
- **Materials.** Never cut PVC, vinyl, or any chlorinated plastic — they
  release chlorine gas that corrodes the machine and injures your lungs.
  Know what your material is before you cut it.
- **Fire.** Never leave a running job unattended. Small flare-ups are normal
  with some materials; sustained flame is not. Keep a fire extinguisher
  (CO₂ preferred) within reach and know how you will open the lid and
  smother a fire before you start.
- **Stop means stop.** The big button, LightBurn's Stop, and opening the
  lid each halt the job. If anything looks wrong, stop first and diagnose
  second.

The laser fires only inside an operator-armed window:

- **Starting a job that fires: press the button.** At the first
  laser-on command of a job the machine unlocks its laser latch,
  lights the big button **white**, and pauses the incoming gcode until
  you **press the button** (the same press the factory firmware
  requires). LightBurn simply waits; press the button and the job
  runs. If nobody presses within `laser_button_timeout_s` (default
  300 s) the job aborts with alarm 3. Stop in LightBurn (soft reset)
  cancels the wait at any time.
- One press covers one job — power changes and M5/M3 toggles do not
  re-prompt. The window relocks when the job ends (program end
  `M2`/`M30`), when the sender connection changes, or after
  `laser_disarm_s` (default 60 s) with the spindle off — counting even
  while a job sits paused in Hold or with the lid open; the next job
  prompts again.
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
`grblHAL_glowforge` on TCP port 23 at your machine's IP address, shown
below as `<machine-ip>`).

1. **Laser window → Devices → Create Manually** (skip auto-find; it
   scans serial ports).
2. Device type: **grblHAL** if your LightBurn version lists it,
   otherwise **GRBL** — both speak the right protocol.
3. Connection: **Ethernet/TCP**. IP address: **`<machine-ip>`**
   (LightBurn uses TCP port 23 for GRBL devices, which is exactly where
   the controller listens).
4. Name: e.g. `Glowforge ForgeFIRM`. Work area: **X 495 mm, Y 279 mm**.
5. **Origin**: pick the corner where the head sits after parking at
   home — **rear-left as you face the machine** (the top-left dot in
   the selector). This is what keeps jobs un-mirrored: machine +X runs
   right, +Y runs from the rear rail toward you.
6. **Auto-home on startup: NO** — LightBurn would issue `$H` at every
   connect, and the working homing method runs a multi-minute session.
   `$H` itself works and is selected by the `homing_mode` setting in the
   machine's web control panel: `gfcloud` (Glowforge web-service vision
   homing — the working method; X/Y home to the factory corner, Z to the
   hall sensor; requires a signed-in Glowforge session), `switches`
   (physical limit switches, once installed), or `none` (`$H` is
   rejected). Run `$H` deliberately from the Console tab when you want a
   true machine origin.
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
when you have not homed.

(`Absolute Coords` also works after a successful `$H`, or if the head
was parked at the home corner when the controller started. After any
Stop/alarm the absolute frame is stale until you re-home with `$H` or
restart the controller with the head re-parked.)

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

## Dry runs (motion only, no fire)

**Setting a low power value does NOT make a job inert — any laser layer
prompts for the arm button and then fires.** The motion-only modes are:

- **Frame** and jogging — never fire.
- A job whose layers emit no laser-on command: turn the layer's
  **Output** off in the cut settings, or send gcode that stays in `M5`.
- A job run with the laser latch left locked (never press the arm
  button): the job pauses at the white-button prompt and aborts after
  `laser_button_timeout_s` — useful only to confirm the prompt itself.

If the white arm prompt appears and you did not intend to fire, press
**Stop** in LightBurn.

## A good first job

First a dry run, then a light cut on scrap:

1. Draw a rectangle (~100 × 60 mm) with a circle inside.
2. Double-click the layer color bar (bottom): mode **Line**, speed
   **50 mm/s** (= 3000 mm/min; check Edit → Settings for your speed
   units). For the dry run turn the layer's **Output** off.
3. Park the head where the job's rear-left corner should be (or leave
   it at home), **Frame**, watch the perimeter trace, then **Start**.

Expected behavior: darting travels at up to 200 mm/s, smooth 50 mm/s
tracing of the shapes, silky and near-silent motion (factory currents +
decay mode), and the head finishing per the job's return setting.

4. For the live pass: put scrap material on the bed (never an empty
   honeycomb over the fan grill), re-enable the layer's **Output**, set
   power to **30 %** or more (below ~30 % the tube barely marks), turn
   the layer's **Air Assist** on, close the lid, **Frame**, **Start**,
   and press the white button when it lights. Watch the whole job.
