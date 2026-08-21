# forgectrl pin. Bump deliberately after pushing forgectrl changes; keep
# only SRCREV and PV here - the image manifest leaves *-pin.inc out of the
# layer content hash because the component entry already identifies the
# pinned source (forgefirm-image-manifest.bbclass).
SRCREV = "e0b41b33ee13c29d0ff772b15a919b2b24bfa24b"
PV = "0.1.0"
