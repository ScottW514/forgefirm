require forgefirm-image.bb

DESCRIPTION = "OpenGlow/ForgeFIRM development image for Glowforge"

# Strict superset of forgefirm-image: everything the main image ships, plus
# debug tooling.
IMAGE_INSTALL += " \
  forgectrl \
"

IMAGE_FEATURES += " \
  tools-debug \
"

# Dev images boot from SD, never from a 200 MiB eMMC slot: lift the slot
# ceiling and give the filesystem generous working space instead.
IMAGE_ROOTFS_MAXSIZE = ""
IMAGE_ROOTFS_EXTRA_SPACE = "262144"

# Dev builds identify by build timestamp (matches the artifact name),
# tagged so a bench machine is never mistaken for a release.
FORGEFIRM_VERSION_STRING = "${DATETIME} (dev)"
