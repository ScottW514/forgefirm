# ForgeFIRM install, update & recovery system

Design and contracts of the ForgeFIRM install/update/recovery system:
the factory's own A/B slot scheme, signed `.fw` packaging, the GUI
update manager, factory restore, and the recovery image. The system is
described in the implementation units ("phases") it is built from; the
bench status of each lives in `BRINGUP.md`, as does the measured ground
truth this rests on (eMMC layout, boot0/boot1 maps, saved-env location,
factory `.fw`/updater internals — "eMMC boot & recovery architecture").

## Settled decisions

- **Factory partition scheme, unmodified**: ForgeFIRM lives in the two
  200 MiB rootfs slots (`mmcblk2p1`/`p2`); `/data` (p3) keeps its full
  factory size. No repartitioning at install, ever.
- **Single-OS, not dual-boot**: a machine runs ForgeFIRM *or* factory
  firmware, with a clean migration each way. The factory updater's
  behavior toward foreign slot contents is irrelevant because we never
  operate both long-term.
- **fwup is the universal package/apply format** (the factory's own
  mechanism): ForgeFIRM upgrades, factory restore, and provisioning all
  use signed `.fw` archives applied to the inactive slot, followed by a
  U-Boot env flip — exactly the factory update flow.
- **Factory firmware is archived to `/data` before any factory slot is
  overwritten.** Restore-to-factory never depends on Glowforge's
  servers; the cloud path (`GET /update/current`, already implemented
  in gfutilities) is the optional "restore to *latest*" upgrade.
- **Release artifacts are built and signed locally**, uploaded as
  GitHub releases. The Ed25519 private key never leaves the build
  host, so GitHub is untrusted hosting: machines verify signatures
  before applying. CI does compile checks only, never artifacts.
- **Reinstalling ForgeFIRM from factory = run the installer again**,
  until the recovery refresh (Phase 5) subsumes it.
- **Recovery refresh is squashfs-only in v1**: factory U-Boot, DTB and
  the 3.14.28 recovery kernel stay in place; only the recovery
  userspace is replaced.

## Invariants (every flash path, every phase)

1. Never write the active (running) slot.
2. Machine idle; one flash operation at a time (lock file); no
   flash/reboot while a job runs.
3. Archive factory content before the write that would destroy the
   last copy of it (rootfs slots; boot0/boot1 before a recovery
   refresh).
4. Env flips are atomic: one `fw_setenv -s` transaction setting all
   four of `mmcdev`/`mmchwpart`/`mmcpart`/`mmcroot`.
5. Automatic paths (release updater, cloud restore) require a valid
   signature — ours or Glowforge's respectively. Manual uploads may be
   unsigned behind an explicit "unsigned dev image" warning.
6. The image must fit the 200 MiB slot; the build fails past the size
   gate rather than producing an unflashable release.
7. Boot selection refuses targets that fail the content probe (no
   kernel / no recognizable rootfs).
8. Verify a written slot (fwup on-the-fly hashes, or an explicit
   readback/mount check for raw writes) before flipping boot to it.

## Phase 0 — enablers (no eMMC flashing)

- **0.1 Slot-agnostic images.** Goal: one image boots unmodified from
  p1, p2, or SD, steered only by the saved env (U-Boot's `mmcargs`
  already takes `root=${mmcroot}` from the env). Audit what our
  `/boot/uEnv.txt` currently sets; strip it to entries that are not
  per-location (`fdt_file` etc.); bench-verify by flipping env alone.
  This removes the mount-and-sed step from every flash path.
  *Exit: the same built image boots from two locations with no
  per-slot edit.*
- **0.2 fwup toolchain + keys.** Yocto recipe for fwup (target) and a
  host-side pack step. Generate the ForgeFIRM Ed25519 keypair
  (custody: offline on the build host, passphrase-protected, backed
  up). Compatibility gates, both directions: (a) a `.fw` we pack must
  apply with the **factory's** fwup 0.14.2 (the installer runs on
  factory firmware; fall back to shipping a static armv7 fwup with the
  installer if archive-format drift bites), and (b) our shipped fwup
  must apply a **factory** `.fw` verified against the GF pubkeys
  (carried from the factory image) for cloud restore.
- **0.3 Build outputs.** `forgefirm-image` additionally emits the raw
  ext4 rootfs and a packed+signed `forgefirm-<ver>.fw` with
  `upgrade.a` / `upgrade.b` tasks in the factory pattern
  (partition-relative raw writes, unmounted-destination +
  on-the-fly-verify options); size gate enforced here. A `complete`
  full-provisioning task joins with the Phase 5 recovery work. The wic
  stays for SD/dev burns.

## Phase 1 — ffboot v2 + slot probe

- Atomic env flip (invariant 4) — fixes the existing gaps: three
  separate `fw_setenv` calls today, and `mmchwpart` never set (relies
  on the saved 0).
- `ffboot -l` (or a sibling tool): inventory every candidate — eMMC
  p1/p2, legacy p4, SD — by read-only mount: factory `/etc/version` or
  `/etc/forgefirm-version`, kernel presence; plus the current env
  selection. Machine-parsable output; this is the probe the GUI and
  the installer both reuse.
- *Exit: bench-verified flips SD ↔ eMMC slots; inventory correct for
  factory / ForgeFIRM / empty slots.*

## Phase 2 — slot installer (factory → ForgeFIRM)

Rewrite `install-forgefirm.sh` as a **single-stage** script run from
factory firmware:

1. Sanity: factory 3-partition layout, both slots 200 MiB, active slot
   detected (`rdev`), enough `/data` space.
2. Archive: **every factory slot version** not already archived —
   `dd | gzip` to `/data/forgefirm/archive/factory-rootfs-<ver>.img.gz`
   with a manifest line (slot, version, date, md5); also dump
   boot0/boot1 (32 MiB) into the archive now, ahead of Phase 5. With
   both slots archived, any later overwrite needs no second archive
   step.
3. Fetch `forgefirm.fw` from GitHub releases (fixed asset name — the
   `releases/latest/download/` URL needs one; the version lives in the
   fwup metadata and the release tag), or take a local file argument
   for offline/dev installs. Verify the signature against the
   ForgeFIRM pubkey embedded in the installer (raw 32-byte form for
   the factory's fwup; a dev key until the production ceremony).
4. Apply to the **inactive** slot (fwup + our pubkey). The booted
   factory install stays bootable in the other slot.
5. Atomic env flip (embed the flip logic — the factory rootfs has no
   ffboot v2), reboot.

No repartitioning, no `/data` backup/restore dance, no stage 2.
Rewrite `INSTALL.md` accordingly (serial console procedure stays).

*Exit: a factory machine converts in one pass; `ffboot` returns it to
the intact factory slot; `/data` (calibration, credentials, logs)
demonstrably untouched.*

## Phase 2b — legacy p4 migration

- Boot-time init script (before `/data` mounts), gated on: booted from
  `mmcblk2p1`/`p2` (never SD, never p4) AND legacy geometry present
  (p4 exists, or p3 ends short of the disk). Actions: delete p4,
  extend p3's end to the disk (starts unchanged), `resize2fs`.
  Idempotent and power-safe: every step keyed off actual disk state,
  re-runnable after interruption.
- Existing p4 users reach the new scheme by running the new installer
  from their running ForgeFIRM (same flow as Phase 2; both factory
  slots intact → archive newer, overwrite older), then the boot-time
  check reclaims p4/p3 on first slot boot.
- *Exit: a legacy-layout machine migrates with `/data` contents intact
  and grown to full size; re-boot is a no-op.*

## Phase 3 — release pipeline

- `scripts/release.sh` (build host): gates → kas build → pack `.fw` →
  sign → `sha256sums.txt` → staged assets + `gh release create`
  command (`--publish` runs it where gh is authenticated). Gates:
  clean tree, version single-source, rootfs-vs-slot size
  (warn ≥ 170 MiB / fail ≥ 195 MiB, under bitbake's own hard cap),
  **installer-embedded pubkey must match the signing key**, and
  factory-era fwup (0.14.2) verification of the packed archive.
- One version source: `FORGEFIRM_RELEASE` = git tag =
  `/etc/forgefirm-version` = `.fw` meta-version; the script enforces
  agreement.
- Cloud-mode compatibility baseline: the cloud client's connect-time
  probe records `{latest_gf_version, tested_against_gf}` to
  `/data/forgefirm/gf-latest.json`, and forgectrl's panel warns when
  the live Glowforge service has moved past the tested version (cloud
  mode may break). `tested_against_gf` is the cloud client's configured
  firmware version (`FACTORY_FIRMWARE.FW_VERSION`, the same value it
  advertises to the service); it is **not** release metadata — neither
  `release.sh` nor the `.fw` meta carries such a field.
- `release.sh --dev` packs a **dev-key-signed** `forgefirm-dev.fw`
  from the release rootfs for the GUI upload path (decides open
  question 4: dev archives are signed with the dev key, never
  unsigned — the GUI exercises the same verification path either
  way).
- GitHub Actions: per-push compile checks for grblHAL-glowforge and
  forgectrl (minutes, no Yocto); optional `workflow_dispatch`
  cold-Yocto reproducibility build whose only product is a checksum.

## Phase 4 — forgectrl update manager (GUI)

Endpoints in `forgectrl/src/update.c`, driven from the panel's System
tab; trust anchors in `/etc/forgefirm/keys` (`forgefirm-keys` recipe:
the release pubkey + the Glowforge keyring). Release version resolves
from the fixed-name asset redirect (`.../releases/latest/download/forgefirm.fw`
→ `.../download/v<ver>/...`), so no GitHub API / rate limits. All slot
writes run on one background job (polled `/update/status`), take the
installer's `/data/forgefirm/update.lock`, require idle + no diagnostic,
refuse the booted root slot, verify signature before writing, and
re-verify the written filesystem. `GET /slots` inventory, `POST /boot`
(probe-gated), `POST /update/{check,download,apply,upload}`,
`POST /restore/factory` (archive md5 checked), `POST /system/reboot`.
Every state-changing call is behind forgectrl's auth layer (bearer
token + origin checks; unsigned installs additionally require the
physical button held).

Functions of the panel page:

- **Inventory**: slot contents (Phase 1 probe), current/next boot
  selection, archive presence/version.
- **Update check** against the GitHub releases API (manual button +
  periodic while idle; offline-tolerant, rate-limit friendly).
- **Apply release**: download `.fw` to `/data`, verify signature,
  apply to inactive slot, verify, then flip only on explicit user
  confirmation, prompt reboot.
- **Upload**: streamed multipart to `/data` (never RAM-buffered);
  accepts `.fw` (verify; warn if unsigned) and `.wic.gz`/`.ext4.gz`
  (dev; size + superblock sanity checks).
- **Boot selector** incl. SD, with warnings — most prominently on
  switch-to-factory: the factory updater may auto-update and overwrite
  the other slot. Refuses unprobeable targets.
- **Factory restore**: from the `/data` archive (offline) or cloud
  latest (gfutilities device auth → GF-signed `.fw` → verify with GF
  pubkeys) → inactive slot → flip. Optional cleanup of ForgeFIRM
  residue in `/data` for true factory condition.
- Interlocks throughout: idle-only, update lock, never the active
  slot, rollback = flip back to the previous slot.

*Exit: full loop on the bench — GUI upgrade, rollback via boot
selector, factory restore and return — without touching a shell.*

## Phase 5 — recovery refresh (not yet built)

- **v1 scope**: replace only the boot0 recovery squashfs (boot1 `/usr`
  only if needed). Never write below offset 0xC0000 in boot0 — U-Boot
  is physically untouchable by the refresh tool. Factory DTB and
  kernel 3.14.28 stay.
- Userspace: static busybox + fwup + a small C webapp (ulfius) +
  hostapd/wpa_supplicant. No Python. Must carry 3.14.28-matched WiFi
  modules (decision gate: lift from the factory recovery vs rebuild
  from Glowforge's published GPL kernel source).
- Functions: button-hold → AP + web UI (factory UX): upload a `.fw`
  (verified against our **and** GF pubkeys — either firmware
  installable), install from the `/data` archive, set boot target,
  export logs.
- Flash tool: boot0/boot1 archived first (Phase 2 already does),
  `force_ro` unlock, write high regions only, readback verify; if both
  partitions are written, boot1 first, boot0 last.
- First flashes bench-gated on an attached serial console.
- Documented recovery ladder from then on: other slot → button-hold
  recovery → SD card → serial console.

## Contracts

- **Artifacts** (consumers: installer, GUI updater, recovery):
  `forgefirm.fw` (fixed asset name; signed; version in the fwup
  metadata = release tag `v<semver>`; tasks `upgrade.a`/`upgrade.b`,
  `complete` from Phase 5), `sha256sums.txt`,
  `forgefirm-image-glowforge.rootfs.wic.gz` (SD burns).
- **Env**: SD = `0/0/1//dev/mmcblk1p1`; slot N = `1/0/N//dev/mmcblk2pN`
  (`mmcdev/mmchwpart/mmcpart/mmcroot`, always one transaction).
- **Archive layout**: `/data/forgefirm/archive/` —
  `factory-rootfs-<ver>.img.gz`, `boot0.img`, `boot1.img`,
  `manifest` (slot versions, dates, checksums).

## Decisions

- uEnv.txt keeps its `mmcargs` override with `root=${mmcroot}` — the
  image is slot-agnostic, steered only by the saved env.
- Modern-fwup-packed signed archives apply with the factory 0.14.2
  binary (raw 32-byte pubkey form); no shipped fwup is needed on the
  factory side.
- Size gates live in two layers: bitbake fails past the 200 MiB slot;
  `release.sh` warns ≥ 170 MiB and fails ≥ 195 MiB.
- Dev archives are always signed with the dedicated dev key
  (`release.sh --dev`), never unsigned.
- Production signing key: held offline by the operator (never in the
  repo, CI, or cloud-synced plaintext), public key embedded in the
  installer. Production-signed archives verify with fwup 1.16 and the
  factory's 0.14.2 (raw pubkey form); dev-signed archives are rejected.
  Custody optimizes against compromise over loss: loss means users
  re-run a fresh installer; compromise means attacker-signed firmware
  on fielded machines.
- U-Boot bootcount/auto-revert is out of scope — the recovery ladder
  covers bad flips.

## Open items

- Periodic GUI update check default-on vs opt-in (it pings GitHub;
  proposal: on by default, apply always manual, config switch to
  disable).
- Recovery kernel modules: carried from the factory image vs rebuilt
  from GPL source (Phase 5 gate).

## Dependencies between the phases

0 → 1 → 2 + 2b → 3 → 4 → 5: everything after Phase 0 assumes
slot-agnostic images and working `.fw` round-trips; the GUI (4) reuses
the probe (1) and pipeline (3); recovery (5) is an independent
mini-project on top of the stable slot scheme.
