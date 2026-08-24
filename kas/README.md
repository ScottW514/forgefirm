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
| Machine | `glowforge` (i.MX6 Solo SOM; Basic/Plus/Pro) |
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

## Pins, pushes, and the release flow

The build is reproducible only when recipe pins, layer branches, and the kas
config move in the right order.

- **Every source repo is pinned.** `kernel-module-glowforge`,
  `python3-gfhardware`, `Glowforge-Utilities`, `grblHAL-glowforge` and
  `forgectrl` are fetched from GitHub at an exact `SRCREV`; there is no
  `AUTOREV` anywhere. When a source repo changes: push it, then bump the pin
  deliberately (BSP recipes in `meta-openglow`, ForgeFIRM components in
  `meta-forgefirm`) and re-verify with `bitbake -c fetch <recipe>`. A
  component's `SRCREV` (and the `PV` that moves with it) lives in
  `<recipe>-pin.inc` next to the recipe, and nothing else goes in that file:
  the image manifest leaves `*-pin.inc` out of the layer content hash, so a pin
  bump changes the component's fingerprint and only that
  (`docs/ACCEPTANCE.md`). A pin written into the recipe body still builds, but
  counts as a platform change and forces a full acceptance campaign.
- **`meta-openglow` lives on its `scarthgap` branch** (Yocto layer convention;
  the Dunfell-era `master` is untouched). Development happens on the local
  sibling checkout; `scarthgap` is pushed as work lands.
- **The upstream layers are locked** by `kas lock` (poky, meta-openembedded,
  meta-freescale, meta-freescale-distro); the lockfile is committed and
  refreshed deliberately.
- **At release time**: flip `meta-openglow` in `forgefirm-glowforge.yml` from
  the local-sibling block to the pinned-remote block (the commented block in
  the file), refresh `kas lock`, tag all repos, and prove self-containment by
  building from a fresh clone. Then `scripts/release.sh <version>` gates
  (version single-source, rootfs-vs-slot size, installer-embedded pubkey vs the
  signing key, factory-era fwup verification, and the acceptance gate: the
  committed `releases/v<version>/acceptance.json` from the bench campaign must
  authorize the built rootfs, `docs/ACCEPTANCE.md`), builds, packs and signs
  `forgefirm.fw`, stages the assets with `sha256sums.txt`, and prints the
  `gh release create` command. Assets and their exact names (the installer and
  the update manager download them verbatim): `forgefirm.fw`,
  `sha256sums.txt`, `forgefirm-image-glowforge.rootfs.wic.gz`, plus
  `acceptance.json` and `acceptance.md`. The release tag `v<version>` =
  `FORGEFIRM_RELEASE` = the rootfs `/etc/forgefirm-version` = the `.fw`
  meta-version; `release.sh` enforces the agreement.

For fast iteration on a source repo, bump its pin per iteration, or add a
**local, untracked** `externalsrc` bbappend pointing at a working checkout;
never commit one, or released images stop matching the pins.

## Build-time facts

- `ACCEPT_FSL_EULA = "1"` is set in the kas config: the image carries NXP's
  VPU firmware blob, and `firmware-imx-lic` ships the EULA text beside it.
- Every `LICENSE` string in the layers (`meta-forgefirm`, `meta-glowforge-bsp`,
  `meta-openglow-core`) is SPDX; recipes for third-party components with more
  than one license (`wlconf`, `python3-gfhardware`) declare each with a
  checksum on its license text.
- `forgefirm-image-dev` is a strict superset of `forgefirm-image` (the bench
  image, `docs/ACCEPTANCE.md`); every build produces both.
- The kernel is `linux-fslc` with the board's device tree, config fragment and
  layer patches in `meta-openglow/meta-glowforge-bsp/recipes-kernel/linux/`;
  the bbappend header lists the patches and `glowforge.cfg` documents the
  config. The bootloader recipe is `u-boot_2020.01.bb` in `recipes-bsp`.

Design facts (the pulse ring, real-time choices, hardware measurements) are in
`docs/BRINGUP.md` ("Hardware facts bank") and
`kernel-module-glowforge/UAPI.md`; bench status and open work are
`docs/BRINGUP.md`; the dated record is `docs/CAMPAIGN-LOG.md`.
