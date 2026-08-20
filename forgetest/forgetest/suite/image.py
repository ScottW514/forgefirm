"""image.* - the post-flash health of the running image (always-required)."""
import glob
import gzip
import os
import re
import stat

from ..catalog import test
from .. import hw


def _read(path, default=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def kernel_config():
    """The running kernel's config as a dict, from /proc/config.gz or
    /boot/config-<release>. None when neither is available."""
    try:
        with gzip.open("/proc/config.gz", "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        text = None
    if text is None:
        rel = _read("/proc/sys/kernel/osrelease", "").strip()
        text = _read("/boot/config-%s" % rel) if rel else None
    if text is None:
        return None
    cfg = {}
    for line in text.splitlines():
        m = re.match(r"^(CONFIG_[A-Z0-9_]+)=(.*)$", line)
        if m:
            cfg[m.group(1)] = m.group(2)
        m = re.match(r"^# (CONFIG_[A-Z0-9_]+) is not set$", line)
        if m:
            cfg[m.group(1)] = "n"
    return cfg


def _dt_u32(path):
    """A device-tree cell as an int (big-endian), or None."""
    try:
        with open(path, "rb") as f:
            raw = f.read(4)
    except OSError:
        return None
    return int.from_bytes(raw, "big") if len(raw) == 4 else None


def fds_of(pid):
    out = []
    try:
        for fd in os.listdir("/proc/%d/fd" % pid):
            try:
                out.append(os.readlink("/proc/%d/fd/%s" % (pid, fd)))
            except OSError:
                pass
    except OSError:
        pass
    return out


@test("image.health", title="Post-flash image health", subsystem="image", kind="auto",
      always=True, est_min=1,
      covers=[("forgectrl", "init/**"), ("forgectrl", "src/main.c"), ("forgectrl", "src/auth.c"),
              ("forgectrl", "CMakeLists.txt"), ("grblhal-glowforge", "src/boards/**"),
              ("grblhal-glowforge", "CMakeLists.txt"), ("kernel-module-glowforge", "**"),
              ("linux-fslc", "**")],
      description="The image that is running is the image the manifest describes, with the "
                  "kernel options, the module and the pulse ring it maps, the daemon ownership, "
                  "the init ordering, and the file modes the release depends on.")
def image_health(ctx):
    ev = ctx.evidence
    manifest = ctx.runner.manifest

    # 1. version stamp
    ver = (_read("/etc/forgefirm-version", "") or "").strip()
    ev["forgefirm_version"] = ver
    ctx.log("forgefirm-version: %s (manifest: %s)", ver, manifest.version)
    ctx.check(ver == manifest.version, "/etc/forgefirm-version %r != manifest %r", ver, manifest.version)

    # 2. kernel options
    cfg = kernel_config()
    ctx.check(cfg is not None, "kernel config unavailable (/proc/config.gz, /boot/config-*)")
    for opt, want in (("CONFIG_PREEMPT", ("y",)), ("CONFIG_IMX2_WDT", ("y", "m")),
                      ("CONFIG_PANIC_ON_OOPS", ("y",))):
        val = cfg.get(opt, "n")
        ev[opt] = val
        ctx.log("%s=%s", opt, val)
        ctx.check(val in want, "%s=%s, expected one of %s", opt, val, want)
    rel = _read("/proc/sys/kernel/osrelease", "").strip()
    ev["kernel_release"] = rel
    mods = manifest.platform.get("kernel_modules") or []
    ctx.log("kernel release %s (manifest modules dirs: %s)", rel, ",".join(mods))
    ctx.check(not mods or rel in mods, "running kernel %r is not the manifest's %s", rel, mods)

    # 3. the module and its sysfs
    ctx.check(os.path.isdir("/sys/module/glowforge"), "glowforge.ko is not loaded")
    state = hw.sysfs_read("cnc/state")
    ev["cnc_state"] = state
    ctx.check(state is not None, "/sys/glowforge/cnc/state unreadable")
    ctx.log("cnc/state: %s", state)
    free = hw.sysfs_int("cnc/free")
    ev["cnc_free"] = free
    ctx.check(free is not None and free > 0, "cnc/free unreadable or zero (ring not mapped?)")
    ctx.log("cnc/free: %s bytes", free)

    # The ring the platform ships: the DT pool is the promise, ring_mb is what
    # the module took. They must agree - a pool the parameter does not use is
    # no-map RAM burned for nothing, and a parameter the pool cannot back would
    # have failed the probe. free can only ever be size less the 32 KiB gap.
    pool = _dt_u32("/proc/device-tree/reserved-memory/cnc-pulsebuf/size")
    try:
        ring = int((_read("/sys/module/glowforge/parameters/ring_mb", "") or "").strip()) << 20
    except ValueError:
        ring = None
    ev["cnc_pool_bytes"] = pool
    ev["cnc_ring_bytes"] = ring
    ctx.log("cnc-pulsebuf pool: %s bytes, ring_mb: %s bytes", pool, ring)
    ctx.check(pool is not None, "no cnc-pulsebuf reserved-memory node (the ring fell back to CMA?)")
    ctx.check(ring is not None, "/sys/module/glowforge/parameters/ring_mb unreadable")
    ctx.check(pool is None or ring is None or pool == ring,
              "DT pool %s and ring_mb %s disagree", pool, ring)
    ctx.check(ring is None or free is None or free <= ring - 32 * 1024,
              "cnc/free %s exceeds the ring less its 32 KiB gap (%s)", free, ring)
    ctx.check(hw.sysfs_read("cnc/interlock_circuit") is not None, "cnc/interlock_circuit unreadable")

    # 4. forgectrl holds /dev/glowforge and supervises the controller
    pids = hw.pidof("forgectrl")
    ev["forgectrl_pids"] = pids
    ctx.check(pids, "forgectrl is not running")
    holders = [p for p in pids if any(l == "/dev/glowforge" for l in fds_of(p))]
    ev["pulse_device_holders"] = holders
    ctx.log("forgectrl pids %s, holding /dev/glowforge: %s", pids, holders)
    ctx.check(holders, "no forgectrl process holds /dev/glowforge")
    st, mode = ctx.forgectrl.get("/mode")
    ev["mode"] = mode
    ctx.check(st == 200 and isinstance(mode, dict), "GET /mode -> %s", st)
    ctx.log("mode: %s", mode)
    ctx.check(mode.get("controller") in ("running", "standby"),
              "controller is %r (expected running or standby)", mode.get("controller"))
    ctx.check(mode.get("motion") != "fault", "supervisor reports a motion fault")

    # 5. init ordering: controllers stop before the daemon
    k = sorted(os.path.basename(p) for p in glob.glob("/etc/rc6.d/K*"))
    ev["rc6_kill"] = k
    kg = [x for x in k if "grblhal" in x]
    kf = [x for x in k if x.endswith("forgectrl")]
    ctx.log("rc6.d: %s", " ".join(k))
    ctx.check(kg and kf, "rc6.d lacks the grblhal/forgectrl kill links")
    ctx.check(kg[0] < kf[0], "controller kill link %s must sort before forgectrl's %s", kg[0], kf[0])

    # 6. logging lever present, no userspace watchdog daemon
    logging = [n for n in ("forgefirm-logging", "forgefirm-logrotate") if os.path.exists("/etc/init.d/" + n)]
    ev["logging_init"] = logging
    ctx.check(logging, "no ForgeFIRM logging/logrotate init script")
    ctx.check(not os.path.exists("/etc/init.d/watchdog"), "a userspace watchdog init script is present")
    # kernel threads (the imx2_wdt kthread is expected) have an empty cmdline
    user_wd = [p for p in hw.pidof("watchdog") if _read("/proc/%d/cmdline" % p, "")]
    ev["userspace_watchdog_pids"] = user_wd
    ctx.check(not user_wd, "a userspace watchdog daemon is running: %s", user_wd)

    # 7. file modes and space
    for path in ("/data/forgefirm/panel.token", "/data/forgefirm.conf"):
        if os.path.exists(path):
            m = stat.S_IMODE(os.stat(path).st_mode)
            ev[path] = "%o" % m
            ctx.log("%s mode %o", path, m)
            ctx.check(m == 0o600, "%s mode %o, expected 600", path, m)
    if os.path.isdir("/data"):
        s = os.statvfs("/data")
        free_mb = s.f_bavail * s.f_frsize // (1024 * 1024)
        ev["data_free_mb"] = free_mb
        ctx.log("/data free: %d MiB", free_mb)
        ctx.check(free_mb >= 20, "/data has only %d MiB free", free_mb)

    # 8. the manifest itself is coherent
    ctx.check(manifest.content_sha and len(manifest.content_sha) == 64, "manifest content_sha256 missing")
    ctx.check("kernel-module-glowforge" in manifest.components, "manifest lacks kernel-module-glowforge")
    ctx.check("linux-fslc" in manifest.components, "manifest lacks the kernel entry")
    ctx.log("manifest %s: %d components", manifest.content_sha[:12], len(manifest.components))
