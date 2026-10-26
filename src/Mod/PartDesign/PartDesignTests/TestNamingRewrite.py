# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""A rewrite keeps the state of every reference it doesn't change (FreeCAD-CH, ops#504 E2,
invariant I-S10): code that sets a link property again (Python assignment, a list edit, a
dialog's OK unchanged, a Sketcher's added external) pairs its entries with the old ones by value,
so a guessed reference keeps its record and warning, and a missing one its fingerprint and
mapped name. In documents with ReferenceSolver on, on designed models."""

import os
import shutil
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree

import FreeCAD as App

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import X, Z, edge, face

# The four property classes that hold element references, as dynamic properties of a holder
# outside the body (the global scope: the holder isn't in the body)
PROPERTIES = {
    "LinkSub": "App::PropertyLinkSubGlobal",
    "LinkSubList": "App::PropertyLinkSubListGlobal",
    "XLinkSub": "App::PropertyXLinkSub",
    "XLinkSubList": "App::PropertyXLinkSubList",
}
SINGLE = ("LinkSub", "XLinkSub")


def setRefs(holder, name, obj, subs):
    """Sets holder.name to subs of obj, in the Python form of its class."""
    if name in SINGLE:
        setattr(holder, name, (obj, list(subs)))
    else:
        setattr(holder, name, [(obj, tuple(subs))])


def refSubs(holder, name):
    """The subs holder.name holds, in order."""
    value = getattr(holder, name)
    if name in SINGLE:
        return list(value[1]) if value else []
    return [sub for _, subs in value for sub in subs]


class TestNamingRewrite(unittest.TestCase):
    def setUp(self):
        self.documents = []

    def tearDown(self):
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    def newDocument(self):
        doc = models.newDocument("NamingRewrite")
        doc.HistoryAlgorithm = "V2"
        doc.ReferenceSolver = True
        self.documents.append(doc.Name)
        return doc

    def savedEntries(self, doc, objectName, propertyName):
        """The saved attributes of each entry of `objectName.propertyName`, in order."""
        folder = tempfile.mkdtemp(prefix="NamingRewrite")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Saved.FCStd")
        doc.saveCopy(path)
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Document.xml"))
        for obj in root.iter("Object"):
            if obj.get("name") != objectName:
                continue
            for prop in obj.iter("Property"):
                if prop.get("name") != propertyName:
                    continue
                return [
                    dict(element.attrib)
                    for element in prop.iter()
                    if element.tag in ("Sub", "Link")
                    or (element.tag == "XLink" and "sub" in element.attrib)
                ]
        raise AssertionError(f"{objectName}.{propertyName} isn't saved")

    def guesses(self, obj, propertyName):
        """{index: guess kind} of obj's report entries of propertyName that hold a guess."""
        return {
            entry["index"]: entry["guess_kind"]
            for entry in App.getReferenceReport(obj)
            if entry["property"] == propertyName and entry.get("guess_kind")
        }

    def guessedHolder(self, doc):
        """A pad of the rectangle 0..20 x 0..10, 10 high, and a holder whose four properties
        reference its vertical edge at (20, 0); the profile redrawn from another corner, so each
        reference is a tier 3 guess (TestNamingSolver.redraw()). Returns (pad, holder, the
        other vertical edge at (0, 0))."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        holder = doc.addObject("App::FeaturePython", "Holder")
        corner = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)
        for name, typeName in PROPERTIES.items():
            holder.addProperty(typeName, name)
            setRefs(holder, name, pad, corner)
        doc.recompute()
        profile.deleteAllGeometry()
        profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()
        for name in PROPERTIES:
            self.assertEqual(self.guesses(holder, name), {0: "tier3"}, name)
        other = edge("line", direction=Z, through=(0, 0, 0)).one(pad.Shape)[0]
        return pad, holder, other

    def testSameValueKeepsTheGuess(self):
        """The value assigned again, as a dialog's OK unchanged does: each class keeps the guess,
        and so does the next recompute."""
        doc = self.newDocument()
        pad, holder, _ = self.guessedHolder(doc)

        for name in PROPERTIES:
            with self.subTest(name):
                setattr(holder, name, getattr(holder, name))

                self.assertEqual(self.guesses(holder, name), {0: "tier3"})
                [entry] = self.savedEntries(doc, "Holder", name)
                self.assertEqual(entry.get("guess"), "tier3")
        doc.recompute()
        for name in PROPERTIES:
            self.assertEqual(self.guesses(holder, name), {0: "tier3"}, name)
        self.assertIn("Warning", holder.State)

    def testAddedEntryKeepsTheGuess(self):
        """An entry added before the guessed one (setValues without shadows, a count change):
        the guess follows its reference to index 1, and the added one starts without a record."""
        doc = self.newDocument()
        pad, holder, other = self.guessedHolder(doc)

        for name in PROPERTIES:
            with self.subTest(name):
                corner = refSubs(holder, name)[0]

                setRefs(holder, name, pad, [other, corner])

                self.assertEqual(refSubs(holder, name), [other, corner])
                self.assertEqual(self.guesses(holder, name), {1: "tier3"})
                entries = self.savedEntries(doc, "Holder", name)
                self.assertNotIn("guess", entries[0])
                self.assertEqual(entries[1].get("guess"), "tier3")
        doc.recompute()
        for name in PROPERTIES:
            self.assertEqual(self.guesses(holder, name), {1: "tier3"}, name)

    def testRemovedEntryKeepsTheOthersGuess(self):
        """Two guessed references, the first removed: the one left keeps its guess."""
        doc = self.newDocument()
        pad, holder, other = self.guessedHolder(doc)
        for name in PROPERTIES:
            setRefs(holder, name, pad, [other] + refSubs(holder, name))
        doc.recompute()

        for name in PROPERTIES:
            with self.subTest(name):
                corner = refSubs(holder, name)[1]

                setRefs(holder, name, pad, [corner])

                self.assertEqual(self.guesses(holder, name), {0: "tier3"})

    def testUndoAndRedoKeepTheGuess(self):
        """An added entry undone and redone: the guess is back on its reference each time."""
        doc = self.newDocument()
        doc.UndoMode = 1
        pad, holder, other = self.guessedHolder(doc)

        for name in PROPERTIES:
            with self.subTest(name):
                corner = refSubs(holder, name)[0]
                doc.openTransaction("add " + name)
                setRefs(holder, name, pad, [other, corner])
                doc.commitTransaction()

                doc.undo()
                self.assertEqual(refSubs(holder, name), [corner])
                self.assertEqual(self.guesses(holder, name), {0: "tier3"})

                doc.redo()
                self.assertEqual(refSubs(holder, name), [other, corner])
                self.assertEqual(self.guesses(holder, name), {1: "tier3"})

    def testRepickOfTheSameElementByIndexKeepsTheGuess(self):
        """The guessed element picked again by its index name (as the attachment editor and
        Python write it), alone: the same reference, so it keeps its record (the user ends a
        guess with Accept or Repair)."""
        doc = self.newDocument()
        pad, holder, _ = self.guessedHolder(doc)
        corner = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)

        for name in PROPERTIES:
            with self.subTest(name):
                setRefs(holder, name, pad, corner)

                self.assertEqual(self.guesses(holder, name), {0: "tier3"})

    def testIndexRepickAfterAnUpstreamEditTakesThePick(self):
        """A notch before the guessed edge renumbers the pad's edges: the reference follows its
        edge to its new index. A re-pick by the old index then names another element: it is the
        pick, with no record, and the next recompute keeps it there (E2's key: an index-only sub
        pairs only with an entry whose mapped name gives that index now)."""
        doc = self.newDocument()
        pad, holder, _ = self.guessedHolder(doc)
        oldIndex = refSubs(holder, "LinkSubList")[0]
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(
            models.polygon([(0, 0), (0, 3), (-2, 3), (-2, 7), (0, 7), (0, 10), (20, 10), (20, 0)]),
            False,
        )
        doc.recompute()
        corner = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)[0]
        self.assertNotEqual(corner, oldIndex)
        picked = pad.Shape.getElement(oldIndex)
        self.assertGreater(picked.CenterOfMass.distanceToPoint(App.Vector(20, 0, 5)), 1)

        for name in PROPERTIES:
            with self.subTest(name):
                self.assertEqual(refSubs(holder, name), [corner])

                setRefs(holder, name, pad, [oldIndex])

                self.assertEqual(self.guesses(holder, name), {})
        doc.recompute()
        for name in PROPERTIES:
            with self.subTest(name):
                self.assertEqual(refSubs(holder, name), [oldIndex])
                self.assertEqual(self.guesses(holder, name), {})

    def testAnotherObjectsEntryKeepsNoRecord(self):
        """The same sub of another object is another reference: the value set to the copy's edge
        keeps no record."""
        doc = self.newDocument()
        pad, holder, _ = self.guessedHolder(doc)
        box = doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 20, 10, 10
        doc.recompute()

        for name in PROPERTIES:
            with self.subTest(name):
                setRefs(holder, name, box, refSubs(holder, name))

                self.assertEqual(self.guesses(holder, name), {})

    def testLabelChangeKeepsTheOtherEntriesGuess(self):
        """Beside the guessed edge, an entry that names a sketch of the body by its label
        (`$Aux.Edge1`); the sketch is renamed. The label change rewrites that entry's path
        (CopyOnLabelChange() and Paste()); the guessed entry keeps its record (the review of
        fork PR 386, R1: Paste set the copy's empty records over the ones the setter kept). In a
        LinkSub and an XLinkSub the guessed sub goes through the body too."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        aux = models.sketch(doc, "Aux", models.rectangle(0, 20, 5, 25), body)
        doc.recompute()
        [corner] = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)
        holder = doc.addObject("App::FeaturePython", "Holder")
        for name, typeName in PROPERTIES.items():
            holder.addProperty(typeName, name)
            if name in SINGLE:
                setRefs(holder, name, body, [f"{pad.Name}.{corner}", "$Aux.Edge1"])
            else:
                setattr(holder, name, [(pad, (corner,)), (body, ("$Aux.Edge1",))])
        doc.recompute()
        profile.deleteAllGeometry()
        profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()
        #   (an XLinkSubList orders its objects by itself: the pad's entry may come second)
        before = {name: self.guesses(holder, name) for name in PROPERTIES}
        for name, guesses in before.items():
            self.assertEqual(list(guesses.values()), ["tier3"], name)

        aux.Label = "Aux2"

        self.assertEqual(holder.LinkSubList[1][1], ("$Aux2.Edge1",))
        for name, guesses in before.items():
            with self.subTest(name):
                self.assertEqual(self.guesses(holder, name), guesses)
        doc.recompute()
        for name, guesses in before.items():
            self.assertEqual(self.guesses(holder, name), guesses, name)

    def missingHolder(self, doc):
        """AmbiguousHalves' model (TestNamingSolver): a pad's top face that a groove across the
        middle splits into two halves. The holder's four properties reference the top face:
        each breaks, as '?FaceN' with its mapped name and fingerprint kept. Returns (groove,
        holder, a side face)."""
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        sketch = models.sketch(doc, "GrooveSketch", models.rectangle(16, 2, 18, 4), body, z=10)
        groove = models.pocket(body, sketch, 4, "Groove")
        doc.recompute()
        top = face("plane", normal=Z, through=(0, 0, 10)).one(groove.Shape)
        holder = doc.addObject("App::FeaturePython", "Holder")
        for name, typeName in PROPERTIES.items():
            holder.addProperty(typeName, name)
            setRefs(holder, name, groove, top)
        doc.recompute()
        models.moveRectangle(sketch, 9, -1, 11, 11)
        doc.recompute()
        side = face("plane", normal=X, through=(20, 0, 0)).one(groove.Shape)[0]
        return groove, holder, side

    def testMissingEntryKeepsItsFingerprintAndName(self):
        """A broken reference ('?Face5') and an entry added after it: the broken one keeps its
        fingerprint and its mapped name, which a later edit can find it again by (N12)."""
        doc = self.newDocument()
        groove, holder, side = self.missingHolder(doc)
        before = {}
        for name in PROPERTIES:
            [entry] = self.savedEntries(doc, "Holder", name)
            self.assertTrue(refSubs(holder, name)[0].startswith("?Face"), name)
            self.assertIn("fp", entry, name)
            self.assertIn("shadow", entry, name)
            before[name] = entry

        for name in PROPERTIES:
            with self.subTest(name):
                missing = refSubs(holder, name)[0]

                setRefs(holder, name, groove, [missing, side])

                entries = self.savedEntries(doc, "Holder", name)
                self.assertEqual(entries[0]["fp"], before[name]["fp"])
                self.assertEqual(entries[0].get("shadow"), before[name]["shadow"])
                self.assertNotEqual(entries[1].get("fp"), before[name]["fp"])

    def testSketchSecondExternalKeepsTheFirstsGuess(self):
        """A sketch projecting the pad's corner edge, guessed after the redraw: adding a second
        external keeps the first one's record (the Sketcher's setExternalLinks passes the kept
        links' shadows with a count change)."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        sketch = models.sketch(doc, "Projection", [], body, z=20)
        top = edge("line", direction=X, through=(0, 0, 10)).one(pad.Shape)[0]
        sketch.addExternal(pad.Name, top)
        doc.recompute()
        profile.deleteAllGeometry()
        profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()
        self.assertEqual(self.guesses(sketch, "ExternalGeometry"), {0: "tier3"})

        back = edge("line", direction=X, through=(0, 10, 10)).one(pad.Shape)[0]
        sketch.addExternal(pad.Name, back)

        self.assertEqual(len(sketch.ExternalGeometry[0][1]), 2)
        self.assertEqual(self.guesses(sketch, "ExternalGeometry"), {0: "tier3"})
        doc.recompute()
        self.assertTrue(sketch.isValid())
        self.assertEqual(self.guesses(sketch, "ExternalGeometry"), {0: "tier3"})

    def testBinderSupportEditKeepsTheGuess(self):
        """A SubShapeBinder of the pad's corner edge, guessed after the redraw: a second edge
        added to its Support (as a drop or the binder's task panel do, through
        PropertyXLinkSubList.setValues()) keeps the first one's record."""
        doc = self.newDocument()
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        corner = edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape)[0]
        binder.Support = [(pad, (corner,))]
        doc.recompute()
        profile.deleteAllGeometry()
        profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()
        self.assertEqual(self.guesses(binder, "Support"), {0: "tier3"})
        held = binder.Support[0][1][0]

        other = edge("line", direction=Z, through=(0, 0, 0)).one(pad.Shape)[0]
        binder.Support = [(pad, (held, other))]

        self.assertEqual(self.guesses(binder, "Support"), {0: "tier3"})
        doc.recompute()
        self.assertEqual(self.guesses(binder, "Support"), {0: "tier3"})
