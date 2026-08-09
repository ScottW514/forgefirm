# Shared fetch for the ForgeFIRM web-service apps (gfhome, python3-ffmachine,
# gfcloud). Their sources live in the forgefirm-app/ directory of the
# python3-gfhardware repository.
HOMEPAGE = "https://github.com/ScottW514/python3-gfhardware"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=62f8bb455fcc4bf177ecab380f71cd5d"

SRC_URI = "git://github.com/ScottW514/python3-gfhardware.git;protocol=https;branch=cloud-action-surface"
# Pinned; bump deliberately (AUTOREV is not reproducible).
SRCREV = "7ea88246fabe1142a1bb728dffce8799a71fa846"

PV = "0.1.0+git"

S = "${WORKDIR}/git"
