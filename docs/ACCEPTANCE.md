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
- **covers** - the source paths whose content the test stands for, as
  `(component, glob)` pairs;
- **requires** - tests that must be satisfied first (the emission tests
  require the motion and readback tests);
- **always** - membership in the **always-required core**, which is run
  in every campaign and is never inherited: image health, the kernel
  latch/safety readbacks, and one live emission witness with the
  armed-window disarm.

`GET /catalog` on the tool lists the definitions; the page shows them under
each test's *details*.

## Domain fingerprints and inheritance

A test's **domain fingerprint** is the hash of the `(component, path,
blob-id)` triples its coverage globs select in the image manifest, plus the
platform identity, plus the hash of the test's own implementation. A PASS
recorded under fingerprint F applies to any build whose recomputed
fingerprint is F - the same code computes it on the board and in the gate.

Consequences:

- A change to a covered file invalidates exactly the tests that cover it.
  A panel-only change reruns the core plus the panel tests, not the
  cooling drills.
- A platform change (kernel, device tree, a layer's content) invalidates
  everything.
- A change to a test's implementation invalidates that test's earlier
  passes and no other.
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

## Running a campaign

1. Boot the dev image on the bench (`forgefirm-image-dev`), open
   `http://<machine>:8090/`.
2. The banner shows the image, the manifest identity, and *Release
   authorized*. Tests marked **required** need to run; **inherited** ones
   do not.
3. Start the required tests. `operator` tests ask questions in the run
   pane; `live` tests need the acknowledgment and the physical arm press;
   `takeover` tests stop forgectrl for the duration.
4. When *Release authorized: YES*, **Export release artifact**, download
   `acceptance.json` and `acceptance.md`, and commit them as
   `releases/v<version>/acceptance.json` and `.md`.

The raw log (`/data/forgetest/results.jsonl`, `Raw log` in the footer) is
the bench's own record; the artifact is the release's.

### Every run starts from, and leaves, the fresh-boot idle state

The runner brackets every test and bench tool with a **baseline** pass
(`baseline.py`): before the run it verifies the machine against the
fresh-boot idle state and restores anything off it; after the run - on
every exit path, pass, fail, or abort - it restores again. Two kinds of
items: **fixed** resting values the boot establishes (the kernel module
defaults, forgectrl's start-up writes, the GRBL controller's init writes:
`motor_lock=8`, `x/y_mode=8`, `x/y_decay=1`, `step_freq=28160`,
`ramp_rate=125000`, `streaming=0`, `state=idle`, latch locked, hold
currents, camera lamps and button LEDs off, heater and TEC off; forgectrl:
the controller running with motion verified, no diagnostic, the camera
engine and cooling engine idle), and **preserved** state with no resting
policy that a run must hand back as it found it (the lid lamp level, the
position counters, the settings map, the controller mode). Deviations are
**leftovers**: logged in the run pane, kept in the result's `evidence`
(`baseline.pre` / `baseline.post`), and surfaced in the page's message
line - a leftover found before a run is attributed to the previous run; one
found after is the run's own defect. Takeover runs additionally capture
the controller-owned kernel attributes on entry and write them back before
forgectrl restarts, so the supervisor's liveness probe runs on the machine
it expects. The runner waits for forgectrl's supervisor to settle (motion
verified, or the ladder's verdict) before and after every takeover.

**Reboot before a campaign.** forgetest takes a **fresh-boot reference**
once per boot (`/data/forgetest/boot-<boot_id>.json`, taken only within
the first ten minutes after boot, after the supervisor settles): the whole
idle picture of this machine as the image boots it. It is the session's
resting lid-lamp level and the check on the fixed values; without one the
lamp level is unknown and the page says so. Position counters cannot be
written back - a run that shifts them is reported and must be fixed.

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

A behavior change with no catalog consequence needs a sentence of
justification in the commit message. Coverage gaps are defects: under the
domain model an uncovered path lets an inherited PASS stay valid across a
change that should have invalidated it.

The mechanical floor is the coverage lint,

    python3 -m forgetest.coverage --manifest <manifest.json> [--enforce]

which lists every manifest path no test covers, minus the allowlist of
non-behavioral paths in `forgetest/forgetest/coverage.py` (docs, CI, tests,
licenses). CI (`forgetest-ci.yml`) runs it on a manifest generated from the
recipe pins with `scripts/manifest-from-tree.py` (no Yocto build needed)
and fails the job on any uncovered path. On the board, run it against
`/etc/forgefirm-manifest.json`. The lint proves a
file is *fingerprinted*; whether the test *exercises* the change is the
change author's judgment (rule 1).

## Bench diagnostics page

The same daemon serves `#bench`: the registry of the bench tools
(`scripts/bench`, installed under `/usr/share/forgetest/bench/`), each with
its safety class (`dry`, `takeover`, `live`, `scope`), argument form, and
last run. A ported tool runs as a subprocess with the output on the page;
unported tools are listed with Start disabled. Bench runs are recorded in
`/data/forgetest/bench.jsonl` and never enter a campaign.

## Layout

    forgetest/forgetest/         the package (stdlib only)
      manifest.py                manifest, globs, fingerprints, coverage report
      catalog.py                 @test registry, catalog hash
      campaign.py                the rules (pure functions)
      artifact.py                export + gate verification
      runner.py                  one run at a time, prompts, abort, takeover
      baseline.py                the fresh-boot idle state around every run
      server.py / page.py        HTTP API + the page (forgectrl's access rules)
      bench.py / coverage.py     bench registry + subprocess runner; the lint
      suite/                     the catalog, one module per subsystem
    forgetest/tests/             host unit tests (python3 -m unittest discover -s tests)
    scripts/acceptance-gate.py   the gate
    scripts/manifest-from-tree.py  manifest from the recipe pins (CI, workstation)
    releases/v<version>/         the committed artifacts
