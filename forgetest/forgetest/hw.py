"""Hardware and service access for the suite: forgectrl's HTTP API, the
kernel module's sysfs, the init scripts, and the Grbl TCP port.

Everything is reachable through environment overrides so the suite can be
exercised against a mock on a host:
  FORGECTRL_URL          default http://127.0.0.1:8080
  FORGECTRL_TOKEN_FILE   default /data/forgefirm/panel.token
  GF_SYSFS_ROOT          default /sys/glowforge/  (must end with '/')
  GRBL_HOST / GRBL_PORT  default 127.0.0.1 / 23
  FORGETEST_INITD        default /etc/init.d
"""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


class HwError(Exception):
    pass


# ------------------------------------------------------------ forgectrl

class Forgectrl:
    """Thin client for the machine-services daemon."""

    def __init__(self, base=None, token=None, timeout=10.0):
        self.base = (base or os.environ.get("FORGECTRL_URL") or "http://127.0.0.1:8080").rstrip("/")
        self.timeout = timeout
        self._token = token

    @property
    def token(self):
        if self._token is None:
            path = os.environ.get("FORGECTRL_TOKEN_FILE") or "/data/forgefirm/panel.token"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._token = f.read().strip()
            except OSError:
                self._token = ""
        return self._token

    def host_header(self):
        return urllib.parse.urlsplit(self.base).netloc

    def request(self, method, path, params=None, data=None, headers=None, auth=True, raw=False):
        """Returns (status, body). body is parsed JSON when the response
        is JSON, else text (or bytes when raw=True). Never raises on an
        HTTP error status - the suite asserts on codes."""
        url = self.base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        body = None
        hdrs = {"Host": self.host_header()}
        if headers:
            hdrs.update(headers)
        if data is not None:
            if isinstance(data, (dict, list)):
                body = urllib.parse.urlencode(data).encode()
                hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif isinstance(data, str):
                body = data.encode()
            else:
                body = data
        if auth and self.token:
            hdrs.setdefault("X-ForgeFIRM-Token", self.token)
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                content = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            status = e.code
            content = e.read()
            ctype = e.headers.get("Content-Type", "") if e.headers else ""
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise HwError("forgectrl %s %s: %s" % (method, path, e))
        if raw:
            return status, content
        text = content.decode("utf-8", "replace")
        if "json" in ctype:
            try:
                return status, json.loads(text)
            except ValueError:
                pass
        return status, text

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def status(self):
        st, body = self.get("/status")
        if st != 200 or not isinstance(body, dict):
            raise HwError("forgectrl /status -> %s" % st)
        return body

    def settings(self):
        st, body = self.get("/settings")
        if st != 200 or not isinstance(body, dict):
            raise HwError("forgectrl /settings -> %s" % st)
        return body

    def wait_idle(self, timeout=60.0, poll=0.5, abort=None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if abort and abort():
                raise HwError("aborted while waiting for idle")
            try:
                if self.status().get("state") == "idle":
                    return True
            except HwError:
                pass
            time.sleep(poll)
        return False


# ---------------------------------------------------------------- sysfs

def sysfs_root():
    r = os.environ.get("GF_SYSFS_ROOT") or "/sys/glowforge/"
    return r if r.endswith("/") else r + "/"


def sysfs_read(attr, default=None):
    try:
        with open(sysfs_root() + attr, "r") as f:
            return f.read().strip()
    except OSError:
        return default


def sysfs_int(attr, default=None):
    v = sysfs_read(attr)
    if v is None or v == "":
        return default
    try:
        return int(v.split()[0], 0)
    except ValueError:
        return default


def sysfs_write(attr, value):
    with open(sysfs_root() + attr, "w") as f:
        f.write(str(value))


# --------------------------------------------------------------- init.d

def initd(service, action, timeout=60):
    """Run /etc/init.d/<service> <action>; returns (rc, output)."""
    base = os.environ.get("FORGETEST_INITD") or "/etc/init.d"
    script = os.path.join(base, service)
    try:
        p = subprocess.run([script, action], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def pidof(comm):
    """PIDs whose /proc/<pid>/comm equals comm (15-char kernel limit applies)."""
    out = []
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/comm" % pid) as f:
                    if f.read().strip() == comm:
                        out.append(int(pid))
            except OSError:
                pass
    except OSError:
        pass
    return out


def run(cmd, timeout=60):
    """Run a command list; returns (rc, combined output)."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, p.stdout.decode("utf-8", "replace")


# ------------------------------------------------------------------ grbl

class Grbl:
    """Minimal Grbl-over-TCP client. The suite is the only client while a
    motion test runs; nothing here is used to poll status when a sender
    may be attached (position for display comes from forgectrl)."""

    def __init__(self, host=None, port=None, timeout=5.0):
        self.host = host or os.environ.get("GRBL_HOST") or "127.0.0.1"
        self.port = int(port or os.environ.get("GRBL_PORT") or 23)
        self.timeout = timeout
        self.sock = None
        self.buf = b""

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        # Drain the greeting.
        time.sleep(0.3)
        self.drain()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def drain(self):
        self.sock.settimeout(0.05)
        try:
            while True:
                d = self.sock.recv(4096)
                if not d:
                    break
                self.buf += d
        except (socket.timeout, OSError):
            pass
        out, self.buf = self.buf, b""
        return out.decode("utf-8", "replace")

    def send_raw(self, data):
        self.sock.settimeout(self.timeout)
        self.sock.sendall(data)

    def command(self, line, timeout=None):
        """Send one line, return the response lines up to ok/error."""
        self.send_raw((line.strip() + "\n").encode())
        return self.wait_response(timeout or self.timeout)

    def wait_response(self, timeout):
        deadline = time.time() + timeout
        lines = []
        self.sock.settimeout(0.2)
        while time.time() < deadline:
            try:
                d = self.sock.recv(4096)
                if not d:
                    break
                self.buf += d
            except socket.timeout:
                pass
            while b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                s = raw.decode("utf-8", "replace").strip()
                if not s:
                    continue
                lines.append(s)
                if s == "ok" or s.startswith("error:"):
                    return lines
        return lines

    def realtime(self, byte):
        self.send_raw(bytes([byte]))

    def status_report(self):
        """One '?' report, parsed: {'state': 'Idle', 'MPos': (x,y,z), ...}.
        The '?' is re-sent every 0.5 s until a report arrives: a soft
        reset (^X) flushes the controller's read buffer and eats a '?'
        that lands in it."""
        self.drain()
        self.send_raw(b"?")
        deadline = time.time() + self.timeout
        resend = time.time() + 0.5
        self.sock.settimeout(0.2)
        while time.time() < deadline:
            try:
                d = self.sock.recv(4096)
                if d:
                    self.buf += d
            except socket.timeout:
                pass
            if time.time() >= resend:
                self.send_raw(b"?")
                resend = time.time() + 0.5
            i = self.buf.find(b"<")
            j = self.buf.find(b">", i + 1) if i >= 0 else -1
            if i >= 0 and j > i:
                rep = self.buf[i + 1:j].decode("utf-8", "replace")
                self.buf = self.buf[j + 1:]
                return parse_report(rep)
        raise HwError("no status report from grbl")


def parse_report(rep):
    parts = rep.split("|")
    out = {"state": parts[0]}
    for p in parts[1:]:
        if ":" in p:
            k, v = p.split(":", 1)
            if k in ("MPos", "WPos", "WCO"):
                try:
                    out[k] = tuple(float(x) for x in v.split(","))
                except ValueError:
                    out[k] = v
            else:
                out[k] = v
    return out
