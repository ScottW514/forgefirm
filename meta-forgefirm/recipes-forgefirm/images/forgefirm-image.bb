require recipes-glowforge/images/glowforge-image.bb

DESCRIPTION = "OpenGlow/ForgeFIRM image for Glowforge"

# ForgeFIRM cuts the cloud dependency: drop the Glowforge cloud client
# (gfui-client connects to Glowforge's servers) — exactly what ForgeFIRM
# replaces with a local grblHAL controller (forgectrl, currently a placeholder;
# see kas/README.md backlog #5). Removing it here (override only; the shared
# glowforge-image base is untouched) also sidesteps its do_package failure.
IMAGE_INSTALL:remove = "gfui-client"

# Camera bring-up tooling: v4l-utils provides v4l2-ctl (the media-ctl binary is
# already pulled in) for configuring the imx-media pipeline and grabbing frames
# while the gfhardware capture path is ported off the factory NXP V4L2 model.
IMAGE_INSTALL:append = " v4l-utils"
