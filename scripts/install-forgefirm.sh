#!/bin/sh
# (C) Copyright 2020-2026
# Scott Wiederhold, s.e.wiederhold@gmail.com
# https://community.openglow.org
# SPDX-License-Identifier:    MIT
#
# Single-stage OpenGlow/ForgeFIRM installer. Runs on FACTORY firmware:
#   1. archives the factory rootfs slots and the recovery boot partitions
#      to /data/forgefirm/archive (offline factory restore, forever),
#   2. applies the signed ForgeFIRM .fw to the INACTIVE rootfs slot using
#      the factory's own fwup (signature-verified),
#   3. flips the saved U-Boot environment to the new slot and reboots.
# The factory /data partition is never repartitioned or modified beyond
# the archive directory; the active factory slot stays bootable.
#
# Usage: install-forgefirm.sh [local-forgefirm.fw]
#   With no argument the latest release .fw is downloaded from GitHub.

RELEASE_FW_URL="https://github.com/ScottW514/forgefirm/releases/latest/download/forgefirm.fw"
FFBOOT_URL="https://raw.githubusercontent.com/ScottW514/forgefirm/master/scripts/ffboot"
ARCHIVE_DIR="/data/forgefirm/archive"
FW_FILE="/data/forgefirm/forgefirm.fw"
MIN_DATA_FREE_KB=300000

# ForgeFIRM release-signing public key (raw 32-byte Ed25519, the format the
# factory's fwup 0.14.2 expects).
# !! DEV KEY - must be replaced at the production key ceremony !!
PUBKEY='\x79\xf5\xc2\x53\x45\x13\x49\x51\xd4\x63\x17\x9d\x60\xd7\x7a\x97\xa7\xd6\xd6\xf4\xd8\x9f\x9d\xbd\x8f\xcc\x28\xfc\xba\xa0\x5d\x11'

LIGHTRED="\033[1;31m"
YELLOW="\033[1;33m"
BRIGHT="\033[1;39m"
RESET="\033[0m"
ASTERISK="${LIGHTRED}✺${RESET}"

die () {
  echo
  echo -e "${LIGHTRED}!! INSTALL FAILED:${RESET} $1"
  echo -e "${LIGHTRED}!! No boot change was made unless stated otherwise. Fix and re-run.${RESET}"
  exit 1
}

stop_gf_services () {
  echo -n -e "${ASTERISK}Stopping Glowforge services"
  for SVC in glowforge glowforge-datalogger glowforge-updater bugeggs; do
    sv stop /sv/$SVC 2>/dev/null >/dev/null; echo -n "."
    sv stop /sv/$SVC/log 2>/dev/null >/dev/null; echo -n "."
  done
  echo "."
}

# slot_probe <1|2>: sets S_TYPE (factory|forgefirm|unknown) and S_VER
slot_probe () {
  S_TYPE=unknown; S_VER=""
  MP="/factory/img$1"
  if [ ! -f "$MP/etc/version" ] && [ ! -f "$MP/etc/forgefirm-version" ]; then
    mkdir -p "$MP"
    mount -o ro "/dev/mmcblk2p$1" "$MP" 2>/dev/null
  fi
  if [ -f "$MP/etc/forgefirm-version" ]; then
    S_TYPE=forgefirm; S_VER=$(cat "$MP/etc/forgefirm-version")
  elif [ -f "$MP/etc/version" ]; then
    S_TYPE=factory; S_VER=$(cat "$MP/etc/version")
  fi
}

# Verified atomic env flip (all four variables, classic u-boot-tools script
# format first - that is what factory firmware ships - then libubootenv
# format, then per-variable writes; read-back verified in every case).
FWCONFIG="/etc/fw_env.config"

env_get () { fw_printenv -c "$FWCONFIG" -n "$1" 2>/dev/null; }

env_verify () {
  [ "$(env_get mmcdev)" = "$1" ] && [ "$(env_get mmchwpart)" = "$2" ] && \
  [ "$(env_get mmcpart)" = "$3" ] && [ "$(env_get mmcroot)" = "$4" ]
}

set_env () {
  SCRIPT="/tmp/ffinstall.env.$$"
  printf 'mmcdev %s\nmmchwpart %s\nmmcpart %s\nmmcroot %s\n' "$1" "$2" "$3" "$4" > "$SCRIPT"
  fw_setenv -c "$FWCONFIG" -s "$SCRIPT" 2>/dev/null
  if env_verify "$1" "$2" "$3" "$4"; then rm -f "$SCRIPT"; return 0; fi
  printf 'mmcdev=%s\nmmchwpart=%s\nmmcpart=%s\nmmcroot=%s\n' "$1" "$2" "$3" "$4" > "$SCRIPT"
  fw_setenv -c "$FWCONFIG" -s "$SCRIPT" 2>/dev/null
  rm -f "$SCRIPT"
  if env_verify "$1" "$2" "$3" "$4"; then return 0; fi
  fw_setenv -c "$FWCONFIG" mmcdev "$1"    && \
  fw_setenv -c "$FWCONFIG" mmchwpart "$2" && \
  fw_setenv -c "$FWCONFIG" mmcpart "$3"   && \
  fw_setenv -c "$FWCONFIG" mmcroot "$4"
  env_verify "$1" "$2" "$3" "$4"
}

echo
echo -e "${LIGHTRED} ✺┈┈┈┈┈┈${RESET}"
echo -e "${BRIGHT}Open${RESET}Glow ForgeFIRM Installation Tool"
echo

# --- pre-flight ---------------------------------------------------------------
[ -f /etc/version ] && [ -d /glowforge ] \
  || die "this script must be run from the FACTORY firmware"
command -v fwup >/dev/null || die "fwup not found on this system"
command -v fw_setenv >/dev/null || die "fw_setenv not found on this system"
[ -f "$FWCONFIG" ] || die "$FWCONFIG not found"

BOOTED=$(sed -n 's/.*root=\([^ ]*\).*/\1/p' /proc/cmdline)
case "$BOOTED" in
  /dev/mmcblk2p1) ACTIVE=1; TARGET=2; TASK=upgrade.b ;;
  /dev/mmcblk2p2) ACTIVE=2; TARGET=1; TASK=upgrade.a ;;
  *) die "booted from $BOOTED - expected factory eMMC slot 1 or 2" ;;
esac

for N in 1 2; do
  SZ=$(cat /sys/class/block/mmcblk2p$N/size 2>/dev/null)
  [ "$SZ" = "409600" ] || die "slot $N is not the 200 MiB factory layout (size=$SZ)"
done

FREE_KB=$(df -k /data | tail -1 | awk '{print $4}')
[ "$FREE_KB" -ge "$MIN_DATA_FREE_KB" ] 2>/dev/null \
  || die "need ${MIN_DATA_FREE_KB} KB free on /data, have ${FREE_KB:-unknown}"

echo -e "${LIGHTRED}!!!!!!!!!!!!!!!!     WARNING     !!!!!!!!!!!!!!!!${RESET}"
echo -e "${YELLOW}         THIS IS EXPERIMENTAL SOFTWARE!${RESET}"
echo -e "The installation and/or use of this software may"
echo -e "result in damage to your device and/or property,"
echo -e "loss of warranty, and severe bodily injury and/or"
echo -e "death. This software is not affiliated with or"
echo -e "endorsed by Glowforge. ${BRIGHT}USE IT AT YOUR OWN RISK!${RESET}"
echo -e "${LIGHTRED}!!!!!!!!!!!!!!!!     WARNING     !!!!!!!!!!!!!!!!${RESET}"
echo
echo -e "Booted slot: $ACTIVE - ForgeFIRM will be installed to slot $TARGET."
echo -e "The factory firmware in slot $ACTIVE stays installed and bootable."
echo
read -p "Are you sure you want to continue [N/y]? " continue
echo
if [ "$continue" != "y" ]; then
  echo "Wise choice.  Exiting without changes."
  exit 0
fi

stop_gf_services

# --- archive factory content --------------------------------------------------
mkdir -p "$ARCHIVE_DIR"
for N in 1 2; do
  slot_probe $N
  [ "$S_TYPE" = "factory" ] || continue
  ARC="$ARCHIVE_DIR/factory-rootfs-$S_VER.img.gz"
  if [ -s "$ARC" ]; then
    echo -e "${ASTERISK}Slot $N (factory $S_VER) already archived."
    continue
  fi
  echo -e "${ASTERISK}Archiving slot $N (factory $S_VER) - takes a few minutes:"
  dd if=/dev/mmcblk2p$N bs=1M 2>/dev/null | gzip -1 > "$ARC" \
    || { rm -f "$ARC"; die "archiving slot $N failed"; }
  echo "$(date '+%Y-%m-%d %H:%M:%S') slot$N factory $S_VER $(basename $ARC) md5=$(md5sum "$ARC" | cut -d' ' -f1)" >> "$ARCHIVE_DIR/manifest"
done
for B in 0 1; do
  ARC="$ARCHIVE_DIR/recovery-boot$B.img.gz"
  [ -s "$ARC" ] && continue
  echo -e "${ASTERISK}Archiving recovery boot$B:"
  dd if=/dev/mmcblk2boot$B bs=1M 2>/dev/null | gzip -1 > "$ARC" \
    || { rm -f "$ARC"; die "archiving boot$B failed"; }
  echo "$(date '+%Y-%m-%d %H:%M:%S') boot$B recovery - $(basename $ARC) md5=$(md5sum "$ARC" | cut -d' ' -f1)" >> "$ARCHIVE_DIR/manifest"
done

# --- acquire the ForgeFIRM .fw ------------------------------------------------
mkdir -p /data/forgefirm
if [ -n "$1" ]; then
  [ -s "$1" ] || die "local firmware file '$1' not found"
  cp "$1" "$FW_FILE"
  echo -e "${ASTERISK}Using local firmware file: $1"
else
  echo -e "${ASTERISK}Downloading latest OpenGlow/ForgeFIRM release:"
  curl -fL "$RELEASE_FW_URL" --output "$FW_FILE" || die "firmware download failed"
fi

# --- verify signature ---------------------------------------------------------
KEYFILE="/tmp/forgefirm.pub.$$"
printf "$PUBKEY" > "$KEYFILE"
[ "$(wc -c < "$KEYFILE")" = "32" ] || die "embedded public key corrupt"
echo -e "${ASTERISK}Verifying firmware signature:"
fwup -V -i "$FW_FILE" -p "$KEYFILE" || { rm -f "$KEYFILE"; die "signature verification FAILED - refusing to install"; }
fwup -m -i "$FW_FILE" | grep meta-version

# --- apply to the inactive slot -----------------------------------------------
echo -e "${ASTERISK}Writing ForgeFIRM to slot $TARGET (/dev/mmcblk2p$TARGET):"
umount "/factory/img$TARGET" 2>/dev/null
fwup -a -d "/dev/mmcblk2p$TARGET" -i "$FW_FILE" -t "$TASK" -p "$KEYFILE" \
  || { rm -f "$KEYFILE"; die "fwup apply failed - slot $TARGET is now undefined, factory slot $ACTIVE is untouched"; }
rm -f "$KEYFILE"

# --- post-write verify --------------------------------------------------------
MP="/factory/img$TARGET"
mkdir -p "$MP"
mount -o ro "/dev/mmcblk2p$TARGET" "$MP" || die "new rootfs does not mount"
NEWVER=$(cat "$MP/etc/forgefirm-version" 2>/dev/null)
[ -n "$NEWVER" ] || { umount "$MP"; die "new rootfs has no ForgeFIRM version stamp"; }
[ -f "$MP/boot/zImage" ] || { umount "$MP"; die "new rootfs has no kernel"; }
umount "$MP"
echo -e "${ASTERISK}Slot $TARGET now holds ForgeFIRM $NEWVER"

# --- ffboot for the factory side ----------------------------------------------
curl -fL "$FFBOOT_URL" --output /data/ffboot || die "ffboot download failed"
chmod +x /data/ffboot

# --- flip the boot selection --------------------------------------------------
echo -e "${ASTERISK}Setting boot to /dev/mmcblk2p$TARGET"
set_env 1 0 "$TARGET" "/dev/mmcblk2p$TARGET" \
  || die "environment write did not verify - boot selection unchanged; run /data/ffboot -e$TARGET manually"

echo
echo -e "${BRIGHT}Installation complete.${RESET}"
echo -e "To return to factory firmware later: ${BRIGHT}/data/ffboot -e${RESET} (from ForgeFIRM: ${BRIGHT}ffboot -e${RESET})"
echo
read -n1 -p "Press any key to reboot into OpenGlow/ForgeFIRM..." continue
echo
reboot
exit 0
