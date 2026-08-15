DESCRIPTION = "System Control Daemon for ForgeFIRM powered Glowforge"
HOMEPAGE = "https://github.com/ScottW514/forgectrl"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=19ed4e3e8c28a4311c16b0b2b91357ec"

PE = "1"
PV = "0.1.0"

SRC_URI = "git://github.com/ScottW514/forgectrl.git;protocol=https;branch=main"
# Pinned; bump deliberately after pushing forgectrl changes.
SRCREV = "3edb7bd6f03a06729d528dfc84f740d88154d4ad"

S = "${WORKDIR}/git"

inherit cmake update-rc.d

DEPENDS += "ulfius jpeg"
# media-ctl / v4l2-ctl configure the imx-media pipeline at runtime;
# the update manager drives ffboot + fwup and verifies against the
# shipped keyring; release checks and downloads use curl; the WiFi
# regulatory region (wifi_country) is applied with iw reg set.
RDEPENDS:${PN} = "v4l-utils ffboot fwup forgefirm-keys curl iw"

INITSCRIPT_NAME = "forgectrl"
INITSCRIPT_PARAMS = "defaults 90"

do_install:append() {
    install -d ${D}${sysconfdir}/init.d
    install -m 0755 ${S}/init/forgectrl.init ${D}${sysconfdir}/init.d/forgectrl
}
