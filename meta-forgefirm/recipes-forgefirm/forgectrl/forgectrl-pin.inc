# forgectrl pin. Bump deliberately after pushing forgectrl changes; keep
# only SRCREV and PV here - the image manifest leaves *-pin.inc out of the
# layer content hash because the component entry already identifies the
# pinned source (forgefirm-image-manifest.bbclass).
SRCREV = "9d1f6f2727955fcffc8ec76b8d55105bec88bf74"
PV = "0.1.0"
