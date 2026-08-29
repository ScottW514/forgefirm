# forgectrl pin. Bump deliberately after pushing forgectrl changes; keep
# only SRCREV and PV here - the image manifest leaves *-pin.inc out of the
# layer content hash because the component entry already identifies the
# pinned source (forgefirm-image-manifest.bbclass).
SRCREV = "f9b48934b32278140510401bd066dac1e1437b7e"
PV = "0.1.0"
