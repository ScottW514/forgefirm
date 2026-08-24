# Release acceptance

A ForgeFIRM release is signed and published only when the **acceptance
catalog** passes on the bench machine and the result is committed with
the release. This document is the contract: what the gate is, how a
campaign runs, how a result stays valid across builds, and what the
release pipeline checks.

## The pieces

| Piece | Where | What it does |
|---|---|---|
| **forgetest** | `forgetest/` in this repo; on the **dev image** as a daemon on HTTP **:8090** | Runs the catalog against the machine from a self-contained web page, keeps the append-only result log under `/data/forgetest/`, exports the release artifact, and carries the bench diagnostics page. Never on a release image. |
| **Image manifest** | `/etc/forgefirm-manifest.json` in every image (`meta-forgefirm/classes/forgefirm-manifest.bbclass`, `forgefirm-image-manifest.bbclass`) | The build's inputs: for every component the pinned revision and one `[path, blob-id]` pair per source file, plus the platform identity (machine, kernel revision + config hash, device tree hashes, layer content hashes). |
| **Artifact** | `releases/v<version>/acceptance.json` (+ `acceptance.md`) committed to this repo, and attached to the GitHub release | What forgetest exported: per catalog test the winning PASS, the fingerprint it ran under, and whether it was inherited. Self-hashed. |
| **Gate** | `scripts/acceptance-gate.py`, called by `scripts/release.sh` | Recomputes every test's fingerprint from the manifest inside the release rootfs and requires the recorded PASS to match. |

## The catalog

Every test declares, in code (`forgetest/forgetest/suite/*.py`):

- **kind** - `auto` (no operator), `operator` (prompts, no emission), or
  `live` (laser emission possible: the page requires the eye-protection /
  fire-watch / exhaust acknowledgment, and the physical arm press is
  required through the controller's normal path - forgetest never touches
  the laser latch);
- **hardware** - `api` (forgectrl and the controller stay up) or
  `takeover` (forgectrl is stopped for the duration; a marker file makes a
  crash recoverable at the next start);
- **mode** - the controller mode the test needs live when it starts
  (`grbl` or `cloud`), or none. The runner switches the machine there
  before the test (through `POST /mode`, settled and with the Grbl port
  answering) and leaves it there; a test with no mode runs in whatever
  mode it finds, or manages the mode itself (the `cloud.*` job tests,
  through `enter_cloud`, which also waits for the service session);
- **covers** - the source paths whose content the test stands for, as
  `(component, glob)` pairs. Globs anchor at the component's repository
  root (`forgefirm-app/gfcloud.py`, not `gfcloud.py`), and a glob that
  selects nothing is a lint failure. Non-behavioral paths (docs, CI, the
  components' own unit tests, licenses; the list is `NON_BEHAVIORAL` in
  `forgetest/forgetest/manifest.py`) are outside every fingerprint, so a
  README edit re-requires nothing;
- **requires** - tests that must be satisfied first (the emission tests
  require the motion and readback tests). This orders the runs; it is not
  a release condition of its own (the release needs every test satisfied
  anyway). The page's **Ignore prerequisites** switch lets any test start
  alone; a run started that way records the unmet prerequisites in its
  `evidence.prerequisites` and its log, and the prerequisites stay
  required;
- **always** - membership in the **always-required core**, which is run
  in every campaign and is never inherited: image health, the kernel
  latch/safety readbacks, and one live emission witness with the
  armed-window disarm;
- **actions** - the machine actions the test asks for by name (`lid`,
  `interlock`, `button`; see "The operator's part"). An `auto` test
  declares none. The page lists them before a start; a bench actuator
  that covers a channel can perform them;
- **precheck** - a condition the machine must meet for the test to start
  at all (`kernel.fire-line` needs HV not reporting good, the kernel's
  rule for a zero-duty latch unlock; `cloud.mode-switch` needs
  `homing_mode = gfcloud`). A start the precheck refuses is not a result:
  the page says why, a queue skips the test with the reason and carries
  on, and nothing is recorded. Neither field is part of the gate-visible
  definition.

`GET /catalog` on the tool lists the definitions; the page shows them under
each test's *details*.

## Domain fingerprints and inheritance

A test's **domain fingerprint** is the hash of the `(component, path,
blob-id)` triples its coverage globs select in the image manifest, plus the
platform identity, plus the hash of the test's own implementation: its
function (decorator included) together with the code its suite module
shares among its tests, everything outside the module's `@test`
functions. A PASS recorded under fingerprint F applies to any build whose
recomputed fingerprint is F - the same code computes it on the board and
in the gate.

Consequences:

- A change to a covered file invalidates exactly the tests that cover it.
  A panel-only change reruns the core plus the panel tests, not the
  cooling drills.
- A platform change (kernel, device tree, a layer's content) invalidates
  everything. Layer content is every file under `meta-forgefirm`,
  `meta-glowforge-bsp` and `meta-openglow-core` except documentation
  (`*.md`) and the component pin files (`<recipe>-pin.inc`, holding only a
  component's `SRCREV` and the `PV` that moves with it). A pin bump is the
  component's change, and the component entry already carries it file by
  file, so it invalidates the tests that cover the component - not the
  bench. A recipe-body change (build flags, patches, config fragments,
  init scripts, a third-party pin with no manifest entry) is layer content
  and invalidates everything; so does a pin written into a recipe body
  instead of its pin file (the safe direction).
- A change inside a test's body invalidates that test's earlier passes
  and no other; a change to a helper its module shares invalidates the
  tests of that module.
- "Touched" is computed from content hashes carried in the image, never
  declared by hand.

## Campaigns

A **campaign** is bound to one image (manifest content hash) and one
catalog (catalog hash). The first Start on an image opens one. It stays
open until a **FAIL** (or an erroring test), an **invalidate-all**, an
explicit **reset**, or a different image or catalog. Reboots into the same
image continue it.

For every test, in order:

1. a PASS in the open campaign with the current fingerprint satisfies it;
2. otherwise, if it is not core, the newest PASS anywhere in the history
   with the current fingerprint and newer than the last invalidate-all is
   **inherited** (its origin - run time, image, campaign - is kept and
   exported);
3. otherwise it is **required** (reason: `always`, `never-passed`, or
   `domain-changed`).

**Release authorized** = a campaign is open and every catalog test is
satisfied. There is no SKIP: a test the bench cannot run means the release
cannot be authorized (that is a catalog change, not a skip).

**Invalidate all** (page footer, reason required) records that the bench
itself changed - new tube, driver swap, cable work, a judgment call - and
forces a full campaign; nothing before it can be inherited.

**Inheritance is local.** The history a bench inherits from is its own
results log; there is no import of a published `acceptance.json`. A second
bench, or one whose `/data` has been wiped, starts from a full campaign.

## Running a campaign

1. Boot the dev image on the bench (`forgefirm-image-dev`), open
   `http://<machine>:8090/`.
2. The banner shows the image, the manifest identity, and *Release
   authorized*. Tests marked **required** need to run; **inherited** ones
   do not.
3. Start the required tests. `operator` tests ask questions in the run
   pane; `live` tests need the acknowledgment and the physical arm press;
   `takeover` tests stop forgectrl for the duration. A test whose
   prerequisites are not satisfied is locked until they are - or until
   the **Ignore prerequisites** switch in the Campaign card is on, which
   unlocks every Start (the switch is remembered by the browser; a run
   started under it says so in its record).
   The `cloud.*` job tests run **in cloud mode and stay there**: the first
   one switches from GRBL mode (once, its connect-time hunt waited out)
   and the following ones reuse the live session; nothing switches back
   after them. The tests that need GRBL mode (`motion.*`, `laser.*`,
   `cooling.fans-quiet-after-motion`, `cloud.mode-switch`) declare it,
   and the runner switches back the moment one of them starts - so the
   mode changes only where the next test asks for it, never between
   tests of the same mode. `cloud.mode-switch` is the one round trip, and
   it carries the two service-driven motions with it: the connect-time
   hunt run with the lid open, and the web-service homing (`$H` with
   `homing_mode = gfcloud`) after the switch back.
   The cloud tests split by what they prove. The service protocol (sign-in,
   the firmware check, the WebSocket, the hunt, the image uploads, a
   print's download and lifecycle as the app sees them) is
   `cloud.service-protocol`: the cloud client restarted as gfutilities'
   emulator in this machine's identity under the `/run/gfcloud-emulate`
   marker, answering the real service with the dev image's canned frames
   and running the print from the app without hardware, so only the app
   has to be driven (by a person or an agent, anywhere). The service and
   the machine together are `cloud.mode-switch` and one real print,
   `cloud.pause-resume` (progress, the button wait, the job's limits
   reaching the engine). The machine's print behavior (the lid and
   interlock aborts, the button-wait cancel, a paused print ended by the
   lid, a print longer than the ring with the app's cancel) runs under the
   **offline service** (`enter_offline`: the cloud client restarted with
   the `/run/gfcloud-offline` marker, no account, no network; the test
   hands it a synthesized job over `/run/gfcloud-offline.sock` and reads
   the machine's events back, see `forgetest/puls.py` and the cloud
   client's `docs/CLOUD.md`). Those jobs carry no laser command, so
   nothing is on the bed and nothing burns, but the arm still unlocks the
   latch, so they stay `live`. The offline client is left running; the
   next test that needs the service restarts it (`enter_cloud` does), as
   does a mode switch or a controller restart.
   **The coverage maps follow the split.** The protocol test stands for
   the web session, the emulator and its fixtures; the offline tests for
   the run loop, the hardware it drives, the offline dispatch and the
   pulse path; `cloud.mode-switch` for the homing path (the session, the
   whole hardware library, `gfhome`); and every one of them for the
   client's common ground (`gfcloud.py`, `ffmachine.py`, the config, the
   identity, the cooling reporter, gfutilities' core and its transport
   helpers). The one real print keeps the coarse maps, all three cloud
   components whole: it is the integration, and the floor the lint needs,
   so whatever the finer maps leave out still re-requires it. A sign-in
   change therefore re-requires the protocol test and the print; a feeder
   change the offline tests and the print; a camera change the mode
   switch and the print.
   **The service's connect-time hunt is paid only where it is the
   subject.** A cloud client the tool starts for anything else (the real
   client back after the emulator, a mode the runner switches to or hands
   back, a controller it restarts) comes up under the `/run/gfcloud-nohunt`
   marker: its first settings report is the reconnect form, and the
   service keeps the head position it has instead of homing. The hunt
   tests (`cloud.mode-switch`, `cloud.service-protocol`) get theirs, and
   so does the one real print: `enter_cloud` reuses a running session
   only when that client has hunted the machine itself (never the
   emulator's, never a no-hunt start), otherwise it restarts the client
   with the hunt, because a print placed on a head position the service
   only believes can run the gantry into a rail. The same holds outside
   the tool: a machine left in cloud mode by a campaign may not have
   hunted since GRBL mode moved the head, so open and close the lid (the
   service re-hunts) or restart the controller before printing from the
   app. Every marker is one start: the client that reads it takes it
   down.
4. Or hand the whole list to a queue. **Run what is left** offers two:
   **Unattended** takes every `auto` test the campaign does not already
   count as satisfied, and needs nobody in the room; **Operator and live**
   takes the `operator` and `live` ones, and needs somebody at the
   machine, since it prompts and it fires the laser. Each button says how
   many it would run, and asks before it starts: the live queue names the
   tests that fire and takes the acknowledgment once, for all of them.
   A queue runs one test at a time in prerequisite order and stops on the
   first result that is not a PASS, because a FAIL closes the campaign. A
   test it cannot start is skipped with the reason on the page and the
   rest carry on, which is what happens to an `auto` test waiting on an
   `operator` one: run the attended queue, then the unattended one again.
   **Stop the queue** cancels what is still waiting and lets the run in
   progress finish; **Abort** ends that one too. The queue lives in the
   runner, so closing the page or reloading it does not disturb the run.
5. When *Release authorized: YES*, **Export release artifact**, download
   `acceptance.json` and `acceptance.md`, and commit them as
   `releases/v<version>/acceptance.json` and `.md`.

The raw log (`/data/forgetest/results.jsonl`, `Raw log` in the footer) is
the bench's own record; the artifact is the release's. The runner's own
events - a queue opening, skipping or stopping, a takeover recovered at
start-up, the leftovers a baseline pass found - go to the **journal**
(`Runner journal` in the footer: the daemon's `daemon.log` under the
data directory, also syslog under the `forgetest` name, and the log of
the run in progress), never to the page's campaign card.

### The operator's part

The run card shows **what you will do** before anything is asked: the
running test's `steps`, the attended tests still waiting in a queue, or
the test whose title you clicked while the machine is idle. What follows
during the run is those steps, taken in turn, in one of four forms:

- a **Ready** prompt pre-announces a timed step: what happens on the
  click and what you do during it ("On Ready the head starts an 8 s move;
  press the button once while it moves"). Nothing moves until you click;
- a **notice** is a standing instruction with no button. The test shows
  it and watches the machine for the result - the lid switch reading
  open, the interlock loop reading open, the controller entering Hold
  after the press, the client's log line - and takes it down when it sees
  it. There is nothing to answer and nothing to race;
- a machine **action** (`ctx.act("lid", "open")`, `("interlock",
  "close")`, `("button", "press", until=...)`) is a notice the runner
  manages: the wording is the action's own, the test adds its context,
  the machine's reading proves it done, and the result's
  `evidence.actions` records each one with who performed it. This is the
  seam the bench actuator plugs into (below): a `fixture` covering a
  channel performs the action instead of the notice, and a test reads
  the same either way;
- a **confirm** is a yes/no the evidence cannot answer. One is left in
  the catalog: the mark `laser.emission-witness` leaves on the scrap, the
  once-per-campaign calibration of the sensor witnesses (the head's beam
  detector, the HV current, the kernel's LASER_ON count), plus the app's
  own display in `cloud.pause-resume`. The head accelerometer stands in
  for "did the gantry move", the button LEDs for "is the button dark",
  the lid lamp toggled between two snapshots for "is the camera live".

### The bench actuator

`forgefixture` (`fixture/`, its own README) is an ESP32-S3 on the bench
network driving three relays at the machine's connectors: a normally
closed contact in the lid-switch loop, another in the interlock loop, a
normally open contact across the button input that is only ever pulsed.
Unpowered, unplugged or rebooting, it leaves a stock machine. The tool
finds it through `/data/forgetest/fixture.json` (bench-local, mode
0600: the hostname, the API key, an optional `ip` override, the
`channels` wired, `arm_press`), resolves `<hostname>.local` itself (the
image carries no mDNS resolver), and probes it before every run and at
most every 30 s otherwise. What holds:

- **Every action is still proven by the machine.** The fixture does not
  read the switches; `ctx.act` asks it and then waits for forgectrl's
  reading exactly as it waits for an operator's hand. An action the box
  fails to perform falls back to the operator's notice, and the record
  says so (`evidence.actions[].by`, `fixture_error`).
- **An operator test the fixture can run alone runs unattended.** A test
  declares its actions and, with `hands=(...)`, whatever else it asks of
  a person ("app" for a job in the Glowforge app). An `operator` test
  whose actions the fixture covers and whose `hands` are empty is routed
  into the unattended queue and out of the attended one; its Ready gates
  pass (the fixture performs the timed step), and a prompt it raises
  anyway is a FAIL naming the undeclared step, never a wait for nobody.
  `live` never moves: the fire watch and the acknowledgment are a
  person's.
- **The button channel needs the jumper.** With the fixture's enable
  jumper out the button is not covered, and tests that press it stay
  attended. The arm press of a live test stays a person's unless the
  bench config says `arm_press: true`: then, and only with the jumper in,
  the fixture presses when the button lights, recorded as its own.
- **What the box still holds after a run is released** and recorded
  (`evidence.fixture.released`), before the baseline's post pass, so a
  lid left open by a failed test never reaches the next one.

### Every run starts from, and leaves, the fresh-boot idle state

The runner brackets every test and bench tool with a **baseline** pass
(`baseline.py`): before the run it verifies the machine against the
fresh-boot idle state and restores anything off it; after the run - on
every exit path, pass, fail, or abort - it restores again. Two kinds of
items: **fixed** resting values the boot establishes (the kernel module
defaults, forgectrl's start-up writes, the GRBL controller's init writes:
`motor_lock=8`, `x/y_mode=8`, `x/y_decay=1`, `step_freq=28160`,
`ramp_rate=125000`, `streaming=0`, `state=idle`, latch locked, hold
currents, head lamp and button LEDs off, heater and TEC off, the lid lamp
at forgectrl's `lid_lamp_idle` setting; forgectrl: the controller running
with motion verified, no diagnostic, the camera engine and cooling engine
idle), and **preserved** state with no resting policy that a run must
hand back as it found it (the position counters, the settings map, the
controller mode). The mode in force decides what the baseline owns: in
cloud mode the cloud client's own configuration (the GRBL controller's
init values, which it rewrites from every pulse header; the lid lamp,
its lid-image level; the position counters, re-zeroed at every service
action) is left to it, and the safety readbacks, latch, ring, module
defaults, and forgectrl's engines are checked as always. The mode itself
is preserved unless the run declared the change (`ctx.mode_changed()`,
the cloud tests entering cloud mode) or the test declared a `mode`, in
which case the runner makes the switch in the pre pass, before the
preserved state is captured, and the post pass keeps the mode the test
asked for; the persisted `controller_mode` setting is never written back
as a bare setting - only the switch keeps it in step with the live mode. Deviations are
**leftovers**: logged in the run pane, kept in the result's `evidence`
(`baseline.pre` / `baseline.post`), and surfaced in the page's message
line - a leftover found before a run is attributed to the previous run; one
found after is the run's own defect. Takeover runs additionally capture
the controller-owned kernel attributes on entry and write them back before
forgectrl restarts, so the supervisor's liveness probe runs on the machine
it expects. The runner waits for forgectrl's supervisor to settle (motion
verified, or the ladder's verdict) before and after every takeover.

**Power-cycle before a campaign.** forgetest takes a **fresh-boot
reference** once per boot (`/data/forgetest/boot-<boot_id>.json`, taken
only within the first ten minutes after boot, after the supervisor
settles): the whole idle picture of this machine as the image boots it,
the check on the fixed values, and the record a leftover is judged
against. Take it after a **power cycle**, not a warm `reboot` - the
machine's true fresh state is the powered-on one (the PIC's own lamp and
sensor defaults, then forgectrl's start-up writes on top).
A displaced head is jogged back along its own path by the kernel-measured
X/Y delta (bounded to 100 mm; Z is never touched); beyond that the
counters are reported and the run must be fixed. A run that legitimately
re-zeroes the counters (cloud mode's connect) tells the runner so
(`ctx.counters_rezeroed()`) and hands the head back itself.

## The gate

`scripts/release.sh <version>` builds the release image, reads
`/etc/forgefirm-manifest.json` out of the release rootfs and runs

    scripts/acceptance-gate.py releases/v<version>/acceptance.json <manifest>

which requires: the artifact self-hash intact; `authorized: true`; the
catalog in the tree identical to the artifact's; for every test a recorded
PASS whose fingerprint equals the one recomputed from the release manifest;
inherited results not core and newer than the invalidate epoch. Any
problem dies before signing. `FORGEFIRM_ACCEPTANCE_SKIP=1` bypasses the gate
deliberately and prints a loud warning; it is never the default. The
artifact is staged and attached to the GitHub release next to
`forgefirm.fw`.

Because the dev image and the release image are built from the same tree
in one `bitbake` invocation, their manifests share the same identity; a pin
bumped after the campaign shows up as a fingerprint mismatch on exactly the
tests that cover it.

## Coverage currency rule

Every change is evaluated against the catalog, in addition to its unit
tests:

1. does an existing test exercise the changed behavior - if not, add or
   extend one in the same change;
2. does that test's `covers` map name the files touched - if not, widen it
   in the same change.

A gate or a limit is exercised through the settings API (a value a healthy
machine cannot meet, re-read by the engine at the next run start, restored
by the test's own teardown), never through `GFCOOL_*` environment overrides,
which need a daemon restart and stay bench-only.

A behavior change with no catalog consequence needs a sentence of
justification in the commit message. Coverage gaps are defects: under the
domain model an uncovered path lets an inherited PASS stay valid across a
change that should have invalidated it.

The mechanical floor is the coverage lint,

    python3 -m forgetest.coverage --manifest <manifest.json> [--enforce]

which lists every manifest path no test covers, minus the non-behavioral
paths (docs, CI, tests, licenses), and every coverage entry that selects
nothing. CI (`forgetest-ci.yml`) runs it on a manifest generated from the
recipe pins with `scripts/manifest-from-tree.py` (no Yocto build needed)
and fails the job on any uncovered path. On the board, run it against
`/etc/forgefirm-manifest.json`. The lint proves a
file is *fingerprinted*; whether the test *exercises* the change is the
change author's judgment (rule 1).

## Bench diagnostics page

The same daemon serves `#bench`: the registry of the bench tools
(`scripts/bench`, installed under `/usr/share/forgetest/bench/`), each with
its safety class, argument form, and last run. The classes: `dry` (reads
or dry motion, forgectrl stays up), `takeover` (forgectrl and the
controller stopped for the run, the pulse device free, the same wrapper
the takeover tests use), `scope` (a takeover whose result only means
something with the named instrument on the bench), `live` (emission
possible; the operator acknowledgment and the physical arm press). A tool
runs as a subprocess with the output on the page and, on the board, the
machine as `GF_HOST=127.0.0.1`, the panel token in `GF_TOKEN`, and its data
files under `/data/forgetest/bench/` (`FORGETEST_BENCH_DATA`); the same
scripts run from a LAN host with `GF_HOST` set (`scripts/bench/gfbench.py`,
`scripts/bench/README.md`). Every board-runnable tool is ported; the entries
that stay unported are the CI harnesses of the null-sink controller and the
factory `.puls` decoder, which do not run against the machine at all - they
are listed so the catalog of what exists is complete. Bench runs are
recorded in `/data/forgetest/bench.jsonl` and never enter a campaign.

## Layout

    forgetest/forgetest/         the package (stdlib only)
      manifest.py                manifest, globs, fingerprints, coverage report
      catalog.py                 @test registry, catalog hash
      campaign.py                the rules (pure functions)
      artifact.py                export + gate verification
      runner.py                  one run at a time, prompts, abort, takeover, queues
      baseline.py                the fresh-boot idle state around every run
      server.py / page.py / ui/  HTTP API + the page (forgectrl's access rules;
                                 Bootstrap and the OpenGlow theme shared with the panel)
      bench.py / coverage.py     bench registry + subprocess runner; the lint
      suite/                     the catalog, one module per subsystem
    forgetest/tests/             host unit tests (python3 -m unittest discover -s tests)
    scripts/bench/               the bench tools (+ gfbench.py, the board/host helper)
    scripts/acceptance-gate.py   the gate
    scripts/manifest-from-tree.py  manifest from the recipe pins (CI, workstation)
    releases/v<version>/         the committed artifacts
