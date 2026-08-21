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


IDLE_DUTY = {"thermal/exhaust_pwm": 0, "thermal/intake_pwm": 0}   # forgectrl's idle posture
TACH_KEYS = ("exhaust", "intake_1", "intake_2")
SAMPLE_S = 5                # tach sampling period (the big exhaust fan coasts for tens of seconds)
STABLE_SAMPLES = 3          # consecutive agreeing samples that make an idle reference
IDLE_REF_TIMEOUT_S = 180    # a previous test's cooldown + spin-down
COOLDOWN_TIMEOUT_S = 240    # the engine's smoke phase + idle drop + spin-down


def _duties():
    return {k: hw.sysfs_int(k) for k in IDLE_DUTY}


def _tach_close(now, ref):
    """Every tach at or below its idle reference, within the tolerance a
    tach reading wanders by (150 rpm or 15 %). Lower is quieter, never a
    fault: the reference is an idle level, not a target."""
    return all(now.get(k, 0) - ref.get(k, 0) <= max(150, 0.15 * max(ref.get(k, 0), 1))
               for k in TACH_KEYS)


def _tach_stable(a, b):
    return all(abs(a.get(k, 0) - b.get(k, 0)) <= max(100, 0.10 * max(a.get(k, 0), 1)) for k in TACH_KEYS)


@test("cooling.fans-quiet-after-motion", title="Fan profile returns to idle after motion and after M8/M9",
      subsystem="cooling", kind="auto", mode="grbl", est_min=3,
      covers=_COOL_COVERS + [("forgectrl", "src/super.c")], requires=["motion.pacing"],
      steps=["Bed clear; the head needs 20 mm of free +X travel."],
      description="A dry jog and an M8/M9 cycle must not leave the run fan profile on: within "
                  "the cooldown the engine is back at its idle duty and the exhaust/intake tachs "
                  "are back at (or below) the idle level they held before the test. The idle "
                  "reference is taken only once the engine is idle and the tachs have stopped "
                  "changing, so a previous test's spin-down cannot be mistaken for idle.")
def fans_quiet(ctx):
    fc = ctx.forgectrl
    ev = ctx.evidence

    def fans():
        s = fc.status()
        return dict(s.get("fans") or {})

    def phase():
        st, c = fc.get("/cool/status")
        return (c or {}).get("phase") if st == 200 and isinstance(c, dict) else None

    # The idle reference: engine idle, idle duty applied, and tachs that
    # have stopped changing (STABLE_SAMPLES consecutive samples that
    # agree). A test that ran just before leaves the fans spinning down
    # for tens of seconds after the engine goes idle; a reference taken
    # then is not idle, and two samples can agree by chance mid-coast.
    t0 = time.time()
    before = None
    recent = []
    while time.time() - t0 < IDLE_REF_TIMEOUT_S:
        ctx.sleep(SAMPLE_S)
        now, ph, d = fans(), phase(), _duties()
        ctx.log("  idle ref: phase %s duty %s fans %s", ph, d, now)
        recent = (recent + [now])[-STABLE_SAMPLES:] if ph == "idle" and d == IDLE_DUTY else []
        if len(recent) == STABLE_SAMPLES and all(_tach_stable(a, b) for a, b in zip(recent, recent[1:])):
            before = now
            break
    ev["before"] = before
    ev["idle_ref_s"] = round(time.time() - t0, 1)
    ctx.check(before is not None, "the fans never settled to an idle reference within %d s (last %s, "
              "phase %s, duty %s)", IDLE_REF_TIMEOUT_S, recent[-1:] or None, phase(), _duties())
    ctx.log("idle reference after %s s: %s", ev["idle_ref_s"], before)

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
        ev["duty_m8"] = _duties()
        ctx.log("fans during M8: %s (duty %s)", during, ev["duty_m8"])
        ctx.check(ev["duty_m8"] != IDLE_DUTY, "M8 did not raise the fan duty off idle: %s", ev["duty_m8"])
        g.command("M9")
        g.command("G90")
    # Cooldown: the engine's smoke phase, then the drop to idle duty, then
    # the tachs coast down. Every sample is logged: a quiet pane here
    # looks like a hang.
    settle = None
    t0 = time.time()
    while time.time() - t0 < COOLDOWN_TIMEOUT_S:
        ctx.sleep(SAMPLE_S)
        now, ph, d = fans(), phase(), _duties()
        ctx.log("  cooldown +%3.0f s: phase %s duty %s fans %s", time.time() - t0, ph, d, now)
        if ph == "idle" and d == IDLE_DUTY and _tach_close(now, before):
            settle = time.time() - t0
            break
    ev["after"] = fans()
    ev["duty_after"] = _duties()
    ev["settle_s"] = round(settle, 1) if settle is not None else None
    ctx.log("fans after: %s duty %s (settled in %s s)", ev["after"], ev["duty_after"], ev["settle_s"])
    ctx.check(settle is not None, "fans did not return to the idle profile within %d s: %s, duty %s, "
              "phase %s (idle reference %s)", COOLDOWN_TIMEOUT_S, ev["after"], ev["duty_after"], phase(), before)
