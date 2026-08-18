# grblHAL-glowforge pin. Bump deliberately after pushing grblHAL-glowforge
# changes; keep only SRCREV and PV here - the image manifest leaves
# *-pin.inc out of the layer content hash because the component entry
# already identifies the pinned source (forgefirm-image-manifest.bbclass).
SRCREV = "2bca017854291f4084ca2bdf6f1ffaed88ff6d4f"
PV = "0.1.0"
