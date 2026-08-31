# forgectrl pin. Bump deliberately after pushing forgectrl changes; keep
# only SRCREV and PV here - the image manifest leaves *-pin.inc out of the
# layer content hash because the component entry already identifies the
# pinned source (forgefirm-image-manifest.bbclass).
SRCREV = "c930b415f6bfa7042f20274c6160c11f5b87b0a9"
PV = "0.1.0"
