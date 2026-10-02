# SPDX-License-Identifier: LGPL-2.1-or-later

"""Fingerprints of element references, saved as `fp` in solver documents (ops#7)."""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part


def _documentXml(path):
    with zipfile.ZipFile(path) as archive:
        return archive.read("Document.xml").decode("utf-8")


def _objectData(xml):
    """The objects' part of Document.xml: everything but the document's own properties, which
    hold the save time and the file name."""
    return xml[xml.index("<Objects ") :]


def _fingerprints(xml):
    return re.findall(r' fp="([^"]*)"', xml)


def _number(value):
    """A number as the fingerprint text writes it."""
    if abs(value) < 1e-12:
        value = 0.0
    return "%.12g" % value


def _vector(v):
    return ",".join(_number(c) for c in (v.x, v.y, v.z))


def _planeFingerprint(face):
    """The expected text of a planar face, from the Python geometry API (an independent path):
    version 3, with the face's bounding box (Task 2 PR 8)."""
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    box = face.optimalBoundingBox(False, False)
    corners = (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)
    return "3|F|Plane|%s|%s|%s|_|%s" % (
        _number(face.Area),
        _vector(face.CenterOfMass),
        _vector(normal),
        ",".join(_number(c) for c in corners),
    )


class ReferenceFingerprintTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ReferenceFingerprintTest")
        self.docNames = []

    def tearDown(self):
        for name in self.docNames:
            if name in App.listDocuments():
                App.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _model(self, name, algorithm="V2", solver=False):
        """A box (moved, so the placement must not reach the fingerprints) and an object whose
        four link properties hold element references to it."""
        doc = App.newDocument(name)
        self.docNames.append(doc.Name)
        doc.HistoryAlgorithm = algorithm
        box = doc.addObject("Part::Box", "Box")
        box.Placement = App.Placement(App.Vector(30, -5, 2), App.Rotation(App.Vector(0, 0, 1), 30))
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSub", "Sub")
        holder.addProperty("App::PropertyLinkSubList", "SubList")
        holder.addProperty("App::PropertyXLinkSub", "XSub")
        holder.addProperty("App::PropertyXLinkSubList", "XSubList")
        doc.recompute()
        # Explicitly, also when off: FREECAD_REFERENCE_SOLVER=1 turns it on in new documents.
        doc.ReferenceSolver = solver
        holder.Sub = (box, ["Face1", "Face6"])
        holder.SubList = [(box, "Face2"), (box, "Edge1")]
        holder.XSub = (box, ["Vertex1"])
        holder.XSubList = [(box, ["Face3", "Face4"])]
        doc.recompute()
        return doc, box, holder

    def _save(self, doc, name):
        path = os.path.join(self.dir, name + ".FCStd")
        doc.saveAs(path)
        return path

    def testSolverOffSavesNoFingerprints(self):
        """A V2 document without the solver saves neither the switch nor fingerprints."""
        doc, _, _ = self._model("FingerprintOff")
        xml = _documentXml(self._save(doc, "off"))
        self.assertNotIn("ReferenceSolver", xml)
        self.assertEqual(_fingerprints(xml), [])

    def testSolverOnThenOffSavesAsBefore(self):
        """Turning the solver on and off again leaves the saved objects byte-identical."""
        doc, _, _ = self._model("FingerprintOnOff")
        before = _documentXml(self._save(doc, "before"))
        doc.ReferenceSolver = True
        doc.recompute()
        self.assertTrue(_fingerprints(_documentXml(self._save(doc, "on"))))
        doc.ReferenceSolver = False
        doc.recompute()
        after = _documentXml(self._save(doc, "after"))
        self.assertNotIn("ReferenceSolver", after)
        self.assertEqual(_objectData(after), _objectData(before))

    def testSwitchIgnoredInV1(self):
        doc, _, _ = self._model("FingerprintV1", algorithm="V1", solver=True)
        xml = _documentXml(self._save(doc, "v1"))
        self.assertEqual(_fingerprints(xml), [])

    def testFingerprintsSaved(self):
        """Every reference of the four property types saves its fingerprint, in the box's own
        coordinates: the box's placement is left out."""
        doc, box, _ = self._model("FingerprintOn", solver=True)
        xml = _documentXml(self._save(doc, "on"))
        self.assertIn('name="ReferenceSolver"', xml)
        fingerprints = _fingerprints(xml)
        self.assertEqual(len(fingerprints), 7, fingerprints)

        local = Part.makeBox(10, 10, 10)  # the box without its placement
        expected = {_planeFingerprint(local.Faces[i - 1]) for i in (1, 2, 3, 4, 6)}
        self.assertTrue(expected.issubset(set(fingerprints)), (expected, fingerprints))
        edge = local.Edges[0]
        direction = edge.Vertexes[1].Point - edge.Vertexes[0].Point
        direction.normalize()
        first = next(c for c in (direction.x, direction.y, direction.z) if abs(c) > 1e-12)
        if first < 0:
            direction = -direction
        self.assertIn(
            "1|E|Line|%s|%s|%s|_"
            % (_number(edge.Length), _vector(edge.CenterOfMass), _vector(direction)),
            fingerprints,
        )
        self.assertIn("1|V|Point|_|%s|_|_" % _vector(local.Vertexes[0].Point), fingerprints)
        # nothing global: the moved box gives the same text as the local one
        self.assertNotIn(_vector(box.Shape.Vertexes[0].Point), "".join(fingerprints))

    def testRoundTrip(self):
        """Saved fingerprints are read back: a reopened document saves them unchanged, including
        one of a reference whose element is gone, which keeps its last fingerprint."""
        doc, box, holder = self._model("FingerprintTrip", solver=True)
        # a reference to an element that will disappear: the second box of a compound
        other = doc.addObject("Part::Box", "Other")
        other.Placement.Base = App.Vector(50, 0, 0)
        compound = doc.addObject("Part::Compound", "Compound")
        compound.Links = [box, other]
        doc.recompute()
        holder.addProperty("App::PropertyLinkSub", "Gone")
        holder.Gone = (compound, ["Face12"])
        doc.recompute()
        first = _documentXml(self._save(doc, "first"))
        goneFingerprint = re.search(r'<LinkSub value="Compound"[^>]*>.*?fp="([^"]*)"', first, re.S)
        self.assertEqual(len(_fingerprints(first)), 8)

        compound.Links = [box]
        doc.recompute()
        self.assertTrue(holder.Gone[1][0].startswith("?"), holder.Gone)
        second = _documentXml(self._save(doc, "second"))
        # the missing reference kept its fingerprint
        self.assertEqual(sorted(_fingerprints(second)), sorted(_fingerprints(first)))

        path = os.path.join(self.dir, "second.FCStd")
        App.closeDocument(doc.Name)
        reopened = App.openDocument(path)
        self.docNames.append(reopened.Name)
        self.assertTrue(reopened.ReferenceSolver)
        third = _documentXml(self._save(reopened, "third"))
        self.assertEqual(_fingerprints(third), _fingerprints(second))
        self.assertIsNotNone(goneFingerprint)


if __name__ == "__main__":
    unittest.main()
