# forgectrl pin. Bump deliberately after pushing forgectrl changes; keep
# only SRCREV and PV here - the image manifest leaves *-pin.inc out of the
# layer content hash because the component entry already identifies the
# pinned source (forgefirm-image-manifest.bbclass).
SRCREV = "d97cb35a270d46ef1348abb001abb64c2a275e30"
PV = "0.1.0"
