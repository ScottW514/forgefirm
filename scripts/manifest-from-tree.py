#!/usr/bin/env python3
# (C) Copyright 2020-2026
# Scott Wiederhold, s.e.wiederhold@gmail.com
# https://community.openglow.org
# SPDX-License-Identifier:    MIT
#
# Build a ForgeFIRM image manifest from the source tree - the same file lists
# forgefirm-image-manifest.bbclass puts in the image, computed from the recipe
# pins with git instead of a Yocto build. For the coverage lint in CI and for
# checking a coverage map on a workstation; NOT a substitute for the image's
# manifest in the release gate (the platform section carries placeholders
# where only a build knows the answer: kernel config hash, modules dir, DTB).
#
#   manifest-from-tree.py [--meta-openglow PATH] [--out manifest.json]
#                         [--cache DIR] [--kernel-srcrev REV]
#
# Component revisions come from the recipes in meta-forgefirm and the sibling
# meta-openglow checkout (default ../meta-openglow relative to this repo).
# Each pinned commit is fetched shallowly into --cache (default
# .manifest-cache/, gitignored) and listed with `git ls-tree`; a submodule
# gitlink is followed through .gitmodules.
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "forgetest"))
from forgetest import manifest as manifest_mod  # noqa: E402

RECIPES = [
    # (component, recipe path relative to the repo or meta-openglow, layer)
    ("forgectrl", "meta-forgefirm/recipes-forgefirm/forgectrl/forgectrl.bb", "forgefirm"),
    ("grblhal-glowforge", "meta-forgefirm/recipes-forgefirm/grblhal-glowforge/grblhal-glowforge.bb", "forgefirm"),
    ("forgefirm-app", "meta-forgefirm/recipes-forgefirm/forgefirm-app/forgefirm-app.inc", "forgefirm"),
    ("kernel-module-glowforge", "meta-glowforge-bsp/recipes-kernel/kernel-modules/kernel-module-glowforge.bb", "meta-openglow"),
    ("python3-gfhardware", "meta-glowforge-bsp/recipes-devtools/python/python3-gfhardware.bb", "meta-openglow"),
    ("python3-gfutilities", "meta-openglow-core/recipes-devtools/python/python3-gfutilities_git.bb", "meta-openglow"),
]
CONTENT_LAYERS = {"meta-forgefirm": ("forgefirm", "meta-forgefirm"),
                  "meta-glowforge-bsp": ("meta-openglow", "meta-glowforge-bsp"),
                  "meta-openglow-core": ("meta-openglow", "meta-openglow-core")}


def git(args, cwd=None, input=None):
    return subprocess.run(["git"] + args, cwd=cwd, input=input, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def parse_recipe(path):
    text = open(path, encoding="utf-8").read()
    uri = re.search(r'^SRC_URI\s*\+?=\s*"([^"]+)"', text, re.M)
    rev = re.search(r'^SRCREV\s*\??=\s*"([0-9a-fA-F]+)"', text, re.M)
    if not uri or not rev:
        raise SystemExit("cannot find SRC_URI/SRCREV in %s" % path)
    first = uri.group(1).split()[0]
    url = first.split(";")[0]
    params = dict(p.split("=", 1) for p in first.split(";")[1:] if "=" in p)
    proto = params.get("protocol", "https")
    if url.startswith("git://") or url.startswith("gitsm://"):
        url = proto + "://" + url.split("://", 1)[1]
    return url, rev.group(1)


def fetch(url, rev, cache):
    """A bare cache repo containing rev (fetched shallowly)."""
    name = hashlib.sha1(url.encode()).hexdigest()[:16]
    repo = os.path.join(cache, name)
    if not os.path.isdir(repo):
        os.makedirs(repo)
        git(["init", "-q", "--bare"], cwd=repo)
    try:
        git(["cat-file", "-e", rev + "^{commit}"], cwd=repo)
    except subprocess.CalledProcessError:
        git(["fetch", "-q", "--depth", "1", url, rev], cwd=repo)
    return repo


def ls_tree(repo, rev, url, cache, prefix, files):
    out = git(["ls-tree", "-r", "--full-tree", rev], cwd=repo).decode()
    modules = None
    for line in out.splitlines():
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        typ, obj = meta.split()[1], meta.split()[2]
        files.append([prefix + path, obj])
        if typ == "commit":
            if modules is None:
                modules = {}
                try:
                    gm = git(["show", "%s:.gitmodules" % rev], cwd=repo).decode()
                except subprocess.CalledProcessError:
                    gm = ""
                cur = None
                for l in gm.splitlines():
                    l = l.strip()
                    m = re.match(r'^path\s*=\s*(.+)$', l)
                    if m:
                        cur = m.group(1).strip()
                    m = re.match(r'^url\s*=\s*(.+)$', l)
                    if m and cur:
                        modules[cur] = m.group(1).strip()
            sub_url = modules.get(path)
            if sub_url:
                if sub_url.startswith("../") or sub_url.startswith("./"):
                    base = url.rsplit("/", 1)[0]
                    sub_url = base + "/" + sub_url.lstrip("./")
                sub_repo = fetch(sub_url, obj, cache)
                ls_tree(sub_repo, obj, sub_url, cache, prefix + path + "/", files)


def layer_content(path):
    out = git(["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."], cwd=path)
    paths = sorted(set(p.decode("utf-8", "replace") for p in out.split(b"\0") if p))
    paths = [p for p in paths if os.path.isfile(os.path.join(path, p)) and not p.endswith(".md")]
    if not paths:
        return None
    # hash-object --stdin-paths resolves against the repository top level
    prefix = git(["rev-parse", "--show-prefix"], cwd=path).decode().strip()
    ids = git(["hash-object", "--stdin-paths"], cwd=path,
              input=("\n".join(prefix + p for p in paths) + "\n").encode()).decode().split()
    h = hashlib.sha256()
    for p, i in zip(paths, ids):
        h.update(p.encode("utf-8") + b"\0" + i.encode("ascii") + b"\n")
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-openglow", default=os.path.join(os.path.dirname(REPO), "meta-openglow"))
    ap.add_argument("--out", default="-")
    ap.add_argument("--cache", default=os.path.join(REPO, ".manifest-cache"))
    ap.add_argument("--kernel-srcrev", default=None,
                    help="linux-fslc SRCREV (default: read from layers/meta-freescale if present)")
    args = ap.parse_args(argv)
    os.makedirs(args.cache, exist_ok=True)

    components = {}
    for name, rel, layer in RECIPES:
        base = REPO if layer == "forgefirm" else args.meta_openglow
        path = os.path.join(base, rel)
        url, rev = parse_recipe(path)
        repo = fetch(url, rev, args.cache)
        files = []
        ls_tree(repo, rev, url, args.cache, "", files)
        files.sort()
        components[name] = {"srcrev": rev, "source": url, "files": files, "recipes": [os.path.basename(rel)]}
        print("%s: %s (%d files)" % (name, rev[:12], len(files)), file=sys.stderr)

    ksrc = args.kernel_srcrev
    if not ksrc:
        for cand in ("layers/meta-freescale/recipes-kernel/linux/linux-fslc_6.12.bb",):
            p = os.path.join(REPO, cand)
            if os.path.exists(p):
                m = re.search(r'^SRCREV\s*=\s*"([0-9a-f]+)"', open(p, encoding="utf-8").read(), re.M)
                if m:
                    ksrc = m.group(1)
    components["linux-fslc"] = {"srcrev": ksrc, "source": "git://github.com/Freescale/linux-fslc.git",
                                "config_sha256": None, "recipes": ["linux-fslc"],
                                "files": [["@config", "unknown-without-a-build"], ["@srcrev", ksrc or "unknown"]]}

    layers = {}
    for lname, (repo_key, sub) in CONTENT_LAYERS.items():
        base = REPO if repo_key == "forgefirm" else args.meta_openglow
        lpath = os.path.join(base, sub)
        if os.path.isdir(lpath):
            layers[lname] = {"content_sha256": layer_content(lpath)}
    platform = {"machine": "glowforge", "layers": layers, "kernel_modules": [], "dtb": {}}
    canonical = manifest_mod.canonical({"components": components, "platform": platform})
    out = {"format": 1, "image": {"name": "tree", "version": "tree (no build)"},
           "content_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
           "components": components, "platform": platform}
    text = json.dumps(out, sort_keys=True, indent=1) + "\n"
    if args.out == "-":
        sys.stdout.write(text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %s" % args.out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
