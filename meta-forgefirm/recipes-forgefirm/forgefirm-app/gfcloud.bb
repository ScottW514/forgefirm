DESCRIPTION = "Full Glowforge web-service controller daemon for ForgeFIRM (cloud mode)"

require forgefirm-app.inc

inherit update-rc.d

INITSCRIPT_NAME = "gfcloud"
INITSCRIPT_PARAMS = "defaults 92"

do_install() {
    install -Dm 0755 ${S}/forgefirm-app/gfcloud.py ${D}${sbindir}/gfcloud.py
    install -d ${D}${sysconfdir}/init.d
    install -m 0755 ${S}/forgefirm-app/gfcloud.init ${D}${sysconfdir}/init.d/gfcloud
}

# Shares the Glowforge web-service config with gfhome (SERVICE section,
# camera captures via forgectrl); pulls the shared machine glue.
RDEPENDS:${PN} += "python3-core python3-ffmachine python3-gfhardware python3-gfutilities"
