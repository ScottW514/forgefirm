import unittest

import helpers
from forgetest import manifest as m
from forgetest import catalog


class GlobTests(unittest.TestCase):
    def test_star_and_doublestar(self):
        rx = m.glob_to_regex("src/*.c")
        self.assertTrue(rx.match("src/main.c"))
        self.assertFalse(rx.match("src/sub/main.c"))
        rx = m.glob_to_regex("src/**")
        self.assertTrue(rx.match("src/main.c"))
        self.assertTrue(rx.match("src/sub/deep/x.h"))
        self.assertFalse(rx.match("docs/x"))
        rx = m.glob_to_regex("**/*.md")
        self.assertTrue(rx.match("README.md"))
        self.assertTrue(rx.match("docs/a/b.md"))
        self.assertFalse(rx.match("docs/a/b.txt"))
        rx = m.glob_to_regex("**")
        self.assertTrue(rx.match("anything/at/all"))
        rx = m.glob_to_regex("src/gfcool*")
        self.assertTrue(rx.match("src/gfcool_client.c"))
        self.assertFalse(rx.match("src/x/gfcool.c"))

    def test_question_mark_and_escaping(self):
        rx = m.glob_to_regex("a?c.d")
        self.assertTrue(rx.match("abc.d"))
        self.assertFalse(rx.match("abcxd"))
        self.assertFalse(rx.match("a/c.d"))


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.man = helpers.make_manifest()

    def test_stable_and_order_independent(self):
        c1 = [("forgectrl", "src/ui.c"), ("forgectrl", "src/auth.c")]
        c2 = list(reversed(c1))
        self.assertEqual(m.fingerprint(self.man, c1), m.fingerprint(self.man, c2))
        self.assertEqual(m.fingerprint(self.man, c1), m.fingerprint(self.man, c1))

    def test_changes_only_when_covered_file_changes(self):
        covers = [("forgectrl", "src/ui.c")]
        base = m.fingerprint(self.man, covers)
        other = helpers.with_file(self.man, "forgectrl", "src/cool.c", "cool v2")
        self.assertEqual(base, m.fingerprint(other, covers), "an uncovered change must not move the fingerprint")
        changed = helpers.with_file(self.man, "forgectrl", "src/ui.c", "ui v2")
        self.assertNotEqual(base, m.fingerprint(changed, covers))
        added = helpers.with_file(self.man, "forgectrl", "src/ui_extra.c", "new")
        self.assertEqual(base, m.fingerprint(added, covers), "an unmatched new file does not move it")
        added2 = helpers.with_file(self.man, "forgectrl", "src/x.c", "new")
        self.assertNotEqual(base, m.fingerprint(added2, [("forgectrl", "src/*.c")]))

    def test_platform_is_always_in(self):
        covers = [("forgectrl", "src/ui.c")]
        base = m.fingerprint(self.man, covers)
        p2 = helpers.with_platform(self.man, dtb={"glowforge.dtb": "e" * 64})
        self.assertNotEqual(base, m.fingerprint(p2, covers))
        p3 = helpers.with_platform(self.man, layers={"meta-forgefirm": {"content_sha256": "2" * 64},
                                                     "poky": {"rev": "p" * 40}})
        self.assertNotEqual(base, m.fingerprint(p3, covers))

    def test_kernel_pseudo_files(self):
        covers = [("linux-fslc", "**")]
        base = m.fingerprint(self.man, covers)
        k2 = helpers.with_file(self.man, "linux-fslc", "@config", "cfg2")
        self.assertNotEqual(base, m.fingerprint(k2, covers))

    def test_missing_component_marker(self):
        f1 = m.fingerprint(self.man, [("nonexistent", "**")])
        f2 = m.fingerprint(self.man, [("forgectrl", "nothing-matches-*")])
        self.assertNotEqual(f1, f2)

    def test_dev_only_refused(self):
        with self.assertRaises(ValueError):
            m.fingerprint(self.man, [("forgetest", "**")])

    def test_extra_folds_in(self):
        covers = [("forgectrl", "src/ui.c")]
        self.assertNotEqual(m.fingerprint(self.man, covers, extra=["a"]),
                            m.fingerprint(self.man, covers, extra=["b"]))

    def test_submodule_gitlink_and_files(self):
        covers = [("grblhal-glowforge", "src/grbl/**")]
        base = m.fingerprint(self.man, covers)
        core = helpers.with_file(self.man, "grblhal-glowforge", "src/grbl/core.c", "core v2")
        self.assertNotEqual(base, m.fingerprint(core, covers))
        link = [("grblhal-glowforge", "src/grbl")]
        self.assertEqual(m.fingerprint(self.man, link), m.fingerprint(core, link),
                         "the gitlink alone does not see a file-level change (fixture keeps the link id)")

    def test_identity_sha_ignores_dev_only(self):
        a = self.man.identity_sha()
        b = helpers.with_file(self.man, "forgetest", "forgetest/x.py", "changed").identity_sha()
        self.assertEqual(a, b)
        c = helpers.with_file(self.man, "forgectrl", "src/ui.c", "changed").identity_sha()
        self.assertNotEqual(a, c)


class CoverageReportTests(unittest.TestCase):
    def test_report(self):
        man = helpers.make_manifest()
        t1 = helpers.make_test("a.one", [("forgectrl", "src/ui.c"), ("forgectrl", "src/auth.c")])
        t2 = helpers.make_test("a.two", [("grblhal-glowforge", "**"), ("kernel-module-glowforge", "**"),
                                         ("linux-fslc", "**")])
        rep = m.coverage_report(man, [t1, t2], allow=[("*", "**/*.md")])
        self.assertEqual(set(rep), {"forgectrl"})
        self.assertEqual(rep["forgectrl"], ["src/cool.c", "src/main.c"])
        rep2 = m.coverage_report(man, [t1, t2, helpers.make_test("a.three", [("forgectrl", "src/**")])],
                                 allow=[("*", "**/*.md")])
        self.assertEqual(rep2, {})
        self.assertNotIn("forgetest", m.coverage_report(man, [], allow=[]),
                         "dev-only components are outside the report")


class CatalogTests(unittest.TestCase):
    def test_catalog_hash_is_definition_only(self):
        r1 = helpers.registry(helpers.make_test("a.one", [("forgectrl", "src/ui.c")]))
        r2 = helpers.registry(helpers.make_test("a.one", [("forgectrl", "src/ui.c")], fn=lambda ctx: 1))
        self.assertEqual(catalog.catalog_hash(r1), catalog.catalog_hash(r2))
        r3 = helpers.registry(helpers.make_test("a.one", [("forgectrl", "src/**")]))
        self.assertNotEqual(catalog.catalog_hash(r1), catalog.catalog_hash(r3))
        r4 = helpers.registry(helpers.make_test("a.one", [("forgectrl", "src/ui.c")], always=True))
        self.assertNotEqual(catalog.catalog_hash(r1), catalog.catalog_hash(r4))

    def test_validate(self):
        r = helpers.registry(helpers.make_test("a.one", [], requires=("a.two",)))
        with self.assertRaises(ValueError):
            catalog.validate(r)
        r = helpers.registry(helpers.make_test("a.one", [], requires=("a.two",)),
                             helpers.make_test("a.two", [], requires=("a.one",)))
        with self.assertRaises(ValueError):
            catalog.validate(r)

    def test_decorator_rules(self):
        with self.assertRaises(ValueError):
            catalog.test("bad id", title="x", subsystem="s")(lambda c: None)
        with self.assertRaises(ValueError):
            catalog.test("s.x", title="x", subsystem="s", covers=[("forgetest", "**")])(lambda c: None)

    def test_real_suite_loads_and_validates(self):
        reg = catalog.load_suite()
        self.assertIn("image.health", reg)
        self.assertTrue(reg["image.health"].always)
        catalog.validate(reg)
        for t in catalog.all_tests(reg):
            self.assertEqual(len(t.source_sha), 64)


if __name__ == "__main__":
    unittest.main()
