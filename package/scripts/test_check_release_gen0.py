# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for check_release_gen0.py (ops#460): python3 -m unittest package/scripts/test_check_release_gen0.py"""

import contextlib
import io
import json
import os
import tempfile
import unittest

import check_release_gen0 as gen0check


def make_source(root, revision, generations):
    """A source tree with Document.cpp at `revision` and {k: MANIFEST namingRevision} generations."""
    os.makedirs(os.path.join(root, "src", "App"))
    with open(os.path.join(root, gen0check.DOCUMENT), "w", encoding="utf-8") as document:
        document.write(f"namespace {{\nconstexpr int ForkNamingRevision = {revision};\n}}\n")
    for k, naming in generations.items():
        folder = os.path.join(root, gen0check.COMPAT, f"gen{k}")
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
        self.assertIn("gen0 is current (naming revision 6)", out)

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
        tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(tmp2.cleanup)
        make_source(tmp2.name, 6, {0: 6, 1: 6, 10: 5})
        self.root = tmp2.name
        code, _, _ = self.run_main()
        self.assertIn("gen10 has naming revision 5", code)

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

    def test_unreadable_input_is_exit_2_not_a_pass(self):
        # missing revision line
        make_source(self.root, 6, {0: 6})
        with open(os.path.join(self.root, gen0check.DOCUMENT), "w", encoding="utf-8") as document:
            document.write("int main() {}\n")
        self.assertIn("no `constexpr int ForkNamingRevision", self.run_main("--warn-only")[0])
        # a MANIFEST without namingRevision
        tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(tmp2.cleanup)
        make_source(tmp2.name, 6, {0: None})
        self.root = tmp2.name
        self.assertIn("can't read namingRevision", self.run_main("--warn-only")[0])
        # no generation at all
        tmp3 = tempfile.TemporaryDirectory()
        self.addCleanup(tmp3.cleanup)
        make_source(tmp3.name, 6, {})
        os.makedirs(os.path.join(tmp3.name, gen0check.COMPAT))
        self.root = tmp3.name
        self.assertIn("no gen<k> folder", self.run_main()[0])


if __name__ == "__main__":
    unittest.main()
