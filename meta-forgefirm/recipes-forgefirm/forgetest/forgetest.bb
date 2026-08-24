SUMMARY = "ForgeFIRM release acceptance tool (dev image)"
DESCRIPTION = "Runs the release acceptance catalog against the machine from a \
self-contained web page (HTTP :8090), keeps the append-only result log under \
/data/forgetest, exports the release artifact the release gate reads, and \
carries the bench diagnostics page. Installed only on the dev image."
HOMEPAGE = "https://github.com/ScottW514/forgefirm"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# The tool's canonical home is forgetest/ in this repo; the bench scripts
# it drives live in scripts/bench/. Both are packaged from the same tree
# that builds the images, so the catalog and the gate agree by construction.
FILESEXTRAPATHS:prepend := "${THISDIR}/../../../:"

SRC_URI = " \
    file://forgetest/ \
    file://scripts/bench/ \
"

S = "${WORKDIR}"

inherit python3-dir update-rc.d forgefirm-manifest

# Non-git sources: fingerprint the package directory (dev-only component;
# it identifies the campaign, never a test fingerprint).
FORGEFIRM_MANIFEST_SRC = "${WORKDIR}/forgetest/forgetest"

RDEPENDS:${PN} = "python3 forgectrl"

INITSCRIPT_NAME = "forgetest"
INITSCRIPT_PARAMS = "start 95 2 3 4 5 . stop 70 0 1 6 ."

do_install() {
    # the package (sources only; python compiles on first import)
    for f in $(cd ${WORKDIR}/forgetest/forgetest && find . -name '*.py' -type f); do
        install -Dm 0644 ${WORKDIR}/forgetest/forgetest/$f \
            ${D}${PYTHON_SITEPACKAGES_DIR}/forgetest/$f
    done
    # the page's sources (ui/), gzipped: page.py inflates them once at
    # first request, and bytes here are bytes on the ext4 rootfs
    for f in $(cd ${WORKDIR}/forgetest/forgetest/ui && find . -type f); do
        install -d ${D}${PYTHON_SITEPACKAGES_DIR}/forgetest/ui/$(dirname $f)
        gzip -9 -n -c ${WORKDIR}/forgetest/forgetest/ui/$f \
            > ${D}${PYTHON_SITEPACKAGES_DIR}/forgetest/ui/$f.gz
        chmod 0644 ${D}${PYTHON_SITEPACKAGES_DIR}/forgetest/ui/$f.gz
    done
    # the bench scripts the #bench tab drives
    install -d ${D}${datadir}/forgetest/bench
    for f in ${WORKDIR}/scripts/bench/*.py; do
        install -m 0755 $f ${D}${datadir}/forgetest/bench/
    done
    install -Dm 0755 ${WORKDIR}/forgetest/forgetest.init ${D}${sysconfdir}/init.d/forgetest
}

FILES:${PN} += "${PYTHON_SITEPACKAGES_DIR}/forgetest ${datadir}/forgetest"
