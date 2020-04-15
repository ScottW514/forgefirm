require recipes-glowforge/images/glowforge-image.bb

DESCRIPTION = "OpenGlow/ForgeFIRM development image for Glowforge"

IMAGE_INSTALL += " \
  forgectrl \
"

IMAGE_INSTALL_remove = " \
  gfui-client \
"

IMAGE_FEATURES += " \
  tools-debug \
"
