require forgefirm-image.bb

DESCRIPTION = "OpenGlow/ForgeFIRM development image for Glowforge"

# Strict superset of forgefirm-image (audit N12): everything the main image
# ships (incl. the gfui-client removal and v4l-utils), plus the forgectrl
# placeholder and debug tooling.
IMAGE_INSTALL += " \
  forgectrl \
"

IMAGE_FEATURES += " \
  tools-debug \
"
