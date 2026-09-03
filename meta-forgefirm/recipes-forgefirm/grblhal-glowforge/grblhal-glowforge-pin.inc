# grblHAL-glowforge pin. Bump deliberately after pushing grblHAL-glowforge
# changes; keep only SRCREV and PV here - the image manifest leaves
# *-pin.inc out of the layer content hash because the component entry
# already identifies the pinned source (forgefirm-image-manifest.bbclass).
SRCREV = "2f5edee5cdf4537793d7f98407fd8c7df8e1e438"
PV = "0.1.2"
