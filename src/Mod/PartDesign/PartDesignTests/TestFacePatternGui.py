# SPDX-License-Identifier: LGPL-2.1-or-later
"""The face pattern commands in the GUI (FreeCAD-CH ops#655 T8, notes/face-pattern-design.md).

Each of PartDesign_FaceLinearPattern, _FacePolarPattern and _FaceMirrored, run with a seed's faces
picked, opens the face pattern panel on those faces (its faces field lists them), and OK leaves a
valid feature, the Body's tip, with the command's defaults (Onshape's): linear along the Body's X
axis, spacing 20, count 2; circular about Z, 360 degrees, count 4; mirror about the YZ plane.

Designed models (mm, volumes in mm^3), built by each test:
- Plate x -30..30, y 0..20, z 0..10 (12000), boss x 2..8, y 7..13, z 10..15 (180), its five faces
  picked. Linear: a copy at x 22..28; mirror: a copy at x -8..-2. Either way 12360, one solid,
  boss tops (6 x 6 at z 15) centred at x 5 and 25, or -5 and 5.
- Disc radius 40, z 0..10, with a through hole radius 3 at (20, 0), its cylinder picked.
  Circular: 4 holes 90 degrees apart, pi 40^2 10 - 4 pi 3^2 10.

The geometry and the expected results are module functions, so a FreeCADCmd run can check them
without the GUI. Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md).
"""

import math

import FreeCAD as App

from PartDesignTests.Scenarios import models

TOL = 1e-6
PLATE = 60 * 20 * 10
BOSS = 6 * 6 * 5
DISC = math.pi * 40**2 * 10
THROUGH_HOLE = math.pi * 3**2 * 10

# The command's defaults (Command.cpp, makeFacePattern), as its feature carries them after OK
DEFAULTS = {
    "FaceLinearPattern": {"Mode": "Spacing", "Offset": 20, "Occurrences": 2},
    "FacePolarPattern": {"Mode": "Extent", "Angle": 360, "Occurrences": 4},
    "FaceMirrored": {},
}


def inBox(point, x0, x1, y0, y1, z0, z1):
    return (
        x0 - TOL <= point.x <= x1 + TOL
        and y0 - TOL <= point.y <= y1 + TOL
        and z0 - TOL <= point.z <= z1 + TOL
    )


def faceNames(feature, test):
    """The names of the feature's faces whose centre passes `test`."""
    return [
        "Face%d" % (i + 1)
        for i, face in enumerate(feature.Shape.Faces)
        if test(face.CenterOfMass, face)
    ]


def plateWithBoss(doc):
    """The plate and its boss; returns (body, boss, the boss's five faces)."""
    body = models.body(doc)
    plate = models.sketch(doc, "PlateSketch", models.rectangle(-30, 0, 30, 20), body)
    models.pad(body, plate, 10, name="Plate")
    sketch = models.sketch(doc, "BossSketch", models.rectangle(2, 7, 8, 13), body, z=10)
    boss = models.pad(body, sketch, 5, name="Boss")
    doc.recompute()
    picks = faceNames(boss, lambda c, f: inBox(c, 2, 8, 7, 13, 10 + 1e-3, 15))
    return body, boss, picks


def discWithHole(doc):
    """The disc and its through hole; returns (body, hole, the hole's cylinder)."""
    body = models.body(doc)
    disc = models.sketch(doc, "DiscSketch", [models.circle(0, 0, 40)], body)
    models.pad(body, disc, 10, name="Disc")
    sketch = models.sketch(doc, "HoleSketch", [models.circle(20, 0, 3)], body, z=10)
    hole = models.pocketThroughAll(body, sketch, name="Hole")
    doc.recompute()
    picks = faceNames(
        hole, lambda c, f: f.Surface.__class__.__name__ == "Cylinder" and f.Surface.Radius < 4
    )
    return body, hole, picks


def bossTops(shape):
    """The x of the centres of the shape's 6 x 6 planar faces at z 15."""
    return sorted(
        round(face.CenterOfMass.x, 6)
        for face in shape.Faces
        if face.Surface.__class__.__name__ == "Plane"
        and abs(face.CenterOfMass.z - 15) < TOL
        and abs(face.Area - 36) < TOL
    )


def holeAngles(shape):
    """The angles (degrees, 0..360) of the centres of the shape's radius 3 cylinders."""
    angles = []
    for face in shape.Faces:
        if face.Surface.__class__.__name__ == "Cylinder" and abs(face.Surface.Radius - 3) < TOL:
            centre = face.Surface.Center
            angles.append(round(math.degrees(math.atan2(centre.y, centre.x)), 6) % 360)
    return sorted(angles)


def plain(value):
    """A property's value without its unit (a Quantity's Value)."""
    return value.Value if hasattr(value, "Value") else value


# What each command makes from its model: (model, expected volume, check of the result's shape)
CASES = {
    "FaceLinearPattern": (plateWithBoss, PLATE + 2 * BOSS, lambda s: bossTops(s) == [5, 25]),
    "FaceMirrored": (plateWithBoss, PLATE + 2 * BOSS, lambda s: bossTops(s) == [-5, 5]),
    "FacePolarPattern": (
        discWithHole,
        DISC - 4 * THROUGH_HOLE,
        lambda s: holeAngles(s) == [0, 90, 180, 270],
    ),
}


def checkResult(case, feature):
    """None if the feature is what the command should make, else what is wrong."""
    _, volume, shapeOk = CASES[case]
    if not feature.isValid():
        return "invalid: " + feature.getStatusString()
    shape = feature.Shape
    if len(shape.Solids) != 1 or not shape.isValid():
        return "not one valid solid"
    if abs(shape.Volume - volume) > 1e-3:
        return "volume %.6f, expected %.6f" % (shape.Volume, volume)
    if not shapeOk(shape):
        return "the copies are not where expected"
    return None


try:
    import FreeCADGui as Gui
    from PySide import QtWidgets
except ImportError:  # FreeCADCmd: the module functions only
    Gui = None

if Gui is not None and App.GuiUp:
    from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
    from PartDesignTests.TestExpressionFieldsGui import pump
    from PartDesignTests.TestReferenceFieldGui import entries, fields

    class TestFacePatternGui(ResultBoxGuiCase):
        """Each face pattern command opens its panel on the picked faces, and OK makes a valid
        feature."""

        def runOnPicks(self, case):
            """The case's model, its seed's faces picked in the 3D view, the command run; returns
            the feature it made and the picks, with the panel open."""
            build = CASES[case][0]
            body, seed, picks = build(self.doc)
            self.assertTrue(picks, "no face picked")
            self.body = body
            Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", body)
            Gui.Selection.clearSelection()
            for sub in picks:
                Gui.Selection.addSelection(self.doc.Name, body.Name, seed.Name + "." + sub)
            before = {o.Name for o in self.doc.Objects}
            Gui.runCommand("PartDesign_" + case)
            self.waitForPanel()
            made = [
                o
                for o in self.doc.Objects
                if o.Name not in before and o.TypeId == "PartDesign::" + case
            ]
            self.assertEqual(len(made), 1, [o.Name for o in made])
            return made[0], seed, picks

        def assertPanelOnPicks(self, pattern, seed, picks):
            """The face pattern panel is the open one, on the feature, its faces field listing
            the picks."""
            panel = Gui.getMainWindow().findChild(
                QtWidgets.QWidget, "PartDesignGui::TaskFacePatternParameters"
            )
            self.assertIsNotNone(panel, "the face pattern panel is not open")
            self.assertTrue(panel.isVisible())
            obj, subs = pattern.Base
            self.assertEqual(obj, seed)
            self.assertEqual(sorted(s for s in subs if s), sorted(picks))
            visible = fields()
            self.assertTrue(visible, "no faces field")
            self.assertEqual(entries(visible[0]).count(), len(picks))

        def assertOkMakesTheFeature(self, case, pattern):
            self.close(ok=True)
            self.doc.recompute()
            pump(0.2)
            self.assertIsNone(checkResult(case, pattern))
            self.assertEqual(self.body.Tip, pattern)
            for name, value in DEFAULTS[case].items():
                self.assertEqual(plain(getattr(pattern, name)), value, name)

        def checkCommand(self, case):
            pattern, seed, picks = self.runOnPicks(case)
            self.assertPanelOnPicks(pattern, seed, picks)
            self.assertOkMakesTheFeature(case, pattern)

        def testLinearPanelOnPicksAndOk(self):
            """Linear on the boss's five faces: a copy at x 22..28, 12360."""
            self.checkCommand("FaceLinearPattern")

        def testCircularPanelOnPicksAndOk(self):
            """Circular on the hole's cylinder: 4 holes over 360 degrees."""
            self.checkCommand("FacePolarPattern")

        def testMirrorPanelOnPicksAndOk(self):
            """Mirror on the boss's five faces about YZ: a copy at x -8..-2, 12360."""
            self.checkCommand("FaceMirrored")
