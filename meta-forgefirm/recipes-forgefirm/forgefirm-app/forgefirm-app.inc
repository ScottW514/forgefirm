# Shared fetch for the ForgeFIRM web-service apps (gfhome, python3-ffmachine,
# gfcloud). Their sources live in the forgefirm-app/ directory of the
# python3-gfhardware repository.
HOMEPAGE = "https://github.com/ScottW514/python3-gfhardware"

# These packages ship only the Python apps under forgefirm-app/, all MIT. The
# repository's LGPL component (the Bayer decoder compiled into
# gfhardware._cam) is not part of them; python3-gfhardware declares it.
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=62f8bb455fcc4bf177ecab380f71cd5d"

SRC_URI = "git://github.com/ScottW514/python3-gfhardware.git;protocol=https;branch=master"
# Pinned; bump deliberately (AUTOREV is not reproducible).
SRCREV = "a0a174d8e9a6b4b6e3abe63acc51018199df4202"

# Bump PV with every SRCREV move: the hash-derived package version is not
# monotonic on its own and buildhistory QA fails the build when it sorts
# backwards.
PV = "0.1.6+git"

S = "${WORKDIR}/git"

# One image-manifest component for the three app recipes (same repository,
# same pinned revision): the entries merge in the image manifest.
inherit forgefirm-manifest
FORGEFIRM_MANIFEST_NAME = "forgefirm-app"
