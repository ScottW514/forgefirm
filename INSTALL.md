# Installing OpenGlow/ForgeFIRM

ForgeFIRM installs **alongside** the factory firmware on the stock eMMC,
using the factory's own A/B rootfs slot scheme: the installer writes
ForgeFIRM to the slot the factory firmware is *not* running from, and
switches the bootloader to it. Nothing is repartitioned, the factory
`/data` partition (settings, calibration, logs) is untouched, and the
booted factory firmware stays installed in the other slot.

Before anything is overwritten, the installer archives **every** factory
firmware version on the machine — both rootfs slots and the recovery
boot partitions — to `/data/forgefirm/archive/`, so a full offline
factory restore is always possible, no Glowforge cloud required.

> **Requires a ForgeFIRM release that ships the `forgefirm.fw` asset
> (v0.1.0 or later).**

## Prerequisites

- [Serial console](SERIAL.md) access. Current factory firmware does not
  offer SSH, so the install is run at the console (login `root`, no
  password).
- ~300 MB free on `/data` (a factory machine has far more).
- Internet access on the machine for the standard flow. For an offline
  install, place a `forgefirm.fw` on `/data` beforehand and pass its
  path to the installer.

**A very important warning: this is experimental software. Use of this
software could seriously maim or kill you or others, and voids your
warranty. It is not affiliated with or endorsed by Glowforge. Use it at
your own risk.**

## Regulatory and legal

Installing ForgeFIRM replaces the firmware of a certified laser product.
This is disclosure, not legal advice — but understand the categories
before you install:

- **Laser product certification (US).** The factory machine is
  certified under FDA/CDRH 21 CFR 1040.10 and 1040.11. Modifying it
  makes **you** the manufacturer of a modified laser product for
  regulatory purposes; the original accession no longer describes the
  article you operate.
- **CE/UKCA (EU/UK).** The manufacturer's declaration of conformity no
  longer covers the modified machine.
- **Safety listing.** Any UL/ETL or equivalent listing applies to the
  product as shipped, not as modified.
- **Insurance.** Property and liability policies commonly exclude fire
  loss involving modified equipment. Check yours before running jobs.

The hardware safety interlocks (lid switches, interlock, power-fault
chain) remain active under ForgeFIRM — but the regulatory status of the
machine is yours to own once you flash it.

## Install

Log in at the factory console and run:

```sh
curl -fL https://raw.githubusercontent.com/ScottW514/forgefirm/master/scripts/install-forgefirm.sh --output /tmp/install-forgefirm.sh
sh /tmp/install-forgefirm.sh
```

(For an offline install: `sh /tmp/install-forgefirm.sh /data/forgefirm.fw`)

One stage, no intermediate reboots. The installer:

1. Confirms it is running on factory firmware, from a factory eMMC
   slot, with the factory partition layout.
2. Stops the Glowforge services (including the updater).
3. Archives every factory slot version and the recovery boot
   partitions to `/data/forgefirm/archive/` (manifest with checksums;
   a few minutes each, with progress).
4. Downloads the latest `forgefirm.fw` release (or uses the local file
   you passed) and **verifies its signature** before touching anything.
5. Writes ForgeFIRM to the inactive slot with the factory's own `fwup`,
   then verifies the written filesystem.
6. Installs `/data/ffboot` (the boot-slot tool) and switches the saved
   U-Boot environment to the new slot — the switch is read-back
   verified; on any failure the machine keeps booting factory firmware.
7. Reboots into ForgeFIRM.

Login is `root`, no password (also via SSH). Change it.

## Switching firmware

Both systems stay installed; `ffboot` switches between them (as
`/data/ffboot` on factory firmware, on the PATH in ForgeFIRM):

```sh
ffboot -l     # inventory: what is in each slot, what boots next
ffboot -e     # switch to the factory firmware (newest factory slot)
ffboot -e2    # switch to ForgeFIRM (slot 2 on a standard install)
```

Switch targets are probed first — `ffboot` refuses to select a slot
that does not look bootable (`-f` overrides). Reverting to factory
firmware and back requires no reinstall.

**Routine updates do not use the installer.** Update from the web
control panel's System page, which downloads (or accepts an upload of)
a signed `forgefirm.fw` release, verifies it, and applies it to the
inactive slot. Rerunning the installer is only for recovering a broken
ForgeFIRM install: switch to factory firmware and run it again — it
skips archives it already has and simply rewrites the ForgeFIRM slot.

## Upgrading from a legacy dual-partition install

Machines installed with the previous (partition-carving) installer
migrate automatically: run this installer from the factory firmware;
on ForgeFIRM's first boot from its new slot, the legacy partition is
reclaimed and `/data` grows back to the full factory size. `/data`
contents are preserved throughout.

**NOTE:** This firmware is in beta. It mostly works. It is for
experimentation purposes — not for production. Expect problems.
