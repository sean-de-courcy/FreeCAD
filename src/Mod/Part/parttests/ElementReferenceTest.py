# SPDX-License-Identifier: LGPL-2.1-or-later

"""Element references across documents, refreshed when documents are opened."""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part


def _box(doc, name, x):
    box = doc.addObject("Part::Box", name)
    box.Placement.Base = App.Vector(x, 0, 0)
    return box


def _faceAtX(shape, x):
    """Return the name of the face lying on the plane at x and facing -x."""
    for i, face in enumerate(shape.Faces, 1):
        if abs(face.CenterOfMass.x - x) < 1e-7 and face.normalAt(0, 0).x < -0.5:
            return "Face%d" % i
    return None


class ElementReferenceTest(unittest.TestCase):
    # Set in subclasses: (HistoryAlgorithm, InternNames) of every document a test makes
    MODE = None

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ElementReferenceTest")
        self.docNames = []

    def tearDown(self):
        for name in self.docNames:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _newDocument(self, name):
        doc = App.newDocument(name)
        self.docNames.append(doc.Name)
        if self.MODE:
            doc.HistoryAlgorithm, doc.InternNames = self.MODE
        doc.saveAs(os.path.join(self.dir, name + ".FCStd"))
        return doc

    def _path(self, name):
        return os.path.join(self.dir, name + ".FCStd")

    def _newTarget(self):
        """Document B: a compound of Box1 (x = 0) and Box2 (x = 20), saved."""
        docB = self._newDocument("ElementRefB")
        box1 = _box(docB, "Box1", 0)
        box2 = _box(docB, "Box2", 20)
        compound = docB.addObject("Part::Compound", "Compound")
        compound.Links = [box1, box2]
        docB.recompute()
        docB.save()
        return docB, compound

    def _newOwner(self, target, subs, propType="App::PropertyXLinkSub"):
        """Document A: an object whose property Target references `subs` of `target`, saved."""
        docA = self._newDocument("ElementRefA")
        ref = docA.addObject("App::FeaturePython", "Ref")
        ref.addProperty(propType, "Target")
        ref.Target = (target, subs)
        docA.recompute()
        docA.save()
        return docA

    @staticmethod
    def _moveFaces(docB):
        """Put a box at x = -20 first in B's compound: every face gets a new index, while its
        mapped name stays the same. Saves B."""
        compound = docB.getObject("Compound")
        compound.Links = [_box(docB, "Box0", -20)] + compound.Links
        docB.recompute()
        docB.save()

    def _prepareMovedCopy(self, docB):
        """Save B with its faces moved as a separate file, and leave B open as it was.

        The copy has the same objects, and so the same mapped names, as B. Returns B, opened
        again, and the copy's path.
        """
        pathB = docB.FileName
        original = self._path("Original")
        moved = self._path("Moved")
        shutil.copy(pathB, original)
        self._moveFaces(docB)
        shutil.copy(pathB, moved)
        App.closeDocument(docB.Name)
        shutil.copy(original, pathB)
        return App.openDocument(pathB), moved

    def _assertFace(self, shape, sub, x):
        """`sub` names the face of `shape` at x that faces -x."""
        face = shape.getElement(sub)
        self.assertAlmostEqual(face.CenterOfMass.x, x)
        self.assertLess(face.normalAt(0, 0).x, -0.5)

    def testReferenceRefreshedAfterOpening(self):
        """A reference saved in a closed document follows its element to a new index (ops#18).

        Document B holds a compound of two boxes; document A references the face of the second
        box at x = 20. With A closed, a third box is put first in the compound, so that face's
        index changes while its mapped name does not. Opening A again must refresh the reference
        to the face's new index: the refresh at the end of opening documents did nothing.
        """
        # Arrange
        docB = self._newDocument("ElementRefB")
        box1 = _box(docB, "Box1", 0)
        box2 = _box(docB, "Box2", 20)
        compound = docB.addObject("Part::Compound", "Compound")
        compound.Links = [box1, box2]
        docB.recompute()
        docB.save()
        oldIndex = _faceAtX(compound.Shape, 20)

        docA = self._newDocument("ElementRefA")
        ref = docA.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyXLinkSub", "Target")
        ref.Target = (compound, [oldIndex])
        docA.save()
        App.closeDocument(docA.Name)

        compound.Links = [_box(docB, "Box0", -20), box1, box2]
        docB.recompute()
        docB.save()
        newIndex = _faceAtX(compound.Shape, 20)
        self.assertNotEqual(oldIndex, newIndex)  # the setup moves the face

        # Act
        docA = App.openDocument(os.path.join(self.dir, "ElementRefA.FCStd"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        face = compound.Shape.getElement(subs[0])
        self.assertAlmostEqual(face.CenterOfMass.x, 20)
        self.assertLess(face.normalAt(0, 0).x, -0.5)
        self.assertEqual(subs[0], newIndex)

    def testReferenceRefreshedWhenTargetClosed(self):
        """As above, with B closed too: opening A loads B, and the reference follows (ops#40).

        Attaching the reference to B, once B is loaded, threw away its saved mapped name and
        took the mapped name of whatever face now has the old index (Box1's face at x = 0).
        """
        # Arrange
        docB, compound = self._newTarget()
        oldIndex = _faceAtX(compound.Shape, 20)
        docA = self._newOwner(compound, [oldIndex])
        App.closeDocument(docA.Name)
        self._moveFaces(docB)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        compound = App.getDocument("ElementRefB").getObject("Compound")
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        self._assertFace(compound.Shape, subs[0], 20)

    def testShadowKeptWhenTargetClosedWhileOpen(self):
        """Closing B while A is open keeps the reference's mapped name, also in A's file (ops#40).

        Closing B threw the mapped name away, and saving A then wrote the reference without it.
        """
        # Arrange
        docB, compound = self._newTarget()
        docA = self._newOwner(compound, [_faceAtX(compound.Shape, 20)])
        App.closeDocument(docB.Name)
        docA.save()
        App.closeDocument(docA.Name)
        with zipfile.ZipFile(self._path("ElementRefA")) as archive:
            xml = archive.read("Document.xml").decode("utf-8")
        # The file is saved relative to A's canonical directory. Where the temporary directory
        # is reached through a symlink (macOS: /var -> /private/var), that is a ../ path to B,
        # not the bare file name.
        xlink = re.search(r'<XLink file="([^"]*ElementRefB\.FCStd)"[^>]*>', xml)
        self.assertIsNotNone(xlink, "\n".join(re.findall(r"<XLink [^>]*>", xml)))
        savedPath = os.path.join(os.path.realpath(self.dir), xlink.group(1))
        self.assertTrue(os.path.samefile(savedPath, self._path("ElementRefB")), xlink.group(0))
        self.assertIn(' shadow="', xlink.group(0))
        docB = App.openDocument(self._path("ElementRefB"))
        self._moveFaces(docB)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        compound = App.getDocument("ElementRefB").getObject("Compound")
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        self._assertFace(compound.Shape, subs[0], 20)

    def testTargetReopenedWhileOwnerOpen(self):
        """A stays open while B is closed, changed and opened again: A's reference follows its
        face, and A's object is touched to be recomputed with it (ops#40)."""
        # Arrange
        docB, _ = self._newTarget()
        docB, moved = self._prepareMovedCopy(docB)
        compound = docB.getObject("Compound")
        docA = self._newOwner(compound, [_faceAtX(compound.Shape, 20)])
        App.closeDocument(docB.Name)
        shutil.copy(moved, self._path("ElementRefB"))

        # Act
        docB = App.openDocument(self._path("ElementRefB"))

        # Assert
        ref = docA.getObject("Ref")
        linked, subs = ref.Target
        compound = docB.getObject("Compound")
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 1)
        self._assertFace(compound.Shape, subs[0], 20)
        self.assertIn("Touched", ref.State)

    def testSubListReference(self):
        """A PropertyXLinkSubList (the type of SubShapeBinder.Support) with a face of each box:
        both references follow their faces when B is closed, changed and opened again (ops#40).
        Its children are restored and detached inside the parent's change notification."""
        # Arrange
        docB, _ = self._newTarget()
        docB, moved = self._prepareMovedCopy(docB)
        compound = docB.getObject("Compound")
        faces = [_faceAtX(compound.Shape, 0), _faceAtX(compound.Shape, 20)]
        docA = self._newOwner(compound, faces, "App::PropertyXLinkSubList")
        App.closeDocument(docB.Name)
        shutil.copy(moved, self._path("ElementRefB"))

        # Act
        docB = App.openDocument(self._path("ElementRefB"))

        # Assert
        compound = docB.getObject("Compound")
        target = docA.getObject("Ref").Target
        self.assertEqual(len(target), 1)
        linked, subs = target[0]
        self.assertEqual(linked, compound)
        self.assertEqual(len(subs), 2)
        self._assertFace(compound.Shape, subs[0], 0)
        self._assertFace(compound.Shape, subs[1], 20)

    def testRemovedElementReportedMissing(self):
        """When the referenced face is gone, the reference is marked missing on opening, and
        does not take the face that now has its old index (ops#40)."""
        # Arrange
        docB, compound = self._newTarget()
        oldIndex = _faceAtX(compound.Shape, 20)
        docA = self._newOwner(compound, [oldIndex])
        App.closeDocument(docA.Name)
        box1 = docB.getObject("Box1")
        compound.Links = [box1, _box(docB, "Box3", 40)]  # Box3's face at x = 40 takes the index
        docB.removeObject("Box2")
        docB.recompute()
        docB.save()
        self.assertEqual(_faceAtX(compound.Shape, 40), oldIndex)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        _, subs = docA.getObject("Ref").Target
        self.assertEqual(len(subs), 1)
        self.assertIn("?", subs[0])

    def testUnchangedTargetLeavesOwnerUntouched(self):
        """When B has not changed, opening A with B closed keeps the reference as it was and
        leaves A's object untouched."""
        # Arrange
        docB, compound = self._newTarget()
        index = _faceAtX(compound.Shape, 20)
        docA = self._newOwner(compound, [index])
        App.closeDocument(docA.Name)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        ref = docA.getObject("Ref")
        _, subs = ref.Target
        self.assertEqual(subs, [index])
        self.assertNotIn("Touched", ref.State)

    def testReferenceThroughLinkInOwner(self):
        """A reference to an App::Link in A that links B's compound, the shape of an Assembly
        joint's reference, follows its face when A is opened with B closed."""
        # Arrange
        docB, compound = self._newTarget()
        oldIndex = _faceAtX(compound.Shape, 20)
        docA = self._newDocument("ElementRefA")
        link = docA.addObject("App::Link", "Link")
        link.LinkedObject = compound
        ref = docA.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyXLinkSub", "Target")
        ref.Target = (link, [oldIndex])
        docA.recompute()
        docA.save()
        App.closeDocument(docA.Name)
        self._moveFaces(docB)
        App.closeDocument(docB.Name)

        # Act
        docA = App.openDocument(self._path("ElementRefA"))

        # Assert
        linked, subs = docA.getObject("Ref").Target
        self.assertEqual(linked, docA.getObject("Link"))
        self.assertEqual(len(subs), 1)
        compound = App.getDocument("ElementRefB").getObject("Compound")
        self._assertFace(compound.Shape, subs[0], 20)

    def testLinkInAnotherDocumentNamesMaplessSourceV2(self):
        """In V2, an App::Link in another document names every element of a source without an
        element map (a Part::Box) as mapSubElement names an element of a single shape, then adds
        the boundary section with the Link's ID (ops#56):
        '<element>;_;<source ID>;MKR;0;<type>;0;IDX,SRC;_|_;_;<Link ID>;EXT;0;<type>;0;_;_'.
        The cross-document retag named nothing; FreeCAD 1.1.3's V1 names them all (ops#41)."""
        # Arrange
        docB = self._newDocument("ElementRefB")
        docB.HistoryAlgorithm = "V2"
        box = _box(docB, "Box", 0)
        docB.recompute()
        docB.save()
        docA = self._newDocument("ElementRefA")
        docA.HistoryAlgorithm = "V2"
        link = docA.addObject("App::Link", "Link")
        link.LinkedObject = box
        docA.recompute()
        docA.save()

        # Act
        shape = Part.getShape(link)

        # Assert
        # the premise: the source names nothing (use another map-less source if this changes)
        self.assertEqual(box.Shape.ElementMapSize, 0)
        reverseMap = shape.ElementReverseMap
        for kind, elements in (
            ("Face", shape.Faces),
            ("Edge", shape.Edges),
            ("Vertex", shape.Vertexes),
        ):
            for index in range(1, len(elements) + 1):
                element = f"{kind}{index}"
                with self.subTest(element=element):
                    # an interned name in its full form (V2i)
                    self.assertEqual(
                        App.expandMappedName(reverseMap.get(element)),
                        App.makeEncodedSection(
                            referenceIDs=[element],
                            iterationTag=str(box.ID),
                            opCode="MKR",
                            elementType=element[0],
                            mapperFlags=["IDX", "SRC"],
                        )
                        + "|"
                        + App.makeEncodedSection(
                            iterationTag=str(link.ID),
                            opCode="EXT",
                            elementType=element[0],
                        ),
                    )
        self.assertEqual(shape.ElementMapSize, 26)
        self.assertEqual(len(set(reverseMap.values())), 26)

    # ops#56: names that crossed from another document, where an object there and one here have
    # the same ID. Both documents number their objects from 1 (clearDocument), so the first
    # object in each gets ID 1.

    def _numberedFromOne(self, name):
        doc = self._newDocument(name)
        doc.clearDocument()
        doc.HistoryAlgorithm, doc.InternNames = self.MODE or ("V2", False)
        doc.save()
        return doc

    def _linkedSource(self, size=10):
        """Document Src56: a box "Src" (ID 1) at the origin, saved."""
        src = self._numberedFromOne("Src56")
        box = src.addObject("Part::Box", "Src")
        box.Length = box.Width = box.Height = size
        src.recompute()
        src.save()
        return box

    @staticmethod
    def _history(obj, sub):
        """The objects of the element's history, as 'Document#Object', in order."""
        chain = []
        for item in obj.getElementHistory(sub, True, False, True):
            who = item[0]
            chain.append(who[0] if isinstance(who, tuple) else f"tag {who}")
        return chain

    def _checkCutHistory(self, collide):
        # Arrange
        box = self._linkedSource()
        asm = self._numberedFromOne("Asm56")
        if collide:
            decoy = asm.addObject("Part::Box", "Decoy")
        else:
            # ID 1 used up by a deleted object: no object here has the source box's ID
            asm.removeObject(asm.addObject("App::FeaturePython", "Filler").Name)
        link = asm.addObject("App::Link", "L")
        link.LinkedObject = box
        tool = asm.addObject("Part::Box", "Tool")
        tool.Length = tool.Width = tool.Height = 4
        tool.Placement.Base = App.Vector(8, 8, 8)
        cut = asm.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = link, tool
        if not collide:
            decoy = asm.addObject("Part::Box", "Decoy")
        decoy.Length = decoy.Width = decoy.Height = 3
        decoy.Placement.Base = App.Vector(100, 0, 0)

        # Act
        asm.recompute()

        # Assert
        self.assertEqual(decoy.ID == box.ID, collide)
        self.assertAlmostEqual(cut.Shape.Volume, 1000 - 8)
        self.assertEqual(len(cut.Shape.Faces), 9)
        for index, face in enumerate(cut.Shape.Faces, 1):
            sub = f"Face{index}"
            # the tool's faces lie on the planes x, y or z = 8; the box's on 0 or 10
            bound = face.BoundBox
            fromTool = any(
                abs(low - 8) < 1e-7 and abs(high - 8) < 1e-7
                for low, high in (
                    (bound.XMin, bound.XMax),
                    (bound.YMin, bound.YMax),
                    (bound.ZMin, bound.ZMax),
                )
            )
            history = self._history(cut, sub)
            with self.subTest(face=sub, history=history):
                self.assertNotIn("Asm56#Decoy", history)
                self.assertEqual(history[0], "Asm56#Cut")
                self.assertEqual(history[-1], "Asm56#Tool" if fromTool else "Src56#Src")

    def testCrossDocumentHistoryWithCollidingId(self):
        """A Part::Cut of an App::Link to a box in another document, where a local box has the
        box's ID: the faces from the linked box trace back through the Link to that box, never
        to the local one, which shares no geometry with the Cut (ops#56)."""
        self._checkCutHistory(collide=True)

    def testCrossDocumentHistoryReachesTheSource(self):
        """As testCrossDocumentHistoryWithCollidingId, with no local object with the box's ID:
        the history reaches the box in the other document instead of stopping (ops#56)."""
        self._checkCutHistory(collide=False)

    def _checkFuseReorder(self, solver):
        # Arrange
        box = self._linkedSource()
        asm = self._numberedFromOne("Asm56")
        asm.ReferenceSolver = solver
        decoy = asm.addObject("Part::Box", "Decoy")  # ID 1, as the linked box
        decoy.Placement.Base = App.Vector(100, 0, 0)
        link = asm.addObject("App::Link", "L")
        link.LinkedObject = box
        fuse = asm.addObject("Part::MultiFuse", "F")
        fuse.Shapes = [link, decoy]
        ref = asm.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyLinkSub", "Face")
        asm.recompute()
        self.assertEqual(decoy.ID, box.ID)
        ref.Face = (fuse, [self._faceFacingX(fuse.Shape, 110)])
        asm.recompute()
        # the two boxes' faces have distinct names, with no duplicate counts: the linked box's
        # end in a boundary section with the Link's ID, the local box's don't
        names = fuse.Shape.ElementReverseMap
        boundary = f";{link.ID};EXT;0;F;0;_;_"
        for index, face in enumerate(fuse.Shape.Faces, 1):
            name = App.expandMappedName(names[f"Face{index}"])
            linked = face.BoundBox.XMax < 50
            with self.subTest(face=index, name=name):
                self.assertEqual(name.endswith(boundary), linked)
                self.assertEqual(App.getDecodedMappedName(name)[-1]["duplicateCount"], "0")

        # Act
        fuse.Shapes = [decoy, link]
        asm.recompute()

        # Assert
        sub = ref.Face[1][0]
        self.assertEqual(sub, self._faceFacingX(fuse.Shape, 110))

    @staticmethod
    def _faceFacingX(shape, x):
        """The name of the face of `shape` on the plane at x that faces +x."""
        for i, face in enumerate(shape.Faces, 1):
            bound = face.BoundBox
            if abs(bound.XMin - x) < 1e-7 and abs(bound.XMax - x) < 1e-7:
                if face.normalAt(0, 0).x > 0.5:
                    return f"Face{i}"
        return None

    def testCrossDocumentFuseKeepsReferenceAfterReorder(self):
        """A Part::MultiFuse of an App::Link to a box in another document and a local box with
        the box's ID, and a reference to the local box's +X face: after the fuse's inputs are
        reordered, the reference still names that face (ops#56). Before, the boxes' faces had
        the same names, and the reference moved to the linked box's +X face."""
        self._checkFuseReorder(solver=False)

    def testCrossDocumentFuseKeepsReferenceAfterReorderSolver(self):
        """As testCrossDocumentFuseKeepsReferenceAfterReorder, with the reference solver on."""
        self._checkFuseReorder(solver=True)

    @staticmethod
    def _paddedSquare(doc, x):
        """A Body with a sketch of the square x..x+10, 0..10 padded 10 high: the same objects,
        so the same IDs, in every document numbered from 1. Returns the Pad."""
        import Sketcher

        body = doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        corners = [
            App.Vector(x, 0, 0),
            App.Vector(x + 10, 0, 0),
            App.Vector(x + 10, 10, 0),
            App.Vector(x, 10, 0),
        ]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        return pad

    def _checkBinderReorder(self, solver):
        # Arrange
        #   Src56: the padded square at x = 0..10. Asm56: the same objects with the square at
        #   x = 100..110 (a part made from the same template), then a binder of Src56's Pad and
        #   a fusion of the binder and the local Pad, which has the source Pad's ID
        src = self._numberedFromOne("Src56")
        source = self._paddedSquare(src, 0)
        src.recompute()
        src.save()
        asm = self._numberedFromOne("Asm56")
        asm.ReferenceSolver = solver
        local = self._paddedSquare(asm, 100)
        binder = asm.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(source, ("",))]
        fuse = asm.addObject("Part::MultiFuse", "F")
        fuse.Shapes = [binder, local]
        ref = asm.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyLinkSub", "Face")
        asm.recompute()
        self.assertEqual(local.ID, source.ID)
        self.assertTrue(fuse.isValid())
        self.assertAlmostEqual(fuse.Shape.Volume, 2000)
        ref.Face = (fuse, [self._faceFacingX(fuse.Shape, 110)])
        asm.recompute()
        #   the binder's names end in a boundary section with its ID; its faces' history goes on
        #   in Src56 (the Pad, or its sketch for the bottom face the sketch names), never to the
        #   local copies with the same IDs
        boundary = f";{binder.ID};EXT;0;F;0;_;_"
        names = binder.Shape.ElementReverseMap
        for index in range(1, len(binder.Shape.Faces) + 1):
            sub = f"Face{index}"
            history = self._history(binder, sub)
            with self.subTest(binderFace=sub, history=history):
                self.assertTrue(App.expandMappedName(names[sub]).endswith(boundary))
                self.assertEqual(history[0], "Asm56#Binder")
                self.assertGreater(len(history), 1)
                for step in history[1:]:
                    self.assertTrue(step.startswith("Src56#"))
        #   the fusion's faces from the binder keep the section, the local Pad's have none; no
        #   duplicate counts
        names = fuse.Shape.ElementReverseMap
        for index, face in enumerate(fuse.Shape.Faces, 1):
            name = App.expandMappedName(names[f"Face{index}"])
            with self.subTest(face=index, name=name):
                self.assertEqual(name.endswith(boundary), face.BoundBox.XMax < 50)
                self.assertEqual(App.getDecodedMappedName(name)[-1]["duplicateCount"], "0")

        # Act
        fuse.Shapes = [local, binder]
        asm.recompute()

        # Assert
        self.assertEqual(ref.Face[1][0], self._faceFacingX(fuse.Shape, 110))

    def testCrossDocumentBinderHistoryAndReference(self):
        """A SubShapeBinder of a Pad in another document, fused with a local Pad that has the
        same ID (both documents made the same way), and a reference to the local Pad's +X face:
        the binder's faces trace back to the source Pad, and the reference keeps its face after
        the fusion's inputs are reordered (ops#56). Before, the binder's faces and the local
        Pad's had the same names."""
        self._checkBinderReorder(solver=False)

    def testCrossDocumentBinderHistoryAndReferenceSolver(self):
        """As testCrossDocumentBinderHistoryAndReference, with the reference solver on."""
        self._checkBinderReorder(solver=True)

    def testNestedLinkPathHistory(self):
        """A Part::Cut in document Top of a Link to an App::Part in document Mid, which holds a
        Link to a box in document Src56; in each document the first object has ID 1. The Cut's
        names from the box cross two boundaries (two EXT sections, the inner Link's first), and
        their history reaches the box in Src56 through both Links, never an object with ID 1 in
        Top or Mid (ops#56)."""
        # Arrange
        box = self._linkedSource()
        mid = self._numberedFromOne("Mid56")
        group = mid.addObject("App::Part", "Group")  # ID 1, as the box
        inner = mid.addObject("App::Link", "Inner")
        inner.LinkedObject = box
        group.addObject(inner)
        mid.recompute()
        mid.save()
        top = self._numberedFromOne("Top56")
        decoy = top.addObject("Part::Box", "Decoy")  # ID 1
        decoy.Placement.Base = App.Vector(100, 0, 0)
        outer = top.addObject("App::Link", "Outer")
        outer.LinkedObject = group
        tool = top.addObject("Part::Box", "Tool")
        tool.Length = tool.Width = tool.Height = 4
        tool.Placement.Base = App.Vector(8, 8, 8)
        cut = top.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = outer, tool

        # Act
        top.recompute()

        # Assert
        self.assertEqual((decoy.ID, group.ID), (box.ID, box.ID))
        self.assertAlmostEqual(cut.Shape.Volume, 1000 - 8)
        names = cut.Shape.ElementReverseMap
        boundaries = f";{inner.ID};EXT;0;F;0;_;_|_;_;{outer.ID};EXT;0;F;0;_;_"
        for index, face in enumerate(cut.Shape.Faces, 1):
            sub = f"Face{index}"
            bound = face.BoundBox
            fromTool = any(
                abs(low - 8) < 1e-7 and abs(high - 8) < 1e-7
                for low, high in (
                    (bound.XMin, bound.XMax),
                    (bound.YMin, bound.YMax),
                    (bound.ZMin, bound.ZMax),
                )
            )
            name = App.expandMappedName(names[sub])
            history = self._history(cut, sub)
            with self.subTest(face=sub, name=name, history=history):
                self.assertEqual(boundaries in name, not fromTool)
                self.assertNotIn("Top56#Decoy", history)
                self.assertNotIn("Mid56#Group", history)
                self.assertEqual(history[-1], "Top56#Tool" if fromTool else "Src56#Src")
                if not fromTool:
                    self.assertIn("Top56#Outer", history)
                    self.assertIn("Mid56#Inner", history)

    def _checkTwoLinks(self, solver):
        # Arrange
        #   Asm56: Links L1 (at the box's place) and L2 (moved to x = 100) to the box in Src56,
        #   and a local box Other (ID 1, as the source box) at y = 100, fused
        box = self._linkedSource()
        asm = self._numberedFromOne("Asm56")
        asm.ReferenceSolver = solver
        other = asm.addObject("Part::Box", "Other")
        other.Placement.Base = App.Vector(0, 100, 0)
        links = []
        for name, x in (("L1", 0), ("L2", 100)):
            link = asm.addObject("App::Link", name)
            link.LinkedObject = box
            link.Placement.Base = App.Vector(x, 0, 0)
            links.append(link)
        fuse = asm.addObject("Part::MultiFuse", "F")
        fuse.Shapes = links + [other]
        ref = asm.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyLinkSub", "Face")
        asm.recompute()
        self.assertAlmostEqual(fuse.Shape.Volume, 3000)
        ref.Face = (fuse, [self._faceFacingX(fuse.Shape, 110)])
        asm.recompute()
        #   18 faces, 18 distinct names, no duplicate counts
        names = fuse.Shape.ElementReverseMap
        faceNames = [App.expandMappedName(names[f"Face{i}"]) for i in range(1, 19)]
        self.assertEqual(len(fuse.Shape.Faces), 18)
        self.assertEqual(len(set(faceNames)), 18)
        for name in faceNames:
            with self.subTest(name=name):
                self.assertEqual(App.getDecodedMappedName(name)[-1]["duplicateCount"], "0")

        # Act
        fuse.Shapes = [links[1], other]
        asm.recompute()

        # Assert
        self.assertTrue(fuse.isValid())
        self.assertAlmostEqual(fuse.Shape.Volume, 2000)
        self.assertEqual(ref.Face[1][0], self._faceFacingX(fuse.Shape, 110))

    def testTwoLinksToOneSourceStayDistinct(self):
        """Two App::Links to one box in another document, fused with a local box: the two
        copies' faces have distinct names, and a reference to the second copy's +X face keeps
        it when the first Link leaves the fusion (ops#56). Before, the copies had the same
        names, told apart only by duplicate counts."""
        self._checkTwoLinks(solver=False)

    def testTwoLinksToOneSourceStayDistinctSolver(self):
        """As testTwoLinksToOneSourceStayDistinct, with the reference solver on."""
        self._checkTwoLinks(solver=True)

    def testCrossDocumentCutOnLinkWithTheSourcesId(self):
        """A Part::Cut of an App::Link that has the same ID as the box it links to in another
        document (the Link is object 1 of its document): the box's faces keep the form they have
        under any other ID, `<face>;_;<box ID>;MKR;...|_;_;<Link ID>;EXT;...`, and trace back
        through the Link to the box. Before, with equal IDs the Link's shape reached the Cut
        unnamed and the Cut named those faces with its own op (ops#56, the MKR/CUT flip)."""
        # Arrange
        box = self._linkedSource()
        asm = self._numberedFromOne("Asm56")
        link = asm.addObject("App::Link", "L")  # ID 1, as the box
        link.LinkedObject = box
        tool = asm.addObject("Part::Box", "Tool")
        tool.Length = tool.Width = tool.Height = 4
        tool.Placement.Base = App.Vector(8, 8, 8)
        cut = asm.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = link, tool

        # Act
        asm.recompute()

        # Assert
        self.assertEqual(link.ID, box.ID)
        self.assertAlmostEqual(cut.Shape.Volume, 1000 - 8)
        names = cut.Shape.ElementReverseMap
        fromBox = 0
        for index, face in enumerate(cut.Shape.Faces, 1):
            bound = face.BoundBox
            if any(
                abs(low - 8) < 1e-7 and abs(high - 8) < 1e-7
                for low, high in (
                    (bound.XMin, bound.XMax),
                    (bound.YMin, bound.YMax),
                    (bound.ZMin, bound.ZMax),
                )
            ):
                continue  # a face of the tool
            fromBox += 1
            sub = f"Face{index}"
            sections = App.getDecodedMappedName(App.expandMappedName(names[sub]))
            history = self._history(cut, sub)
            with self.subTest(face=sub, sections=sections, history=history):
                self.assertEqual(len(sections), 2)
                self.assertEqual(
                    (sections[0]["opCode"], sections[0]["iterationTag"]), ("MKR", str(box.ID))
                )
                self.assertEqual(
                    (sections[1]["opCode"], sections[1]["iterationTag"]), ("EXT", str(link.ID))
                )
                self.assertEqual(history, ["Asm56#Cut", "Asm56#L", "Src56#Src"])
        self.assertEqual(fromBox, 6)

    def testLinkInTheSameDocumentKeepsTheNames(self):
        """An App::Link to a Body in the same document has the Body's names, with no boundary
        section, and a fusion of the Body and the Link gives the copies the same names told
        apart by duplicate counts, as in FreeCAD 1.1.3 (ops#104: same-document links are left
        as they are; ops#56's section is for links across documents only)."""
        # Arrange
        doc = self._numberedFromOne("Same56")
        pad = self._paddedSquare(doc, 0)
        body = pad.getParentGeoFeatureGroup()
        link = doc.addObject("App::Link", "L")
        link.LinkedObject = body
        link.Placement.Base = App.Vector(100, 0, 0)
        fuse = doc.addObject("Part::MultiFuse", "F")
        fuse.Shapes = [body, link]

        # Act
        doc.recompute()

        # Assert
        self.assertAlmostEqual(fuse.Shape.Volume, 2000)
        expand = App.expandMappedName
        linkNames = sorted(expand(n) for n in link.Shape.ElementMap)
        self.assertEqual(linkNames, sorted(expand(n) for n in body.Shape.ElementMap))
        names = [expand(n) for n in fuse.Shape.ElementMap]
        self.assertTrue(names)
        self.assertFalse([n for n in names if ";EXT;" in n])
        counts = {App.getDecodedMappedName(n)[-1]["duplicateCount"] for n in names}
        self.assertIn("1", counts)

    def testCrossDocumentBinderOfAFace(self):
        """A SubShapeBinder of one face of a box in another document, where a local box has the
        box's ID: the bound face's name ends in a boundary section with the binder's ID, and its
        history reaches the box's Face6, never the local box (ops#56)."""
        # Arrange
        box = self._linkedSource()
        asm = self._numberedFromOne("Asm56")
        decoy = asm.addObject("Part::Box", "Decoy")  # ID 1, as the box
        decoy.Placement.Base = App.Vector(100, 0, 0)
        binder = asm.addObject("PartDesign::SubShapeBinder", "B")
        binder.Support = [(box, ("Face6",))]

        # Act
        asm.recompute()

        # Assert
        self.assertEqual(decoy.ID, box.ID)
        self.assertEqual(len(binder.Shape.Faces), 1)
        self.assertAlmostEqual(binder.Shape.Faces[0].BoundBox.ZMin, 10)
        name = App.expandMappedName(binder.Shape.ElementReverseMap["Face1"])
        self.assertTrue(name.endswith(f";{binder.ID};EXT;0;F;0;_;_"))
        history = binder.getElementHistory("Face1", True, False, True)
        objects = [item[0][0] if isinstance(item[0], tuple) else item[0] for item in history]
        self.assertEqual(objects, ["Asm56#B", "Src56#Src"])
        self.assertEqual(history[-1][1], "Face6")


class ElementReferenceTestV2i(ElementReferenceTest):
    """The same cases with every document in V2 with interned names (ops#6, Task 1 PR 8): the
    references are saved, refreshed and reported missing as they are with plain names."""

    MODE = ("V2", True)
