SUMMARY = "Log rotation for the ForgeFIRM logs on /data"
DESCRIPTION = "Size-capped rotation for the daemon and controller logs \
on the persistent /data partition: a full /data breaks settings, update \
staging, and the controllers' own writes. Rotation runs at every boot \
and hourly while the machine is up."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://forgefirm.logrotate \
    file://forgefirm-logrotate.init \
"

S = "${WORKDIR}"

inherit update-rc.d

INITSCRIPT_NAME = "forgefirm-logrotate"
INITSCRIPT_PARAMS = "defaults 40"

RDEPENDS:${PN} = "logrotate"

do_install() {
    install -Dm 0644 ${WORKDIR}/forgefirm.logrotate ${D}${sysconfdir}/logrotate.d/forgefirm
    install -Dm 0755 ${WORKDIR}/forgefirm-logrotate.init ${D}${sysconfdir}/init.d/forgefirm-logrotate
}
