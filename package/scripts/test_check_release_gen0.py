# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for check_release_gen0.py (ops#460): python3 -m unittest package/scripts/test_check_release_gen0.py"""

import contextlib
import io
import json
import os
import tempfile
import unittest

import check_release_gen0 as gen0check


MISSING = object()


def make_source(root, revision, generations, macos=None):
    """A source tree with Document.cpp at `revision` and {k: MANIFEST namingRevision} generations,
    both halves (gen<k>, gen<k>-macos) alike unless `macos` {k: namingRevision, or MISSING for no
    folder} says otherwise for the macOS half."""
    os.makedirs(os.path.join(root, "src", "App"))
    with open(os.path.join(root, gen0check.DOCUMENT), "w", encoding="utf-8") as document:
        document.write(f"namespace {{\nconstexpr int ForkNamingRevision = {revision};\n}}\n")
    halves = [(f"gen{k}", naming) for k, naming in generations.items()]
    for k, naming in generations.items():
        naming = (macos or {}).get(k, naming)
        if naming is not MISSING:
            halves.append((f"gen{k}-macos", naming))
    for name, naming in halves:
        folder = os.path.join(root, gen0check.COMPAT, name)
        os.makedirs(folder)
        manifest = {"build": "26 3 0 1 (Git) fix/x ddd509d6f94606011f8d19b0b6ccb7aed235ec10"}
        if naming is not None:
            manifest["namingRevision"] = naming
        with open(os.path.join(folder, "MANIFEST"), "w", encoding="utf-8") as out:
            json.dump(manifest, out)


class CheckReleaseGen0(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def run_main(self, *extra):
        """(exit code or None, stdout, stderr) of main() on self.root."""
        out, err = io.StringIO(), io.StringIO()
        argv = ["check_release_gen0.py", "--source", self.root, *extra]
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            old, gen0check.sys.argv = gen0check.sys.argv, argv
            try:
                gen0check.main()
            except SystemExit as stop:
                code = stop.code
            finally:
                gen0check.sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_current_gen0_passes(self):
        make_source(self.root, 6, {0: 6})
        code, out, _ = self.run_main()
        self.assertIsNone(code)
        self.assertIn("gen0 and gen0-macos are current (naming revision 6)", out)

    def test_both_halves_must_be_current(self):
        # ops#538: a batch that regenerated only one half
        make_source(self.root, 6, {0: 6}, macos={0: 5})
        code, _, _ = self.run_main()
        self.assertIn("gen0-macos has naming revision 5", code)
        self.assertNotIn("gen0 has", code)
        self.fresh_root()
        make_source(self.root, 6, {0: 5}, macos={0: 6})
        code, _, _ = self.run_main()
        self.assertIn("gen0 has naming revision 5", code)
        self.assertNotIn("gen0-macos has", code)

    def test_a_missing_half_is_exit_2(self):
        make_source(self.root, 6, {0: 6}, macos={0: MISSING})
        self.assert_exit_2("no gen0-macos folder")
        # the newest number counts with either half alone
        self.fresh_root()
        make_source(self.root, 6, {0: 6})
        os.makedirs(os.path.join(self.root, gen0check.COMPAT, "gen1-macos"))
        self.assert_exit_2("no gen1 folder")

    def test_aged_gen0_is_refused(self):
        make_source(self.root, 6, {0: 3})
        code, _, _ = self.run_main()
        self.assertIsInstance(code, str)
        self.assertIn("gen0 has naming revision 3", code)
        self.assertIn("older than", code)
        self.assertIn("regen_gen0.sh --install", code)
        self.assertIn("Refusing to build the release", code)

    def test_newer_gen0_is_refused_too(self):
        make_source(self.root, 6, {0: 7})
        code, _, _ = self.run_main()
        self.assertIn("newer than", code)

    def test_only_the_newest_generation_counts(self):
        # after the beta an old generation stays old on purpose; the newest must match
        make_source(self.root, 6, {0: 3, 1: 6, 2: 6})
        self.assertIsNone(self.run_main()[0])
        # gen10 is newer than gen2 (a text sort would take gen2)
        self.fresh_root()
        make_source(self.root, 6, {0: 6, 1: 6, 2: 6, 10: 5})
        code, _, _ = self.run_main()
        self.assertIn("gen10 has naming revision 5", code)
        self.fresh_root()
        make_source(self.root, 6, {0: 5, 2: 5, 10: 6})
        self.assertIsNone(self.run_main()[0])

    def test_warn_only_reports_and_passes(self):
        make_source(self.root, 6, {0: 3})
        code, out, err = self.run_main("--warn-only")
        self.assertIsNone(code)
        self.assertIn("::warning::", out)
        self.assertIn("older than", out)
        self.assertEqual(err, "")

    def test_summary_gets_the_result(self):
        make_source(self.root, 6, {0: 3})
        summary = os.path.join(self.root, "summary.md")
        self.run_main("--summary", summary)
        with open(summary, encoding="utf-8") as text:
            self.assertIn("**Refused:**", text.read())

    def assert_exit_2(self, text):
        """main() exits 2, even with --warn-only, naming `text` on stderr and in the summary."""
        summary = os.path.join(self.root, "summary.md")
        code, out, err = self.run_main("--warn-only", "--summary", summary)
        self.assertEqual(code, 2)
        self.assertIn(text, err)
        self.assertEqual(out, "")
        with open(summary, encoding="utf-8") as written:
            self.assertIn(text, written.read())

    def fresh_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def test_unreadable_input_is_exit_2_not_a_pass(self):
        # missing revision line
        make_source(self.root, 6, {0: 6})
        with open(os.path.join(self.root, gen0check.DOCUMENT), "w", encoding="utf-8") as document:
            document.write("int main() {}\n")
        self.assert_exit_2("no `constexpr int ForkNamingRevision")
        # a MANIFEST without namingRevision
        self.fresh_root()
        make_source(self.root, 6, {0: None})
        self.assert_exit_2("can't read namingRevision")
        # no generation at all
        self.fresh_root()
        make_source(self.root, 6, {})
        os.makedirs(os.path.join(self.root, gen0check.COMPAT))
        self.assert_exit_2("no gen<k> folder")
        # no Compat folder
        self.fresh_root()
        make_source(self.root, 6, {})
        self.assert_exit_2("can't list")

    def test_newest_folder_without_manifest_does_not_fall_back(self):
        make_source(self.root, 6, {0: 6})
        os.makedirs(os.path.join(self.root, gen0check.COMPAT, "gen1"))
        os.makedirs(os.path.join(self.root, gen0check.COMPAT, "gen1-macos"))
        self.assert_exit_2("can't read namingRevision")

    def test_naming_revision_must_be_an_int(self):
        for value in ("6", 6.0, True, [6]):
            with self.subTest(value=value):
                self.fresh_root()
                make_source(self.root, 1 if value is True else 6, {0: value})
                self.assert_exit_2("not an integer")


if __name__ == "__main__":
    unittest.main()
