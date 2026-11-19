# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#910: a studio copied into another document computes as its file does
#
# One file per document: a studio saved in its own file is copied into a document that already
# holds another studio (Document.copyObject, or Merge project). The copies must then recompute as
# the file alone does: no feature in error, every Body's shape the same.
#
# What went wrong (measured on merged documents, then read):
# - A copy (Document.copyObject, a paste) drops the element maps (the export doesn't write them;
#   Merge project reads the file itself and keeps them), so a copy's shape has no names until its
#   first recompute, and the references into it hold an index and a fingerprint.
#   A feature whose Placement the file doesn't give back bit for bit (a sketch placed at an angle)
#   is moved at its first recompute, before its new shape is set. The moved
#   shape, still the imported one, was named by a match (provisional MLN names), the references
#   took those names, and the feature's real result then had none of them: "Ambiguous face
#   reference: Face10 moved and Face10 sits where it was".
# - A Boolean's tool that is in a group of its own (a Body in the studio's App::Part, another
#   Body's feature) was dropped from the Boolean's list by the import: "Boolean has no tools".
#
# Designed geometry only, in a frame turned 37 degrees about (1, 2, 3): the sketches are placed by
# that Placement, without an attachment, and what follows is in the frame's coordinates. Part A: a
# pad x 0..20, y 0..10, 10 high (2000); a pad of its top face, 2 high (400); a fillet, radius 1, of
# the top edge along x at y 0, 20 long (takes (1 - pi/4) * 20); a pocket on a sketch on the top
# face, 4 x 4, 3 deep (48); a Subtract of part B (the overlap x 15..20, y 2..8, 4 high: 120); a
# fillet, radius 1, of the notch's inner edge at x 15, z 4, 6 long (a concave edge: adds
# (1 - pi/4) * 6). Part B: a pad x 15..25, y 2..8, 4 high (240). Both parts are in an App::Part.

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.TestStudio import pad, rect

V = App.Vector
ROUND = 1 - math.pi / 4  # a fillet of radius 1 takes this much per unit length of a square edge
VOLUME_A = 2000 + 400 - ROUND * 20 - 48 - 120 + ROUND * 6
VOLUME_B = 240
# The frame: a turn whose quaternion a file doesn't give back bit for bit
FRAME = App.Placement(V(0, 0, 0), App.Rotation(V(1, 2, 3), 37))
TO_FRAME = FRAME.inverse()


def faceAt(feature, z, nz=1):
    """The planar face of feature's shape at height z facing nz, in the frame."""
    for i, face in enumerate(feature.Shape.Faces, 1):
        if (
            face.Surface.__class__.__name__ == "Plane"
            and abs(TO_FRAME.Rotation.multVec(face.normalAt(0, 0)).z - nz) < 1e-9
            and abs(TO_FRAME.multVec(face.CenterOfMass).z - z) < 1e-6
        ):
            return f"Face{i}"
    return None


def edgeAt(feature, start, end):
    """The edge of feature's shape between the points start and end of the frame."""
    for i, edge in enumerate(feature.Shape.Edges, 1):
        ends = {
            tuple(round(c, 6) + 0.0 for c in TO_FRAME.multVec(v.Point)) for v in edge.Vertexes
        }
        if ends == {tuple(map(float, start)), tuple(map(float, end))}:
            return f"Edge{i}"
    return None


def placedSketch(body, name, *rects):
    """A sketch in the frame's xy plane: placed, not attached."""
    s = body.newObject("Sketcher::SketchObject", name)
    s.Placement = FRAME
    for r in rects:
        rect(s, *r)
    return s


def buildStudio(name, shift):
    """A document holding one studio (an App::Part with the parts A and B), moved by shift along
    the frame's x."""
    doc = App.newDocument(name)
    studio = doc.addObject("App::Part", "Studio")
    a = doc.addObject("PartDesign::Body", "A")
    studio.addObject(a)
    first = pad(a, "APad", placedSketch(a, "ASketch", (shift, 0, shift + 20, 10)), 10)
    doc.recompute()

    second = a.newObject("PartDesign::Pad", "APad2")
    second.Profile = (first, [faceAt(first, 10)])
    second.Length = 2
    doc.recompute()

    fillet = a.newObject("PartDesign::Fillet", "AFillet")
    fillet.Base = (second, [edgeAt(second, (shift, 0, 12), (shift + 20, 0, 12))])
    fillet.Radius = 1
    doc.recompute()

    onTop = a.newObject("Sketcher::SketchObject", "ASketch2")
    onTop.AttachmentSupport = [(fillet, faceAt(fillet, 12))]
    onTop.MapMode = "FlatFace"
    doc.recompute()
    # The square x 2..6, y 3..7 of the frame, in the sketch's own coordinates (the face gives the
    # sketch its directions)
    toSketch = onTop.getGlobalPlacement().inverse()
    corners = [
        toSketch.multVec(FRAME.multVec(V(shift + x, y, 12))) for x, y in ((2, 3), (6, 3), (6, 7), (2, 7))
    ]
    for i in range(4):
        onTop.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        onTop.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pocket = a.newObject("PartDesign::Pocket", "APocket")
    pocket.Profile = onTop
    pocket.Length = 3
    doc.recompute()

    b = doc.addObject("PartDesign::Body", "B")
    studio.addObject(b)
    pad(b, "BPad", placedSketch(b, "BSketch", (shift + 15, 2, shift + 25, 8)), 4)
    doc.recompute()

    cut = a.newObject("PartDesign::Boolean", "ACut")
    cut.Type = "Cut"
    cut.addObjects([b])
    doc.recompute()

    notch = a.newObject("PartDesign::Fillet", "AFillet2")
    notch.Base = (cut, [edgeAt(cut, (shift + 15, 2, 4), (shift + 15, 8, 4))])
    notch.Radius = 1
    doc.recompute()
    return doc


def measure(body, shift=0.0):
    """What a part's shape is: its solids, its faces, its volume, its area and its centre in the
    frame, moved back by shift."""
    shape = body.Shape
    centre = TO_FRAME.multVec(shape.Solids[0].CenterOfMass) if shape.Solids else V()
    return (len(shape.Solids), len(shape.Faces)) + tuple(
        round(value, 6) + 0.0
        for value in (shape.Volume, shape.Area, centre.x - shift, centre.y, centre.z)
    )


def inError(doc):
    return {obj.Name: obj.getStatusString() for obj in doc.Objects if not obj.isValid()}


class TestImportReferences(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="TestImportReferences")
        self.file = self.save(buildStudio("TestImportReferencesSource", 0), "studio.FCStd")
        self.other = self.save(buildStudio("TestImportReferencesOther", 100), "other.FCStd")
        # The control: the file alone, every object touched and recomputed
        doc = App.openDocument(self.file, hidden=True)
        self.touchAll(doc)
        self.assertEqual(inError(doc), {})
        self.alone = {name: measure(doc.getObject(name)) for name in ("A", "B")}
        App.closeDocument(doc.Name)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            # FileName has forward slashes, the temporary folder the platform's
            if doc.Name.startswith("TestImportReferences") or os.path.normcase(
                os.path.normpath(doc.FileName)
            ).startswith(os.path.normcase(os.path.normpath(self.dir))):
                App.closeDocument(doc.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def save(self, doc, name):
        path = os.path.join(self.dir, name)
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        return path

    @staticmethod
    def touchAll(doc):
        for obj in doc.Objects:
            obj.touch()
        doc.recompute()

    def assertAsAlone(self, host, copies):
        """The copies compute as the file alone, and the studio the document held is as it was."""
        self.touchAll(host)
        self.assertEqual(inError(host), {})
        # By the label's first letter: a copy's label is "A" or, where labels must differ, "A001"
        bodies = {obj.Label[:1]: obj for obj in copies if obj.isDerivedFrom("PartDesign::Body")}
        self.assertEqual(sorted(bodies), ["A", "B"])
        for label, body in bodies.items():
            self.assertEqual(measure(body), self.alone[label], label)
        cut = [obj for obj in copies if obj.isDerivedFrom("PartDesign::Boolean")]
        self.assertEqual(len(cut), 1)
        self.assertEqual(cut[0].Group, [bodies["B"]])
        for name in ("A", "B"):
            self.assertEqual(measure(host.getObject(name), 100), self.alone[name], "the host's " + name)

    # --------------------------------------------------------------------------------- tests
    def testTheModelIsAsDesigned(self):
        """The control's volumes are the designed ones (the test's own model, not a run's result)."""
        self.assertAlmostEqual(self.alone["A"][2], VOLUME_A, places=4)
        self.assertAlmostEqual(self.alone["B"][2], VOLUME_B, places=4)
        self.assertEqual(self.alone["A"][0], 1)

    def testCopiedStudioComputesAsItsFile(self):
        host = App.openDocument(self.other, hidden=True)
        source = App.openDocument(self.file, hidden=True)
        copies = host.copyObject(list(source.Objects), False, False)
        App.closeDocument(source.Name)
        self.assertAsAlone(host, copies)

    def testMergedStudioComputesAsItsFile(self):
        host = App.openDocument(self.other, hidden=True)
        before = {obj.Name for obj in host.Objects}
        host.mergeProject(self.file)
        self.assertAsAlone(host, [obj for obj in host.Objects if obj.Name not in before])

    def testCopyStaysRightAfterSaveAndReopen(self):
        host = App.openDocument(self.other, hidden=True)
        source = App.openDocument(self.file, hidden=True)
        names = [obj.Name for obj in host.copyObject(list(source.Objects), False, False)]
        App.closeDocument(source.Name)
        self.touchAll(host)
        path = os.path.join(self.dir, "merged.FCStd")
        host.saveAs(path)
        App.closeDocument(host.Name)
        host = App.openDocument(path, hidden=True)
        self.assertAsAlone(host, [host.getObject(name) for name in names])
