"""The acceptance catalog: test definitions and the registry.

A test is a function decorated with @test(...). The decorator records
what the release gate needs to know without running anything: the id,
the subsystem, the kind (auto / operator / live), how it takes the
hardware (api / takeover), what source it covers, what it requires, and
whether it belongs to the always-required core. The function body runs
under the runner with a Context (log, prompts, evidence, hardware
helpers) and reports by returning normally (PASS) or raising
runner.Failed (FAIL).
"""
import hashlib
import inspect
import os
import re

from . import manifest as _manifest

KINDS = ("auto", "operator", "live")
HARDWARE = ("api", "takeover")
_ID_RX = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")

REGISTRY = {}


class Test:
    def __init__(self, id, title, subsystem, kind, hardware, covers, requires,
                 always, est_min, steps, description, fn):
        self.id = id
        self.title = title
        self.subsystem = subsystem
        self.kind = kind
        self.hardware = hardware
        self.covers = tuple((str(c), str(g)) for c, g in covers)
        self.requires = tuple(requires)
        self.always = bool(always)
        self.est_min = est_min
        self.steps = tuple(steps)
        self.description = description or (fn.__doc__ or "").strip()
        self.fn = fn
        self._source_sha = None
        self._fp = (None, None)   # (manifest content sha, fingerprint)

    @property
    def source_sha(self):
        """sha256 of the module file that defines the test, line endings
        normalized. Part of the fingerprint: a changed implementation
        invalidates earlier passes of this test and no other."""
        if self._source_sha is None:
            path = inspect.getsourcefile(self.fn) or inspect.getfile(self.fn)
            self._source_sha = source_file_sha(path)
        return self._source_sha

    def fingerprint(self, manifest):
        """The domain fingerprint on this manifest, memoized by the
        manifest's content hash: the page recomputes every test's
        fingerprint on every poll, and a manifest never changes under a
        running tool."""
        key = manifest.content_sha
        if key and self._fp[0] == key:
            return self._fp[1]
        fp = _manifest.fingerprint(manifest, self.covers, extra=[self.source_sha])
        if key:
            self._fp = (key, fp)
        return fp

    def definition(self):
        """The gate-visible definition (no implementation, no prose)."""
        return {
            "id": self.id,
            "subsystem": self.subsystem,
            "kind": self.kind,
            "hardware": self.hardware,
            "covers": [list(c) for c in self.covers],
            "requires": list(self.requires),
            "always": self.always,
        }

    def describe(self):
        d = self.definition()
        d.update({"title": self.title, "est_min": self.est_min,
                  "steps": list(self.steps), "description": self.description})
        return d


def source_file_sha(path):
    with open(path, "rb") as f:
        data = f.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def test(id, *, title, subsystem, kind="auto", hardware="api", covers=(),
         requires=(), always=False, est_min=1, steps=(), description=""):
    if not _ID_RX.match(id):
        raise ValueError("test id %r must look like subsystem.name" % id)
    if kind not in KINDS:
        raise ValueError("test %s: kind %r" % (id, kind))
    if hardware not in HARDWARE:
        raise ValueError("test %s: hardware %r" % (id, hardware))
    for c, g in covers:
        if c in _manifest.DEV_ONLY_COMPONENTS:
            raise ValueError("test %s: may not cover dev-only component %r" % (id, c))

    def deco(fn):
        if id in REGISTRY:
            raise ValueError("duplicate test id %r" % id)
        REGISTRY[id] = Test(id, title, subsystem, kind, hardware, covers, requires,
                            always, est_min, steps, description, fn)
        return fn
    return deco


def all_tests(registry=None):
    """Tests in registration order (the suite modules import in
    subsystem order, so this is the display order)."""
    return list((registry if registry is not None else REGISTRY).values())


def get(id, registry=None):
    return (registry if registry is not None else REGISTRY).get(id)


def validate(registry=None):
    """Every `requires` names a known test and there are no cycles."""
    reg = registry if registry is not None else REGISTRY
    for t in reg.values():
        for r in t.requires:
            if r not in reg:
                raise ValueError("test %s requires unknown test %s" % (t.id, r))
    seen = {}

    def visit(tid, stack):
        if tid in stack:
            raise ValueError("requires cycle: %s" % " -> ".join(stack + [tid]))
        if seen.get(tid):
            return
        for r in reg[tid].requires:
            visit(r, stack + [tid])
        seen[tid] = True
    for tid in reg:
        visit(tid, [])


def catalog_hash(registry=None):
    """Identity of the catalog's definitions (ids, kinds, coverage,
    requirements, core membership) - not of the implementations, which
    the per-test fingerprints carry."""
    defs = sorted((t.definition() for t in all_tests(registry)), key=lambda d: d["id"])
    return _manifest.sha256_text(_manifest.canonical(defs))


def load_suite():
    """Import the suite modules (each registers its tests) and validate."""
    from . import suite  # noqa: F401  (registers on import)
    validate()
    return REGISTRY


def suite_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "suite")
