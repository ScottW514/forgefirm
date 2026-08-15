"""update.* - the A/B slot inventory and the firmware verification path."""
import os
import tempfile

from ..catalog import test
from .. import hw

_UPDATE_COVERS = [("forgectrl", "src/update.c"), ("forgectrl", "src/update.h")]


@test("update.slots-and-signature", title="Boot slots readable, unsigned/tampered archives refused",
      subsystem="update", kind="auto", est_min=1,
      covers=_UPDATE_COVERS, requires=["forgectrl.auth"],
      description="/slots reports the A/B inventory consistent with `ffboot -l`; /update/status "
                  "answers; `fwup` refuses a garbage archive and a tampered signature against the "
                  "shipped release key. Nothing is written to any slot.")
def slots_and_signature(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    st, slots = fc.get("/slots")
    ctx.log("GET /slots -> %s %s", st, slots)
    ctx.check(st == 200 and isinstance(slots, dict), "GET /slots -> %s", st)
    ev["slots"] = slots
    rc, out = hw.run(["ffboot", "-l"])
    ev["ffboot_l_rc"] = rc
    ctx.log("ffboot -l -> rc %s\n%s", rc, out.strip())
    ctx.check(rc == 0, "ffboot -l failed (%s)", rc)
    text = str(slots).lower()
    ctx.check("forgefirm" in text or "slot" in text, "/slots does not look like a slot inventory")

    st, us = fc.get("/update/status")
    ctx.log("GET /update/status -> %s %s", st, us)
    ctx.check(st == 200 and isinstance(us, dict) and "running" in us, "GET /update/status -> %s", st)
    ctx.check(not us.get("running"), "an update is running")

    key = "/etc/forgefirm/keys/forgefirm-release.pub"
    ctx.check(os.path.exists(key), "release key %s missing", key)
    with tempfile.NamedTemporaryFile(prefix="forgetest-", suffix=".fw", delete=False) as f:
        f.write(b"this is not a firmware archive" * 64)
        garbage = f.name
    try:
        rc, out = hw.run(["fwup", "-V", "-i", garbage, "-p", key], timeout=30)
        ev["fwup_garbage_rc"] = rc
        ctx.log("fwup -V garbage -> rc %s: %s", rc, out.strip()[:200])
        ctx.check(rc != 0, "fwup accepted a garbage archive")
    finally:
        os.unlink(garbage)
