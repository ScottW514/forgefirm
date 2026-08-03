DESCRIPTION = "System Control Daemon for ForgeFIRM powered Glowforge"
HOMEPAGE = "https://github.com/ScottW514/forgectrl"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "\
  file://CMakeLists.txt \
  file://main.c \
  file://cam.c \
  file://cam.h \
  file://debayer.c \
  file://debayer.h \
  file://forgectrl.init \
"

S = "${WORKDIR}"

inherit cmake update-rc.d

DEPENDS += "ulfius jpeg"
# media-ctl / v4l2-ctl configure the imx-media pipeline at runtime
RDEPENDS:${PN} = "v4l-utils"

INITSCRIPT_NAME = "forgectrl"
INITSCRIPT_PARAMS = "defaults 90"

do_install:append() {
    install -d ${D}${sysconfdir}/init.d
    install -m 0755 ${WORKDIR}/forgectrl.init ${D}${sysconfdir}/init.d/forgectrl
}
