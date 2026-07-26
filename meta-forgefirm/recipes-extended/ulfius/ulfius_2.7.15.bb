DESCRIPTION = "Web Framework to build REST APIs, Webservices or any HTTP endpoint in C"
HOMEPAGE = "https://github.com/babelouest/ulfius"

LICENSE = "LGPL-2.1-or-later"
LIC_FILES_CHKSUM = "file://LICENSE;md5=40d2542b8c43a3ec2b7f5da31a697b88"

# Pinned to the v2.7.15 release tag, together with orcania v2.3.3 and
# yder v1.4.20 (its release-mate dependency versions). AUTOREV against master
# was unbuildable: master's CMake requires orcania/yder versions that have no
# release tags, and the git:// fetch never brought in the bundled-subproject
# fallback (audit M10).
SRC_URI = "git://github.com/babelouest/ulfius;protocol=https;branch=master"
SRCREV = "a0603447d3ed63c0880db396b9c395fb4bf6b559"

S = "${WORKDIR}/git"

inherit cmake pkgconfig

# curl backs the default-ON WITH_CURL client-request API (find_package REQUIRED).
DEPENDS = "gnutls jansson libmicrohttpd curl orcania yder"

# No systemd journald on the forgefirm image.
EXTRA_OECMAKE += "-DWITH_JOURNALD=off"

# ulfius builds itself with -Werror -Wconversion; under Yocto's arm32
# time64 ABI (-D_TIME_BITS=64) a long-long-to-long time conversion in
# u_websocket.c trips it. Warning stays visible, just not fatal.
CFLAGS += "-Wno-error=conversion"
