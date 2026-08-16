"""cooling.* - the cooling engine: flow verification through forgectrl's
diagnostics runner (the same check the fire gate runs), and the fan
profile returning to idle after motion."""
import time

from ..catalog import test
from .. import hw

_COOL_COVERS = [("forgectrl", "src/cool.*"), ("forgectrl", "src/diag.*"),
                ("grblhal-glowforge", "src/gfcool*"), ("kernel-module-glowforge", "src/thermal*"),
                ("kernel-module-glowforge", "src/pic*")]


@test("cooling.flow-verify", title="Coolant flow check separates flow from no-flow",
      subsystem="cooling", kind="auto", est_min=4,
      covers=_COOL_COVERS, requires=["kernel.latch-locked-idle"],
      steps=["Coolant loop normal (pump on); the machine idle. The controller is suspended by "
             "forgectrl for the duration (about 3 minutes)."],
      description="forgectrl's flow-verify diagnostic: one heater window with the pump on and "
                  "one with it commanded off, judged against the configured threshold. PASS = "
                  "the threshold separates the two readings with the margins forgectrl reports; "
                  "a thin margin is recorded as a warning.")
def flow_verify(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence
    st, body = fc.get("/diag/status")
    ctx.check(st == 200 and isinstance(body, dict), "GET /diag/status -> %s", st)
    ctx.check(not body.get("running"), "a diagnostic is already running (%s)", body.get("tool"))
    st, body = fc.post("/diag/flow-verify")
    ctx.log("POST /diag/flow-verify -> %s %s", st, body if isinstance(body, dict) else "")
    ctx.check(st == 202 and isinstance(body, dict) and body.get("started") is True,
              "could not start flow-verify (%s %s)", st, body)
    last_phase = None
    result = None
    t0 = time.time()
    try:
        while time.time() - t0 < 900:
            ctx.checkpoint()
            st, d = fc.get("/diag/status")
            if st == 200 and isinstance(d, dict):
                if d.get("phase") != last_phase:
                    last_phase = d.get("phase")
                    ctx.log("phase: %s (down %.1f C, up %.1f C)", last_phase, d.get("down_c", 0), d.get("up_c", 0))
                if not d.get("running") and d.get("result") is not None:
                    result = d.get("result")
                    for line in d.get("log", [])[-12:]:
                        ctx.log("  diag: %s", line)
                    break
            time.sleep(2)
    except BaseException:
        fc.post("/diag/abort")
        raise
    ctx.check(result is not None, "flow-verify did not finish within 15 minutes")
    ev["result"] = result
    ctx.check("error" not in result, "flow-verify error: %s", result.get("error"))
    ctx.log("verdict: pass=%s threshold=%s flow_rise=%s noflow_rise=%s margins %s/%s thin=%s",
            result.get("pass"), result.get("threshold"), result.get("flow_rise"),
            result.get("noflow_rise"), result.get("margin_flow"), result.get("margin_noflow"),
            result.get("thin_margin"))
    ctx.check(result.get("pass") is True, "the threshold does not separate flow from no-flow: %s", result)
    if result.get("thin_margin"):
        ctx.log("WARNING: thin margin - run flow-calibrate")
    ctx.check(fc.wait_idle(120, abort=ctx.aborted), "machine did not return to idle after the diagnostic")


@test("cooling.fans-quiet-after-motion", title="Fan profile returns to idle after motion and after M8/M9",
      subsystem="cooling", kind="auto", est_min=2,
      covers=_COOL_COVERS + [("forgectrl", "src/super.c")], requires=["motion.pacing"],
      steps=["Bed clear; the head needs 20 mm of free +X travel."],
      description="A dry jog and an M8/M9 cycle must not leave the run fan profile on: within "
                  "the cooldown the exhaust/intake tachs return to the idle level seen before.")
def fans_quiet(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence

    def fans():
        s = fc.status()
        return dict(s.get("fans") or {})

    before = fans()
    ev["before"] = before
    ctx.log("fans before: %s", before)
    with ctx.grbl() as g:
        st = g.status_report()
        ctx.check(st["state"].startswith("Idle"), "controller is %s", st["state"])
        g.command("G91")
        g.command("$J=G91X20F2400")
        t0 = time.time()
        while time.time() - t0 < 30 and not g.status_report()["state"].startswith("Idle"):
            ctx.sleep(0.2)
        g.command("$J=G91X-20F2400")
        while time.time() - t0 < 60 and not g.status_report()["state"].startswith("Idle"):
            ctx.sleep(0.2)
        g.command("M8")
        ctx.sleep(3)
        during = fans()
        ev["during_m8"] = during
        ctx.log("fans during M8: %s", during)
        g.command("M9")
        g.command("G90")
    # cooldown: forgectrl's engine takes cool_cooldown_s (default tens of seconds)
    settle = None
    t0 = time.time()
    while time.time() - t0 < 240:
        ctx.sleep(5)
        now = fans()
        close = all(abs(now.get(k, 0) - before.get(k, 0)) <= max(150, 0.15 * max(before.get(k, 0), 1))
                    for k in ("exhaust", "intake_1", "intake_2"))
        if close:
            settle = time.time() - t0
            break
    ev["after"] = fans()
    ev["settle_s"] = round(settle, 1) if settle is not None else None
    ctx.log("fans after: %s (settled in %s s)", ev["after"], ev["settle_s"])
    ctx.check(settle is not None, "fans did not return to the idle profile within 240 s: %s", ev["after"])
