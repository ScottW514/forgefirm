require forgefirm-image.bb

DESCRIPTION = "OpenGlow/ForgeFIRM development image for Glowforge"

# Strict superset of forgefirm-image: everything the main image ships, plus
# the forgectrl placeholder and debug tooling.
IMAGE_INSTALL += " \
  forgectrl \
"

IMAGE_FEATURES += " \
  tools-debug \
"
