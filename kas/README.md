# Building ForgeFIRM with kas

The **forgefirm** repo is the base of the project: it controls the build,
the resulting firmware images land here, and all build/install docs live here.
It uses [**kas**](https://kas.readthedocs.io/) to manage Yocto layers and drive
the build, replacing the old Google `repo` + `default.xml` manifest and the
hand-maintained `base/conf/forgefirm-bblayers.conf`.

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
   (the forward-port landing zone), **not** re-applied as the old 4.14 patches.
   - **Foundation — DONE.** `linux-fslc` 6.12.20 builds for `glowforge` with a
     ported device tree (`glowforge.dts` + `openglow_common.dtsi` overlaid into
     `arch/arm/boot/dts/nxp/imx/`, registered via a Makefile patch) and deploys
     `zImage` + `glowforge.dtb`. Boot-core + mainline-bound peripherals only.
   - **Free wins — DONE.** bus-freq disable *dropped* (no mainline busfreq);
     `st,lis2hh12` ×3 + `national,lm75b` + `ti,wl1805` + gpio keys/leds bind to
     mainline drivers; `reg-userspace-consumer` enabled via `glowforge.cfg`.
     (SPI-delay / PWM-prescaler dispositions are under Motion polish below.)
   - **Motion path — DONE (builds clean; runtime needs hardware).** The whole
     chain forward-ports and compiles on 6.12:
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
   - **Camera — DONE (builds clean; runtime needs hardware).** The factory
     `ov5648_mipi.c` (NXP's removed `v4l2_int_device`/`mxc_v4l2_capture`) is
     replaced by the mainline `ovti,ov5648` subdev + imx6 `imx-media` (IPU CSI)
     + `imx6-mipi-csi2` receiver. The factory CAM_SEL MIPI switch is modelled
     with the mainline `video-mux` (gpio-mux on `gpio7 10`): both `ov5648`s →
     video-mux → `mipi_csi` → IPU CSI. Sensor `xvclk` (25 MHz fixed-clock) +
     avdd/dovdd/dvdd rails in the DT. All drivers build as modules and
     `glowforge.dtb` compiles with the full pipeline. **HW bring-up:** confirm
     the real supply rails, CSI-2 lane count/order and CAM_SEL polarity, then
     validate with `media-ctl` + a v4l2 capture.
3. **u-boot** — ~~rebuild for Scarthgap~~ **DONE.** The `glowforge` u-boot is now
   a standalone `u-boot_2020.01.bb` (Scarthgap dropped the Dunfell-era poky base
   recipe the old `.bbappend` extended). It reuses poky's
   `u-boot-common.inc`/`u-boot.inc`, pins `SRCREV` to the upstream **v2020.01**
   tag with the matching `Licenses/README` md5, and overlays the glowforge board
   support + arch-Kconfig patch. **Builds clean under Scarthgap (GCC 13, no
   source fixes) and deploys `u-boot-glowforge.imx`.** Remaining: move
   `fw_printenv`/`fw_setenv` from `u-boot-fw-utils` to `libubootenv`
   (`PREFERRED_PROVIDER_u-boot-fw-utils` in `glowforge.inc`) when the rootfs needs
   them.
4. **Device tree** — revalidate the `glowforge` `.dts` against the linux-fslc
   6.12 DT bindings (paired with the kernel forward-port in #2).
5. **gfui-client → forgectrl** — the Glowforge **cloud client is now removed**
   from `forgefirm-image` (`IMAGE_INSTALL:remove = "gfui-client"` in
   `meta-forgefirm/recipes-forgefirm/images/forgefirm-image.bb`) — it connected to
   Glowforge's servers, the dependency ForgeFIRM exists to cut. The grblHAL
   controller + web UI (`forgectrl`, currently a placeholder) will fill its place.

---

**Image status:** `forgefirm-image` **builds end-to-end** on the forward-ported
stack and deploys `forgefirm-image-glowforge.rootfs.wic.gz` (+ `zImage`,
`glowforge.dtb`, `u-boot-glowforge.imx`) under `build/tmp/deploy/images/glowforge/`.
Build-time prerequisites baked into the config: `ACCEPT_FSL_EULA = "1"` (NXP
firmware-imx) and the kernel default in `glowforge.conf`. Everything compiles;
on-hardware bring-up (motion timing, laser/safety chain, camera pipeline) is the
remaining validation and needs a real board.
