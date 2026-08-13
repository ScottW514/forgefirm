# Shared fetch for the ForgeFIRM web-service apps (gfhome, python3-ffmachine,
# gfcloud). Their sources live in the forgefirm-app/ directory of the
# python3-gfhardware repository.
HOMEPAGE = "https://github.com/ScottW514/python3-gfhardware"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=62f8bb455fcc4bf177ecab380f71cd5d"

SRC_URI = "git://github.com/ScottW514/python3-gfhardware.git;protocol=https;branch=master"
# Pinned; bump deliberately (AUTOREV is not reproducible).
SRCREV = "7a4973bc9add9cc6f356335669b282fcd7bf7aeb"

# Bump PV with every SRCREV move: the hash-derived package version is not
# monotonic on its own and buildhistory QA fails the build when it sorts
# backwards.
PV = "0.1.1+git"

S = "${WORKDIR}/git"
