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


def make_test(id, covers, always=False, requires=(), kind="auto", fn=None, subsystem=None):
    return catalog_mod.Test(id, "Title " + id, subsystem or id.split(".")[0], kind, "api",
                            covers, requires, always, 1, (), "desc", fn or _noop)


def registry(*tests):
    return {t.id: t for t in tests}
