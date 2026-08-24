require forgefirm-image.bb

DESCRIPTION = "OpenGlow/ForgeFIRM development image for Glowforge"

# Strict superset of forgefirm-image: everything the main image ships, plus
# debug tooling. forgetest is the release acceptance tool (HTTP :8090) and
# the bench diagnostics page; it belongs to the bench, never to a release
# image (docs/ACCEPTANCE.md). The gfutilities emulator fixtures are the
# canned frames its service-protocol test answers the service with.
IMAGE_INSTALL += " \
  forgectrl \
  forgetest \
  python3-gfutilities-emulator \
  htop \
"

# The release recipe removes nano from the shared base list (bench
# convenience, 8.7 MB with libmagic). A removal applies after every append,
# so the dev image re-sets the removal list to keep nano instead of adding
# it back.
IMAGE_INSTALL:remove = "gfui-client"

# debug-tweaks (passwordless root, root SSH login) belongs ONLY to the dev
# image - never the release image. It lives here, not in the shared kas
# local.conf, so the release forgefirm-image cannot inherit it.
IMAGE_FEATURES += " \
  tools-debug \
  debug-tweaks \
"

# Dev images boot from SD, never from a 200 MiB eMMC slot: lift the slot
# ceiling and give the filesystem generous working space instead.
IMAGE_ROOTFS_MAXSIZE = ""
IMAGE_ROOTFS_EXTRA_SPACE = "262144"

# Dev builds identify by build timestamp (matches the artifact name),
# tagged so a bench machine is never mistaken for a release.
FORGEFIRM_VERSION_STRING = "${DATETIME} (dev)"
