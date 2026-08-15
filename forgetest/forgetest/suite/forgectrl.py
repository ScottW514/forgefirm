"""forgectrl.* - the machine-services daemon's API, access control, and panel."""
import json
import socket

from ..catalog import test
from .. import hw

_COVERS_AUTH = [("forgectrl", "src/auth.*"), ("forgectrl", "src/main.c")]


def lan_ip():
    """The board's own non-loopback IPv4 (the address a LAN client would
    use), or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 9))
        ip = s.getsockname()[0]
    except OSError:
        ip = None
    finally:
        s.close()
    if ip and not ip.startswith("127."):
        return ip
    return None


@test("forgectrl.auth", title="API access control", subsystem="forgectrl", kind="auto", est_min=1,
      covers=_COVERS_AUTH,
      description="Every state-changing endpoint refuses an unauthenticated write; a non-literal "
                  "Host, a non-literal Origin and a cross-site Sec-Fetch-Site are refused; the "
                  "cooling report channel refuses a non-loopback peer; the fuse view is token-gated; "
                  "the flash and factory-restore chain is refused unauthenticated.")
def auth(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence

    st, body = fc.get("/status")
    ctx.log("GET /status -> %s", st)
    ctx.check(st == 200, "GET /status -> %s", st)

    # unauthenticated writes: every one must be refused before it acts
    for path, params in (("/controller/stop", None), ("/controller/start", None),
                         ("/mode", {"controller": "grbl"}), ("/settings", {"ui_units": "mm"}),
                         ("/diag/flow-verify", None), ("/diag/abort", None),
                         ("/update/apply", None), ("/boot", {"slot": "a"}),
                         ("/system/reboot", None), ("/restore/factory", None)):
        st, body = fc.post(path, params=params, auth=False)
        ctx.log("POST %s (no token) -> %s %s", path, st, body if isinstance(body, dict) else "")
        ev["noauth " + path] = st
        ctx.check(st == 403, "POST %s without a token -> %s, expected 403", path, st)
        ctx.check(isinstance(body, dict) and body.get("error") == "authentication required",
                  "POST %s without a token: unexpected body %r", path, body)

    # the upload sink refuses during body parse; only the status is asserted
    st, body = fc.post("/update/upload", data=b"not a firmware archive", auth=False,
                       headers={"Content-Type": "application/octet-stream"})
    ev["noauth /update/upload"] = st
    ctx.log("POST /update/upload (no token) -> %s", st)
    ctx.check(st in (400, 403), "POST /update/upload without a token -> %s", st)

    # origin checks (read endpoint, so only the origin layer decides)
    st, body = fc.get("/status", headers={"Host": "evil.example.net"})
    ev["host_name"] = st
    ctx.log("GET /status Host=evil.example.net -> %s", st)
    ctx.check(st == 403, "a DNS-name Host was accepted (%s)", st)
    st, body = fc.get("/status", headers={"Origin": "http://evil.example.net"})
    ev["origin_name"] = st
    ctx.log("GET /status Origin=http://evil.example.net -> %s", st)
    ctx.check(st == 403, "a DNS-name Origin was accepted (%s)", st)
    st, body = fc.get("/status", headers={"Sec-Fetch-Site": "cross-site"})
    ev["sfs_cross"] = st
    ctx.log("GET /status Sec-Fetch-Site=cross-site -> %s", st)
    ctx.check(st == 403, "a cross-site fetch was accepted (%s)", st)
    st, body = fc.get("/status", headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://127.0.0.1:8080"})
    ctx.check(st == 200, "same-origin literal Origin refused (%s)", st)

    # the token opens the fuse view; without it, refused
    st, body = fc.get("/fuse-identity", auth=False)
    ev["fuse_noauth"] = st
    ctx.check(st == 403, "GET /fuse-identity without token -> %s", st)
    st, body = fc.get("/fuse-identity")
    ev["fuse_auth"] = st
    ctx.log("GET /fuse-identity with token -> %s", st)
    ctx.check(st == 200, "GET /fuse-identity with the token -> %s", st)

    # the cooling report channel: loopback only, even with a token
    ip = lan_ip()
    ev["lan_ip"] = ip
    ctx.check(ip, "cannot determine the board's LAN address")
    port = fc.base.rsplit(":", 1)[-1]
    lan = hw.Forgectrl("http://%s:%s" % (ip, port), token=fc.token)
    st, body = lan.post("/cool/state", params={"mode": "idle", "armed": "0"})
    ev["cool_state_from_lan"] = st
    ctx.log("POST /cool/state from %s -> %s %s", ip, st, body if isinstance(body, dict) else "")
    ctx.check(st == 403 and isinstance(body, dict) and body.get("error") == "loopback only",
              "/cool/state accepted a non-loopback peer (%s %r)", st, body)


@test("forgectrl.settings-bounds", title="Settings validation and restore", subsystem="forgectrl",
      kind="auto", est_min=1,
      covers=[("forgectrl", "src/settings.*"), ("forgectrl", "src/main.c")],
      description="An over-length value and an out-of-range value are refused (400) and leave the "
                  "settings byte-identical; an in-range value is accepted (200).")
def settings_bounds(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    before = fc.settings()
    ev["keys"] = len(before)

    st, body = fc.post("/settings", data={"gf_serial": "X" * 300})
    ev["overlong"] = st
    ctx.log("POST /settings gf_serial=<300 chars> -> %s %s", st, body if isinstance(body, dict) else "")
    ctx.check(st == 400, "over-length value -> %s, expected 400", st)

    st, body = fc.post("/settings", data={"laser_disarm_s": "99999"})
    ev["out_of_range"] = st
    ctx.log("POST /settings laser_disarm_s=99999 -> %s", st)
    ctx.check(st == 400, "out-of-range value -> %s, expected 400", st)

    st, body = fc.post("/settings", data={"no_such_key_forgetest": "1"})
    ev["unknown_key"] = st
    ctx.log("POST /settings no_such_key_forgetest=1 -> %s", st)
    ctx.check(st in (400, 404), "unknown key -> %s, expected 400", st)

    after = fc.settings()
    ctx.check(json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True),
              "settings changed after refused writes")
    ctx.log("settings unchanged after the refused writes")

    # an accepted in-range write: rewrite a present key with its own value
    key = None
    for k in ("ui_units", "laser_disarm_s", "cool_flow_rise", "rail_settle_s"):
        v = before.get(k)
        if isinstance(v, str) and v != "":
            key = k
            break
    if key is None:
        key, val = "ui_units", "mm"
        ctx.log("no settable key is present; writing %s=%s (recorded in evidence)", key, val)
    else:
        val = before[key]
    st, body = fc.post("/settings", data={key: val})
    ev["accepted"] = {"key": key, "value": val, "status": st}
    ctx.log("POST /settings %s=%s -> %s", key, val, st)
    ctx.check(st == 200, "in-range write -> %s, expected 200", st)
    final = fc.settings()
    others_before = {k: v for k, v in before.items() if k != key}
    others_after = {k: v for k, v in final.items() if k != key}
    ctx.check(others_before == others_after, "other settings changed by the write")
    ctx.check(final.get(key) == val, "%s reads back %r, wrote %r", key, final.get(key), val)


@test("forgectrl.panel-serves", title="Control panel and status endpoints", subsystem="forgectrl",
      kind="auto", est_min=1,
      covers=[("forgectrl", "src/ui.*"), ("forgectrl", "src/status.*"), ("forgectrl", "src/cam.c"),
              ("forgectrl", "src/main.c")],
      description="The panel page is served, /status carries the machine telemetry the panel and "
                  "the acceptance tool read, and /cam/status answers.")
def panel_serves(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    st, body = fc.get("/", raw=True)
    ev["panel_status"] = st
    ctx.log("GET / -> %s (%d bytes)", st, len(body) if body else 0)
    ctx.check(st == 200, "GET / -> %s", st)
    text = body.decode("utf-8", "replace")
    ctx.check("<html" in text.lower() and "ForgeFIRM" in text, "the panel does not look like the panel")
    ctx.check(fc.token and fc.token in text, "the panel does not embed the bearer token")

    s = fc.status()
    for key in ("state", "switches", "coolant", "fans"):
        ctx.check(key in s, "/status lacks %r", key)
    ev["state"] = s.get("state")
    ev["switches"] = s.get("switches")
    ctx.log("/status state=%s switches=%s", s.get("state"), s.get("switches"))
    for key in ("lid", "button", "interlock_ok", "head", "hv_enable"):
        ctx.check(key in (s.get("switches") or {}), "/status switches lacks %r", key)

    st, cam = fc.get("/cam/status")
    ev["cam_status"] = st
    ctx.log("GET /cam/status -> %s %s", st, cam)
    ctx.check(st == 200 and isinstance(cam, dict) and "running" in cam, "GET /cam/status -> %s", st)
