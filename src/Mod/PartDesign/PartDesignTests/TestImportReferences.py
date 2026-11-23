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
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part
import PartDesign
import Sketcher

from PartDesignTests.TestStudio import pad, rect, sketch, xyPlane

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


def saveWithLastId(path, last):
    """An empty document saved at path whose saved LastObjectId is last: the objects a merge then
    adds get the IDs from last + 1 on."""
    doc = App.newDocument("TestImportReferencesEmpty")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    temporary = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Document.xml":
                text, count = re.subn(
                    r'LastObjectId="\d+"', 'LastObjectId="%d"' % last, data.decode("utf-8"), count=1
                )
                assert count == 1, "Document.xml has no LastObjectId"
                data = text.encode("utf-8")
            zout.writestr(item, data)
    os.replace(temporary, path)


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

    def checkWhateverTheNewIds(self, bring):
        """ops#1002: Merge project and a copy give the file's objects new IDs, counted on from the
        receiving document's last one. Each document starts its IDs at a random offset, so by
        chance the receiving document's last ID could lie a few below or above the file's IDs (seen
        once in about 20 full suite runs, on Windows and on macOS: with the new IDs the file's
        shifted by 1 to 15 the notch's fillet broke, "Ambiguous edge reference: Edge29 moved and
        Edge29 sits where it was"; by -3 to -1 the pad, fillet or sketch before it). Whatever it
        is, the copies compute as the file alone. The receiving document's last ID is set here by
        its saved LastObjectId; bring(host) copies the file's objects into it."""
        doc = App.openDocument(self.file, hidden=True)
        ids = [obj.ID for obj in doc.Objects]
        App.closeDocument(doc.Name)
        for shift in (-40, -3, -2, -1, 0, 1, 2, 5, 11, 15, 40):
            with self.subTest(shift=shift):
                path = os.path.join(self.dir, "empty%+d.FCStd" % shift)
                saveWithLastId(path, min(ids) - 1 + shift)
                host = App.openDocument(path, hidden=True)
                try:
                    copies = bring(host)
                    self.assertEqual(len(copies), len(ids))
                    self.touchAll(host)
                    self.assertEqual(inError(host), {})
                    bodies = {o.Label[:1]: o for o in copies if o.isDerivedFrom("PartDesign::Body")}
                    self.assertEqual(sorted(bodies), ["A", "B"])
                    for label, body in bodies.items():
                        self.assertEqual(measure(body), self.alone[label], label)
                    # the new IDs never equal one the file gave
                    self.assertGreater(min(obj.ID for obj in copies), max(ids))
                finally:
                    App.closeDocument(host.Name)

    def testMergedStudioComputesAsItsFileWhateverTheNewIds(self):
        def merge(host):
            host.mergeProject(self.file)
            return list(host.Objects)

        self.checkWhateverTheNewIds(merge)

    def testCopiedStudioComputesAsItsFileWhateverTheNewIds(self):
        def copy(host):
            source = App.openDocument(self.file, hidden=True)
            try:
                return host.copyObject(list(source.Objects), False, False)
            finally:
                App.closeDocument(source.Name)

        self.checkWhateverTheNewIds(copy)

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


class TestStudioMoveKeepsBodies(unittest.TestCase):
    """FreeCAD-CH ops#910: a studio's objects put into an App::Part leave its Bodies whole.

    The merge of a studio file into a document puts the studio's top-level objects into an
    App::Part. One of them was a part mirror (Part::Mirroring) of a Body's feature, at the history
    point the mirror was made, feeding a second Body's BaseFeature. App::Part.addObjects takes an
    object's linked objects along; it took the mirrored feature, and through it the Body's other
    features and sketches, out of the Body and into the Part: "Missing face reference", then "No
    base set" down the Body, with no import at all.

    Designed: Body A, a pad x 0..20, y 0..10, 10 high (2000), then a pad x 0..4, y 0..4, 13 high
    (adds 4 * 4 * 3 = 48). The mirror of A's first pad in the plane x = -5 (x -30..-10: 2000).
    Body B on the mirror, with a pad x -30..-26, y 0..4, 12 high (adds 4 * 4 * 2 = 32).
    """

    def setUp(self):
        self.doc = App.newDocument("TestStudioMoveKeepsBodies")
        doc = self.doc
        self.a = doc.addObject("PartDesign::Body", "A")
        first = sketch(self.a, "ASketch", xyPlane(self.a), (0, 0, 20, 10))
        self.first = pad(self.a, "APad", first, 10)
        second = sketch(self.a, "ASketch2", xyPlane(self.a), (0, 0, 4, 4))
        pad(self.a, "APad2", second, 13)
        self.mirror = doc.addObject("Part::Mirroring", "Mirror")
        self.mirror.Source = self.first
        self.mirror.Base = V(-5, 0, 0)
        self.mirror.Normal = V(1, 0, 0)
        self.b = doc.addObject("PartDesign::Body", "B")
        self.b.BaseFeature = self.mirror
        third = sketch(self.b, "BSketch", xyPlane(self.b), (-30, 0, -26, 4))
        pad(self.b, "BPad", third, 12)
        doc.recompute()
        self.groups = {body.Name: [obj.Name for obj in body.Group] for body in (self.a, self.b)}

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertWhole(self, part, members):
        self.assertEqual(sorted(obj.Name for obj in part.Group), sorted(obj.Name for obj in members))
        for body in (self.a, self.b):
            self.assertEqual([obj.Name for obj in body.Group], self.groups[body.Name], body.Name)
        self.assertEqual(self.first.getParentGeoFeatureGroup(), self.a)
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        self.assertEqual(inError(self.doc), {})
        self.assertAlmostEqual(self.a.Shape.Volume, 2048, places=6)
        self.assertAlmostEqual(self.mirror.Shape.Volume, 2000, places=6)
        self.assertAlmostEqual(self.b.Shape.Volume, 2032, places=6)
        self.assertAlmostEqual(self.b.Shape.BoundBox.XMin, -30, places=6)

    def testTheModelIsAsDesigned(self):
        self.assertEqual(inError(self.doc), {})
        self.assertAlmostEqual(self.a.Shape.Volume, 2048, places=6)
        self.assertAlmostEqual(self.b.Shape.Volume, 2032, places=6)

    def testStudioPutIntoAPartKeepsItsBodies(self):
        part = self.doc.addObject("App::Part", "Studio")
        part.addObjects([self.a, self.mirror, self.b])
        self.assertWhole(part, [self.a, self.mirror, self.b])

    def testMirrorAlonePutIntoAPartLeavesTheBody(self):
        part = self.doc.addObject("App::Part", "Studio")
        part.addObject(self.mirror)
        self.assertWhole(part, [self.mirror])

    def testOtherMirrorOfTheBodyStays(self):
        """Nothing is reached through the Body: a second mirror of it isn't taken along."""
        other = self.doc.addObject("Part::Mirroring", "Other")
        other.Source = self.a.Tip
        other.Base = V(0, -5, 0)
        other.Normal = V(0, 1, 0)
        self.doc.recompute()
        part = self.doc.addObject("App::Part", "Studio")
        part.addObject(self.mirror)
        self.assertIsNone(other.getParentGeoFeatureGroup())
        self.assertIsNone(self.b.getParentGeoFeatureGroup())
        self.assertWhole(part, [self.mirror])
        self.assertAlmostEqual(other.Shape.Volume, 2048, places=6)

    def testSiblingInTheOldPartStays(self):
        """Moved on from one Part to another, a mirror leaves the Body and its other mirror."""
        other = self.doc.addObject("Part::Mirroring", "Other")
        other.Source = self.a.Tip
        other.Base = V(0, -5, 0)
        other.Normal = V(0, 1, 0)
        old = self.doc.addObject("App::Part", "Old")
        old.addObjects([self.a, self.mirror, self.b, other])
        self.doc.recompute()
        self.assertEqual(len(old.Group), 4)
        new = self.doc.addObject("App::Part", "New")
        new.addObject(self.mirror)
        self.assertEqual(new.Group, [self.mirror])
        self.assertEqual(sorted(obj.Name for obj in old.Group), ["A", "B", "Other"])
        self.assertEqual([obj.Name for obj in self.a.Group], self.groups["A"])
        old.removeObject(other)
        self.assertEqual(sorted(obj.Name for obj in old.Group), ["A", "B"])
        self.assertEqual([obj.Name for obj in self.a.Group], self.groups["A"])
        self.doc.recompute()
        self.assertEqual(inError(self.doc), {})

    def testObjectsOfOneGroupStillMoveTogether(self):
        """The rule kept: an object moved to another group takes its own group's links along."""
        one = self.doc.addObject("App::Part", "One")
        two = self.doc.addObject("App::Part", "Two")
        box = self.doc.addObject("Part::Box", "Box")
        copy = self.doc.addObject("Part::Mirroring", "BoxMirror")
        copy.Source = box
        one.addObject(copy)
        self.assertEqual(sorted(obj.Name for obj in one.Group), ["Box", "BoxMirror"])
        two.addObject(box)
        self.assertEqual(one.Group, [])
        self.assertEqual(sorted(obj.Name for obj in two.Group), ["Box", "BoxMirror"])


class TestImportPieces(unittest.TestCase):
    """FreeCAD-CH ops#920: a split part's pieces hold their solids after a copy into another document.

    A piece Body (made by a split, PartDesign.studioMakePieces) keeps a witness: the names of the
    faces that tell its solid apart, with the IDs of the objects that made them. A copy gives every
    object a new ID, so after the copy's first recompute no name of the witness was on any solid:
    "None of the faces that told '<part>' apart is on a piece any more: it holds nothing".

    Designed: a bar P x 0..100, y 0..10, 10 high, in the studio S, split by a studio Pocket E (a
    slot 1 wide at x 30..31 through it): pieces x 0..30 (3000) and x 31..100 (6900). The right piece
    gets a boss x 60..70, y 2..8, 2 high on its top (adds 120: 7020).
    """

    def setUp(self):
        from PartDesignTests.TestStudioList import studioList
        from PartDesignTests.TestStudioOwner import makeOwner, studioSketch

        self.dir = tempfile.mkdtemp(prefix="TestImportPieces")
        doc = App.newDocument("TestImportPiecesSource")
        studio = doc.addObject("App::Part", "S")
        bar = doc.addObject("PartDesign::Body", "P")
        studio.addObject(bar)
        pad(bar, "PPad", sketch(bar, "PSk", xyPlane(bar), (0, 0, 100, 10)), 10)
        doc.recompute()
        PartDesign.studioReconcile(studioList(doc))
        slot = studioSketch(doc, studio, "ESk", ((30, -1, 31, 11),), z=10)
        split = makeOwner(doc, studio, "Pocket", "E", slot, ("P",), Length=11)
        doc.recompute()
        doc.openTransaction("pieces")
        made = PartDesign.studioMakePieces(split)
        doc.commitTransaction()
        self.assertEqual(len(made), 2)
        right = max(made, key=lambda b: b.Shape.BoundBox.XMin)
        boss = pad(right, "RBoss", sketch(right, "RBossSk", xyPlane(right), (60, 2, 70, 8), z=10), 2)
        PartDesign.studioInsert(boss.Profile[0], -1)
        doc.recompute()
        self.assertEqual(inError(doc), {})
        self.file = os.path.join(self.dir, "pieces.FCStd")
        doc.saveAs(self.file)
        App.closeDocument(doc.Name)
        self.other = os.path.join(self.dir, "other.FCStd")
        doc = buildStudio("TestImportPiecesOther", 100)
        doc.saveAs(self.other)
        App.closeDocument(doc.Name)
        # The control: the file alone, every object touched and recomputed
        doc = App.openDocument(self.file, hidden=True)
        TestImportReferences.touchAll(doc)
        self.assertEqual(inError(doc), {})
        self.alone = self.pieces(doc.Objects)
        App.closeDocument(doc.Name)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestImportPieces") or os.path.normcase(
                os.path.normpath(doc.FileName)
            ).startswith(os.path.normcase(os.path.normpath(self.dir))):
                App.closeDocument(doc.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    @staticmethod
    def pieces(objs):
        """Each piece's solids, volume and centre, by its part id."""
        out = {}
        for obj in objs:
            if obj.isDerivedFrom("PartDesign::Body") and obj.StudioPieceWitness:
                shape = obj.Shape
                centre = shape.Solids[0].CenterOfMass if shape.Solids else V()
                out[obj.StudioPartId] = (len(shape.Solids),) + tuple(
                    round(value, 6) + 0.0 for value in (shape.Volume, centre.x, centre.y, centre.z)
                )
        return out

    def assertAsAlone(self, host, copies):
        TestImportReferences.touchAll(host)
        self.assertEqual(inError(host), {})
        self.assertEqual(self.pieces(copies), self.alone)

    def testThePiecesAreAsDesigned(self):
        designed = [
            (1, 3000, 15, 5, 5),
            (1, 7020, (6900 * 65.5 + 120 * 65) / 7020, 5, (6900 * 5 + 120 * 11) / 7020),
        ]
        actual = sorted(self.alone.values())
        self.assertEqual(len(actual), 2)
        for got, want in zip(actual, designed):
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, places=4, msg=(got, want))

    def testCopiedPiecesHoldTheirSolids(self):
        host = App.openDocument(self.other, hidden=True)
        source = App.openDocument(self.file, hidden=True)
        copies = host.copyObject(list(source.Objects), False, False)
        App.closeDocument(source.Name)
        self.assertAsAlone(host, copies)

    def testMergedPiecesHoldTheirSolids(self):
        host = App.openDocument(self.other, hidden=True)
        before = {obj.Name for obj in host.Objects}
        host.mergeProject(self.file)
        self.assertAsAlone(host, [obj for obj in host.Objects if obj.Name not in before])

    def testMergedPieceEditedFirst(self):
        """Merge project keeps the file's element maps, named with the file's IDs: an edit in a
        piece recomputed before the rest still finds the piece's faces (review pr920pre-r1 T1).
        The boss on the right piece is made 1 higher: 7020 + 60."""
        host = App.openDocument(self.other, hidden=True)
        before = {obj.Name for obj in host.Objects}
        host.mergeProject(self.file)
        copies = [obj for obj in host.Objects if obj.Name not in before]
        boss = [obj for obj in copies if obj.Label.startswith("RBoss") and obj.isDerivedFrom("PartDesign::Pad")]
        self.assertEqual(len(boss), 1)
        body = boss[0].getParentGeoFeatureGroup()
        step = [f for f in body.Group if getattr(f, "StudioOwner", None) is body.StudioMadeBy]
        self.assertEqual(len(step), 1)
        step[0].touch()
        boss[0].Length = 3
        host.recompute()
        self.assertEqual(inError(host), {})
        expected = dict(self.alone)
        right = max(expected, key=lambda k: expected[k][1])
        count, volume = expected[right][:2]
        got = self.pieces(copies)
        self.assertAlmostEqual(got[right][1], volume + 60, places=4)
        self.assertEqual({k: v for k, v in got.items() if k != right},
                         {k: v for k, v in expected.items() if k != right})

    def testMergedFrozenMaker(self):
        """The maker's step saved frozen keeps the file's shape and names: a merge keeps the
        pieces' records as the file has them, and they hold their solids (review pr920pre-r1 F1)."""
        import re
        import zipfile

        frozen = os.path.join(self.dir, "frozen.FCStd")
        with zipfile.ZipFile(self.file) as z:
            items = {i: z.read(i) for i in z.namelist()}
        xml = items["Document.xml"].decode("utf-8")
        xml, n = re.subn(r'(<Object type="[^"]*" name="E_at_P")', r'\1 Freeze="1"', xml, count=1)
        self.assertEqual(n, 1)
        items["Document.xml"] = xml.encode("utf-8")
        with zipfile.ZipFile(frozen, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in items.items():
                z.writestr(name, data)
        host = App.openDocument(self.other, hidden=True)
        before = {obj.Name for obj in host.Objects}
        host.mergeProject(frozen)
        copies = [obj for obj in host.Objects if obj.Name not in before]
        host.recompute()
        self.assertEqual(inError(host), {})
        self.assertEqual(self.pieces(copies), self.alone)

    def testPastedWithinTheDocumentHoldTheirSolids(self):
        """A copy within the source document: the copies' pieces hold the copies' solids, and the
        original's pieces stay as they were."""
        doc = App.openDocument(self.file, hidden=True)
        copies = doc.copyObject(list(doc.Objects), False, False)
        TestImportReferences.touchAll(doc)
        self.assertEqual(inError(doc), {})
        self.assertEqual(self.pieces(copies), self.alone)
        originals = [obj for obj in doc.Objects if obj not in copies]
        self.assertEqual(self.pieces(originals), self.alone)

    def testCopiedIntoADocumentHoldingTheSameStudio(self):
        """The host already holds the same studio: the copies are renamed (P001, E001) and keep
        the part ids the host's studio has too; each piece takes its parent in its own studio.
        The host is filled so that the copies' IDs cross a power of ten where the file's don't:
        names sort by their bytes, the IDs' digits included."""
        twin = os.path.join(self.dir, "twin.FCStd")
        shutil.copyfile(self.file, twin)
        host = App.openDocument(twin, hidden=True)
        source = App.openDocument(self.file, hidden=True)
        ids = sorted(obj.ID for obj in source.Objects)
        power = 10 ** len(str(ids[-1]))
        last = max(obj.ID for obj in host.Objects)
        for _ in range(max(0, power - len(ids) // 2 - last)):
            host.addObject("App::DocumentObjectGroup", "Filler")
        copies = host.copyObject(list(source.Objects), False, False)
        App.closeDocument(source.Name)
        copied = sorted(obj.ID for obj in copies)
        self.assertLess(copied[0], power)
        self.assertGreater(copied[-1], power)
        self.assertAsAlone(host, copies)
        originals = [obj for obj in host.Objects if obj not in copies]
        self.assertEqual(self.pieces(originals), self.alone)


class TestImportedSketchOnAFace(unittest.TestCase):
    """FreeCAD-CH ops#930: a sketch on a face of a feature, copied into another document, keeps
    the references into it.

    A copy (Document.copyObject, as the document merge does) has no element names until each object
    recomputes. The support's recompute moves the sketch before the sketch runs (its attachment
    sets the identity, then the face's placement). That move named the sketch's name-less shape by
    a match (MLN names); the references into the sketch took them, and the sketch read such a
    name as one of its own geometry names: the index after the '.' (wire order) as a geometry
    index. A sweep's spine `Edge<k>` became `edge<k>` ("Invalid shape name"), and another sketch's
    external geometry silently followed geometry k instead of the edge.

    Designed geometry: a pad 40 x 40 x 40; on its top face (z 40) a sketch with a construction line
    first, then the lines B-C, C-D and A-B (out of chain order: A (10, 20), B (30, 20), C (30, 30),
    D (20, 30)), and the pad's top edge at y 0 as external geometry; a sweep cut along A-B of a
    circle of radius 1.5 centred on A, perpendicular to A-B (half of it in the pad: takes
    pi * 1.5^2 / 2 * 20); a sketch at z 40 whose external geometry is the edge A-B."""

    A, B, C, D = (10, 20), (30, 20), (30, 30), (20, 30)
    Z = 40
    VOLUME = 40**3 - math.pi * 1.5**2 / 2 * 20

    @classmethod
    def build(cls, name):
        V = App.Vector
        doc = App.newDocument(name)
        body = doc.addObject("PartDesign::Body", "Body")
        base = body.newObject("Sketcher::SketchObject", "BaseSketch")
        corners = [V(0, 0, 0), V(40, 0, 0), V(40, 40, 0), V(0, 40, 0)]
        for i in range(4):
            base.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            base.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = base
        pad.Length = 40
        doc.recompute()

        top = next(
            f"Face{i}"
            for i, face in enumerate(pad.Shape.Faces, 1)
            if abs(face.CenterOfMass.z - cls.Z) < 1e-9 and face.normalAt(0, 0).z > 0.5
        )
        topEdge = next(
            f"Edge{i}"
            for i, edge in enumerate(pad.Shape.Edges, 1)
            if all(abs(v.Point.z - cls.Z) < 1e-9 and abs(v.Point.y) < 1e-9 for v in edge.Vertexes)
        )
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(pad, top)]
        onTop.MapMode = "FlatFace"
        doc.recompute()
        local = onTop.getGlobalPlacement().inverse()

        def at(xy):
            return local.multVec(V(xy[0], xy[1], cls.Z))

        onTop.addGeometry(Part.LineSegment(at((0, 35)), at((40, 35))), True)
        for p, q in ((cls.B, cls.C), (cls.C, cls.D), (cls.A, cls.B)):
            onTop.addGeometry(Part.LineSegment(at(p), at(q)))
        onTop.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 1, 1))
        onTop.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        onTop.addExternal(pad.Name, topEdge)
        doc.recompute()

        profile = body.newObject("Sketcher::SketchObject", "Profile")
        profile.Placement = App.Placement(
            V(cls.A[0], 0, 0), App.Rotation(V(0, 0, 1), V(1, 0, 0))
        )
        centre = profile.Placement.inverse().multVec(V(cls.A[0], cls.A[1], cls.Z))
        profile.addGeometry(Part.Circle(centre, V(0, 0, 1), 1.5))
        doc.recompute()

        spine = cls.edgeOf(onTop, cls.A, cls.B)
        sweep = body.newObject("PartDesign::SubtractivePipe", "Sweep")
        sweep.Profile = profile
        sweep.Spine = (onTop, [spine])
        doc.recompute()

        follower = body.newObject("Sketcher::SketchObject", "Follower")
        follower.Placement = App.Placement(V(0, 0, cls.Z), App.Rotation())
        follower.addExternal(onTop.Name, spine)
        doc.recompute()
        return doc

    @classmethod
    def edgeOf(cls, sketch, p, q):
        """The edge of the sketch's public shape from p to q."""
        want = {(float(p[0]), float(p[1])), (float(q[0]), float(q[1]))}
        for i, edge in enumerate(sketch.Shape.Edges, 1):
            ends = {(round(v.Point.x, 6) + 0.0, round(v.Point.y, 6) + 0.0) for v in edge.Vertexes}
            if ends == want:
                return f"Edge{i}"
        return None

    @staticmethod
    def externalLine(sketch):
        """The ends, global x and y, of the sketch's one external line (after the two axes)."""
        line = sketch.ExternalGeo[2]
        place = sketch.getGlobalPlacement()
        return {
            (round(place.multVec(pt).x, 6) + 0.0, round(place.multVec(pt).y, 6) + 0.0)
            for pt in (line.StartPoint, line.EndPoint)
        }

    @staticmethod
    def inError(doc):
        return {obj.Name: obj.getStatusString() for obj in doc.Objects if not obj.isValid()}

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="TestImportedSketch")
        doc = self.build("TestImportedSketchSource")
        self.file = os.path.join(self.dir, "source.FCStd")
        doc.saveAs(self.file)
        App.closeDocument(doc.Name)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestImportedSketch"):
                App.closeDocument(doc.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def copied(self):
        """The source file and a copy of all its objects in an empty document, every object of
        the copy touched and recomputed (the merge's order)."""
        source = App.openDocument(self.file, hidden=True)
        host = App.newDocument("TestImportedSketchHost", hidden=True)
        copies = host.copyObject(list(source.Objects), False, False)
        for obj in host.Objects:
            obj.touch()
        host.recompute()
        byLabel = {obj.Label: obj for obj in copies}
        return source, host, byLabel

    def testTheModelIsAsDesigned(self):
        """The source computes as designed, and the spine's public index is not its geometry's
        (the case needs the two to differ)."""
        source = App.openDocument(self.file, hidden=True)
        self.assertEqual(self.inError(source), {})
        self.assertAlmostEqual(source.getObject("Body").Shape.Volume, self.VOLUME, places=4)
        onTop = source.getObject("OnTop")
        spine = source.getObject("Sweep").Spine[1][0]
        self.assertEqual(spine, self.edgeOf(onTop, self.A, self.B))
        # `edge<k>` reads geometry k - 1: a line of the sketch, not A-B
        geometry = onTop.Geometry[int(spine[4:]) - 1]
        ends = {(round(p.x, 6), round(p.y, 6)) for p in (geometry.StartPoint, geometry.EndPoint)}
        local = onTop.getGlobalPlacement().inverse()
        ab = {
            (round(local.multVec(App.Vector(x, y, self.Z)).x, 6), round(local.multVec(App.Vector(x, y, self.Z)).y, 6))
            for x, y in (self.A, self.B)
        }
        self.assertNotEqual(ends, ab)
        self.assertEqual(self.externalLine(source.getObject("Follower")), {self.A, self.B})

    def testCopiedSweepKeepsItsSpine(self):
        source, host, copy = self.copied()
        self.assertEqual(self.inError(host), {})
        self.assertEqual(copy["Sweep"].Spine[1], source.getObject("Sweep").Spine[1])
        self.assertAlmostEqual(
            copy["Body"].Shape.Volume, source.getObject("Body").Shape.Volume, places=6
        )

    def testCopiedExternalGeometryFollowsTheSameEdge(self):
        """The silent case: another sketch's external geometry names the edge by index."""
        source, host, copy = self.copied()
        self.assertEqual(
            copy["Follower"].ExternalGeometry[0][1], source.getObject("Follower").ExternalGeometry[0][1]
        )
        self.assertEqual(self.externalLine(copy["Follower"]), {self.A, self.B})
