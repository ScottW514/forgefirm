DESCRIPTION = "C library for web frameworks"
HOMEPAGE = "https://github.com/babelouest/ulfius"

LICENSE = "LGPL-2.1"
LIC_FILES_CHKSUM = "file://LICENSE;md5=40d2542b8c43a3ec2b7f5da31a697b88"

SRC_URI = "git://github.com/babelouest/ulfius"
SRCREV = "${AUTOREV}"

S = "${WORKDIR}/git"

inherit cmake pkgconfig

# For some reason, this package wants to install headers from other packages
# do_install_append() {
#   rm -f ${D}${includedir}/orcania.h
#   rm -f ${D}${includedir}/orcania-cfg.h
#   rm -f ${D}${includedir}/yder.h
#   rm -f ${D}${includedir}/yder-cfg.h
# }

DEPENDS = "gnutls jansson libmicrohttpd"
RDEPENDS_${PN} = "gnutls jansson libmicrohttpd"

EXTRA_OECMAKE += "-DWITH_JOURNALD=off"
