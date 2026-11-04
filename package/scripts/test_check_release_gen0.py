# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for check_release_gen0.py (ops#460, ops#482): python3 -m unittest package/scripts/test_check_release_gen0.py"""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

import check_release_gen0 as gen0check


MISSING = object()
# a throwaway repository: none of the machine's identity, signing or hooks
GIT = [
    "git",
    "-c", "user.name=t",
    "-c", "user.email=t@t",
    "-c", "commit.gpgsign=false",
    "-c", "tag.gpgsign=false",
    "-c", "core.hooksPath=.no-hooks",
    "-c", "init.defaultBranch=main",
]


def write_document(root, revision):
    """Document.cpp with `revision`, or with no revision line for None."""
    line = "int main() {}" if revision is None else f"constexpr int ForkNamingRevision = {revision};"
    with open(os.path.join(root, gen0check.DOCUMENT), "w", encoding="utf-8") as document:
        document.write(f"namespace {{\n{line}\n}}\n")


def git(root, *args):
    subprocess.run([*GIT, "-C", root, *args], check=True, capture_output=True)


def make_source(root, revision, generations, macos=None, previous=MISSING, tag="fork-0.7.0"):
    """A git checkout: its first commit's Document.cpp at `previous` (default `revision`; None: no
    revision line) tagged `tag` (None: untagged), then HEAD with Document.cpp at `revision` and
    {k: MANIFEST namingRevision} generations, both halves (gen<k>, gen<k>-macos) alike unless
    `macos` {k: namingRevision, or MISSING for no folder} says otherwise for the macOS half."""
    os.makedirs(os.path.join(root, "src", "App"))
    git(root, "init", "-q")
    write_document(root, revision if previous is MISSING else previous)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "release")
    if tag:
        git(root, "tag", tag)
    write_document(root, revision)
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
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", "after the release")


class CheckReleaseGen0(unittest.TestCase):
    def setUp(self):
        self.fresh_root()

    def fresh_root(self):
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

    def assert_exit_2(self, text):
        """main() exits 2, even with --warn-only, naming `text` on stderr and in the summary."""
        summary = os.path.join(self.root, "summary.md")
        code, out, err = self.run_main("--warn-only", "--summary", summary)
        self.assertEqual(code, 2)
        self.assertIn(text, err)
        self.assertEqual(out, "")
        with open(summary, encoding="utf-8") as written:
            self.assertIn(text, written.read())

    def test_the_previous_releases_generation_passes(self):
        make_source(self.root, 15, {1: 15})
        code, out, _ = self.run_main()
        self.assertIsNone(code)
        self.assertIn("gen1 and gen1-macos hold fork-0.7.0's generation (naming revision 15", out)

    def test_a_naming_bump_since_the_release_passes(self):
        # the first release after a naming PR: its own generation comes after its tag
        make_source(self.root, 17, {1: 15}, previous=15)
        code, out, _ = self.run_main()
        self.assertIsNone(code)
        self.assertIn("naming revision 15; this source's is 17", out)

    def test_a_missing_generation_is_refused(self):
        # fork-0.7.0 bumped the naming revision, and its generation never landed: gen0 is the newest
        make_source(self.root, 17, {0: 12}, previous=15)
        code, _, _ = self.run_main()
        self.assertIsInstance(code, str)
        self.assertIn("gen0 has naming revision 12", code)
        self.assertIn("older than fork-0.7.0's ForkNamingRevision 15", code)
        self.assertIn("fork-0.7.0's generation is gen1, not landed yet", code)
        self.assertIn("Save gen1 and gen1-macos with fork-0.7.0's own build", code)
        self.assertIn("compat_generation=1", code)
        self.assertIn("Refusing to build the release", code)

    def test_a_generation_above_the_source_is_refused(self):
        make_source(self.root, 15, {1: 16})
        code, _, _ = self.run_main()
        self.assertIn("newer than this source's ForkNamingRevision 15", code)

    def test_a_generation_from_a_later_build_is_refused(self):
        # up to the source's revision, but not what the release wrote
        make_source(self.root, 17, {1: 16}, previous=15)
        code, _, _ = self.run_main()
        self.assertIn("newer than fork-0.7.0's ForkNamingRevision 15", code)
        self.assertNotIn("this source's", code)

    def test_both_halves_must_hold_it(self):
        # ops#538: a generation landed with one half from another build
        make_source(self.root, 15, {1: 15}, macos={1: 14})
        code, _, _ = self.run_main()
        self.assertIn("gen1-macos has naming revision 14", code)
        self.assertNotIn("gen1 has", code)
        # only that half is saved again, not a next generation
        self.assertIn("Save gen1-macos with fork-0.7.0's own build", code)
        self.fresh_root()
        make_source(self.root, 15, {1: 14}, macos={1: 15})
        code, _, _ = self.run_main()
        self.assertIn("gen1 has naming revision 14", code)
        self.assertNotIn("gen1-macos has", code)

    def test_a_missing_half_is_exit_2(self):
        make_source(self.root, 15, {1: 15}, macos={1: MISSING})
        self.assert_exit_2("no gen1-macos folder")
        # the newest number counts with either half alone
        self.fresh_root()
        make_source(self.root, 15, {1: 15})
        os.makedirs(os.path.join(self.root, gen0check.COMPAT, "gen2-macos"))
        self.assert_exit_2("no gen2 folder")

    def test_only_the_newest_generation_counts(self):
        # older generations stay as their releases wrote them
        make_source(self.root, 15, {0: 3, 1: 9, 2: 15})
        self.assertIsNone(self.run_main()[0])
        # gen10 is newer than gen2 (a text sort would take gen2)
        self.fresh_root()
        make_source(self.root, 15, {1: 15, 2: 15, 10: 14})
        code, _, _ = self.run_main()
        self.assertIn("gen10 has naming revision 14", code)
        self.fresh_root()
        make_source(self.root, 15, {1: 14, 2: 14, 10: 15})
        self.assertIsNone(self.run_main()[0])

    def test_a_tag_on_head_is_not_its_own_previous_release(self):
        # fork-0.8.0's release run after its tag: fork-0.7.0 is still the previous release
        make_source(self.root, 17, {1: 15}, previous=15)
        git(self.root, "tag", "fork-0.8.0")
        code, out, _ = self.run_main()
        self.assertIsNone(code)
        self.assertIn("fork-0.7.0's generation", out)

    def test_a_release_tagged_on_a_merged_branch_counts(self):
        # fork-0.6.1's way: a hotfix branch from the release, tagged there and merged into
        # integration; the merge's first parent alone would give the tag before it
        make_source(self.root, 15, {1: 15})
        git(self.root, "checkout", "-q", "-b", "hotfix", "fork-0.7.0")
        write_document(self.root, 16)
        git(self.root, "commit", "-q", "-am", "hotfix with a naming bump")
        git(self.root, "tag", "fork-0.7.1")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-edit", "hotfix")
        code, _, _ = self.run_main()
        self.assertIn("older than fork-0.7.1's ForkNamingRevision 16", code)
        self.assertIn("fork-0.7.1's generation is gen2, not landed yet", code)
        # the same with the next release's tag on the merge commit
        git(self.root, "tag", "fork-0.8.0")
        code, _, _ = self.run_main()
        self.assertIn("older than fork-0.7.1's ForkNamingRevision 16", code)

    def test_other_tags_dont_count(self):
        make_source(self.root, 17, {1: 15}, previous=15)
        git(self.root, "tag", "weekly-2026.11.04", "HEAD^")
        self.assertIsNone(self.run_main()[0])

    def test_warn_only_reports_and_passes(self):
        make_source(self.root, 17, {0: 12}, previous=15)
        code, out, err = self.run_main("--warn-only")
        self.assertIsNone(code)
        self.assertIn("::warning::", out)
        self.assertIn("older than", out)
        self.assertEqual(err, "")

    def test_summary_gets_the_result(self):
        make_source(self.root, 17, {0: 12}, previous=15)
        summary = os.path.join(self.root, "summary.md")
        self.run_main("--summary", summary)
        with open(summary, encoding="utf-8") as text:
            self.assertIn("**Refused:**", text.read())

    def test_unreadable_input_is_exit_2_not_a_pass(self):
        # missing revision line
        make_source(self.root, None, {1: 15}, previous=15)
        self.assert_exit_2("no `constexpr int ForkNamingRevision")
        # a MANIFEST without namingRevision
        self.fresh_root()
        make_source(self.root, 15, {1: None})
        self.assert_exit_2("can't read namingRevision")
        # no generation at all
        self.fresh_root()
        make_source(self.root, 15, {})
        os.makedirs(os.path.join(self.root, gen0check.COMPAT))
        self.assert_exit_2("no gen<k> folder")
        # no Compat folder
        self.fresh_root()
        make_source(self.root, 15, {})
        self.assert_exit_2("can't list")

    def test_no_previous_release_is_exit_2(self):
        make_source(self.root, 15, {1: 15}, tag=None)
        self.assert_exit_2("git describe --tags --abbrev=0 --match fork-* HEAD failed")
        # a tag from before the revision line
        self.fresh_root()
        make_source(self.root, 15, {1: 15}, previous=None)
        self.assert_exit_2("line in fork-0.7.0:src/App/Document.cpp")
        # not a git checkout
        self.fresh_root()
        make_source(self.root, 15, {1: 15})
        os.rename(os.path.join(self.root, ".git"), os.path.join(self.root, "not-git"))
        self.assert_exit_2("not a git repository")

    def test_newest_folder_without_manifest_does_not_fall_back(self):
        make_source(self.root, 15, {1: 15})
        os.makedirs(os.path.join(self.root, gen0check.COMPAT, "gen2"))
        os.makedirs(os.path.join(self.root, gen0check.COMPAT, "gen2-macos"))
        self.assert_exit_2("can't read namingRevision")

    def test_naming_revision_must_be_an_int(self):
        for value in ("15", 15.0, True, [15]):
            with self.subTest(value=value):
                self.fresh_root()
                make_source(self.root, 1 if value is True else 15, {1: value})
                self.assert_exit_2("not an integer")


if __name__ == "__main__":
    unittest.main()
