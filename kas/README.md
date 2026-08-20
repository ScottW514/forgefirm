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
└── meta-openglow/             ← Glowforge BSP layers (local sibling checkout)
```

`meta-openglow` is referenced as a **local sibling** (`../meta-openglow`), so
its in-place edits are what gets built. The commented pinned-remote block in
`forgefirm-glowforge.yml` makes the forgefirm repo fully self-contained when
flipped on. The source repos the recipes build (`kernel-module-glowforge`,
`grblHAL-glowforge`, `forgectrl`, `python3-gfhardware`, `Glowforge-Utilities`)
are fetched by pinned `SRCREV` and are not needed as local checkouts.

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
   then bump the pin deliberately (BSP recipes in meta-openglow, ForgeFIRM
   components in meta-forgefirm) and re-verify with
   `bitbake -c fetch <recipe>`. A component's `SRCREV` (and the `PV` that
   moves with it) lives in `<recipe>-pin.inc` next to the recipe, nothing
   else goes in that file: the image manifest leaves `*-pin.inc` out of the
   layer content hash, so a pin bump changes the component's fingerprint
   and only that (`docs/ACCEPTANCE.md`) — a pin written into the recipe body
   still builds, but counts as a platform change and forces a full
   acceptance campaign.
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
   verification, and the **acceptance gate** - the committed
   `releases/v<version>/acceptance.json` from the bench campaign must
   authorize the built rootfs, `docs/ACCEPTANCE.md`), builds, packs and
   signs `forgefirm.fw`, stages the assets with `sha256sums.txt`, and
   prints the `gh release create` command. Assets and their exact names
   (the installer and the update manager download them verbatim):
   `forgefirm.fw`, `sha256sums.txt`,
   `forgefirm-image-glowforge.rootfs.wic.gz`, plus `acceptance.json` and
   `acceptance.md`. The release tag
   `v<version>` = `FORGEFIRM_RELEASE` = the rootfs `/etc/forgefirm-version`
   = the `.fw` meta-version; `release.sh` enforces the agreement.

All recipes fetch their pinned revision from GitHub, so an image build is
reproducible from the repos alone. For fast iteration on a source repo, bump
its pin per iteration, or add a **local, untracked** `externalsrc` bbappend
pointing at a working checkout — never commit one, or released images stop
matching the pins.

## Scarthgap migration backlog

The kas scaffold + `LAYERSERIES_COMPAT` bumps let the layers be *selected* under
Scarthgap, but the legacy (Dunfell/Gatesgarth) layers won't build clean until:

1. ~~**Override-syntax migration**~~ — **DONE.** All `_append`/`_prepend`/
   `_remove`/`_${PN}` override syntax converted to the colon form across
   `meta-forgefirm`, `meta-openglow-core`, and `meta-glowforge-bsp` (22
   occurrences).
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
         1-arg i2c probe). Compiles + links, 0 undefined symbols; the recipe
         fetches the module by pinned `SRCREV`.
       - **DT**: `glowforge,cnc/thermal/pic/head` re-added with `pwms`/`pwm-names`
         phandles; `glowforge.dtb` compiles with all motion nodes.
     Motion polish: PWM prescaler (factory 1001) is **obsolete** — 6.12
     `pwm-imx27` auto-computes the prescaler from the requested period. The PIC
     inter-word SPI delay (factory 1005) is a **hardware-bring-up TODO**: 6.12
     `spi-imx.c` has no `PERIODREG`/`word_delay` programming, so re-derive it in
     `spi_imx_setupxfer` (write `MX51_ECSPI_PERIODREG` from `t->word_delay`,
     guarded to ECSPI) and verify the wait-states on a scope. pic.c keeps the
     inter-transfer delay meanwhile. The factory `glowforge,imx-pwm-audio`
   (buzzer) driver is not part of ForgeFIRM.
   - **Camera — DONE and hardware-validated.** The factory
     `ov5648_mipi.c` (NXP's removed `v4l2_int_device`/`mxc_v4l2_capture`) is
     replaced by the mainline `ovti,ov5648` subdev + imx6 `imx-media` (IPU CSI)
     + `imx6-mipi-csi2` receiver. The factory CAM_SEL MIPI switch is modeled
     with the mainline `video-mux` (gpio-mux on `gpio7 10`): both sensors →
     video-mux → `mipi_csi` → IPU CSI. Sensor `xvclk` is the board's 24 MHz
     fixed oscillator (matching the factory DTB); avdd/dovdd/dvdd rails are in
     the DT. Both cameras stream live through forgectrl (MJPEG at 15 fps with
     VPU JPEG encode, full-resolution snapshots, mux arbitration).
     **HD units (8 MP OV8856) — code complete, UNTESTED.** The DT lists both
     `ovti,ov5648` (5 MP) and `ovti,ov8856` (8 MP) at 0x36 so one image covers
     both, and the driver matching the chip ID wins. Everything the OV8856
     needs is in the build: patch 0011 gives it the `get_mbus_config` the
     IPU-CSI hard-fails without (the same gap 0006 closes for ov5648), patch
     0012 retunes both PLL multipliers for the board's 24 MHz xvclk (mainline's
     tables are written for 19.2 MHz, which would run the link 25 % above the
     frequency the driver publishes), patch 0013 adds the 2-lane RAW8 modes
     (below), the endpoint's `link-frequencies` list carries the driver's whole
     2-lane menu (it rejects the endpoint outright if any entry is missing —
     the old list omitted 720 MHz, so probe would have failed), and forgectrl
     and gfhardware pick geometry and the sensor's control set from whichever
     driver bound.

     The capture mode is the **full 3264×2448**, reached in RAW8. The
     sensor's stock RAW10 full-resolution 2-lane mode asks for 1.44 Gbps/lane
     and the i.MX6 CSI-2 D-PHY stops at 1 Gbps (`hsfreq_map` in
     `imx6-mipi-csi2.c` ends at 1000 Mbps and `max_mbps_to_hsfreqrange_sel()`
     returns `-EINVAL` above it), so `imx6-mipi-csi2` refuses to program it —
     but 8-bit samples carry the same frame at half the rate, which puts it on
     the 360 MHz link the binned modes already use, at 180 Mpx/s and 15 fps.
     Patch 0013 builds those modes from mainline's own 4-lane 3264×2448 and
     1632×1224 register lists plus a per-mode delta list: `0x3018` for two
     lanes, `0x3031` for 8-bit readout, and double the HTS because half the
     lanes carry half a line in the same time. It also makes the sample depth a
     mode property, so pixel rate, blanking and exposure ranges follow the mode
     instead of a fixed 10. Side effect worth having: the OV8856 path becomes
     byte-identical in shape to the OV5648's (8-bit BGGR, one byte per sample),
     and 3264 is a multiple of 32 so the NEON superpixel converter applies,
     which 1640 did not allow.

     The values are the factory firmware's: its own OV8856 driver is RAW8-only
     and ships exactly these two resolutions over two lanes with the same
     `0x3018`/`0x3031` and the same HTS/VTS pairs. It reaches them through a
     different PLL divider chain (`0x0302=0x1e`, `0x0303=0x03`, `0x030f=0x07`,
     `0x0312=0x05`, `0x4837=0x58`) that halves the link again to 180 MHz and
     the internal SCLK with it — a self-consistent alternative, recorded in the
     patch header as the configuration to fall back to if the D-PHY will not
     lock at 720 Mbps/lane on real hardware.

     Open, and only answerable on an 8 MP machine: whether it streams at all at
     720 Mbps/lane, and exposure/gain/white-balance commissioning — the OV8856
     driver publishes no red/blue balance controls, so white balance is
     uncorrected.
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
   readbacks, cameras, sensors all bind and work).
5. **Real-time strategy — decided.** The kernel runs
   `CONFIG_PREEMPT=y` (factory behavior; `imx_v6_v7_defconfig` alone gives only
   `PREEMPT_VOLUNTARY`). **PREEMPT_RT is not selectable on arm32 6.12** (no
   `ARCH_SUPPORTS_RT`) and is **not needed for the pulse feeder**. The
   argument is about queue depth, not ring size: the ring drains at 1 byte
   per EPIT tick (≤200 KB/s even at the 200 kHz ceiling), so the live
   feeder's bounded queue depth of ~150 ms — a few KB in flight — already
   rides out worst-case scheduling latency with orders of magnitude to spare
   (measured: 0.2 ms worst write latency under full CPU + I/O load; the
   underrun bench ran 100 kHz for 120 s with zero underruns). The ring
   itself is 32 MiB (the `ring_mb` module parameter, backed by the 32 MiB
   reserved pool, matching the factory ring): ~168 s of stream at 200 kHz,
   ~56 min at the 10 kHz cloud-mode tick — a capacity that matters for the whole-job preload of
   cloud mode, not for latency. Bounded queue depth + `SCHED_FIFO` for the
   feeder is the design; revisit RT only if the underrun bench ever
   contradicts this arithmetic.

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
ships beside the blobs) and the kernel default in `glowforge.conf`. Every
`LICENSE` string in the layers (`meta-forgefirm`, `meta-glowforge-bsp`,
`meta-openglow-core`) is SPDX, and the recipes for third-party components
that carry more than one license (`wlconf`, `python3-gfhardware`) declare
each of them with a checksum on its license text. The stack
is hardware-validated end to end: motion timing, the laser and safety chain,
the camera pipeline, both controller modes, and the A/B install path.
