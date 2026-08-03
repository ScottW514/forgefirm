# Build

ForgeFIRM is built with [**kas**](https://kas.readthedocs.io/), which manages
the Yocto layers and pins their versions. The **forgefirm** repo is the base
of the build.

Builds run on a Linux host, or on **WSL2** (officially supported by Yocto —
keep the tree on the native ext4 filesystem, not `/mnt/c`).

## Host setup

On Ubuntu/Debian (including WSL2), install the Yocto host packages and kas:

```console
sudo apt-get install -y gawk wget git diffstat unzip texinfo gcc build-essential \
  chrpath socat cpio python3 python3-pip python3-pexpect xz-utils debianutils \
  iputils-ping python3-git python3-jinja2 python3-subunit zstd liblz4-tool file \
  locales libacl1 lz4 rsync
sudo locale-gen en_US.UTF-8
pipx install kas        # use pipx — Ubuntu 24.04 (PEP 668) blocks `pip install --user`
```

For other distros, see the
[Yocto Project Quick Build](https://docs.yoctoproject.org/brief-yoctoprojectqs/index.html).
Do not build as root (the Yocto sanity checks refuse it).

## Get the sources

Clone the repos as siblings (the kas config references `meta-openglow` at
`../meta-openglow` while it is under active Scarthgap migration):

```console
git clone https://github.com/ScottW514/forgefirm.git
git clone https://github.com/ScottW514/meta-openglow.git
git clone https://github.com/ScottW514/kernel-module-glowforge.git
```

```
openglow-forgefirm/
├── forgefirm/                 ← base repo, build runs here
├── meta-openglow/
└── kernel-module-glowforge/
```

## Build the image

```console
cd forgefirm
kas build kas/forgefirm-glowforge.yml
```

kas fetches the upstream layers into `forgefirm/layers/`, builds in
`forgefirm/build/`, and produces the bootable image at:

```
forgefirm/build/tmp/deploy/images/glowforge/forgefirm-image-glowforge.rootfs.wic.gz
```

(The `u-boot-glowforge.imx` also deployed there is **reference-only**: every
supported install/boot flow keeps the factory bootloader on the eMMC. Its env
Kconfig now matches the factory layout — 0x80000 primary / 0x82000 redundant —
but it is not wired into any install path and flashing it is unsupported.)

For exact, reproducible layer versions, generate a lockfile once:

```console
kas lock kas/forgefirm-glowforge.yml
```

See [`kas/README.md`](kas/README.md) for details, the container-build option,
and the Scarthgap migration backlog.

## Write to an SD card

```console
cd build/tmp/deploy/images/glowforge
sudo zcat forgefirm-image-glowforge.rootfs.wic.gz | dd of=/dev/sdX bs=1M
```

To install onto the factory eMMC (dual-boot with the Glowforge firmware), see
[`INSTALL.md`](INSTALL.md).
