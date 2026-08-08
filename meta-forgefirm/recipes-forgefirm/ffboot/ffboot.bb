SUMMARY = "Boot-slot selection and inventory for Glowforge factory hardware"
DESCRIPTION = "Inventories the bootable partitions (ffboot -l) and switches \
the boot target by rewriting the saved U-Boot environment with read-back \
verification. Ships the fw_env.config for the factory eMMC environment \
layout."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# ffboot's canonical home is scripts/ffboot in this repo (the factory-side
# installer downloads it from there); the recipe packages that same file.
FILESEXTRAPATHS:prepend := "${THISDIR}/../../../scripts:"

SRC_URI = " \
    file://ffboot \
    file://fw_env.config \
"

S = "${WORKDIR}"

RDEPENDS:${PN} = "libubootenv-bin"

do_install() {
    install -Dm 0755 ${WORKDIR}/ffboot ${D}${sbindir}/ffboot
    install -Dm 0644 ${WORKDIR}/fw_env.config ${D}${sysconfdir}/fw_env.config
}
