DESCRIPTION = "Full Glowforge web-service controller daemon for ForgeFIRM (cloud mode)"
HOMEPAGE = "https://github.com/ScottW514/forgefirm"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "0.1.0"

SRC_URI = " \
    file://gfcloud.py \
    file://gfcloud.init \
"

S = "${WORKDIR}"

inherit update-rc.d

INITSCRIPT_NAME = "gfcloud"
INITSCRIPT_PARAMS = "defaults 92"

do_install() {
    install -Dm 0755 ${WORKDIR}/gfcloud.py ${D}${sbindir}/gfcloud.py
    install -d ${D}${sysconfdir}/init.d
    install -m 0755 ${WORKDIR}/gfcloud.init ${D}${sysconfdir}/init.d/gfcloud
}

# Shares the Glowforge web-service config with gfhome (SERVICE section,
# camera captures via forgectrl); pulls the shared machine glue.
RDEPENDS:${PN} += "python3-core python3-ffmachine python3-gfhardware python3-gfutilities"
