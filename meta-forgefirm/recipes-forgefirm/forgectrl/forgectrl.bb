DESCRIPTION = "System Control Daemon for ForgeFIRM powered Glowforge"
HOMEPAGE = "https://github.com/ScottW514/forgectrl"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "\
  file://CMakeLists.txt \
  file://hello.c \
"

S = "${WORKDIR}"

inherit cmake

DEPENDS += "libconfig ulfius"
RDEPENDS_${PN} = "libconfig ulfius"

EXTRA_OECMAKE = ""
