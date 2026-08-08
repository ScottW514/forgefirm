DESCRIPTION = "Shared ForgeFIRM web-service hardware-machine glue (gfhome + gfcloud)"
HOMEPAGE = "https://github.com/ScottW514/forgefirm"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "0.1.0"

SRC_URI = "file://ffmachine.py"

S = "${WORKDIR}"

inherit python3-dir

do_install() {
    install -Dm 0644 ${WORKDIR}/ffmachine.py ${D}${PYTHON_SITEPACKAGES_DIR}/ffmachine.py
}

FILES:${PN} += "${PYTHON_SITEPACKAGES_DIR}/ffmachine.py"

RDEPENDS:${PN} += "python3-core python3-gfhardware python3-gfutilities python3-requests"
