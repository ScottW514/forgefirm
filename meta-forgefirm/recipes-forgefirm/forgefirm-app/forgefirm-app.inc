# Shared fetch for the ForgeFIRM web-service apps (gfhome, python3-ffmachine,
# gfcloud). Their sources live in the forgefirm-app/ directory of the
# python3-gfhardware repository.
HOMEPAGE = "https://github.com/ScottW514/python3-gfhardware"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=62f8bb455fcc4bf177ecab380f71cd5d"

SRC_URI = "git://github.com/ScottW514/python3-gfhardware.git;protocol=https;branch=master"
# Pinned; bump deliberately (AUTOREV is not reproducible).
SRCREV = "ec8c2de4453b997af0b524d334c7130e1d31c2ad"

PV = "0.1.0+git"

S = "${WORKDIR}/git"
