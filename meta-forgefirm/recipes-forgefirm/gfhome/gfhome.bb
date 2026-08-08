DESCRIPTION = "One-shot Glowforge web-service homing for ForgeFIRM"
HOMEPAGE = "https://github.com/ScottW514/forgefirm"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "0.1.0"

SRC_URI = " \
    file://gfhome.py \
    file://gfhome.conf.sample \
"

S = "${WORKDIR}"

do_install() {
    install -Dm 0755 ${WORKDIR}/gfhome.py ${D}${sbindir}/gfhome.py
    install -Dm 0600 ${WORKDIR}/gfhome.conf.sample ${D}${sysconfdir}/gfhome.conf.sample
}

RDEPENDS:${PN} += "python3-core python3-ffmachine python3-gfhardware python3-gfutilities"
