DESCRIPTION = "grblHAL motion controller for the Glowforge factory board"
HOMEPAGE = "https://github.com/ScottW514/grblHAL-glowforge"

LICENSE = "GPL-3.0-or-later"
LIC_FILES_CHKSUM = "file://COPYING;md5=3237e48bcef3455c7bea5c0ce16206f6"

PV = "0.1.0"

# gitsm: the grblHAL core rides as a submodule (ScottW514/core, branch
# forgefirm = upstream master + the step_us_min buffer fix pending
# upstream).
SRC_URI = "gitsm://github.com/ScottW514/grblHAL-glowforge.git;protocol=https;branch=main"
# Pinned; bump deliberately after pushing grblHAL-glowforge changes.
SRCREV = "05c3b2d84599321fa96bca43e6917e51e171793b"

SRC_URI += "file://grblhal.init"

S = "${WORKDIR}/git"

inherit cmake update-rc.d

INITSCRIPT_NAME = "grblhal"
INITSCRIPT_PARAMS = "defaults 92"

do_install:append() {
    install -d ${D}${sysconfdir}/init.d
    install -m 0755 ${WORKDIR}/grblhal.init ${D}${sysconfdir}/init.d/grblhal
}

# The controller streams into /dev/glowforge (glowforge.ko) at runtime.
RRECOMMENDS:${PN} = "kernel-module-glowforge"
