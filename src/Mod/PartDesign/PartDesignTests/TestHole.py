# SPDX-License-Identifier: LGPL-2.1-or-later

# **************************************************************************
#   Copyright (c) 2017 Kurt Kremitzki <kkremitzki@gmail.com>              *
#                                                                         *
#   This file is part of the FreeCAD CAx development system.              *
#                                                                         *
#   This program is free software; you can redistribute it and/or modify  *
#   it under the terms of the GNU Lesser General Public License (LGPL)    *
#   as published by the Free Software Foundation; either version 2 of     *
#   the License, or (at your option) any later version.                   *
#   for detail see the LICENCE text file.                                 *
#                                                                         *
#   FreeCAD is distributed in the hope that it will be useful,            *
#   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
#   GNU Library General Public License for more details.                  *
#                                                                         *
#   You should have received a copy of the GNU Library General Public     *
#   License along with FreeCAD; if not, write to the Free Software        *
#   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
#   USA                                                                   *
# **************************************************************************
from math import pi
import os
import tempfile
import unittest

import FreeCAD
import Part
import TestSketcherApp

App = FreeCAD


class TestHole(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestHole")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Box.Length = 10
        self.Box.Width = 10
        self.Box.Height = 10
        self.Body.addObject(self.Box)
        self.Doc.recompute()
        self.HoleSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchHole")
        self.HoleSketch.AttachmentSupport = (self.Doc.XY_Plane, [""])
        self.HoleSketch.MapMode = "FlatFace"
        self.HoleSketch.MapReversed = True
        self.Body.addObject(self.HoleSketch)
        TestSketcherApp.CreateCircleSketch(self.HoleSketch, (-5, 5), 1)
        self.Doc.recompute()
        self.Hole = self.Doc.addObject("PartDesign::Hole", "Hole")
        self.Hole.Profile = self.HoleSketch
        self.Body.addObject(self.Hole)
        self.Doc.recompute()

    def testPlainHole(self):
        self.Hole.Diameter = 6
        self.Hole.Depth = 10
        # self.Hole.DrillPointAngle = 118.000000
        # self.Hole.TaperedAngle = 90
        self.Hole.ThreadType = 0
        self.Hole.HoleCutType = 0  # 1 = Counterbore, 2 = Countersink
        # self.Hole.HoleCutDiameter = 5
        # self.Hole.HoleCutCountersinkAngle = 90
        # self.Hole.HoleCutDepth = 2 # Counterbore
        self.Hole.DepthType = 0  # 1 = Through all
        self.Hole.DrillPoint = 0  # 1 = Angled
        self.Hole.Tapered = 0  # On/off
        self.Doc.recompute()
        self.assertAlmostEqual(self.Hole.Shape.Volume, 10**3 - pi * 3**2 * 10)

    def testStartOffset(self):
        self.Hole.Diameter = 6
        self.Hole.Depth = 5
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 0
        self.Hole.StartType = "Offset"
        self.Hole.StartOffset = 2
        self.Doc.recompute()
        self.assertAlmostEqual(self.Hole.Shape.Volume, 10**3 - pi * 3**2 * 5)
        self.assertAlmostEqual(self.Hole.AddSubShape.BoundBox.ZMin, 2)
        self.assertAlmostEqual(self.Hole.AddSubShape.BoundBox.ZMax, 7)

        reference = self.Doc.addObject("Part::Feature", "StartReference")
        reference.Shape = Part.makePlane(20, 20, App.Vector(-10, -10, 1))
        self.Hole.StartType = "Reference"
        self.Hole.StartReference = (reference, ["Face1"])
        self.Doc.recompute()
        self.assertAlmostEqual(self.Hole.Shape.Volume, 10**3 - pi * 3**2 * 5)
        self.assertAlmostEqual(self.Hole.AddSubShape.BoundBox.ZMin, 3)
        self.assertAlmostEqual(self.Hole.AddSubShape.BoundBox.ZMax, 8)

    def testStartReferenceOffsetForPointProfile(self):
        self.HoleSketch.deleteAllGeometry()
        self.HoleSketch.AttachmentOffset.Base.z = 10
        for point in ((2, 2), (8, 2), (2, 8), (8, 8)):
            self.HoleSketch.addGeometry(Part.Point(App.Vector(*point)), False)

        self.Hole.BaseProfileType = 1
        self.Hole.Diameter = 2
        self.Hole.Depth = 5
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 0

        reference = self.Doc.addObject("Part::Feature", "StartReference")
        reference.Shape = Part.makePlane(20, 20, App.Vector(-5, -5, 20))
        self.Hole.StartType = "Reference"
        self.Hole.StartReference = (reference, ["Face1"])
        self.Hole.StartOffset = 2
        self.Doc.recompute()

        self.assertAlmostEqual(self.Hole.AddSubShape.BoundBox.ZMin, 22)
        self.assertAlmostEqual(self.Hole.AddSubShape.BoundBox.ZMax, 27)

    def testTaperedHole(self):
        self.Hole.Diameter = 6
        self.Hole.Depth = 5
        self.Hole.TaperedAngle = 60
        self.Hole.ThreadType = 0
        self.Hole.HoleCutType = 0
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 0
        self.Hole.Tapered = 1
        self.Doc.recompute()
        self.assertEqual(len(self.Hole.Shape.Faces), 8)

    def testAngledDrillHole(self):
        self.Hole.Diameter = 6
        self.Hole.Depth = 10
        self.Hole.DrillPointAngle = 118
        self.Hole.ThreadType = 0
        self.Hole.HoleCutType = 0
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 1
        self.Hole.Tapered = 0
        self.Hole.DrillForDepth = 1
        self.Doc.recompute()
        self.assertEqual(len(self.Hole.Shape.Faces), 8)

    def testCounterboreHole(self):
        self.Hole.Diameter = 6
        self.Hole.Depth = 10
        self.Hole.ThreadType = 0
        self.Hole.HoleCutType = 1
        self.Hole.HoleCutDiameter = 8
        self.Hole.HoleCutDepth = 5
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 0
        self.Hole.Tapered = 0
        self.Doc.recompute()
        self.assertAlmostEqual(self.Hole.Shape.Volume, 10**3 - pi * 3**2 * 5 - pi * 4**2 * 5)

    def testCountersinkHole(self):
        self.Hole.Diameter = 6
        self.Hole.Depth = 10
        self.Hole.ThreadType = 0
        self.Hole.HoleCutType = 2
        self.Hole.HoleCutDiameter = 9
        self.Hole.HoleCutCountersinkAngle = 90
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 0
        self.Hole.Tapered = 0
        self.Doc.recompute()
        self.assertAlmostEqual(self.Hole.Shape.Volume, 10**3 - pi * 3**2 * 10 - 24.7400421)

    def testCustomCutValuesSurviveReopen(self):
        """Custom counterbore values of a normed hole cut stay after a save and reopen (ops#389)"""
        # An M6 hole with an ISO 4762 counterbore, whose normed cut is wider than 10, overridden
        # with a cut 9 wide and 2 deep. The restore reset them to the normed values.
        self.Hole.ThreadType = "ISOMetricProfile"
        self.Hole.ThreadSize = "M6x1.0"
        self.Hole.HoleCutType = "ISO 4762"
        self.Hole.Depth = 10
        self.Hole.DepthType = "Dimension"
        self.Hole.DrillPoint = "Flat"
        self.Hole.Tapered = False
        self.Doc.recompute()
        self.assertGreater(self.Hole.HoleCutDiameter.Value, 10)
        self.Hole.HoleCutCustomValues = True
        self.Hole.HoleCutDiameter = 9
        self.Hole.HoleCutDepth = 2
        self.Doc.recompute()
        self.assertAlmostEqual(self.Hole.HoleCutDiameter.Value, 9)
        self.assertAlmostEqual(self.Hole.HoleCutDepth.Value, 2)
        volume = self.Hole.Shape.Volume

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "PartDesignTestHole.FCStd")
        self.Doc.saveAs(path)
        FreeCAD.closeDocument(self.Doc.Name)
        self.Doc = FreeCAD.openDocument(path)
        hole = self.Doc.getObject("Hole")

        self.assertTrue(hole.HoleCutCustomValues)
        self.assertAlmostEqual(hole.HoleCutDiameter.Value, 9)
        self.assertAlmostEqual(hole.HoleCutDepth.Value, 2)
        hole.touch()
        self.Doc.recompute()
        self.assertAlmostEqual(hole.Shape.Volume, volume)

    def testNormedCutValuesStayReadOnlyAfterReopen(self):
        """Normed hole cut values stay read-only after a save and reopen (ops#389): the restore
        made them editable, and a later edit of another property put the normed value back over
        an edit of them."""
        self.Hole.ThreadType = "ISOMetricProfile"
        self.Hole.ThreadSize = "M6x1.0"
        self.Hole.Depth = 10
        self.Hole.DepthType = "Dimension"
        self.Hole.DrillPoint = "Flat"
        self.Hole.Tapered = False
        folder = tempfile.mkdtemp()
        for cut, names in (
            ("ISO 4762", ("HoleCutDiameter", "HoleCutDepth")),
            ("ISO 10642", ("HoleCutDiameter", "HoleCutDepth", "HoleCutCountersinkAngle")),
        ):
            hole = self.Doc.getObject("Hole")
            hole.HoleCutType = cut
            self.Doc.recompute()
            self.assertFalse(hole.HoleCutCustomValues)
            for name in names:
                self.assertIn("ReadOnly", hole.getPropertyStatus(name), (cut, name))

            path = os.path.join(folder, "PartDesignTestHoleNormed.FCStd")
            self.Doc.saveAs(path)
            FreeCAD.closeDocument(self.Doc.Name)
            self.Doc = FreeCAD.openDocument(path)
            hole = self.Doc.getObject("Hole")
            self.assertFalse(hole.HoleCutCustomValues)
            for name in names:
                self.assertIn("ReadOnly", hole.getPropertyStatus(name), (cut, name, "reopened"))

    def testForcedCustomCutValuesStay(self):
        """Cut values the user entered for a size the norm has none for stay through unrelated
        edits and a save and reopen (ops#389). Each change of the hole diameter (a Depth or
        ThreadFit edit, the restore) recalculated them, and the next recompute cut those
        without a message. A new size still proposes new values."""
        self.Hole.ThreadType = "ISOMetricProfile"
        self.Hole.Depth = 10
        self.Hole.DepthType = "Dimension"
        self.Hole.DrillPoint = "Flat"
        self.Hole.Tapered = False
        folder = tempfile.mkdtemp()

        def removed(hole):
            # 10 deep through the 10 box; counterbore: a cylinder; countersink (90 degrees):
            # a cone from the cut diameter down to the hole's
            r = hole.Diameter.Value / 2
            cut = hole.HoleCutDiameter.Value / 2
            if hole.HoleCutType == "ISO 4762":
                return pi * r**2 * 10 + pi * (cut**2 - r**2) * hole.HoleCutDepth.Value
            h = cut - r
            return pi * r**2 * 10 + pi * h / 3 * (cut**2 + cut * r + r**2) - pi * r**2 * h

        for cut, depth in (("ISO 4762", 2), ("ISO 10642", None)):
            hole = self.Doc.getObject("Hole")
            hole.ThreadSize = "M4.5x0.75"
            hole.HoleCutType = cut
            self.Doc.recompute()
            # no normed values for M4.5: custom values, forced on, editable
            self.assertTrue(hole.HoleCutCustomValues, cut)
            self.assertIn("ReadOnly", hole.getPropertyStatus("HoleCutCustomValues"), cut)
            self.assertNotIn("ReadOnly", hole.getPropertyStatus("HoleCutDiameter"), cut)
            hole.HoleCutDiameter = 9
            if depth:
                hole.HoleCutDepth = depth
            self.Doc.recompute()
            values = (hole.HoleCutDiameter.Value, hole.HoleCutDepth.Value)
            self.assertAlmostEqual(values[0], 9, msg=cut)
            self.assertAlmostEqual(hole.Shape.Volume, 10**3 - removed(hole), msg=cut)

            hole.Depth = 9
            hole.Depth = 10
            hole.ThreadFit = hole.getEnumerationsOfProperty("ThreadFit")[-1]
            self.Doc.recompute()
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, values[0], msg=(cut, "edits"))
            self.assertAlmostEqual(hole.HoleCutDepth.Value, values[1], msg=(cut, "edits"))
            self.assertAlmostEqual(hole.Shape.Volume, 10**3 - removed(hole), msg=(cut, "edits"))
            volume = hole.Shape.Volume

            # round 3: the same values written again (as the task panel's OK does), a ThreadSize
            # bound to an expression (set on every recompute), and an undo and redo of a size
            # change propose nothing: each replaced the values
            hole.ThreadType = hole.ThreadType
            hole.ThreadSize = hole.ThreadSize
            hole.HoleCutType = hole.HoleCutType
            self.Doc.recompute()
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, values[0], msg=(cut, "same values"))
            self.assertAlmostEqual(hole.HoleCutDepth.Value, values[1], msg=(cut, "same values"))
            # (a string, which the expression engine writes on every evaluation: it compares
            # it with the size's index)
            hole.setExpression("ThreadSize", "<<M4.5x0.75>>")
            self.Doc.recompute()
            hole.touch()
            self.Doc.recompute()
            hole.setExpression("ThreadSize", None)
            self.assertEqual(hole.ThreadSize, "M4.5x0.75")
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, values[0], msg=(cut, "expression"))
            self.assertAlmostEqual(hole.HoleCutDepth.Value, values[1], msg=(cut, "expression"))
            self.Doc.UndoMode = 1
            self.Doc.openTransaction("size")
            hole.ThreadSize = "M2.2x0.45" if depth else "M3.5x0.6"
            self.Doc.commitTransaction()
            self.Doc.recompute()
            changed = (hole.HoleCutDiameter.Value, hole.HoleCutDepth.Value)
            self.assertNotAlmostEqual(changed[0], values[0], msg=(cut, "size"))
            self.Doc.undo()
            self.Doc.recompute()
            self.assertEqual(hole.ThreadSize, "M4.5x0.75")
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, values[0], msg=(cut, "undo"))
            self.assertAlmostEqual(hole.HoleCutDepth.Value, values[1], msg=(cut, "undo"))
            self.Doc.redo()
            self.Doc.recompute()
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, changed[0], msg=(cut, "redo"))
            self.assertAlmostEqual(hole.HoleCutDepth.Value, changed[1], msg=(cut, "redo"))
            self.Doc.undo()
            self.Doc.recompute()
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, values[0], msg=(cut, "undo 2"))
            self.assertAlmostEqual(hole.Shape.Volume, volume, msg=(cut, "undo 2"))

            path = os.path.join(folder, "PartDesignTestHoleForced.FCStd")
            self.Doc.saveAs(path)
            FreeCAD.closeDocument(self.Doc.Name)
            self.Doc = FreeCAD.openDocument(path)
            hole = self.Doc.getObject("Hole")
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, values[0], msg=(cut, "reopened"))
            self.assertAlmostEqual(hole.HoleCutDepth.Value, values[1], msg=(cut, "reopened"))
            editable = ("HoleCutDiameter",) + (("HoleCutDepth",) if depth else ("HoleCutCountersinkAngle",))
            for name in editable:
                self.assertNotIn("ReadOnly", hole.getPropertyStatus(name), (cut, name, "reopened"))
            hole.Depth = 9
            hole.Depth = 10
            hole.touch()
            self.Doc.recompute()
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, values[0], msg=(cut, "reopened"))
            self.assertAlmostEqual(hole.Shape.Volume, volume, msg=(cut, "reopened"))

            # another size the norm has no values for: values proposed for it
            hole.ThreadSize = "M2.2x0.45" if depth else "M3.5x0.6"
            self.Doc.recompute()
            self.assertTrue(hole.HoleCutCustomValues, cut)
            proposed = 1.5 * hole.Diameter.Value + 1 if depth else 2.24 * hole.Diameter.Value
            self.assertAlmostEqual(hole.HoleCutDiameter.Value, proposed, msg=(cut, "new size"))

    def testFirstThreadSizeSurvivesReopen(self):
        """A hole of the first size of a thread type (M1) keeps it after a save and reopen
        (ops#389): its ThreadDiameter was never set, and the restore picked the size closest to
        the stale value (M1.2, a wider hole) without a message."""
        self.Hole.ThreadType = "ISOMetricProfile"
        self.Hole.ThreadSize = "M6x1.0"
        self.Hole.ThreadSize = "M1.2x0.25"
        self.Hole.ThreadSize = "M1x0.25"
        self.Hole.Depth = 10
        self.Hole.DepthType = "Dimension"
        self.Hole.DrillPoint = "Flat"
        self.Hole.Tapered = False
        self.Doc.recompute()
        diameter = self.Hole.Diameter.Value
        self.assertAlmostEqual(self.Hole.Shape.Volume, 10**3 - pi * (diameter / 2) ** 2 * 10)

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "PartDesignTestHoleM1.FCStd")
        self.Doc.saveAs(path)
        FreeCAD.closeDocument(self.Doc.Name)
        self.Doc = FreeCAD.openDocument(path)
        hole = self.Doc.getObject("Hole")
        self.assertEqual(hole.ThreadSize, "M1x0.25")
        self.assertAlmostEqual(hole.Diameter.Value, diameter)
        hole.touch()
        self.Doc.recompute()
        self.assertAlmostEqual(hole.Shape.Volume, 10**3 - pi * (diameter / 2) ** 2 * 10)

        # a thread type change picks the new type's size closest to the old one (round 3: the
        # first size's change, when the new type's sizes were set, overwrote the diameter the
        # closest size is looked up from: M12 became M1 or #1)
        hole.ThreadType = "ISOMetricFineProfile"
        self.assertAlmostEqual(hole.ThreadDiameter.Value, 1.0)
        # (the nearest by diameter and the old size's pitch: 1/2" is 12.7 with 1.954, 1 1/8"
        # 28.575; 7/16" is nearer in diameter alone, ops#405 N1)
        for start, other, nearest in (
            ("M12x1.75", "ISOMetricFineProfile", 12.0),
            ("M12x1.75", "UNC", 12.7),
            ("M30x3.5", "UNC", 28.575),
        ):
            hole.ThreadType = "ISOMetricProfile"
            hole.ThreadSize = start
            self.assertAlmostEqual(hole.ThreadDiameter.Value, float(start[1:3]))
            hole.ThreadType = other
            self.assertAlmostEqual(hole.ThreadDiameter.Value, nearest, msg=(start, other))
        # a size of the same name in the new type is kept, as before (3/4 UNC to 3/4 NPT)
        hole.ThreadSize = "3/4"
        hole.ThreadType = "NPT"
        self.assertEqual(hole.ThreadSize, "3/4")

    def testThreadTypeChangePicksTheSizeNearestByTheOldPitch(self):
        """ops#405 N1: a thread type change picks the new type's size nearest the old one by
        diameter and by the old size's pitch. The pitch was the new type's first size's
        (M12x1.75 to UNC gave 7/16, 11.113 with 1.814, not 1/2, 12.700 with 1.954; to NPT
        1/8, not 1/4; to ISO fine M12x1.0, not M12x1.5), silently from Python.
        Model: M12x1.75, diameter 12 and pitch 1.75: UNC 7/16 is 0.889 away (0.887 in diameter,
        0.064 in pitch), 1/2 0.729 (0.700, 0.204); NPT 1/8 1.894, 1/4 1.749; M12x1.0 0.75 away
        in pitch, M12x1.5 0.25."""
        for other, expected in (
            ("UNC", "1/2"),
            ("NPT", "1/4"),
            ("ISOMetricFineProfile", "M12x1.5"),
        ):
            self.Hole.ThreadType = "ISOMetricProfile"
            self.Hole.ThreadSize = "M12x1.75"
            self.Hole.ThreadType = other
            self.assertEqual(self.Hole.ThreadSize, expected, other)

    def testThreadTypeChangeFromNoneIsByDiameter(self):
        """ops#405 N1, PR 360 round 2: from "None" the old size has no pitch, and the closest
        size is the nearest by diameter alone. The pitch was the new type's first size's, which
        setEnums() had fallen back to (UNC #1: 0.397): Diameter 12 gave 7/16 (11.113, 1.814;
        1.67 away with that pitch), not 1/2 (12.700, 1.954; 1.71 away), though 1/2 is nearer in
        diameter (0.7 against 0.887)."""
        self.assertEqual(self.Hole.ThreadType, "None")
        for other, expected in (("UNC", "1/2"), ("ISOMetricProfile", "M12x1.75")):
            self.Hole.ThreadType = "None"
            self.Hole.Diameter = 12
            self.Hole.ThreadType = other
            self.assertEqual(self.Hole.ThreadSize, expected, other)

    def consoleOutput(self, action):
        """What `action()` prints through the console's std observer (stderr, fd 2), warnings and
        errors on, as text (TestNamingSolver.consoleOutput)."""
        if "Console" not in App.Console.GetObservers():
            self.skipTest("no console observer to catch the warnings (the GUI)")
        kinds = ("Wrn", "Err")
        statuses = {kind: App.Console.GetStatus("Console", kind) for kind in kinds}
        for kind in kinds:
            App.Console.SetStatus("Console", kind, True)
        saved = os.dup(2)
        with tempfile.TemporaryFile() as caught:
            os.dup2(caught.fileno(), 2)
            try:
                action()
            finally:
                os.dup2(saved, 2)
                os.close(saved)
                for kind, status in statuses.items():
                    App.Console.SetStatus("Console", kind, bool(status))
            caught.seek(0)
            return caught.read().decode("utf-8", "replace")

    def testThreadSizeExpressionOfAnotherTypeWarnsAndStays(self):
        """ops#405 N2 (decision 116): ThreadType and ThreadSize bound to cells, the type cell
        changed to a type with no size of the size cell's name. The enumeration took its first
        size (UNC #1) without a word. The recompute now warns, naming the expression's value
        and the type, and the expression stays; a size of the new type warns nothing."""
        sheet = self.Doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "'ISOMetricProfile")
        sheet.set("B1", "'M12x1.75")
        self.Doc.recompute()
        self.Hole.setExpression("ThreadType", "Sheet.A1")
        self.Doc.recompute()
        self.Hole.setExpression("ThreadSize", "Sheet.B1")
        self.Doc.recompute()
        self.assertEqual(self.Hole.ThreadType, "ISOMetricProfile")
        self.assertEqual(self.Hole.ThreadSize, "M12x1.75")
        self.assertNotIn("ThreadSize", self.consoleOutput(self.Doc.recompute))

        sheet.set("A1", "'UNC")
        printed = self.consoleOutput(self.Doc.recompute)
        self.assertIn("the expression of ThreadSize gives 'M12x1.75'", printed)
        self.assertIn("no size of the thread type 'UNC'", printed)
        self.assertEqual(self.Hole.ThreadType, "UNC")
        self.assertEqual(dict(self.Hole.ExpressionEngine).get("ThreadSize"), "Sheet.B1")

        sheet.set("B1", "'1/2")
        printed = self.consoleOutput(self.Doc.recompute)
        self.assertNotIn("ThreadSize", printed)
        self.assertEqual(self.Hole.ThreadSize, "1/2")
        self.assertEqual(dict(self.Hole.ExpressionEngine).get("ThreadSize"), "Sheet.B1")

    def testIsoFineSizesNextToTheRepeatedRowsSurviveReopen(self):
        """ops#404: the ISO metric fine table's M26x1.5 row held M27x1.0's diameter and pitch,
        and M38x1.5's those of M39x1.5. A hole of M27x1.0 reopened as M26x1.5 (the restore picks
        the first row nearest the saved diameter and pitch), M39x1.5 as M38x1.5, and M26x1.5 and
        M38x1.5 holes were 27 and 39 mm. Each of the four reopens as itself with its own
        diameter."""
        self.Hole.ThreadType = "ISOMetricFineProfile"
        for size, diameter in (
            ("M26x1.5", 26.0),
            ("M27x1.0", 27.0),
            ("M38x1.5", 38.0),
            ("M39x1.5", 39.0),
        ):
            self.Hole.ThreadSize = size
            self.Doc.recompute()
            self.assertAlmostEqual(self.Hole.ThreadDiameter.Value, diameter, msg=size)

            folder = tempfile.mkdtemp()
            path = os.path.join(folder, "PartDesignTestHoleFine.FCStd")
            self.Doc.saveAs(path)
            FreeCAD.closeDocument(self.Doc.Name)
            self.Doc = FreeCAD.openDocument(path)
            self.Hole = self.Doc.getObject("Hole")
            self.assertEqual(self.Hole.ThreadSize, size)
            self.assertAlmostEqual(self.Hole.ThreadDiameter.Value, diameter, msg=size)

    def bindTypeAndSize(self, typeCell, sizeCell, order):
        """A spreadsheet with the type in A1 and the size in B1, bound to the hole's ThreadType
        and ThreadSize in the order given, then one recompute (ops#457)."""
        sheet = self.Doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "'" + typeCell)
        sheet.set("B1", "'" + sizeCell)
        self.Doc.recompute()
        cells = {"ThreadType": "Sheet.A1", "ThreadSize": "Sheet.B1"}
        for prop in order:
            self.Hole.setExpression(prop, cells[prop])
        self.Doc.recompute()
        return sheet

    def assertHoleIsOfSize(self, threadType, threadSize, msg):
        """The hole has the type and size, and the diameters a hole set directly to them has
        (the expressions are taken off for the comparison and put back)."""
        self.assertEqual(
            (self.Hole.ThreadType, self.Hole.ThreadSize), (threadType, threadSize), msg
        )
        bound = (self.Hole.ThreadDiameter.Value, self.Hole.Diameter.Value)
        expressions = dict(self.Hole.ExpressionEngine)
        for prop in expressions:
            self.Hole.setExpression(prop, None)
        self.Hole.ThreadType = "None"
        self.Hole.ThreadType = threadType
        self.Hole.ThreadSize = threadSize
        self.Doc.recompute()
        self.assertEqual((self.Hole.ThreadType, self.Hole.ThreadSize), (threadType, threadSize))
        self.assertGreater(self.Hole.ThreadDiameter.Value, 0.0, msg)
        self.assertAlmostEqual(bound[0], self.Hole.ThreadDiameter.Value, msg=msg)
        self.assertAlmostEqual(bound[1], self.Hole.Diameter.Value, msg=msg)
        for prop, expression in expressions.items():
            self.Hole.setExpression(prop, expression)
        self.Doc.recompute()
        self.assertEqual(
            (self.Hole.ThreadType, self.Hole.ThreadSize), (threadType, threadSize), msg
        )

    def testThreadTypeAndSizeBoundTogetherChangeInOneRecompute(self):
        """ops#457: ThreadType and ThreadSize bound to cells, both cells changed before one
        recompute. ThreadSize's expression is applied first, its name is no size of the old type,
        so the enumeration took its first size (M1x0.25), and the type change then picked the
        size closest to that: M12x1.75 gave M1x0.25, UNC 1/4 gave UNC #1, M6x1.0 gave M1.8x0.35,
        silently. The size is the bound cell's, in both orders of binding."""
        steps = (
            ("UNC", "1/4"),
            ("ISOMetricProfile", "M6x1.0"),
            ("ISOMetricFineProfile", "M20x1.5"),
            ("ISOMetricProfile", "M12x1.75"),
        )
        for order in (("ThreadType", "ThreadSize"), ("ThreadSize", "ThreadType")):
            self.tearDown()
            self.setUp()
            sheet = self.bindTypeAndSize("ISOMetricProfile", "M12x1.75", order)
            self.assertHoleIsOfSize("ISOMetricProfile", "M12x1.75", (order, "bound"))
            for typeCell, sizeCell in steps:
                sheet.set("A1", "'" + typeCell)
                sheet.set("B1", "'" + sizeCell)
                self.Doc.recompute()
                self.assertHoleIsOfSize(typeCell, sizeCell, (order, typeCell, sizeCell))

    def testThreadTypeAndSizeBoundBeforeTheFirstRecompute(self):
        """ops#457: both bound at once (the hole is of type None, sized for no thread), one
        recompute: the cells' size, not the first of the type."""
        for typeCell, sizeCell in (
            ("ISOMetricProfile", "M12x1.75"),
            ("UNC", "1/4"),
            ("ISOMetricProfile", "M6x1.0"),
        ):
            for order in (("ThreadType", "ThreadSize"), ("ThreadSize", "ThreadType")):
                self.tearDown()
                self.setUp()
                self.bindTypeAndSize(typeCell, sizeCell, order)
                self.assertHoleIsOfSize(typeCell, sizeCell, (order, typeCell, sizeCell))

    def testThreadSizeExpressionWithAFractionIsTruncatedAndSaid(self):
        """ops#457 (PR 360 round 2, F2): ThreadSize bound to 2.5 takes the size at place 2 (the
        enumeration truncates), and the warning says so, not that the size is the enumeration's
        fallback."""
        sheet = self.Doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "'ISOMetricProfile")
        sheet.set("B1", "2.5")
        self.Doc.recompute()
        self.Hole.setExpression("ThreadType", "Sheet.A1")
        self.Doc.recompute()
        self.Hole.setExpression("ThreadSize", "Sheet.B1")
        printed = self.consoleOutput(self.Doc.recompute)
        sizes = self.Hole.getEnumerationsOfProperty("ThreadSize")
        self.assertEqual(self.Hole.ThreadSize, sizes[2])
        self.assertIn("the expression of ThreadSize gives '2.5", printed)
        self.assertIn("no whole place in the sizes of the thread type 'ISOMetricProfile'", printed)
        self.assertIn("the size is the one at place 2", printed)
        self.assertNotIn("fallback", printed)

        sheet.set("B1", "3")
        printed = self.consoleOutput(self.Doc.recompute)
        self.assertEqual(self.Hole.ThreadSize, sizes[3])
        self.assertNotIn("ThreadSize", printed)

    def testNoRefineHole(self):
        # Add a second box to get a shape with more faces
        self.Box2 = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Box2.Length = 10
        self.Box2.Width = 10
        self.Box2.Height = 10
        self.Box2.AttacherEngine = "Engine 3D"
        self.Box2.AttachmentOffset = App.Placement(
            App.Vector(1.0000000000, 0.0000000000, 0.0000000000),
            App.Rotation(0.0000000000, 0.0000000000, 0.0000000000),
        )
        self.Box2.MapReversed = False
        self.Box2.AttachmentSupport = self.Doc.getObject("XY_Plane")
        self.Box2.MapPathParameter = 0.000000
        self.Box2.MapMode = "FlatFace"

        # Set the Refine option to False, otherwise adding the second box would be useless
        self.Box2.Refine = False
        self.Body.addObject(self.Box2)
        self.Doc.recompute()

        # Move the Hole on top of the Body
        self.Body.removeObject(self.Hole)
        self.Body.insertObject(self.Hole, self.Box2, True)
        self.Body.Tip = self.Hole
        self.Hole.Diameter = 6
        self.Hole.Depth = 10
        self.Hole.ThreadType = 0
        self.Hole.HoleCutType = 0
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 0
        self.Hole.Tapered = 0
        self.Hole.Visibility = True

        # Test the number of faces with the Refine option set to False
        self.Hole.Refine = False
        self.Doc.recompute()
        self.assertEqual(len(self.Hole.Shape.Faces), 15)

    def testRefineHole(self):
        # Add a second box to get a shape with more faces
        self.Box2 = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Box2.Length = 10
        self.Box2.Width = 10
        self.Box2.Height = 10
        self.Box2.AttacherEngine = "Engine 3D"
        self.Box2.AttachmentOffset = App.Placement(
            App.Vector(1.0000000000, 0.0000000000, 0.0000000000),
            App.Rotation(0.0000000000, 0.0000000000, 0.0000000000),
        )
        self.Box2.MapReversed = False
        self.Box2.AttachmentSupport = self.Doc.getObject("XY_Plane")
        self.Box2.MapPathParameter = 0.000000
        self.Box2.MapMode = "FlatFace"

        # Set the Refine option to False, otherwise adding the second box would be useless
        self.Box2.Refine = False
        self.Body.addObject(self.Box2)
        self.Doc.recompute()

        # Move the Hole on top of the Body
        self.Body.removeObject(self.Hole)
        self.Body.insertObject(self.Hole, self.Box2, True)
        self.Body.Tip = self.Hole
        self.Hole.Diameter = 6
        self.Hole.Depth = 10
        self.Hole.ThreadType = 0
        self.Hole.HoleCutType = 0
        self.Hole.DepthType = 0
        self.Hole.DrillPoint = 0
        self.Hole.Tapered = 0
        self.Hole.Visibility = True

        # Test the number of faces with the Refine option set to True
        self.Hole.Refine = True
        self.Doc.recompute()
        self.assertEqual(len(self.Hole.Shape.Faces), 7)

    def testThreadEnums(self):
        """Test thread enums for correct order"""
        # Due to the savefile use of indexes and not strings
        # The correct mapping needs to be ensured to not break savefiles
        # The order of the arrays and elements is critical
        thread_types = {
            "ISOMetricProfile": [
                "M1x0.25",
                "M1.1x0.25",
                "M1.2x0.25",
                "M1.4x0.3",
                "M1.6x0.35",
                "M1.8x0.35",
                "M2x0.4",
                "M2.2x0.45",
                "M2.5x0.45",
                "M3x0.5",
                "M3.5x0.6",
                "M4x0.7",
                "M4.5x0.75",
                "M5x0.8",
                "M6x1.0",
                "M7x1.0",
                "M8x1.25",
                "M9x1.25",
                "M10x1.5",
                "M11x1.5",
                "M12x1.75",
                "M14x2.0",
                "M16x2.0",
                "M18x2.5",
                "M20x2.5",
                "M22x2.5",
                "M24x3.0",
                "M27x3.0",
                "M30x3.5",
                "M33x3.5",
                "M36x4.0",
                "M39x4.0",
                "M42x4.5",
                "M45x4.5",
                "M48x5.0",
                "M52x5.0",
                "M56x5.5",
                "M60x5.5",
                "M64x6.0",
                "M68x6.0",
            ],
            "ISOMetricFineProfile": [
                "M1x0.2",
                "M1.1x0.2",
                "M1.2x0.2",
                "M1.4x0.2",
                "M1.6x0.2",
                "M1.8x0.2",
                "M2x0.25",
                "M2.2x0.25",
                "M2.5x0.35",
                "M3x0.35",
                "M3.5x0.35",
                "M4x0.5",
                "M4.5x0.5",
                "M5x0.5",
                "M5.5x0.5",
                "M6x0.75",
                "M7x0.75",
                "M8x0.75",
                "M8x1.0",
                "M9x0.75",
                "M9x1.0",
                "M10x0.75",
                "M10x1.0",
                "M10x1.25",
                "M11x0.75",
                "M11x1.0",
                "M12x1.0",
                "M12x1.25",
                "M12x1.5",
                "M14x1.0",
                "M14x1.25",
                "M14x1.5",
                "M15x1.0",
                "M15x1.5",
                "M16x1.0",
                "M16x1.5",
                "M17x1.0",
                "M17x1.5",
                "M18x1.0",
                "M18x1.5",
                "M18x2.0",
                "M20x1.0",
                "M20x1.5",
                "M20x2.0",
                "M22x1.0",
                "M22x1.5",
                "M22x2.0",
                "M24x1.0",
                "M24x1.5",
                "M24x2.0",
                "M25x1.0",
                "M25x1.5",
                "M25x2.0",
                "M26x1.5",
                "M27x1.0",
                "M27x1.5",
                "M27x2.0",
                "M28x1.0",
                "M28x1.5",
                "M28x2.0",
                "M30x1.0",
                "M30x1.5",
                "M30x2.0",
                "M30x3.0",
                "M32x1.5",
                "M32x2.0",
                "M33x1.5",
                "M33x2.0",
                "M33x3.0",
                "M35x1.5",
                "M36x1.5",
                "M36x2.0",
                "M36x3.0",
                "M38x1.5",
                "M39x1.5",
                "M39x2.0",
                "M39x3.0",
                "M40x1.5",
                "M40x2.0",
                "M40x3.0",
                "M42x1.5",
                "M42x2.0",
                "M42x3.0",
                "M42x4.0",
                "M45x1.5",
                "M45x2.0",
                "M45x3.0",
                "M45x4.0",
                "M48x1.5",
                "M48x2.0",
                "M48x3.0",
                "M48x4.0",
                "M50x1.5",
                "M50x2.0",
                "M50x3.0",
                "M52x1.5",
                "M52x2.0",
                "M52x3.0",
                "M52x4.0",
                "M55x1.5",
                "M55x2.0",
                "M55x3.0",
                "M55x4.0",
                "M56x1.5",
                "M56x2.0",
                "M56x3.0",
                "M56x4.0",
                "M58x1.5",
                "M58x2.0",
                "M58x3.0",
                "M58x4.0",
                "M60x1.5",
                "M60x2.0",
                "M60x3.0",
                "M60x4.0",
                "M62x1.5",
                "M62x2.0",
                "M62x3.0",
                "M62x4.0",
                "M64x1.5",
                "M64x2.0",
                "M64x3.0",
                "M64x4.0",
                "M65x1.5",
                "M65x2.0",
                "M65x3.0",
                "M65x4.0",
                "M68x1.5",
                "M68x2.0",
                "M68x3.0",
                "M68x4.0",
                "M70x1.5",
                "M70x2.0",
                "M70x3.0",
                "M70x4.0",
                "M70x6.0",
                "M72x1.5",
                "M72x2.0",
                "M72x3.0",
                "M72x4.0",
                "M72x6.0",
                "M75x1.5",
                "M75x2.0",
                "M75x3.0",
                "M75x4.0",
                "M75x6.0",
                "M76x1.5",
                "M76x2.0",
                "M76x3.0",
                "M76x4.0",
                "M76x6.0",
                "M80x1.5",
                "M80x2.0",
                "M80x3.0",
                "M80x4.0",
                "M80x6.0",
                "M85x2.0",
                "M85x3.0",
                "M85x4.0",
                "M85x6.0",
                "M90x2.0",
                "M90x3.0",
                "M90x4.0",
                "M90x6.0",
                "M95x2.0",
                "M95x3.0",
                "M95x4.0",
                "M95x6.0",
                "M100x2.0",
                "M100x3.0",
                "M100x4.0",
                "M100x6.0",
            ],
            "UNC": [
                "#1",
                "#2",
                "#3",
                "#4",
                "#5",
                "#6",
                "#8",
                "#10",
                "#12",
                "1/4",
                "5/16",
                "3/8",
                "7/16",
                "1/2",
                "9/16",
                "5/8",
                "3/4",
                "7/8",
                "1",
                "1 1/8",
                "1 1/4",
                "1 3/8",
                "1 1/2",
                "1 3/4",
                "2",
                "2 1/4",
                "2 1/2",
                "2 3/4",
                "3",
                "3 1/4",
                "3 1/2",
                "3 3/4",
                "4",
            ],
            "UNF": [
                "#0",
                "#1",
                "#2",
                "#3",
                "#4",
                "#5",
                "#6",
                "#8",
                "#10",
                "#12",
                "1/4",
                "5/16",
                "3/8",
                "7/16",
                "1/2",
                "9/16",
                "5/8",
                "3/4",
                "7/8",
                "1",
                "1 1/8",
                "1 3/16",
                "1 1/4",
                "1 3/8",
                "1 1/2",
            ],
            "UNEF": [
                "#12",
                "1/4",
                "5/16",
                "3/8",
                "7/16",
                "1/2",
                "9/16",
                "5/8",
                "11/16",
                "3/4",
                "13/16",
                "7/8",
                "15/16",
                "1",
                "1 1/16",
                "1 1/8",
                "1 1/4",
                "1 5/16",
                "1 3/8",
                "1 7/16",
                "1 1/2",
                "1 9/16",
                "1 5/8",
                "1 11/16",
            ],
            "NPT": [
                "1/16",
                "1/8",
                "1/4",
                "3/8",
                "1/2",
                "3/4",
                "1",
                "1 1/4",
                "1 1/2",
                "2",
                "2 1/2",
                "3",
                "3 1/2",
                "4",
                "5",
                "6",
                "8",
                "10",
                "12",
            ],
            "BSP": [
                "1/16",
                "1/8",
                "1/4",
                "3/8",
                "1/2",
                "5/8",
                "3/4",
                "7/8",
                "1",
                "1 1/8",
                "1 1/4",
                "1 1/2",
                "1 3/4",
                "2",
                "2 1/4",
                "2 1/2",
                "2 3/4",
                "3",
                "3 1/2",
                "4",
                "4 1/2",
                "5",
                "5 1/2",
                "6",
            ],
            "BSW": [
                "1/8",
                "3/16",
                "1/4",
                "5/16",
                "3/8",
                "7/16",
                "1/2",
                "9/16",
                "5/8",
                "11/16",
                "3/4",
                "7/8",
                "1",
                "1 1/8",
                "1 1/4",
                "1 1/2",
                "1 3/4",
                "2",
                "2 1/4",
                "2 1/2",
                "2 3/4",
                "3",
                "3 1/4",
                "3 1/2",
                "3 3/4",
                "4",
                "4 1/2",
                "5",
                "5 1/2",
                "6",
            ],
            "BSF": [
                "3/16",
                "7/32",
                "1/4",
                "9/32",
                "5/16",
                "3/8",
                "7/16",
                "1/2",
                "9/16",
                "5/8",
                "11/16",
                "3/4",
                "7/8",
                "1",
                "1 1/8",
                "1 1/4",
                "1 3/8",
                "1 1/2",
                "1 5/8",
                "1 3/4",
                "2",
                "2 1/4",
                "2 1/2",
                "2 3/4",
                "3",
                "3 1/4",
                "3 1/2",
                "3 3/4",
                "4",
                "4 1/4",
            ],
            "ISOTyre": [
                "5v1",
                "5v2",
                "6v1",
                "8v1",
                "9v1",
                "10v2",
                "12v1",
                "13v1",
                "8v2",
                "10v1",
                "11v1",
                "13v2",
                "15v1",
                "16v1",
                "17v1",
                "17v2",
                "17v3",
                "19v1",
                "20v1",
            ],
        }
        allowed_types = self.Hole.getEnumerationsOfProperty("ThreadType")
        for type_index, thread_type in enumerate(thread_types.keys(), 1):
            if thread_type not in allowed_types:
                self._helperNotFoundMessage(thread_type, allowed_types)
            # Set by number like the saved files
            self.Hole.ThreadType = type_index
            self._helperNotCorrectMessage(self.Hole.ThreadType, thread_type)

            allowed_sizes = self.Hole.getEnumerationsOfProperty("ThreadSize")
            for size_index, designation in enumerate(thread_types[thread_type]):
                if designation not in allowed_sizes:
                    self._helperNotFoundMessage(designation, allowed_sizes)
                # Set by number like the saved files
                self.Hole.ThreadSize = size_index
                self._helperNotCorrectMessage(self.Hole.ThreadSize, designation)

    def testCounterboreFacesKeepNamesWhenTilted(self):
        """The faces a Hole generates from its circle keep their indexes through a tilt.

        A counterbored Hole with an angled drill point in a 40 x 20 x 10 block, its sketch
        tilted about Y from -1 to +1 degree (an attachment edit), then on the block's bottom
        face drilling up (Reversed). The four faces generated from the one circle are told apart
        only by their place k, `<k>of<n>` (ops#378, ops#468); it follows the order the Hole lists
        them in, its drilled profile's from the top: counterbore wall 1, counterbore floor 2,
        cylinder 3, cone 4 (0 is the drilled shape's top disc, named before the cut removes it),
        in every state. A key in
        the shape's coordinates renumbered them when the axis passed vertical and when the Hole
        drilled the other way (fork PR 355 round 1, finding 2)."""
        self.Box.Length = 40
        self.Box.Width = 20
        self.HoleSketch.MapReversed = False
        self.Hole.ThreadType = "None"
        self.Hole.Diameter = 6
        self.Hole.DepthType = "Dimension"
        self.Hole.Depth = 8
        self.Hole.HoleCutType = "Counterbore"
        self.Hole.HoleCutDiameter = 10
        self.Hole.HoleCutDepth = 2
        self.Hole.DrillPoint = "Angled"
        self.Hole.DrillPointAngle = 118

        def kind(face):
            surface = face.Surface
            name = type(surface).__name__
            if name == "Cone":
                return "cone"
            if name == "Cylinder":
                return "cylinder" if abs(surface.Radius - 3) < 1e-6 else "wall"
            if name == "Plane" and abs(face.Area - 16 * pi) < 0.5:
                return "floor"
            return None

        def indexes(state):
            self.Doc.recompute()
            shape = self.Hole.Shape
            self.assertTrue(shape.isValid(), state)
            result = {}
            for i, face in enumerate(shape.Faces):
                k = kind(face)
                if k is None:
                    continue
                name = shape.getElementMappedName(f"Face{i + 1}")
                name = str(name[0] if isinstance(name, tuple) else name)
                self.assertIn(";MAK;", name, f"{state}: {k} has no Hole name: {name}")
                # `<op>;MAK;<index>;F;<k>of<n>;...`
                result[k] = int(name.split(";MAK;")[1].split(";")[2].split("of")[0])
            return result

        expected = {"wall": 1, "floor": 2, "cylinder": 3, "cone": 4}
        for tilt in (-1.0, -0.1, -0.001, 0.0, 0.001, 0.1, 1.0):
            # the sketch's circle (-5, 5) lands at (15, 10, 10), the counterbore well inside
            # the block's top face
            self.HoleSketch.AttachmentOffset = App.Placement(
                App.Vector(20, 5, 10), App.Rotation(App.Vector(0, 1, 0), tilt)
            )
            self.assertEqual(indexes(f"tilt {tilt}"), expected, f"tilt {tilt}")
        # on the bottom face, drilling up: the cone's tip stays inside the block
        self.Hole.Reversed = True
        self.HoleSketch.AttachmentOffset = App.Placement(App.Vector(20, 5, 0), App.Rotation())
        self.assertEqual(indexes("Reversed"), expected, "Reversed")

    def _helperNotCorrectMessage(self, value, comparison):
        self.assertEqual(
            value,
            comparison,
            f"{comparison} is not in the correct position\n\n"
            "it will break compatibility with older saves",
        )

    def _helperNotFoundMessage(self, prop, allowed_props):
        raise AssertionError(
            "\n"
            f"{prop} is not in {allowed_props}\n\n"
            "Verify that the tested enums names are updated \n\n"
        )

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument(self.Doc.Name)
        # print ("omit closing document for debugging")
