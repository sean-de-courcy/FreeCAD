# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (notes/derived-design.md, slice 0: same-document Derived under the team's follow-ups)

"""What the team's Insert studios do after a Derived (inventory: splitPart, booleanBodies,
deleteBodies after importDerived): split the derived part, subtract with it as target and as tool,
delete it; then the source is edited, and the document saved and reopened.

Designed geometry: Part Studio 1 (the top level) holds Body "Box", a 10 x 10 x 10 box from
x = -5 to 5 (1000 mm^3). Part Studio 2 is an App::Part at the origin; the Box is derived into it.
Its YZ origin plane halves the box (500 + 500). A "Pin" part (2 x 2 x 10 inside the box) and a
"Slab" part (30 x 10 x 10 from x = -15, 3000) are made in Part Studio 2 as the other operands.
The source edit: the box's height 10 to 20 (2000)."""

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import PartDesign

V = App.Vector


def boxBody(doc, container, name, length, x=0, width=10, height=10, y=0):
    body = doc.addObject("PartDesign::Body", name)
    if container is not None:
        container.addObject(body)
    box = body.newObject("PartDesign::AdditiveBox", name + "Box")
    box.Length = length
    box.Width = width
    box.Height = height
    box.Placement.Base = V(x, y, 0)
    return body, box


class TestDerivedFollowUps(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("DerivedFollowUps")
        self.box, self.boxFeature = boxBody(self.doc, None, "Box", 10, x=-5)
        self.studio2 = self.doc.addObject("App::Part", "Studio2")
        self.studio2.Label = "Part Studio 2"
        self.doc.recompute()
        self.lead = PartDesign.makeDerived(self.studio2, [self.box])
        self.doc.recompute()
        self.derived = self.lead.getParentGeoFeatureGroup()
        self.folder = tempfile.mkdtemp(prefix="derivedfollow")

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name.startswith("DerivedFollowUps"):
                App.closeDocument(name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def editSource(self):
        self.boxFeature.Height = 20
        self.doc.recompute()

    def reopen(self):
        path = os.path.join(self.folder, "DerivedFollowUps.FCStd")
        names = {
            k: v.Name for k, v in vars(self).items() if hasattr(v, "Name") and hasattr(v, "Document")
        }
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        for key, name in names.items():
            setattr(self, key, self.doc.getObject(name))
        self.doc.recompute()

    def parts(self):
        """The studio's parts that stand: Bodies with a shape, not deleted, not consumed."""
        return [
            b for b in PartDesign.derivableParts(self.studio2) if PartDesign.consumerOf(b) is None
        ]

    def yzPlane(self):
        """The studio's Right plane, as the GUI passes it: the part's own origin plane standing
        for it (BodyBase::studioOriginFeature)."""
        plane = [f for f in self.studio2.Origin.OriginFeatures if f.Role == "YZ_Plane"][0]
        own = PartDesign.studioOriginFeature(self.derived, plane)
        self.assertIsNotNone(own)
        return own

    def assertValid(self, *objs):
        for obj in objs:
            self.assertTrue(obj.isValid(), obj.Label + ": " + obj.getStatusString())

    def testSplitTheDerivedPart(self):
        """Split by the YZ plane: two parts of 500; the source to height 20: 1000 each; the same
        after save and reopen."""
        other = PartDesign.split(self.derived, self.yzPlane(), "Front")
        self.doc.recompute()
        self.other = other
        self.assertValid(self.lead, self.derived, other)
        self.assertEqual(len(self.parts()), 2)
        self.assertEqual(sorted(round(b.Shape.Volume, 6) for b in self.parts()), [500, 500])
        self.editSource()
        self.assertEqual(sorted(round(b.Shape.Volume, 6) for b in self.parts()), [1000, 1000])
        self.reopen()
        self.assertValid(self.lead, self.derived, self.other)
        self.assertEqual(sorted(round(b.Shape.Volume, 6) for b in self.parts()), [1000, 1000])

    def testSubtractFromTheDerivedPart(self):
        """The derived part as the target: the Pin (2 x 2 x 10) cut out, 960; Pin consumed; the
        source to height 20 (the pin still 10 high): 1960; the same after reopen."""
        pin, _ = boxBody(self.doc, self.studio2, "Pin", 2, x=-1, width=2, y=4)
        self.doc.recompute()
        cut = self.derived.newObject("PartDesign::Boolean", "Subtract")
        cut.setObjects([pin])
        cut.Type = "Cut"
        cut.KeepTools = False
        self.doc.recompute()
        self.cut = cut
        self.assertValid(cut, self.derived)
        self.assertAlmostEqual(self.derived.Shape.Volume, 960, places=6)
        self.assertEqual(self.parts(), [self.derived])
        self.editSource()
        self.assertAlmostEqual(self.derived.Shape.Volume, 1960, places=6)
        self.reopen()
        self.assertValid(self.cut, self.derived)
        self.assertAlmostEqual(self.derived.Shape.Volume, 1960, places=6)

    def testSubtractWithTheDerivedPart(self):
        """The derived part as the tool: cut from the Slab (3000), 2000, the derived part consumed;
        the source to height 20 (taller than the slab): still 2000; the same after reopen."""
        slab, _ = boxBody(self.doc, self.studio2, "Slab", 30, x=-15)
        self.doc.recompute()
        cut = slab.newObject("PartDesign::Boolean", "Subtract")
        cut.setObjects([self.derived])
        cut.Type = "Cut"
        cut.KeepTools = False
        self.doc.recompute()
        self.slab = slab
        self.assertValid(cut, slab, self.lead)
        self.assertAlmostEqual(slab.Shape.Volume, 2000, places=6)
        self.assertEqual(self.parts(), [slab])
        self.boxFeature.Height = 5
        self.doc.recompute()
        self.assertAlmostEqual(slab.Shape.Volume, 2500, places=6)
        self.reopen()
        self.assertValid(self.slab, self.lead)
        self.assertAlmostEqual(self.slab.Shape.Volume, 2500, places=6)

    def testDeleteTheDerivedPart(self):
        """Delete part on the derived part: no part left in the studio; the source edited and the
        document reopened: still none, nothing failing."""
        PartDesign.deletePart(self.derived)
        self.doc.recompute()
        self.assertEqual(self.parts(), [])
        self.editSource()
        self.reopen()
        self.assertEqual(self.parts(), [])
        self.assertValid(self.lead)
