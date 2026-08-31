# forgectrl serves plain HTTP on the LAN: no TLS in the HTTP library, so
# the rootfs carries no GnuTLS stack for it.
PACKAGECONFIG:remove = "https"
