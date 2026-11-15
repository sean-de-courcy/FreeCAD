# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 4).

"""One file is one document, whatever the spelling of its path (FreeCAD-CH, folder sync item 4).

notes/folder-sync.md 2.1 and section 3 item 4. A file opened under two spellings of its path (the
case of a folder, a `..`) was opened twice, two documents of one file, and a link written with
another spelling opened a second copy beside the open one. Now `openDocument` returns the open
document when the path names the same file on disk, and a link attaches to it.

Designed documents: `Parts/A.FCStd` holds one App::FeatureTest, "Marker"; `B.FCStd` beside the
folder holds an App::Link to it. All are made by the test in a temporary folder. The case tests run
on a case-insensitive volume only (Windows, default APFS) and are skipped elsewhere."""

import os
import shutil
import tempfile
import unittest

import FreeCAD


class TestOneFileOneDocument(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fcch-spelling-")
        os.mkdir(os.path.join(self.root, "Parts"))
        self.caseInsensitive = os.path.isdir(os.path.join(self.root, "PARTS"))
        self.before = set(FreeCAD.listDocuments())
        doc = FreeCAD.newDocument("SpellA")
        doc.addObject("App::FeatureTest", "Marker")
        doc.saveAs(self.path("Parts", "A.FCStd"))
        FreeCAD.closeDocument(doc.Name)

    def tearDown(self):
        for name in set(FreeCAD.listDocuments()) - self.before:
            FreeCAD.closeDocument(name)
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def opened(self):
        """The documents this test opened, by name."""
        return sorted(set(FreeCAD.listDocuments()) - self.before)

    def needsCaseInsensitive(self):
        if not self.caseInsensitive:
            self.skipTest("the volume tells PARTS from Parts")

    def testTwoCasesOpenOneDocument(self):
        """`Parts/A.FCStd`, then `PARTS/A.FCStd`: the second open returns the first document."""
        self.needsCaseInsensitive()
        first = FreeCAD.openDocument(self.path("Parts", "A.FCStd"))
        second = FreeCAD.openDocument(self.path("PARTS", "A.FCStd"))
        self.assertEqual(second.Name, first.Name)
        self.assertEqual(self.opened(), [first.Name])

    def testADotDotSpellingOpensOneDocument(self):
        """`Parts/A.FCStd`, then `Parts/../Parts/A.FCStd` (any volume): one document."""
        first = FreeCAD.openDocument(self.path("Parts", "A.FCStd"))
        second = FreeCAD.openDocument(self.path("Parts", "..", "Parts", "A.FCStd"))
        self.assertEqual(second.Name, first.Name)
        self.assertEqual(self.opened(), [first.Name])

    def testALinkInAnotherCaseUsesTheOpenDocument(self):
        """B links A as `parts/A.FCStd` (saved while A was open under that spelling). With A open
        as `Parts/A.FCStd`, opening B resolves its link to that A: two documents, not three, and
        the link's object is A's Marker."""
        self.needsCaseInsensitive()
        lowerA = FreeCAD.openDocument(self.path("parts", "A.FCStd"))
        b = FreeCAD.newDocument("SpellB")
        link = b.addObject("App::Link", "Link")
        link.LinkedObject = lowerA.getObject("Marker")
        b.recompute()
        b.saveAs(self.path("B.FCStd"))
        FreeCAD.closeDocument(b.Name)
        FreeCAD.closeDocument(lowerA.Name)
        with open(self.path("B.FCStd"), "rb") as f:
            import zipfile

            with zipfile.ZipFile(f) as z:
                xml = z.read("Document.xml").decode("utf-8")
        self.assertIn('file="parts/A.FCStd"', xml)

        a = FreeCAD.openDocument(self.path("Parts", "A.FCStd"))
        b = FreeCAD.openDocument(self.path("B.FCStd"))
        self.assertEqual(sorted(self.opened()), sorted([a.Name, b.Name]))
        linked = b.getObject("Link").LinkedObject
        self.assertIsNotNone(linked)
        self.assertEqual(linked.Document.Name, a.Name)
        self.assertEqual(linked.Name, "Marker")


if __name__ == "__main__":
    unittest.main()
