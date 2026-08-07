require recipes-glowforge/images/glowforge-image.bb

DESCRIPTION = "OpenGlow/ForgeFIRM image for Glowforge"

# ForgeFIRM cuts the cloud dependency: drop the Glowforge cloud client
# (gfui-client connects to Glowforge's servers). Removing it here (override
# only; the shared glowforge-image base is untouched) also sidesteps its
# do_package failure. Its slot is filled locally by forgectrl (camera MJPEG
# service; the grblHAL controller recipe is tracked in kas/README.md
# backlog #5).
IMAGE_INSTALL:remove = "gfui-client"

# grblhal-glowforge: the grblHAL motion controller (Grbl over TCP:23).
# forgectrl: the ForgeFIRM control daemon (camera MJPEG service on :8080).
# gfhome: one-shot Glowforge web-service homing, invoked by the controller
# for $H when homing_mode = gfcloud (/data/forgefirm.conf).
# v4l-utils provides media-ctl / v4l2-ctl for the imx-media pipeline (also a
# forgectrl runtime dependency, kept explicit here for bring-up use).
IMAGE_INSTALL:append = " grblhal-glowforge forgectrl gfhome v4l-utils"
