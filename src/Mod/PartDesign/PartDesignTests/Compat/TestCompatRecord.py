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

"""Units of Part's CompatRecord (FreeCAD-CH ops#343): what the record must see in shapes, values
and names that no corpus model holds yet, so that the reopen gate can't miss a change there.
Designed shapes only."""

import json
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
from FreeCAD import Vector as V

import CompatRecord


class TestCompatRecord(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.folder = None

    def tearDown(self):
        for doc in reversed(self.docs):
            App.closeDocument(doc.Name)
        if self.folder:
            shutil.rmtree(self.folder, ignore_errors=True)

    def newDocument(self, name):
        doc = App.newDocument(name)
        self.docs.append(doc)
        return doc

    def recordOf(self, shape):
        """The record of a document holding the shape in a Part::Feature named Shape"""
        doc = self.newDocument("CompatRecordShape")
        doc.addObject("Part::Feature", "Shape").Shape = shape
        doc.recompute()
        rec = CompatRecord.record(doc)
        App.closeDocument(doc.Name)
        self.docs.remove(doc)
        return rec

    def differences(self, a, b):
        lines, _ = CompatRecord.compare(a, b, "recompute")
        return [line for line in lines if not line.startswith("Shape.id")]

    def testSolidBesideAnInfinitePlaneIsRecordedInFull(self):
        # A compound of a box and an infinite plane (a Part::Compound holding a datum plane, a
        # binder of a datum and a solid): the box's volume, area, box, centre and names are
        # recorded, the plane counted. Recorded as an infinite shape, the box's move was unseen
        plane = Part.Face(Part.Plane(V(0, 0, 5), V(0, 0, 1)))
        rec = self.recordOf(Part.Compound([Part.makeBox(10, 20, 30), plane]))
        shape = rec["objects"]["Shape"]["shape"]
        self.assertNotIn("infinite", shape)
        self.assertEqual(shape["unbounded"], 1)
        self.assertAlmostEqual(shape["volume"], 6000)
        self.assertAlmostEqual(shape["area"], 2200)
        for value, expected in zip(shape["box"] + shape["centre"], [0, 0, 0, 10, 20, 30, 5, 10, 15]):
            self.assertAlmostEqual(value, expected)
        names = rec["objects"]["Shape"]["names"]
        plane = "Face infinite n=(0.0000,0.0000,1.0000) d=5.0000 : "
        self.assertTrue([line for line in names if line.startswith(plane)])
        self.assertFalse([line for line in names if "e+" in line])
        moved = self.recordOf(Part.Compound([Part.makeBox(10, 20, 30, V(1, 0, 0)), plane]))
        self.assertTrue(self.differences(rec, moved))

    def testDegenerateEdgeIsKeyedByItsVertex(self):
        # ops#538: a cone's apex edge has zero length, so no defined centre of mass: OCCT gives
        # (0, 0, 0) for it here, and gen0-macos/HoleFeature's apex edge read as (10, 10, 10) on
        # Windows and as its vertex on macOS. It is keyed (and named) at its vertex, the apex at
        # (3, 4, 15), away from the origin so an undefined centre can't match it by chance.
        cone = Part.makeCone(5, 0, 10, V(3, 4, 5))
        apex = [e for e in cone.Edges if e.Length < 1e-7]
        self.assertEqual(len(apex), 1)
        for actual, expected in zip(CompatRecord.elementKey(apex[0])["centre"], (3, 4, 15)):
            self.assertAlmostEqual(actual, expected, places=9)
        names = self.recordOf(cone)["objects"]["Shape"]["names"]
        apexLine = "Edge c=(3.0000,4.0000,15.0000) m=0.0000"
        self.assertTrue(any(line.startswith(apexLine) for line in names), names)
        # an edge with a length keeps its centre of mass
        rim = [e for e in cone.Edges if abs(e.Length - 10 * 3.141592653589793) < 1e-9]
        self.assertEqual(len(rim), 1)
        for actual, expected in zip(CompatRecord.elementKey(rim[0])["centre"], (3, 4, 5)):
            self.assertAlmostEqual(actual, expected, places=9)

    def testInfinitePlaneIsRecordedWithItsPlane(self):
        # An infinite plane on an object other than a datum (a binder of a datum plane): its
        # position is in no property of its own, so the record keeps the plane
        rec = self.recordOf(Part.Face(Part.Plane(V(0, 0, 5), V(0, 0, 1))))
        shape = rec["objects"]["Shape"]["shape"]
        self.assertTrue(shape["infinite"])
        self.assertEqual(shape["plane"], {"normal": [0.0, 0.0, 1.0], "offset": 5.0})
        moved = self.recordOf(Part.Face(Part.Plane(V(0, 0, 6), V(0, 0, 1))))
        self.assertTrue(self.differences(rec, moved))

    def testPlainPythonDataIsRecordedByItsContent(self):
        # A PropertyPythonObject holding plain data: its content, not "builtins.dict" (a dict's
        # __getstate__() is None on Python 3.11+, so its content went unseen)
        def recorded(data):
            doc = self.newDocument("CompatRecordData")
            obj = doc.addObject("App::FeaturePython", "Holder")
            obj.addProperty("App::PropertyPythonObject", "Data")
            obj.Data = data
            rec = CompatRecord.record(doc)
            App.closeDocument(doc.Name)
            self.docs.remove(doc)
            return rec

        rec = recorded({"b": [1, 2.5], "a": "x"})
        kind, value = rec["objects"]["Holder"]["props"]["Data"]
        self.assertEqual(kind, "App::PropertyPythonObject")
        self.assertEqual(value, {"a": "x", "b": [1, 2.5]})
        self.assertEqual(CompatRecord.opaqueValues(rec), [])
        lines, _ = CompatRecord.compare(rec, recorded({"b": [1, 2.5], "a": "y"}), "recompute")
        self.assertTrue([line for line in lines if line.startswith("Holder.Data")])

    def testReferenceToAnInfiniteFace(self):
        # A reference to a datum plane's face (DatumPlane:Face1), and to an infinite cylinder:
        # keyed by the surface's type, and a plane by its normal and offset
        doc = self.newDocument("CompatRecordRefs")
        body = doc.addObject("PartDesign::Body", "Body")
        datum = body.newObject("PartDesign::Plane", "DatumPlane")
        datum.MapMode = "Deactivated"
        datum.Placement = App.Placement(V(0, 0, 7), App.Rotation())
        cylinder = doc.addObject("Part::Feature", "Cylinder")
        cylinder.Shape = Part.Face(Part.Cylinder())
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubList", "Refs")
        holder.Refs = [(datum, ["Face1"]), (cylinder, ["Face1"])]
        doc.recompute()
        refs = CompatRecord.record(doc)["objects"]["Holder"]["refs"]
        plane = refs["Refs[0]"]["key"]
        self.assertEqual(plane["kind"], "Face")
        self.assertTrue(plane["infinite"])
        self.assertEqual(plane["surface"], "Plane")
        self.assertAlmostEqual(abs(plane["normal"][2]), 1.0)
        self.assertAlmostEqual(abs(plane["offset"]), 7.0)
        tube = refs["Refs[1]"]["key"]
        self.assertTrue(tube["infinite"])
        self.assertEqual(tube["surface"], "Cylinder")

    def testOtherDocumentsTagsAreMasked(self):
        # A link across documents names its elements with the other document's object ids: masked
        # as `{stem#Name}`, as the document's own are as `{Name}`, so a regeneration (new ids)
        # doesn't rewrite them
        self.folder = tempfile.mkdtemp(prefix="CompatRecord")
        part = self.newDocument("CompatRecordPart")
        box = part.addObject("Part::Box", "Box")
        part.recompute()
        part.saveAs(os.path.join(self.folder, "PartFile.FCStd"))
        assembly = self.newDocument("CompatRecordAssembly")
        assembly.saveAs(os.path.join(self.folder, "AssemblyFile.FCStd"))
        link = assembly.addObject("App::Link", "Link")
        link.LinkedObject = box
        assembly.recompute()
        masker = CompatRecord._Masker(assembly)
        if str(box.ID) not in {str(obj.ID) for obj in assembly.Objects}:
            self.assertEqual(masker.tag(str(box.ID)), "{PartFile#Box}")
            self.assertEqual(masker.tag("-" + str(box.ID)), "{-PartFile#Box}")
        self.assertEqual(masker.tag(str(link.ID)), "{Link}")


class TestCompatDeltas(unittest.TestCase):
    """A generation's delta file (beta-compatibility 3.5, ops#640 SC7): an intended change of a
    float, the record's old value and the build's new one, each within the entry's tolerance;
    anything else still a difference. Records of a designed box, scaled by hand."""

    def setUp(self):
        doc = App.newDocument("CompatDeltaBox")
        try:
            doc.addObject("Part::Feature", "Shape").Shape = Part.makeBox(2, 3, 4)
            doc.recompute()
            self.old = CompatRecord.record(doc)
        finally:
            App.closeDocument(doc.Name)
        self.new = json.loads(
            json.dumps(self.old)
        )
        self.volume = self.old["objects"]["Shape"]["shape"]["volume"]  # 24 within 1e-15
        self.new["objects"]["Shape"]["shape"]["volume"] = self.volume * (1 + 1e-6)

    def lines(self, deltas, actual=None, allDeltas=True):
        lines, _ = CompatRecord.compare(
            self.old, actual or self.new, "recompute", deltas=deltas, allDeltas=allDeltas
        )
        return lines

    def testWithoutADeltaTheChangeIsRed(self):
        self.assertEqual(
            [line.split(":")[0] for line in self.lines(None)], ["Shape.shape.volume"]
        )

    def testTheDeltaMadeOfTheChangeHoldsIt(self):
        entries, others = CompatRecord.deltaEntries(self.old, self.new, "recompute")
        self.assertEqual(others, [])
        self.assertEqual(list(entries), ["Shape.shape.volume"])
        self.assertEqual(entries["Shape.shape.volume"]["old"], self.volume)
        self.assertEqual(self.lines(entries), [])

    def testANewValueOffTheDeltaIsRed(self):
        entries, _ = CompatRecord.deltaEntries(self.old, self.new, "recompute")
        wrong = json.loads(
            json.dumps(self.new)
        )
        wrong["objects"]["Shape"]["shape"]["volume"] = self.volume * (1 + 2e-6)
        self.assertEqual(len(self.lines(entries, wrong)), 1)
        self.assertIn("the delta's new value", self.lines(entries, wrong)[0])
        # within the entry's own tolerance it holds (another platform's spread)
        wrong["objects"]["Shape"]["shape"]["volume"] = self.volume * (1 + 1e-6) * (1 + 1e-11)
        self.assertEqual(self.lines(entries, wrong), [])

    def testADeltaOnAnotherOldValueIsRed(self):
        entries = {"Shape.shape.volume": {"old": 25.0, "new": self.volume * (1 + 1e-6), "rel": 1e-9}}
        self.assertIn("the delta's old value", self.lines(entries)[0])

    def testAStaleDeltaIsRedUnlessNotAllAreCompared(self):
        entries, _ = CompatRecord.deltaEntries(self.old, self.new, "recompute")
        entries["Gone.shape.area"] = {"old": 1.0, "new": 2.0, "rel": 1e-9}
        self.assertEqual(self.lines(entries), ["Gone.shape.area: a delta entry that nothing compared"])
        self.assertEqual(self.lines(entries, allDeltas=False), [])

    def testADeltaFileReads(self):
        folder = tempfile.mkdtemp(prefix="compat-delta-")
        try:
            path = os.path.join(folder, "Model.delta.json")
            body = {
                "format": 1,
                "issue": "ops#640",
                "label": "compat-change",
                "approved": "test",
                "why": "test",
                "changes": {"Model": {"Shape.shape.volume": {"old": 24.0, "new": 24.1}}},
            }
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(body))
            self.assertEqual(
                CompatRecord.loadDeltas(folder, "Model"), body["changes"]
            )
            self.assertEqual(CompatRecord.loadDeltas(folder, "Other"), {})
            body["label"] = "accepted"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(body))
            with self.assertRaises(ValueError):
                CompatRecord.loadDeltas(folder, "Model")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TestCompatNamesMeasure(unittest.TestCase):
    """A names line's `m=` (an area or length printed beside the name) compares within
    CompatRecord.NAMES_MEASURE_REL, the rest of the line exactly; and a difference a delta can't
    hold stops make_delta (the coordinator's ruling c742, ops#640)."""

    LINE = "Face c=(1.0000,2.0000,3.0000) m={} : _;_;{{Box}};MLN;26;F;0;_;_"

    def records(self, newMeasure, newName=None):
        old = {"objects": {"Body": {"type": "PartDesign::Body", "names": [
            self.LINE.format("10.0000"), "Vertex c=(0.0000,0.0000,0.0000) m=0.0000 : -"]}}}
        new = json.loads(json.dumps(old))
        line = self.LINE.format(newMeasure)
        new["objects"]["Body"]["names"][0] = newName and line.replace("{Box}", newName) or line
        return old, new

    def lines(self, old, new):
        return CompatRecord.compare(old, new, "recompute")[0]

    def testAMeasureWithinTheToleranceMatches(self):
        self.assertEqual(self.lines(*self.records("10.0020")), [])  # 2e-4 relative

    def testAMeasureBeyondTheToleranceIsRed(self):
        lines = self.lines(*self.records("10.0200"))  # 2e-3 relative
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("Body.names: 1 lines gone, 1 new"), lines[0])

    def testTheRestOfTheLineIsExact(self):
        self.assertEqual(len(self.lines(*self.records("10.0000", "Cylinder"))), 1)

    def testEqualLinesCountedDifferentlyAreRed(self):
        old, new = self.records("10.0000")
        new["objects"]["Body"]["names"].append(new["objects"]["Body"]["names"][0])
        self.assertEqual(CompatRecord.unmatchedNameLines(
            old["objects"]["Body"]["names"], new["objects"]["Body"]["names"]),
            ([], [self.LINE.format("10.0000")]))

    def testMakeDeltaStopsOnANamesChange(self):
        from PartDesignTests.Compat import make_delta
        import contextlib
        import io

        old, new = self.records("10.0200")
        folder = tempfile.mkdtemp(prefix="compat_make_delta_")
        try:
            report, corpus = os.path.join(folder, "report"), os.path.join(folder, "corpus")
            os.makedirs(report)
            os.makedirs(os.path.join(corpus, "gen1"))
            stem = "gen1-Model-alone.recompute.Doc"
            for rec, kind in ((old, "expected"), (new, "actual")):
                with open(os.path.join(report, f"{stem}.{kind}.json"), "w", encoding="utf-8") as fh:
                    json.dump(rec, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = make_delta.main([report, corpus, "--issue", "ops#640", "--label",
                                        "compat-neutral", "--approved", "test", "--why", "test"])
            self.assertEqual(code, 1)
            self.assertIn(f"not a delta: {stem}.expected.json: Body.names", out.getvalue())
            self.assertEqual(os.listdir(os.path.join(corpus, "gen1")), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TestCompatMovedBody(unittest.TestCase):
    """An intended move of a body (ops#683, C2: a mate on a bottom face turns its part 180 degrees
    about x): its Placement's delta entries hold it, its element names follow the placement
    change, and the controls of c768's ruling stay red. A designed box, moved by hand."""

    OLD = App.Placement(V(1, -1, 13), App.Rotation(V(0, 0, 1), 4))
    NEW = App.Placement(V(10, 20, 5), App.Rotation(V(1, 0, 0), 180))

    def setUp(self):
        doc = App.newDocument("CompatMovedBox")
        try:
            box = doc.addObject("Part::Feature", "Box")
            box.Shape = Part.makeBox(20, 20, 5)
            box.Placement = self.OLD
            doc.recompute()
            self.old = CompatRecord.record(doc)
            box.Placement = self.NEW
            doc.recompute()
            self.new = CompatRecord.record(doc)
        finally:
            App.closeDocument(doc.Name)

    def copy(self, rec):
        return json.loads(json.dumps(rec))

    def lines(self, deltas, actual=None):
        return CompatRecord.compare(self.old, actual or self.new, "recompute", deltas=deltas)[0]

    def entries(self):
        entries, others = CompatRecord.deltaEntries(self.old, self.new, "recompute")
        self.assertEqual(others, [])
        return entries

    def testTheMoveIsRedWithoutItsDeltas(self):
        lines = self.lines(None)
        self.assertTrue(any(line.startswith("Box.Placement.") for line in lines), lines)
        self.assertTrue(any(line.startswith("Box.names:") for line in lines), lines)

    def testItsDeltasHoldTheMoveAndTheNamesFollow(self):
        entries = self.entries()
        self.assertTrue(any(where.startswith("Box.Placement.rotation[") for where in entries))
        for where, entry in entries.items():
            if where.startswith("Box.Placement."):
                self.assertEqual((entry["rel"], entry["abs"]), CompatRecord.PLACEMENT_TOLERANCE)
        self.assertEqual(self.lines(entries), [])

    def testNamesThatDontFollowThePlacementAreRed(self):
        entries = self.entries()
        stale = self.copy(self.new)
        stale["objects"]["Box"]["names"] = list(self.old["objects"]["Box"]["names"])
        lines = self.lines(entries, stale)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("Box.names:"), lines[0])

    def testAWrongDeltaPlacementIsRed(self):
        entries = self.entries()
        wrong = self.copy(entries)
        wrong["Box.Placement.base[0]"]["new"] += 1.0
        lines = self.lines(wrong)
        self.assertTrue(any("Box.Placement.base[0] (the delta's new value)" in line for line in lines), lines)

    def testA1e9ChangeInAQuaternionComponentIsRed(self):
        entries = self.entries()
        slipped = self.copy(self.new)
        q = slipped["objects"]["Box"]["props"]["Placement"][1]["rotation"]
        i = max(range(4), key=lambda k: abs(q[k]))
        q[i] += 1e-9
        lines = self.lines(entries, slipped)
        self.assertTrue(any(f"Box.Placement.rotation[{i}]" in line for line in lines), lines)

    def testWithoutNamesInTheBuildsRecordNoNamesAreCompared(self):
        # a generation of another naming revision: the gate records no names for the build
        bare = self.copy(self.new)
        for obj in bare["objects"].values():
            obj.pop("names", None)
        entries, others = CompatRecord.deltaEntries(self.old, bare, "recompute")
        self.assertEqual(others, [])
        self.assertTrue(entries)

    def testMakeDeltaPassesAgreeWithinTheAbsoluteFloor(self):
        from PartDesignTests.Compat import make_delta

        folder = tempfile.mkdtemp(prefix="compat_make_delta_floor_")
        try:
            old = {"objects": {"J": {"type": "App::FeaturePython", "props": {
                "Placement2": ["App::PropertyPlacement", {"base": [0.0, 0.0, 0.0],
                                                          "rotation": [0.0, 0.0, 0.0, 1.0]}]}}}}
            recompute = self.copy(old)
            recompute["objects"]["J"]["props"]["Placement2"][1]["rotation"] = [1.0, 0.0, 0.0, 0.0]
            roundtrip = self.copy(recompute)
            roundtrip["objects"]["J"]["props"]["Placement2"][1]["rotation"] = [1.0, 0.0, 0.0, 6.123e-17]
            for passName, new in (("recompute", recompute), ("roundtrip", roundtrip)):
                stem = f"gen1-Model-alone.{passName}.Doc"
                for rec, kind in ((old, "expected"), (new, "actual")):
                    with open(os.path.join(folder, f"{stem}.{kind}.json"), "w", encoding="utf-8") as fh:
                        json.dump(rec, fh)
            found, problems = make_delta.collect(folder, CompatRecord.DELTA_TOLERANCE[0])
            self.assertEqual(problems, [])
            held = found["gen1"]["Model"]["Doc"]
            self.assertEqual(sorted(held), ["J.Placement2.rotation[0]", "J.Placement2.rotation[3]"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def testAReferencesMovedFaceIsADeltaToo(self):
        # an angle mate that turns its part moves the face it references (ops#683, AsmMotion)
        def rec(centre, normal):
            return {"objects": {"Angle": {"type": "App::FeaturePython", "props": {}, "refs": {
                "Reference2[0]": {"target": "Tilted", "sub": "Face5",
                                  "key": {"centre": centre, "normal": normal}}}}}}
        old = rec([52.5, 22.165063509461095, 6.25], [0.0, 0.5, -0.8660254037844387])
        new = rec([52.5, 17.8349364905389, 6.25], [0.0, 0.5, 0.8660254037844388])
        entries, others = CompatRecord.deltaEntries(old, new, "recompute")
        self.assertEqual(others, [])
        where = "Angle.Reference2[0] (Face5 -> Face5).centre[1]"
        self.assertIn(where, entries)
        self.assertEqual(CompatRecord.compare(old, new, "recompute", deltas=entries)[0], [])
        wrong = json.loads(json.dumps(new))
        wrong["objects"]["Angle"]["refs"]["Reference2[0]"]["key"]["centre"][1] += 1e-3
        self.assertIn(where + " (the delta's new value)",
                      CompatRecord.compare(old, wrong, "recompute", deltas=entries)[0][0])

    # c768's controls (ops#673 6871844284): both must be red

    def angleRecords(self):
        def rec(centre, normal):
            return {"objects": {"Angle": {"type": "App::FeaturePython", "props": {}, "refs": {
                "Reference2[0]": {"target": "Tilted", "sub": "Face5",
                                  "key": {"centre": centre, "normal": normal}}}}}}
        return (rec([52.5, 22.165063509461095, 6.25], [0.0, 0.5, -0.8660254037844387]),
                rec([52.5, 17.8349364905389, 6.25], [0.0, 0.5, 0.8660254037844388]))

    def testAReferencedFaceThatMovesWithoutADeltaIsRed(self):
        old, new = self.angleRecords()
        lines = CompatRecord.compare(old, new, "recompute")[0]
        self.assertIn("Angle.Reference2[0] (Face5 -> Face5).centre[1]", "\n".join(lines))
        self.assertIn("Angle.Reference2[0] (Face5 -> Face5).normal[2]", "\n".join(lines))

    def testADeltaForRecomputeAndRoundtripIsRedWhenTheOpenPassChangesToo(self):
        # 'passes' holds only where the open pass is checked unchanged: the gate's open pass takes
        # the entries `deltasFor(..., "open")` leaves, so a change the open pass sees stays red there
        old, new = self.angleRecords()
        entries, others = CompatRecord.deltaEntries(old, new, "recompute")
        self.assertEqual(others, [])
        for entry in entries.values():
            entry["passes"] = ["recompute", "roundtrip"]
        self.assertEqual(
            CompatRecord.compare(old, new, "recompute", deltas=CompatRecord.deltasFor(entries, "recompute"))[0], [])
        lines = CompatRecord.compare(old, new, "open", deltas=CompatRecord.deltasFor(entries, "open"))[0]
        self.assertTrue(any("Angle.Reference2[0] (Face5 -> Face5).centre[1]" in line for line in lines), lines)

    def testMakeDeltaWritesNoPassesForAChangeTheOpenPassSaw(self):
        from PartDesignTests.Compat import make_delta

        old, new = self.angleRecords()
        folder = tempfile.mkdtemp(prefix="compat_make_delta_open_")
        try:
            for passName in ("open", "recompute"):
                stem = f"gen1-Model-alone.{passName}.Doc"
                for rec, kind in ((old, "expected"), (new, "actual")):
                    with open(os.path.join(folder, f"{stem}.{kind}.json"), "w", encoding="utf-8") as fh:
                        json.dump(rec, fh)
            found, problems = make_delta.collect(folder, CompatRecord.DELTA_TOLERANCE[0])
            self.assertEqual(problems, [])
            for entry in found["gen1"]["Model"]["Doc"].values():
                self.assertNotIn("passes", make_delta.entryOf(entry))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
