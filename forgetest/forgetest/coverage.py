"""Coverage lint: every source path in the manifest must be selected by
some test's coverage globs, except the allowlisted non-behavioral paths.

Why a hard rule: under the domain model an uncovered file is worse than an
untested one - a change there leaves every inherited PASS valid when it
should have invalidated them. The lint is the floor (the file is
fingerprinted by at least one test); whether that test exercises the
change stays with the change author.

  python3 -m forgetest.coverage [--manifest PATH] [--enforce] [--json]

Exit 0 when nothing is uncovered (or when only reporting), 1 under
--enforce with uncovered paths, 2 on a usage or load error.
"""
import argparse
import json
import sys

from . import catalog as _catalog
from . import manifest as _manifest

# Non-behavioral paths that need no acceptance coverage. Reviewed with the
# catalog: widening this list is a change like any other.
ALLOW = [
    ("*", ".github/**"),
    ("*", ".gitignore"),
    ("*", ".gitmodules"),
    ("*", "**/*.md"),
    ("*", "LICENSE*"),
    ("*", "COPYING*"),
    ("*", "docs/**"),
    ("*", "tests/**"),
    ("*", "graphify-out/**"),
    ("*", "**/.gitkeep"),
    ("*", ".devcontainer/**"),        # editor/dev-environment setup, no target
    ("*", ".vscode/**"),              #   behavior
    ("*", ".env.example"),
    ("forgectrl", "tools/**"),        # host-side dev tools (panel dev server)
]


def run(manifest, tests, allow=ALLOW):
    return _manifest.coverage_report(manifest, tests, allow)


def main(argv=None):
    ap = argparse.ArgumentParser(description="forgetest coverage lint")
    ap.add_argument("--manifest", default=None, help="manifest JSON (default: the running image's)")
    ap.add_argument("--enforce", action="store_true", help="exit 1 when any path is uncovered")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args(argv)
    try:
        manifest = _manifest.Manifest.load(args.manifest)
    except (OSError, ValueError) as e:
        print("cannot load manifest: %s" % e, file=sys.stderr)
        return 2
    registry = _catalog.load_suite()
    tests = _catalog.all_tests(registry)
    report = run(manifest, tests)
    total = sum(len(v) for v in report.values())
    if args.json:
        print(json.dumps({"uncovered": report, "total": total, "tests": len(tests)}, indent=1, sort_keys=True))
    else:
        for comp in sorted(report):
            print("%s: %d uncovered path(s)" % (comp, len(report[comp])))
            for p in report[comp]:
                print("  %s" % p)
        print("coverage: %d uncovered path(s) across %d component(s), %d tests"
              % (total, len(report), len(tests)))
    if args.enforce and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
