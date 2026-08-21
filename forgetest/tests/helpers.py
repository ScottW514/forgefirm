"""Shared fixtures for the forgetest unit tests: synthetic manifests and
catalog entries that never touch hardware."""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from forgetest import catalog as catalog_mod  # noqa: E402
from forgetest import manifest as manifest_mod  # noqa: E402


def blob(text):
    """A git-style blob id for text (what ls-tree would report)."""
    data = text.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def make_manifest(components=None, platform=None, version="20260101000000 (dev)", name="forgefirm-image-dev"):
    comps = components if components is not None else {
        "forgectrl": {"srcrev": "aaa", "files": [["src/main.c", blob("main")], ["src/ui.c", blob("ui")],
                                                  ["src/auth.c", blob("auth")], ["src/cool.c", blob("cool")],
                                                  ["README.md", blob("readme")]]},
        "grblhal-glowforge": {"srcrev": "bbb", "files": [["src/driver.c", blob("drv")],
                                                          ["src/grbl", "cccc"], ["src/grbl/core.c", blob("core")]]},
        "kernel-module-glowforge": {"srcrev": "ddd", "files": [["src/cnc.c", blob("cnc")]]},
        "linux-fslc": {"srcrev": "eee", "files": [["@srcrev", "eee"], ["@config", "cfg1"]]},
        "forgetest": {"srcrev": None, "files": [["forgetest/x.py", blob("x")]]},
    }
    plat = platform if platform is not None else {
        "machine": "glowforge", "kernel_modules": ["6.12.20-fslc+g0e01ec9f0d3f"],
        "dtb": {"glowforge.dtb": "d" * 64},
        "layers": {"meta-forgefirm": {"content_sha256": "1" * 64}, "poky": {"rev": "p" * 40}},
    }
    data = {"format": 1, "image": {"name": name, "version": version},
            "components": comps, "platform": plat}
    data["content_sha256"] = manifest_mod.sha256_text(
        manifest_mod.canonical({"components": comps, "platform": plat}))
    return manifest_mod.Manifest(data)


def with_file(manifest, component, path, text):
    """A copy of the manifest with one file's content changed/added."""
    import copy
    data = copy.deepcopy(manifest.data)
    files = data["components"][component]["files"]
    for f in files:
        if f[0] == path:
            f[1] = blob(text)
            break
    else:
        files.append([path, blob(text)])
    data["content_sha256"] = manifest_mod.sha256_text(
        manifest_mod.canonical({"components": data["components"], "platform": data["platform"]}))
    return manifest_mod.Manifest(data)


def with_platform(manifest, **changes):
    import copy
    data = copy.deepcopy(manifest.data)
    data["platform"].update(changes)
    data["content_sha256"] = manifest_mod.sha256_text(
        manifest_mod.canonical({"components": data["components"], "platform": data["platform"]}))
    return manifest_mod.Manifest(data)


def _noop(ctx):
    pass


def make_test(id, covers, always=False, requires=(), kind="auto", fn=None, subsystem=None, mode=None):
    return catalog_mod.Test(id, "Title " + id, subsystem or id.split(".")[0], kind, "api",
                            covers, requires, always, 1, (), "desc", fn or _noop, mode=mode)


def registry(*tests):
    return {t.id: t for t in tests}


# ------------------------------------------------------- fake forgectrl

class FakeForgectrl:
    """A stand-in for the machine-services daemon on localhost: canned
    JSON for the endpoints the suite reads, a mutable `state` the test
    scripts, every POST recorded, and an optional `on_post(path, form)`
    hook returning (status, body) to script the daemon's reactions.
    Point the suite at it with FORGECTRL_URL (see start/stop)."""

    def __init__(self):
        import http.server
        import json as _json
        import threading as _threading
        import urllib.parse as _up
        self.state = {
            "mode": {"mode": "grbl", "controller": "running", "pid": 100, "motion": "verified"},
            "status": {"state": "idle", "homed": False, "diag": False, "laser_locked": True,
                       "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
                       "switches": {"lid": True, "button": False, "interlock_ok": True,
                                    "head": True, "hv_enable": False}},
            "cool": {"phase": "idle", "armed": False, "hold": False},
            "cam": {"running": False, "clients": 0},
            "diag": {"running": False},
            "settings": {"controller_mode": "grbl", "lid_lamp_idle": ""},
        }
        self.posts = []
        self.on_post = None
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, st, body):
                data = _json.dumps(body).encode()
                self.send_response(st)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                key = {"/mode": "mode", "/status": "status", "/cool/status": "cool", "/cam/status": "cam",
                       "/diag/status": "diag", "/settings": "settings"}.get(path)
                if key is None:
                    return self._send(404, {"error": "no " + path})
                self._send(200, fake.state[key])

            def do_POST(self):
                path, _, query = self.path.partition("?")
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode() if n else ""
                form = dict(_up.parse_qsl(raw)) if raw else dict(_up.parse_qsl(query))
                fake.posts.append((path, form))
                if fake.on_post:
                    r = fake.on_post(path, form)
                    if r is not None:
                        return self._send(*r)
                if path == "/mode" and form.get("controller"):
                    fake.state["mode"] = dict(fake.state["mode"], mode=form["controller"], controller="running",
                                              pid=fake.state["mode"].get("pid", 0) + 1)
                    fake.state["settings"]["controller_mode"] = form["controller"]
                elif path == "/settings":
                    fake.state["settings"].update(form)
                self._send(200, {"ok": True})

        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._srv.daemon_threads = True
        self._srv.block_on_close = False        # never wait on a lingering connection
        self.url = "http://127.0.0.1:%d" % self._srv.server_address[1]
        self._th = _threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self):
        self._th.start()
        os.environ["FORGECTRL_URL"] = self.url
        os.environ["FORGECTRL_TOKEN_FILE"] = os.devnull
        return self

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()
        os.environ.pop("FORGECTRL_URL", None)
        os.environ.pop("FORGECTRL_TOKEN_FILE", None)
