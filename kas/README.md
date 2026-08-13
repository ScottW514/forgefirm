# Building ForgeFIRM with kas

The **forgefirm** repo is the base of the project: it controls the build,
the resulting firmware images land here, and all build/install docs live here.
It uses [**kas**](https://kas.readthedocs.io/) to manage Yocto layers and drive
the build.

## Baseline

| | |
|---|---|
| Yocto release | **Scarthgap 5.0 LTS** |
| Kernel | **linux-fslc 6.12** (mainline LTS, from meta-freescale) |
| Machine | `glowforge` (i.MX6 Solo SOM — Basic/Plus/Pro) |
| Distro | `forgefirm` |
| Image | `forgefirm-image` |

## Layout

```
openglow-forgefirm/
├── forgefirm/                 ← THIS repo, the base
│   ├── kas/
│   │   ├── forgefirm-glowforge.yml   ← build entry point
│   │   └── README.md                 ← this file
│   ├── meta-forgefirm/        ← the forgefirm layer (this repo)
│   ├── BUILD.md / INSTALL.md / SERIAL.md
│   ├── layers/                ← kas-cloned upstreams (gitignored)
│   ├── build/                 ← bitbake output incl. images (gitignored)
│   ├── downloads/ sstate-cache/       ← caches (gitignored)
│   └── .gitignore
├── meta-openglow/             ← Glowforge BSP layers (local sibling, under migration)
└── kernel-module-glowforge/   ← glowforge.ko sources (pulled by recipe SRC_URI)
```

`meta-openglow` is referenced as a **local sibling** (`../meta-openglow`) while
we migrate it to Scarthgap, so its in-place edits are what gets built. Once that
migration is committed/pushed, flip it to a kas-cloned + pinned repo (commented
block in `forgefirm-glowforge.yml`) and the forgefirm repo becomes fully
self-contained.

## Prerequisites

A Linux build host, or **WSL2** on Windows (officially supported by Yocto).

> **WSL2 note:** keep this whole tree on the WSL2 *native* ext4 filesystem
> (e.g. `~/dev/openglow-forgefirm`), **not** under `/mnt/c/...`. The Windows
> mount breaks case-sensitivity/permissions and is very slow for Yocto. Give the
> WSL2 VM plenty of RAM and disk in `.wslconfig`.

```bash
pipx install kas      # or: pip install kas
```

## Build

Run from the **forgefirm repo root** so outputs land inside it:

```bash
cd forgefirm
kas build  kas/forgefirm-glowforge.yml     # fetch layers + full build
kas shell  kas/forgefirm-glowforge.yml     # interactive bitbake environment
kas dump   kas/forgefirm-glowforge.yml     # print the resolved config
```

The bootable image lands in `build/tmp/deploy/images/glowforge/`. Flashing /
dual-boot install steps are in [`../INSTALL.md`](../INSTALL.md).

### Container build (optional, reproducible host)

```bash
cd forgefirm
kas-container build kas/forgefirm-glowforge.yml
```

## Pinning exact versions (reproducible builds)

The config tracks the `scarthgap` **branch** of each upstream layer. To lock
every layer to an exact commit:

```bash
kas lock kas/forgefirm-glowforge.yml      # writes kas/forgefirm-glowforge.lock.yml
```

kas auto-loads the lockfile on subsequent runs. Commit it; refresh deliberately.

## Push & release order (source-of-truth sequencing)

The build is only reproducible when recipe pins, layer branches, and the kas
config move in the right order. The sequence, with current status:

1. **Source repos pushed & pinned** — **DONE.** Every source repo
   (`kernel-module-glowforge`, `python3-gfhardware`, `Glowforge-Utilities`,
   `grblHAL-glowforge`, `forgectrl`) is on GitHub and its recipe pins an exact
   `SRCREV` — no `AUTOREV` anywhere. Whenever a source repo changes: push it,
   then bump the recipe `SRCREV` deliberately (BSP recipes in meta-openglow,
   ForgeFIRM components in meta-forgefirm) and re-verify with
   `bitbake -c fetch <recipe>`.
2. **meta-openglow pushed** — **DONE.** The Scarthgap port lives on
   the **`scarthgap` branch** (Yocto layer convention; the Dunfell-era `master`
   is untouched). Development continues on the local sibling checkout; push /
   fast-forward `scarthgap` as work lands.
3. **forgefirm pushed** with the kas config and a `kas lock` lockfile pinning
   the upstream layers (poky, meta-openembedded, meta-freescale,
   meta-freescale-distro).
4. **At release time**:
   - flip `meta-openglow` in `forgefirm-glowforge.yml` from the local-sibling
     block to the pinned-remote block (commented FUTURE block in the file);
   - refresh `kas lock`, tag all repos, and prove self-containment by building
     from a **fresh clone**.
5. **GitHub release**: run `scripts/release.sh <version>` on the build
   host. It gates (version single-source, rootfs-vs-slot size,
   installer-embedded pubkey vs the signing key, factory-era fwup
   verification), builds, packs and signs `forgefirm.fw`, stages the
   assets with `sha256sums.txt`, and prints the `gh release create`
   command. Assets and their exact names (the installer and the update
   manager download them verbatim): `forgefirm.fw`, `sha256sums.txt`,
   `forgefirm-image-glowforge.rootfs.wic.gz`. The release tag
   `v<version>` = `FORGEFIRM_RELEASE` = the rootfs `/etc/forgefirm-version`
   = the `.fw` meta-version; `release.sh` enforces the agreement.

All recipes fetch their pinned revision from GitHub, so an image build is
reproducible from the repos alone. For fast iteration on a source repo, bump
its pin per iteration, or add a **local, untracked** `externalsrc` bbappend
pointing at the sibling checkout — never commit one, or released images stop
matching the pins.

## Scarthgap migration backlog

The kas scaffold + `LAYERSERIES_COMPAT` bumps let the layers be *selected* under
Scarthgap, but the legacy (Dunfell/Gatesgarth) layers won't build clean until:

1. ~~**Override-syntax migration**~~ — **DONE.** All `_append`/`_prepend`/
   `_remove`/`_${PN}` override syntax converted to the colon form across
   `meta-forgefirm`, `meta-openglow-core`, and `meta-glowforge-bsp` (22
   occurrences). Note: `meta-openglow-bsp` (the separate OpenGlow_std board,
   not built here) was intentionally left unconverted.
2. **Kernel forward-port (4.14 → linux-fslc 6.12.20)** — the factory NXP vendor
   kernel (linux-imx 4.14.98) carried 7 out-of-tree changes; these are re-derived
   against mainline 6.12 in `meta-glowforge-bsp/recipes-kernel/linux/linux-fslc_%.bbappend`
   (the forward-port landing zone), **not** re-applied as the 4.14 patches.
   - **Foundation — DONE.** `linux-fslc` 6.12.20 builds for `glowforge` with a
     ported device tree (`glowforge.dts` + `openglow_common.dtsi` overlaid into
     `arch/arm/boot/dts/nxp/imx/`, registered via a Makefile patch) and deploys
     `zImage` + `glowforge.dtb`. Boot-core + mainline-bound peripherals only.
   - **Free wins — DONE.** bus-freq disable *dropped* (no mainline busfreq);
     `st,lis2hh12` ×3 + `national,lm75b` + `ti,wl1805` + gpio keys/leds bind to
     mainline drivers; `reg-userspace-consumer` enabled via `glowforge.cfg`.
     (SPI-delay / PWM-prescaler dispositions are under Motion polish below.)
   - **Motion path — DONE and hardware-validated** (live-fed pulse stream,
     real gantry motion, laser fire). The whole chain forward-ports and
     compiles on 6.12:
       - **EPIT API**: `epit_api.c` in `arch/arm/mach-imx` (`CONFIG_MXC_EPIT_API`),
         in vmlinux, symbols exported; `&epit1/&epit2` in the DT.
       - **SDMA-expose**: re-created `dma-imx-sdma.h` + `0003-imx-sdma-*.patch`
         (un-static survivors, re-added the glowforge helpers, custom int-callback
         hook); expose symbols in `Module.symvers`.
       - **`glowforge.ko`**: ported across many 6.12 API changes
         (`tasklet_hrtimer`→soft hrtimer, `timer_setup`, LED-trigger API,
         `pwm_get`, `spi_delay`/`controller`, `filelock.h`, void `.remove`,
         1-arg i2c probe). Compiles + links, 0 undefined symbols. Built from the
         local sibling via an `externalsrc` bbappend during migration.
       - **DT**: `glowforge,cnc/thermal/pic/head` re-added with `pwms`/`pwm-names`
         phandles; `glowforge.dtb` compiles with all motion nodes.
     Motion polish: PWM prescaler (factory 1001) is **obsolete** — 6.12
     `pwm-imx27` auto-computes the prescaler from the requested period. The PIC
     inter-word SPI delay (factory 1005) is a **hardware-bring-up TODO**: 6.12
     `spi-imx.c` has no `PERIODREG`/`word_delay` programming, so re-derive it in
     `spi_imx_setupxfer` (write `MX51_ECSPI_PERIODREG` from `t->word_delay`,
     guarded to ECSPI) and verify the wait-states on a scope. pic.c keeps the
     inter-transfer delay meanwhile. `glowforge,imx-pwm-audio` (buzzer) deferred.
   - **Camera — DONE and hardware-validated.** The factory
     `ov5648_mipi.c` (NXP's removed `v4l2_int_device`/`mxc_v4l2_capture`) is
     replaced by the mainline `ovti,ov5648` subdev + imx6 `imx-media` (IPU CSI)
     + `imx6-mipi-csi2` receiver. The factory CAM_SEL MIPI switch is modelled
     with the mainline `video-mux` (gpio-mux on `gpio7 10`): both sensors →
     video-mux → `mipi_csi` → IPU CSI. Sensor `xvclk` is the board's 24 MHz
     fixed oscillator (matching the factory DTB); avdd/dovdd/dvdd rails are in
     the DT. Both cameras stream live through forgectrl (MJPEG at 15 fps with
     VPU JPEG encode, full-resolution snapshots, mux arbitration).
     **HD-unit caveat:** the DT lists both `ovti,ov5648` (5 MP) and
     `ovti,ov8856` (8 MP) at 0x36 so one image covers both, and the driver
     matching the chip ID wins — but mainline `ov8856` expects a 19.2 MHz
     xvclk and only warns at 24 MHz, and the capture path is written to
     ov5648's SBGGR8 2592×1944 format set. 8 MP "HD" modules therefore bind
     but do not capture; adding 24 MHz PLL modes plus a sensor-aware capture
     path is the open work.
3. **u-boot** — **DONE.** The `glowforge` u-boot is
   a standalone `u-boot_2020.01.bb` (Scarthgap's poky has no u-boot 2020.01
   base recipe to extend). It reuses poky's
   `u-boot-common.inc`/`u-boot.inc`, pins `SRCREV` to the upstream **v2020.01**
   tag with the matching `Licenses/README` md5, and overlays the glowforge board
   support + arch-Kconfig patch. **Builds clean under Scarthgap (GCC 13, no
   source fixes) and deploys `u-boot-glowforge.imx`.** Remaining: move
   `fw_printenv`/`fw_setenv` from `u-boot-fw-utils` to `libubootenv`
   (`PREFERRED_PROVIDER_u-boot-fw-utils` in `glowforge.inc`) when the rootfs needs
   them.
4. **Device tree — DONE.** The `glowforge` `.dts` is validated against the
   linux-fslc 6.12 bindings and against the running board (motion, safety
   readbacks, cameras, sensors all bind and work). Residue: `control_12v`
   still uses the `reg-userspace-consumer` compatible, which matches no 6.12
   driver — convert it to `regulator-output` or drop the node.
5. **Real-time strategy — decided.** The kernel runs
   `CONFIG_PREEMPT=y` (factory behavior; `imx_v6_v7_defconfig` alone gives only
   `PREEMPT_VOLUNTARY`). **PREEMPT_RT is not selectable on arm32 6.12** (no
   `ARCH_SUPPORTS_RT`) and is **not needed for the pulse feeder**: the SDMA
   ring is 128 MiB draining at 1 byte per EPIT tick — ≤200–400 KB/s even at
   the 200 kHz ceiling — so a full ring holds **~5–11 minutes** of stream and
   a modest 1 MiB of queued data already rides out ~3–5 s of scheduling
   latency, orders of magnitude beyond anything PREEMPT exhibits. Deep
   buffering + `SCHED_FIFO` for the feeder is the design; revisit RT only if
   the underrun bench ever contradicts this arithmetic. (Bench: 5 s of
   continuous feed at a 1 s buffer depth, zero underruns.)

6. **gfui-client → forgectrl — DONE.** The stock `gfui-client` is excluded
   from `forgefirm-image` (`IMAGE_INSTALL:remove = "gfui-client"` in
   `meta-forgefirm/recipes-forgefirm/images/forgefirm-image.bb`). Its slot is
   filled by `forgectrl` (github.com/ScottW514/forgectrl — the machine-services
   daemon: web control panel, cameras, telemetry, settings, diagnostics,
   cooling engine, updates, and controller-mode supervision) plus the two
   controllers it supervises, `grblhal-glowforge` (Grbl over TCP:23) and
   `gfcloud` (the optional Glowforge web-service client, off unless selected).

---

**Image status:** `forgefirm-image` **builds end-to-end** on the forward-ported
stack and deploys `forgefirm-image-glowforge.rootfs.wic.gz` (+ `zImage`,
`glowforge.dtb`, `u-boot-glowforge.imx`) under `build/tmp/deploy/images/glowforge/`.
Build-time prerequisites baked into the config: `ACCEPT_FSL_EULA = "1"` (NXP
firmware-imx — the image also installs `firmware-imx-lic` so the EULA text
ships beside the blobs) and the kernel default in `glowforge.conf`. The stack
is hardware-validated end to end: motion timing, the laser and safety chain,
the camera pipeline, both controller modes, and the A/B install path.
