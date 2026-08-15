"""camera.* - the lid camera pipeline through forgectrl."""
from ..catalog import test

_CAM_COVERS = [("forgectrl", "src/cam.*"), ("forgectrl", "src/debayer.*"), ("forgectrl", "src/vpu_jpeg.*"),
               ("python3-gfhardware", "gfhardware/src/**"), ("python3-gfhardware", "gfhardware/cam*")]


@test("camera.snapshot", title="Lid camera snapshot and stream", subsystem="camera",
      kind="operator", est_min=2,
      covers=_CAM_COVERS, requires=["forgectrl.panel-serves"],
      steps=["Lid closed. You will be asked to look at the control panel's Status tab."],
      description="/cam/snapshot returns a JPEG of a plausible size (a black frame compresses "
                  "far smaller), the MJPEG stream starts and stops, and the operator confirms "
                  "the panel shows the bed.")
def snapshot(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    st, body = fc.get("/cam/status")
    ctx.check(st == 200 and isinstance(body, dict), "GET /cam/status -> %s", st)
    ev["cam_status"] = body
    ctx.log("cam status: %s", body)

    st, data = fc.get("/cam/snapshot", params={"cam": "lid", "res": "half"}, raw=True)
    ctx.log("GET /cam/snapshot?cam=lid&res=half -> %s (%d bytes)", st, len(data) if data else 0)
    ctx.check(st == 200, "snapshot -> %s %s", st, data[:120] if data else "")
    ctx.check(data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9", "snapshot is not a complete JPEG")
    ev["snapshot_bytes"] = len(data)
    ctx.check(len(data) > 20000, "snapshot is only %d bytes - a dark or empty frame?", len(data))

    st, data = fc.get("/cam/snapshot", params={"cam": "lid", "res": "full"}, raw=True)
    ctx.log("GET /cam/snapshot?cam=lid&res=full -> %s (%d bytes)", st, len(data) if data else 0)
    ctx.check(st == 200 and data[:2] == b"\xff\xd8", "full-resolution snapshot -> %s", st)
    ev["snapshot_full_bytes"] = len(data)

    # the stream: fetch a little of it and let it close
    import urllib.request
    req = urllib.request.Request(fc.base + "/cam/stream", headers={"Host": fc.host_header()})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ctype = r.headers.get("Content-Type", "")
            chunk = r.read(65536)
    except Exception as e:  # noqa: BLE001
        ctx.fail("stream did not open: %s", e)
    ev["stream_ctype"] = ctype
    ctx.log("stream: %s, first %d bytes", ctype, len(chunk))
    ctx.check("multipart" in ctype and b"\xff\xd8" in chunk, "stream is not an MJPEG multipart")
    ctx.sleep(2)
    st, body = fc.get("/cam/status")
    ev["cam_status_after"] = body
    ctx.log("cam status after: %s", body)
    ctx.confirm("Open the control panel (port 8080), Status tab: does the lid snapshot show the bed "
                "(not black, not frozen, roughly the right orientation)?")
