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
# gfcloud: full Glowforge web-service controller daemon (the factory cloud
# experience), started when controller_mode = cloud - mutually exclusive with
# grblHAL. Pulls python3-ffmachine (shared web-service machine glue).
# v4l-utils provides media-ctl / v4l2-ctl for the imx-media pipeline (also a
# forgectrl runtime dependency, kept explicit here for bring-up use).
# fwup: applies signed .fw archives (ForgeFIRM upgrades + factory restore)
# to the inactive rootfs slot.
# ffboot: boot-slot inventory and switching (also ships fw_env.config).
# slotmigrate: boot-time reclaim of the legacy p4 layout (grows /data).
# forgefirm-logrotate: size-capped rotation of the /data logs (boot +
# hourly; a full /data breaks settings, updates, and controller writes).
IMAGE_INSTALL:append = " grblhal-glowforge forgectrl gfhome gfcloud v4l-utils fwup ffboot slotmigrate forgefirm-logrotate"

# NXP's firmware EULA covers the i.MX VPU/EPDC blobs the BSP installs, so the
# image ships the license text with them (/usr/share/licenses/firmware-imx).
# The SDMA firmware brings its own -license package through linux-firmware.
IMAGE_INSTALL:append = " firmware-imx-lic"

# The release rootfs must fit a 200 MiB factory eMMC slot (409600 blocks).
# Sizing: content + 40 MiB working space, hard-capped at the slot size —
# the build fails rather than emit an unflashable image. The raw ext4 is
# deployed alongside the wic; scripts/mkfw.sh packs it into the signed
# .fw release artifact.
IMAGE_FSTYPES:append = " ext4"
IMAGE_OVERHEAD_FACTOR = "1.0"
IMAGE_ROOTFS_EXTRA_SPACE = "40960"
IMAGE_ROOTFS_MAXSIZE = "204800"

# Version stamp: /etc/forgefirm-version (machine-readable), echoed on the
# serial-console login prompt (/etc/issue) and at SSH login (motd).
# Release images carry the release version; the dev image overrides the
# string with the build timestamp (the same DATETIME as the artifact
# name) plus a dev tag.
FORGEFIRM_RELEASE ?= "0.1.0"
FORGEFIRM_VERSION_STRING ?= "v${FORGEFIRM_RELEASE}"

write_forgefirm_version() {
    echo "${FORGEFIRM_VERSION_STRING}" > ${IMAGE_ROOTFS}${sysconfdir}/forgefirm-version
    echo "ForgeFIRM ${FORGEFIRM_VERSION_STRING}" >> ${IMAGE_ROOTFS}${sysconfdir}/issue
    echo "" >> ${IMAGE_ROOTFS}${sysconfdir}/issue
    echo "ForgeFIRM ${FORGEFIRM_VERSION_STRING}" > ${IMAGE_ROOTFS}${sysconfdir}/motd
}
write_forgefirm_version[vardepsexclude] += "DATETIME"
ROOTFS_POSTPROCESS_COMMAND += "write_forgefirm_version;"
