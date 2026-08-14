#!/bin/bash
# (C) Copyright 2020-2026
# Scott Wiederhold, s.e.wiederhold@gmail.com
# https://community.openglow.org
# SPDX-License-Identifier:    MIT
#
# ForgeFIRM release pipeline (runs on the Yocto build host).
#
#   release.sh <version> [--publish]   full release: gates, build, pack,
#                                      sign, checksums, stage, publish cmd
#   release.sh --dev                   build + pack a dev-signed .fw for
#                                      the GUI upload path; no staging
#
# Environment:
#   FWUP                 host fwup for packing (default: fwup in PATH)
#   FWUP_COMPAT          factory-era fwup 0.14.2 binary; when set, the
#                        packed archive is verified with it (raw-format
#                        key), replicating the factory-compat guarantee
#   FORGEFIRM_SIGNING_KEY  private key for release mode (REQUIRED - no
#                        default, so key choice is always deliberate)
#   FORGEFIRM_DEV_KEY    private key for --dev mode (REQUIRED for --dev)
#   RELEASE_STAGING_DIR  where release assets are staged
#                        (default: <repo>/release-staging)
#
# Version contract: <version> == FORGEFIRM_RELEASE in forgefirm-image.bb
# == /etc/forgefirm-version ("v<version>") in the built rootfs == .fw
# meta-version ("v<version>") == release tag ("v<version>").

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$REPO/build/tmp/deploy/images/glowforge"
IMAGE_BB="$REPO/meta-forgefirm/recipes-forgefirm/images/forgefirm-image.bb"
INSTALLER="$REPO/scripts/install-forgefirm.sh"
WARN_BYTES=$((170 * 1024 * 1024))
FAIL_BYTES=$((195 * 1024 * 1024))

die () { echo "RELEASE FAILED: $*" >&2; exit 1; }
warn () { echo "WARNING: $*" >&2; }

VERSION=""
MODE=release
PUBLISH=0
for ARG in "$@"; do
  case "$ARG" in
    --dev) MODE=dev ;;
    --publish) PUBLISH=1 ;;
    -*) die "unknown option $ARG" ;;
    *) VERSION="$ARG" ;;
  esac
done

FWUP="${FWUP:-fwup}"
command -v "$FWUP" >/dev/null || die "fwup not found (set FWUP=)"
command -v kas >/dev/null || die "kas not found on PATH"

build_images () {
  echo "== building images =="
  ( cd "$REPO" && kas shell kas/forgefirm-glowforge.yml \
      -c 'bitbake forgefirm-image forgefirm-image-dev' ) \
    || die "bitbake failed"
}

resolve_ext4 () {
  EXT4=$(readlink -f "$DEPLOY/forgefirm-image-glowforge.rootfs.ext4")
  [ -s "$EXT4" ] || die "release ext4 not found in $DEPLOY"
}

check_size () {
  SZ=$(stat -c%s "$EXT4")
  [ "$SZ" -lt "$FAIL_BYTES" ] \
    || die "rootfs is $SZ bytes - too close to the 200 MiB slot"
  if [ "$SZ" -ge "$WARN_BYTES" ]; then
    warn "rootfs is $((SZ / 1048576)) MiB - $(( (FAIL_BYTES - SZ) / 1048576 )) MiB of margin left before the release gate"
  fi
}

# --- dev mode -----------------------------------------------------------------
if [ "$MODE" = "dev" ]; then
  KEY="${FORGEFIRM_DEV_KEY:?set FORGEFIRM_DEV_KEY to the dev signing key}"
  build_images
  resolve_ext4
  check_size
  REL=$(sed -n 's/^FORGEFIRM_RELEASE ?= "\(.*\)"/\1/p' "$IMAGE_BB")
  DEVVER="v${REL}-dev-$(date +%Y%m%d%H%M%S)"
  OUT="$DEPLOY/forgefirm-dev.fw"
  "$REPO/scripts/mkfw.sh" "$EXT4" "$DEVVER" "$OUT" "$KEY"
  echo "== dev archive ready: $OUT ($DEVVER) =="
  exit 0
fi

# --- release mode -------------------------------------------------------------
[ -n "$VERSION" ] || die "usage: release.sh <version> [--publish] | release.sh --dev"
KEY="${FORGEFIRM_SIGNING_KEY:?set FORGEFIRM_SIGNING_KEY to the release signing key}"
PUB="${KEY%.priv}.pub"
[ -f "$KEY" ] || die "signing key '$KEY' not found"
[ -f "$PUB" ] || die "public key '$PUB' not found"

echo "== gates =="

# Repo state (informational when the build tree is not a git checkout).
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  [ -z "$(git -C "$REPO" status --porcelain)" ] \
    || die "working tree is dirty - release from a clean tree"
  if ! git -C "$REPO" diff --quiet "@{upstream}" 2>/dev/null; then
    warn "HEAD differs from upstream - push before publishing"
  fi
else
  warn "$REPO is not a git checkout - repo-state gates skipped (rsynced build tree)"
fi

# Version single-source check.
BB_REL=$(sed -n 's/^FORGEFIRM_RELEASE ?= "\(.*\)"/\1/p' "$IMAGE_BB")
[ "$BB_REL" = "$VERSION" ] \
  || die "FORGEFIRM_RELEASE in forgefirm-image.bb is '$BB_REL', not '$VERSION'"

# The installer must embed the pubkey matching the signing key, or every
# install will refuse the published archive.
INST_HEX=$(sed -n "s/^PUBKEY='\(.*\)'$/\1/p" "$INSTALLER" | tr -d '\\x')
KEY_HEX=$(base64 -d "$PUB" | xxd -p | tr -d '\n')
[ -n "$INST_HEX" ] || die "cannot extract the embedded pubkey from the installer"
[ "$INST_HEX" = "$KEY_HEX" ] \
  || die "installer's embedded pubkey does not match the signing key - update install-forgefirm.sh"

build_images
resolve_ext4
check_size

# Rootfs version stamp.
STAMP=$(debugfs -R "cat /etc/forgefirm-version" "$EXT4" 2>/dev/null)
[ "$STAMP" = "v$VERSION" ] \
  || die "rootfs stamp is '$STAMP', expected 'v$VERSION'"

# Back-door gate: the release image must not ship a passwordless root. A
# debug-tweaks image sets root's password field empty (root::...); a
# hardened image leaves it locked (root:*: / root:!:) or hashed. Read the
# actual built shadow file - this catches the flag however it slipped in
# (recipe, local.conf, an inherited class).
ROOT_PW=$(debugfs -R "cat /etc/shadow" "$EXT4" 2>/dev/null \
          | awk -F: '$1=="root"{print $2; exit}')
[ -n "$ROOT_PW" ] \
  || die "release rootfs has a passwordless root (debug-tweaks leaked into forgefirm-image?)"
echo "root login gate OK (root password field is not empty)"

# Config-level guard: debug-tweaks must not sit in the shared kas config,
# where it would apply to every target including the release image.
if ( cd "$REPO" && kas dump kas/forgefirm-glowforge.yml 2>/dev/null ) \
     | grep -q 'debug-tweaks'; then
  die "debug-tweaks appears in the resolved kas config - it must live only in forgefirm-image-dev.bb"
fi
echo "kas config gate OK (no debug-tweaks in the shared config)"

echo "== pack + sign =="
STAGE="${RELEASE_STAGING_DIR:-$REPO/release-staging}/v$VERSION"
mkdir -p "$STAGE"
"$REPO/scripts/mkfw.sh" "$EXT4" "v$VERSION" "$STAGE/forgefirm.fw" "$KEY"

# Factory-era compat verification (fwup 0.14.2 wants raw 32-byte keys).
if [ -n "${FWUP_COMPAT:-}" ]; then
  RAW=$(mktemp)
  base64 -d "$PUB" > "$RAW"
  "$FWUP_COMPAT" -V -i "$STAGE/forgefirm.fw" -p "$RAW" \
    || { rm -f "$RAW"; die "factory-era fwup rejects the archive"; }
  rm -f "$RAW"
  echo "factory-era fwup verification OK"
else
  warn "FWUP_COMPAT not set - factory-era verification skipped"
fi

echo "== stage assets =="
cp -L "$DEPLOY/forgefirm-image-glowforge.rootfs.wic.gz" "$STAGE/forgefirm-image-glowforge.rootfs.wic.gz"
( cd "$STAGE" && sha256sum forgefirm.fw forgefirm-image-glowforge.rootfs.wic.gz > sha256sums.txt )
ls -la "$STAGE"

cat <<EOF

== release v$VERSION staged ==

Pre-publish checklist (kas/README.md "Push & release order" step 4):
  - meta-openglow pushed; kas config flipped to the pinned-remote block
  - externalsrc bbappend dropped; kas lock refreshed
  - self-containment proven from a fresh clone

Publish (from a directory with an authenticated gh):
  cd "$STAGE"
  gh release create "v$VERSION" --repo ScottW514/forgefirm \\
    --title "ForgeFIRM v$VERSION" --generate-notes \\
    forgefirm.fw sha256sums.txt forgefirm-image-glowforge.rootfs.wic.gz
EOF

if [ "$PUBLISH" = "1" ]; then
  command -v gh >/dev/null || die "--publish requested but gh is not on PATH"
  ( cd "$STAGE" && gh release create "v$VERSION" --repo ScottW514/forgefirm \
      --title "ForgeFIRM v$VERSION" --generate-notes \
      forgefirm.fw sha256sums.txt forgefirm-image-glowforge.rootfs.wic.gz ) \
    || die "gh release create failed"
  echo "== published v$VERSION =="
fi
