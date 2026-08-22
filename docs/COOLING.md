# Cooling and airflow

The tube is water-cooled and the enclosure is air-cleared, and both matter
while the laser fires: coolant that has stopped circulating will let a tube
overheat within a cut, and smoke that is not pulled out spoils the work and
fogs the optics. ForgeFIRM runs this as one service — the **cooling engine** —
that owns every piece of thermal hardware and answers one question at a time
for whichever controller is running: *is it safe to fire right now?*

This page explains what the system is made of, how it decides, what you will
see when it intervenes, and what you can tune.

- The beam itself is gated in hardware; see [Laser safety](SAFETY.md).
- For how the laser and motion are driven, see [Motion and laser drive](MOTION.md).

---

## 1. What the hardware is

**The coolant loop** is closed: a pump, a radiator with fans, the laser tube,
and two thermistors — one **upstream** of the tube and one **downstream** of a
small inline heater. Pro machines are specified with a thermoelectric cooler
(TEC) on the loop; the board cannot tell whether one is fitted (§9). The
heater exists for diagnostics, not for warming the machine up: it is
how the engine proves the coolant is actually moving (§4).

**The airflow path** has four independently driven pieces:

| Piece | What it does |
|---|---|
| Exhaust blower | pulls smoke out of the enclosure |
| Two intake fans | feed clean air in behind it |
| Air assist (in the head) | blows the cut line clear at the focal point |
| Purge air (in the head) | keeps the optics clean; on whenever the machine is on |

Every fan reports a tachometer, so the engine can tell a commanded duty from an
actual airflow, and the panel shows real speeds rather than setpoints.

**Coolant temperature is read, not guessed.** Both thermistors are converted
with the factory's own beta-equation curve, checked against a thermometer. A
sensor reading at either rail is treated as open or shorted — not as a
temperature.

---

## 2. One owner, two clients

The cooling engine lives in `forgectrl`, the machine-services daemon, and it is
the **only** thing that writes fans, pump, TEC and heater. Whichever controller
is running — GRBL or cloud — is a client of it, over two channels:

- **The controller reports its job state** about once a second: idle, running
  or cooling down, whether the laser is armed, and (in cloud mode) the fan
  duties the job asks for. The reports are level-triggered, so a lost one
  simply corrects itself on the next.
- **The engine publishes a verdict** the controller reads and enforces in its
  own process: may the laser fire, should the job hold, may it resume.

Two properties of that split are worth understanding, because they explain the
machine's behavior in odd situations:

**A missing verdict is a bad verdict.** If the verdict is absent or more than two
seconds old, a controller treats it as *fire blocked, hold*. The engine going
away looks exactly like a fault, never like permission.

**Arming requires being seen.** The engine only grants fire when it is
receiving fresh job reports. A controller about to fire is, by contract, one
that is reporting — an armed window the engine cannot see never gets a green
light.

**If a controller goes silent** past five seconds, the engine blocks fire
immediately and stands the machine down through the normal cooldown, because a
smoke clear is the right physical response to a job that died mid-cut. If the
silence happens while the laser is armed, or while the pulse engine still says
a program is playing, the engine additionally stops motion and locks the laser
latch itself. It also refuses to let exhaust and intake drop below cooldown
duty while a program is still running.

**A cloud job brings its own envelope.** The pulse file the Glowforge service
sends opens with the job's operating limits, and the cloud client hands the
ones the engine has a use for along with every report: the coolant window
and the fans' minimum speeds. The engine takes each only where it is
stricter than the setting on the Machine tab: a ceiling can only come down
for a job, a floor can only go up, a looser value is noted in the log and
ignored, and a gate you turned off (§8a) stays off whatever the job says.
The coolant ceiling is the one limit a job can tighten today (the service
sends 33 °C on a cut, which is also the shipped default); the fan floors
are carried and logged ahead of the airflow gates. The effective set shows
in the log as `effective limits:` and in `/cool/status` as `limits`. A GRBL
job has no header and runs on the settings alone.

**If a diagnostic takes the hardware over** (§6), the engine suspends its own
writes and publishes fire-blocked until the diagnostic finishes.

**If the engine itself is provably gone** while the laser is armed, the
controller writes the factory run duties to the fans once, holds the job, and
stands down. That is the single sanctioned exception to single-owner control,
and the duties are compiled in so that a lost configuration file cannot take
the fans with it.

---

## 3. What the fans do, and when

The engine runs in phases. Duties are the factory machine's own values.

| Phase | Pump | Air assist | Exhaust | Intake | Heater |
|---|---|---|---|---|---|
| **Idle** | on | 204 | off | off | off |
| **Run** (or armed, whatever the reported mode) | on | 1023 | 65535 | 43278 | flow checks only |
| **Cooldown — smoke clear** (15 s) | on | run duty | run duty | run duty | off |
| **Cooldown — thermal** | on | idle | 32768 | 21639 | off |
| **Over-temp / fault hold** | on | run duty | forced | forced | off |

Notes on the phases:

- **The pump runs whenever the machine is on**, including at idle. Circulation
  is cheap; a stagnant loop with a warm tube is not.
- **The heater is off at idle by design.** An always-on flow heater measurably
  warms the loop within minutes, eating headroom below the start gate for no
  benefit while nothing can fire.
- **Being armed counts as running.** If the laser is armed, the engine forces
  the run profile and the flow checks regardless of what mode the controller
  reported — fire never happens without cut airflow and active flow
  verification.
- **Cooldown has two stages**: a smoke clear at full run duty, then reduced
  airflow (the radiator cools the loop measurably) until the upstream coolant
  temperature is back under the resume gate or the cooldown budget expires.
- **The TEC is left off.** Its output has no readback, so the machine cannot
  tell whether one is fitted; driving it blind is not something ForgeFIRM does
  (see §9).

In **GRBL mode** the run profile follows your sender's `M8`/`M9` (LightBurn's
per-layer Air Assist), OR'd with the armed window. In **cloud mode** the job's
own header carries the duties and the client passes them through, so a print
gets the fan profile the service designed for it and a lens hunt stays quiet.

### 3a. Airflow gates: a fan that is not moving the air

Commanding a fan and getting airflow are two different things, and the
machine can tell them apart: the exhaust, the two intakes and the air assist
carry tachometers, and the purge-air fan in the head reports its current.
While the run profile is applied, the engine holds every one of them to a
floor.

- **The floors** are settings (§8): `cool_tach_exhaust_min_rpm`,
  `cool_tach_intake_min_rpm` (either intake), `cool_tach_air_assist_min_rpm`
  and `cool_purge_min_current`, each 55 percent of the steady speed the fan
  reaches at the cut profile on the bench machine (exhaust 11640, intakes
  4160, air assist 11050 rpm; the recommended bands are 50 to 60 percent).
  A cloud job's header can raise a tach floor for that job, never lower it
  (§2).
- **A fan is judged at the operating point its floor was measured at.**
  While the laser is armed every fan is judged, and a job's own fan profile
  (a cloud header's run duties) may raise a fan above the cut profile but
  never lower it while armed. Unarmed, a fan is judged whenever it is
  commanded at or above the cut profile (a bare `M8` from a GRBL job), and a
  fan the job runs slower is measured, published as `unjudged`, and not
  judged: the factory's hunts and homing moves run with the exhaust and the
  intakes off and the air assist at idle, and nothing can fire during them.
  The purge fan has no duty (it is always on) and is judged in every run.
- **A spin-up grace** (`cool_fan_grace_s`) runs from the moment the run
  profile is written; nothing counts inside it, because the big exhaust fan
  takes seconds to reach speed.
- **Three seconds under the floor trip the gate**, and a single reading at
  or above it in between clears the count, so a tach reading that wanders
  does not end a job.
- **A trip is a fault, not a pause.** The verdict goes `AIRFLOW`, fire is
  blocked, the job holds, and there is no resume for the rest of that run
  session: a fan that has stopped moving air is not a condition to cut
  through. The fans stay at run duty (a stalled extraction fan needs every
  other fan around it running), and the reason names the fan, the reading
  and the floor. The fault ends with the session: at idle the verdict is
  `OK` again (a standing hold would cancel jogs and refuse the next job
  before it could re-prove the fan), and the next session judges every fan
  afresh after the grace.
- **A floor of zero is that gate off** (§8a). It still measures: the first
  reading in a job that would have tripped the shipped default is logged.

`/cool/status` carries each fan's reading, floor and state (`grace`, `ok`,
`under`, `TRIPPED`, `off`, `unjudged` for a fan the job runs below the cut
profile unarmed, or `idle` outside a run) as `fan_gates`.

---

## 4. Coolant flow verification

### The problem

A pump can stop, an impeller can slip, a line can airlock — and none of it
shows up in a temperature reading until the tube is already in trouble.
Absolute coolant temperature only tracks a loop that is *circulating*, and
"coolant should warm up while cutting" is not a usable signal either: a light
engrave may add no measurable heat at all.

### The method

The small heater sits between the two thermistors. Each check runs it at a
fixed duty for a fixed window and watches how far the **downstream** sensor
climbs:

- **flowing coolant carries that heat away** — the downstream sensor rises a
  little;
- **a stagnant loop cooks the sensor** — the downstream sensor rises a lot.

The discriminator is the rise, not the difference between sensors, and the
operating point is measured rather than assumed:

| Parameter | Value | Why |
|---|---|---|
| Heater duty | 40 % | Below about 40 %, natural convection sheds the heat well enough to *mimic* flow — dead-pump trials have looked healthier than a working pump. At 40 % heat input outruns convection, and it is the cheapest duty that does. |
| Window | 50 s | Long enough for the bands to separate cleanly. |
| Fault threshold | 14.4 °C rise | Midway between the observed flowing band and the observed stagnant band. |
| Re-check interval | 150 s | A pump that stops mid-job is invisible otherwise. |

Each check costs the loop under a degree of heating, and with cut-profile fans
running the loop still nets cooler over a long job.

### Checks start from a settled loop

Measuring a rise from a baseline captured while the loop is still cooling from
earlier heat produces garbage — and it fails in the dangerous direction: it can
report flow with the pump stopped. So a check is *requested*, and starts only
once the two sensors agree within 1.5 °C **and** the downstream reading has
stopped drifting.

Stationarity is judged by comparing the mean of the first half of a 15-second
window against the second half, not by peak-to-peak spread. On a settled loop,
peak-to-peak noise is about 0.5 °C while the split-half difference is about
0.1 °C — any peak-to-peak threshold tight enough to catch real drift would sit
below the noise floor and never open the gate.

### One bad reading is a suspicion, not a fault

Transients happen: cycling the pump by hand can burp an airlock that clears
itself within minutes. So the engine runs a two-step decision:

1. **First over-limit check → `COOLANT FLOW SUSPECT`.** A warning, a hold
   request, and an immediate re-check — no waiting for the normal cadence.
2. **The next completed check decides.** Over-limit again, with no clean check
   in between → `COOLANT FLOW FAULT`. Clean → the suspicion clears and the job
   continues.

Two more rules close the loopholes:

- **A suspicion that cannot resolve escalates.** If no verdict can be produced
  within the confirmation budget (default 480 s), it becomes a fault: a loop
  that will not settle after a fault-level reading has shown no evidence of
  health.
- **Cleared suspicions still count.** Three of them in one job earn an
  aggregated "check your coolant" warning; the counter resets when cooldown
  reaches idle.

A clean check from the fault state logs a recovery.

### What the verdicts do

| Verdict | Effect |
|---|---|
| `OK` | Fire permitted. |
| `SUSPECT` | Hold requested, cut airflow held; auto-resumes on a clean re-check. |
| `FAULT` | Fire gated and the hold stands — for the operator to resolve. |
| `OVERTEMP` | Hold with forced cooling airflow; auto-resumes below the resume gate (§5). |
| `CRITICAL` | The coolant at or over the critical line in a run session: fire blocked, hold, no resume this job (§5). |
| `AIRFLOW` | A fan under its floor: fire blocked, hold, no resume this job (§3a). |
| `FIRE` | Motion stopped, latch locked, hold until the next run session (§7). |

Practical note: **expect a legitimate suspicion on the first checks after
manually stopping and starting the pump.** That is an airlock, the machinery
above absorbs it, and it clears on its own.

---

## 5. Over-temperature

The engine uses the factory's coolant windows:

- **Run ceiling 33 °C** — above this, the verdict goes `OVERTEMP` with a hold
  request and cooling airflow forced on.
- **Resume gate 31 °C** — below this, recovery is signaled and the controller
  resumes automatically.
- **Critical line 38 °C** (`cool_temp_critical_c`, §8) — a second tier above
  the ceiling, and a different kind: at or over it during a run session the
  verdict goes `CRITICAL`, fire is blocked, the job holds, and there is no
  resume for the rest of that session, because a loop that ran through the
  pause tier and kept climbing is not a condition to cut through. The fault
  ends with the session; the ceiling's pause keeps holding while the loop is
  hot, and the next session judges the line afresh. A cloud job's header
  carries no critical line for the coolant, so this one is always the local
  setting; the settings API keeps it above the ceiling, and at its top
  (70 °C) it is the gate turned off (§8a).

The **upstream** sensor gates, because it reads the coolant actually entering
the tube.

What you see depends on what the machine was doing. A running cycle takes a
feed hold and resumes by itself once the loop recovers — your sender shows the
hold state and a warning message. A jog is canceled instead (a jog cannot be
held). Fire stays gated for the whole excursion.

---

## 6. Diagnostics: verifying and calibrating flow

The web panel's **Diagnostics** tab runs the two cooling tools. Both take the
hardware over: the active controller is suspended for the duration, the engine
stands aside, and the controller is restored on every exit path — completion,
error, or your pressing Abort. The laser stays latched throughout. Progress,
both coolant temperatures and a scrolling log stream to the page while it runs.

Both tools run at your *configured* duty, window and threshold, so the verdict
applies to the check the machine actually performs, and both use cut-profile
chassis fans — the condition the numbers were characterized under. Any
pump-off window aborts immediately if the downstream sensor passes 48 °C.

**Flow verify** (about 3 minutes) — one check with the pump running and one
with it commanded off.

- **PASS** = your threshold separates the two readings.
- Margins under 1.5 °C add a warning that you should re-calibrate.
- A failure here means the threshold no longer suits the loop, or the loop has
  a real problem.

**Flow calibrate** (15–25 minutes) — three trials of each case, alternating,
with settle gates between them. It reports both bands and recommends a
threshold midway between the highest flowing reading and the lowest stagnant
one, with an **Apply** button that writes it to your settings.

- If the gap between the bands is under 3 °C it refuses to recommend anything
  and tells you to raise the heater duty and rerun.

**When to calibrate:** after replacing coolant, after changing or servicing the
pump, if flow verify warns about thin margins, or if you see suspicions that
you can trace to nothing real. The shipped default suits the factory loop; a
rebuilt one may differ.

---

## 7. The fire watch

Alongside the flow work, the engine watches for evidence of things going wrong
at one-second resolution:

- **Emission evidence.** The kernel samples the *gated output* of the hardware
  AND-gate — actual emission, not a commanded state. Emission seen with no
  armed window in the recent past stops motion and locks the latch, and keeps
  doing so while the evidence persists.
- **Laser power-good degradation** during an armed window is warned once per
  session.
- **Stepper-driver faults** appearing during a run are warned, and HV current
  is ranged for each job in the same log line.
- **Lid infrared channels** are polled every tick, and every job logs their
  baseline and peaks.

**About the lid IR fire watch specifically:** it ships in *watch-only* mode and
logs rather than acts. The reason is honest and worth stating — those sensors
are, first of all, a photometer for the lid lamp. A full-power cut raises them
only a few counts above the level the lamp sets, a candle burning on the bed
raises them about the same amount, and anything that changes the lamp (a camera
snapshot, for instance) moves them by tens of counts. A fixed threshold would
therefore stop jobs for lighting changes while still missing a small flame. A
lamp-aware design is planned; until then the channels are recorded, not acted
on, and **the fire watch is not a fire alarm**. Never leave a running laser
unattended.

---

## 8. Settings

All of these live in the panel's Machine tab, are validated on entry, and can
only be changed while the machine is idle. The engine re-reads them at the
start of every run, so a change takes effect on your next job.

| Setting | Default | Legal range | Recommended | What it controls |
|---|---|---|---|---|
| `cool_flow_rise` | 14.4 °C | 1 to 40 °C | 8 to 16 °C | Downstream rise that counts as no-flow. Set this from **flow calibrate**; above the band the check can never fault. |
| `cool_flow_heater_pct` | 40 % | 0 to 100 % | | Heater duty during a check. Raising it separates the bands further at the cost of warming the loop more. |
| `cool_flow_check_s` | 50 s | 0 to 300 s | 30 to 120 s | Length of a check window. `0` turns flow verification off (§8a). |
| `cool_recheck_s` | 150 s | 0 to 3600 s | | How often checks repeat during a job. |
| `cool_confirm_max_s` | 480 s | 60 to 3600 s | | How long a suspicion may stay unresolved before it escalates to a fault. |
| `cool_temp_max` | 33 °C | 5 to 60 °C | 25 to 38 °C | Run ceiling: above it, hold. `60` turns the gate off (§8a). |
| `cool_temp_resume` | 31 °C | 5 to 59 °C | 20 to 36 °C | Resume gate: below it, continue. Always kept below the ceiling. |
| `cool_temp_critical_c` | 38 °C | 6 to 70 °C | 36 to 45 °C | Critical line: a fault with no resume in the job (§5). Always kept above the ceiling; `70` turns the gate off. |
| `cool_cooldown_s` | 15 s | 0 to 1800 s | | Smoke-clear phase at run duty after a job. |
| `cool_cooldown_max_s` | 300 s | 0 to 1800 s | | Cap on the thermal cooldown phase. |
| `cool_tach_exhaust_min_rpm` | 6400 rpm | 0 to 20000 | 5800 to 7000 | Exhaust fan floor at run duty (§3a). `0` turns the gate off. |
| `cool_tach_intake_min_rpm` | 2290 rpm | 0 to 20000 | 2100 to 2500 | Intake fan floor, either intake (§3a). `0` turns the gate off. |
| `cool_tach_air_assist_min_rpm` | 6000 rpm | 0 to 30000 | 5500 to 6600 | Air-assist fan floor (§3a). `0` turns the gate off. |
| `cool_purge_min_current` | 300 raw | 0 to 1023 | 150 to 500 | Purge-air fan current floor (the fan has no tachometer; about 1 off, about 630 on). `0` turns the gate off. |
| `cool_fan_grace_s` | 15 s | 0 to 120 s | 5 to 30 s | Spin-up window after the run profile is written, during which no floor counts. |

Two settings are deliberately not on the panel:

- `cool_fire_ir_delta`, the lid-IR fire gate (§7). It is `0`, watch-only, and
  changing it by hand is not recommended until the watch is lamp-aware.
- `GFCOOL_*` environment overrides exist for bench work; they win for the
  lifetime of the process and are not a normal operating path.

### 8a. Turning a gate off

The gates are settings, and the far end of a gate setting's range is the off
switch: a coolant ceiling of 60 °C never trips, a check window of 0 s runs
no flow verification at all, and a fan floor of 0 never trips. There is no other switch, and no list of names to
get wrong. The ranges are wide on purpose: the shipped defaults and the
recommended bands come from one bench machine, and a machine whose loop or
sensors read differently changes the number rather than waiting for new
firmware.

A gate that is off is not a gate that is forgotten. The panel flags any value
outside its recommended band beside the field and says "this gate is OFF" at
the far end; the Status tab shows a standing banner while any gate is off; the
engine logs one line per gate setting at every run start, and with the ceiling
off it still logs the first reading in a job that would have tripped the
default. `/status` and `/cool/status` carry the off gates as `gates_off`.
Nothing about it reaches the cloud service.

What no setting can reach: the hardware safety chain, the laser latch, the
emission witness, the lid-IR fire watch, the controller-silence dead-man, and
the motion-liveness gate. A machine with every thermal gate off still stops
firing the moment its controller goes quiet; what it no longer does is hold a
job for a stopped pump or an overheating loop. The banner says so.

---

## 9. Not implemented yet

Stated plainly so nobody counts on them:

- **Low-temperature gates and warm-up.** The factory holds a job and warms the
  coolant when the loop is below roughly 16 °C, and refuses to fire at all near
  freezing. ForgeFIRM does not yet; a cold-room machine will start cutting at a
  temperature the factory would have waited out. Two settings — a hard floor
  and a warm-up gate — are planned.
- **TEC control.** ForgeFIRM never drives the thermoelectric cooler. Presence
  cannot be detected (the output has no readback), so this will become a user
  setting plus a simple hysteresis around the factory's setpoints.
- **A fire watch that acts** (§7).
- **Chassis and supply ceilings.** Both temperatures are measured and not
  gated: the chassis LM75 in degrees and the supply sensor as a raw count,
  in `/status` as `temps`, and ranged over every job in one log line
  (`temps this job: ...`). A ceiling for each comes from that record once
  there is enough of it, and the supply's conversion from a thermometer on
  its heatsink (`temp_calibrate.py supply-point`).
- **Fan floors measured on more than one machine.** The shipped floors are
  a fraction of one bench machine's run-duty speeds; a machine whose fans
  read differently sets its own (§8), and a floor of zero turns that gate
  off while it does.

---

## 10. Quick reference: what the machine does when

| Situation | Machine response |
|---|---|
| Idle | Pump on, purge air on, fans at idle, heater off, TEC off. |
| Job starts (or the laser arms) | Cut airflow, flow check requested once the loop is settled. |
| Flow check over limit, first time | `SUSPECT`: warning, hold, immediate re-check. |
| Second consecutive over limit | `FAULT`: fire gated, hold stands until you resolve it. |
| Suspicion unresolved past the budget | Escalates to `FAULT`. |
| Three cleared suspicions in one job | Aggregated "check your coolant" warning. |
| Upstream coolant above 33 °C | `OVERTEMP`: hold + forced cooling; auto-resume under 31 °C. |
| Upstream coolant at or over 38 °C during a job | `CRITICAL`: fire blocked, hold, no resume this job; the ceiling's hold stands until the loop is under 31 °C. |
| A fan under its floor inside the spin-up grace | Nothing yet: the gate reads `grace`. |
| A fan under its floor for three seconds after the grace | `AIRFLOW`: fire blocked, hold, no resume this job; fans held at run duty; the next job starts the gates fresh. |
| Purge-air current absent at run duty | `AIRFLOW`, the same way. |
| A gate setting at its off end (ceiling 60 °C, check window 0 s) | No verdict from that gate; a run-start log line, `gates_off` in `/status`, and a standing panel banner. |
| Job ends | 15 s smoke clear at run duty, then reduced airflow until the loop is under the resume gate. |
| Controller stops reporting | Fire blocked at once, stand-down through cooldown. |
| Silence while armed, or a program still playing | Motion stopped and the latch locked by the engine itself. |
| Verdict file missing or stale | The controller treats it as fire-blocked and holds. |
| Diagnostic running | Engine suspends its writes and publishes fire-blocked. |
| Engine gone while armed | Controller writes factory run duties once, holds, stands down. |

---

## See also

- [Motion and laser drive](MOTION.md) — arming, job phases, both controller modes.
- [Laser safety](SAFETY.md) — the hardware chain the beam actually passes through.
- [LightBurn setup & operation](LIGHTBURN.md) — `M8`/`M9` and air assist in practice.
- `forgectrl/docs/SERVICES.md` — the machine-services contract, including the
  report and verdict channels in full.
