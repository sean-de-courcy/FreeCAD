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

"""Corpus cases (ops#501, class B): the names of up-to features' walls and caps, under a profile
edit (the ops repo's `corpus/predicted/B.json`).

Ports:
- `row217|ops442_2_curved_D2_walls`: `RevolutionUpToHookWallProfileTaller` (ops#442.2,
  `work/pr357-r2v/pE1_tilted_hook.txt`, the profile's height edit; the probe's other edits (x1,
  back) are the same wall and each costs another 9 s recompute, so they aren't ported; the
  second probe, `pE2_tilted_folds.txt`, a wall with two folds, takes 3 minutes to recompute
  once and isn't ported);
- `rows222_277_302|fixed_pos_rules`, row 222: `PadCapPieceCoversTheWholeFill`,
  `PadCapPieceGrowsOnOneSideOnly` (ops#360 H2, PR 340 round 2; rows 277 and 302 are in
  `pipe_leg_names.py`).

The hook (row 217, ops#293 D2's walls between first-contact jumps): a wall from
z = -1, 4 high and leaning (extruded along (0.6, 0, 4): `pE1` is the tilted hook), whose base
curve runs through the polar legs (r 2 to 0.5 over 100 to 130
degrees, then r 0.5 to 3.5 over 130 to 220 degrees), a B-spline through points on them (20
to a leg, the test's 60 take no longer to recompute); the profile x in [1, 3], z in [0, 2]
on XZ, fully constrained, revolved about its V axis up to the wall's face. First contact jumps
at r = 2 (the hook's first point is the curve's maximum of the radius), and the solid is
built between walls: the one at r = 2 is the image of the wall's face, a surface of revolution
at radius 2. Its names hold the wall's edge there and a key built from the profile's window
of the wall (`FCW<n>_<line>`), which a profile edit changes. A SubShapeBinder of that face
must go on holding it when the profile's height goes from 2 to 2.2 (the wall at r = 2 stands,
with a new height). A curved D2 wall's key follows the window,
and the reference broke loudly ("Missing face reference", candidates Face3 and Face7, 3.5 mm):
ops#442.2.

The cap (row 222): a Pad of the rectangle A (x -3..3, y -0.5..0.5) and the rectangle B (x 5..8,
y 0..3) up to a shell of two B-spline faces at z = 10: the rectangle x -10..20, y -10..10 with
the hole x -1..1, y -2..2, and the hole's fill. A's cap is three pieces, the middle one on the
fill and the two others on the plate. A datum point is on the middle piece, on the fill. A is
made taller, y -3..2.5: its cap covers the whole fill; the split leaves the fill whole and the
datum must stay on the cap that is the fill (it went to the ring that A's other pieces became,
valid and with no warning). Or A is made taller on one side only, y -0.5..2.5: the middle piece
is still alone on the fill, its bounds changed, and the datum stays on it."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    Bound,
    Scenario,
    ScenarioError,
    face,
)

V = App.Vector


# ---------------------------------------------------------------------------------------------
# A revolution up to a hook-shaped wall (row 217)
# ---------------------------------------------------------------------------------------------

HOOK = ((2, 0.5, 100, 130), (0.5, 3.5, 130, 220))
WALL_RADIUS = 2.0
POINTS_PER_LEG = 20
TILT = 0.6  # the wall leans: it is extruded along (TILT, 0, 4)


def polarWall(legs, low=-1, height=4):
    """A wall along (TILT, 0, height) from z = `low`, whose curve runs through the polar legs
    (r0, r1, a0, a1), the radius linear in the angle (degrees) along each"""
    points = []
    for index, (r0, r1, a0, a1) in enumerate(legs):
        for k in range(POINTS_PER_LEG + 1 if index == len(legs) - 1 else POINTS_PER_LEG):
            radius = r0 + (r1 - r0) * k / POINTS_PER_LEG
            angle = math.radians(a0 + (a1 - a0) * k / POINTS_PER_LEG)
            points.append(V(radius * math.cos(angle), radius * math.sin(angle), low))
    curve = Part.BSplineCurve()
    curve.interpolate(points)
    return Part.Edge(curve).extrude(V(TILT, 0, height))


def atRadius(radius):
    """The face of revolution (the wall between first-contact jumps) whose points all lie within
    0.1 of `radius` from Z (the leaning wall's radius varies by 0.01 over the profile's height)"""

    def test(f):
        if f.Surface.TypeId != "Part::GeomSurfaceOfRevolution":
            return False
        u0, u1, v0, v1 = f.ParameterRange
        points = [v.Point for v in f.Vertexes] + [
            f.valueAt(u0 + (u1 - u0) * a, v0 + (v1 - v0) * b)
            for a in (0.25, 0.5, 0.75)
            for b in (0.25, 0.5, 0.75)
        ]
        return all(abs(math.hypot(p.x, p.y) - radius) < 0.1 for p in points)

    return face(where=test)


class RevolutionUpToHookWall(Scenario):
    """The revolution up to the hook's wall and a SubShapeBinder of its wall at r = 2."""

    abstract = True
    area = "upto_wall_and_cap_names"
    CLASSES = ("B",)
    AXES = ("M2", "E5")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("wall_binder",)

    def build(self, doc):
        import Sketcher

        self.x0, self.x1, self.height = 1.0, 3.0, 2.0
        wall = doc.addObject("Part::Feature", "Wall")
        wall.Shape = polarWall(HOOK)
        body = doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        corners = [
            V(self.x0, 0),
            V(self.x1, 0),
            V(self.x1, self.height),
            V(self.x0, self.height),
        ]
        for start, end in zip(corners, corners[1:] + corners[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 2))
        sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
        sketch.addConstraint(Sketcher.Constraint("Vertical", 3))
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", 0, 1, -1))
        sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, self.x0))
        self.width = sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, self.x1 - self.x0))
        self.top = sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, self.height))
        doc.recompute()
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.Type = "UpToFace"
        revolution.UpToFace = (wall, ["Face1"])
        doc.recompute()
        if not revolution.isValid():
            raise ScenarioError(f"the revolution is invalid: {revolution.getStatusString()}")
        binder = doc.addObject("PartDesign::SubShapeBinder", "WallBinder")
        binder.Support = [(revolution, self.names(revolution, atRadius(WALL_RADIUS))[0])]
        doc.recompute()
        self.ref("wall_binder", binder, "Support", lambda: atRadius(WALL_RADIUS), Bound())

    def setProfile(self, doc, x1=None, height=None):
        if x1 is not None:
            self.x1 = x1
            doc.Profile.setDatum(self.width, App.Units.Quantity("%.12g mm" % (x1 - self.x0)))
        if height is not None:
            self.height = height
            doc.Profile.setDatum(self.top, App.Units.Quantity("%.12g mm" % height))


class RevolutionUpToHookWallProfileTaller(RevolutionUpToHookWall):
    """The profile's height 2 -> 2.2: the wall at r = 2 stays, with a new height."""

    def edit(self, doc):
        self.setProfile(doc, height=2.2)


# ---------------------------------------------------------------------------------------------
# A cap piece that comes to cover a whole face of the up-to shape (row 222, ops#360 H2)
# ---------------------------------------------------------------------------------------------


def dimensionedRectangle(sketch, tag, x0, y0, x1, y1):
    """A closed rectangle in `sketch`, held by constraints, its width and height named w<tag> and
    h<tag>, the place of its first corner x<tag> and y<tag>"""
    import Sketcher

    start = sketch.GeometryCount
    corners = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", start + i, 2, start + (i + 1) % 4, 1)
        )
    sketch.addConstraint(Sketcher.Constraint("Horizontal", start))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", start + 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", start + 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", start + 3))
    for name, constraint in (
        ("w", Sketcher.Constraint("DistanceX", start, 1, start, 2, x1 - x0)),
        ("h", Sketcher.Constraint("DistanceY", start + 1, 1, start + 1, 2, y1 - y0)),
        ("x", Sketcher.Constraint("DistanceX", -1, 1, start, 1, x0)),
        ("y", Sketcher.Constraint("DistanceY", -1, 1, start, 1, y0)),
    ):
        sketch.renameConstraint(sketch.addConstraint(constraint), name + tag)


class PadCapCoversTheFill(Scenario):
    """Row 222 (PR 340 round 2, H2): a Pad of the rectangle A (x -3..3, y -0.5..0.5) and the
    rectangle B (x 5..8, y 0..3) up to a shell of two B-spline faces at z = 10: the rectangle
    x -10..20, y -10..10 with the hole x -1..1, y -2..2, and the hole's fill. A's cap is three
    pieces, the middle one on the fill and the two others on the plate. A datum point is on the
    middle piece, on the fill. A is made taller, y -3..2.5 (`COVERS`): its cap covers the whole
    fill. The split leaves the fill whole and the datum must stay on the cap that is the fill
    (it went to the ring that A's other pieces became, valid and with no warning). Or A is made
    taller on one side only, y -0.5..2.5 (`HALF`): the middle piece is still alone on the fill,
    its bounds changed, and the datum stays on it."""

    abstract = True
    area = "upto_wall_and_cap_names"
    CLASSES = ("B",)
    AXES = ("M2", "E4")
    ISSUE = "ops#501"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("middle",)
    Z = 10
    NEW = (0, 0, 0, 0)  # the new y and height of A

    def build(self, doc):
        body = doc.addObject("PartDesign::Body", "Body")
        xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
        z = self.Z
        outer = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
        hole = [V(-1, -2, z), V(-1, 2, z), V(1, 2, z), V(1, -2, z)]
        wires = [Part.makePolygon(c + c[:1]) for c in (outer, hole)]
        plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), wires).toNurbs().Faces[0]
        fill = [V(-1, -2, z), V(1, -2, z), V(1, 2, z), V(-1, 2, z)]
        fillFace = Part.Face(Part.makePolygon(fill + fill[:1])).toNurbs().Faces[0]
        shell = doc.addObject("Part::Feature", "Plate")
        shell.Shape = Part.Shell([plate, fillFace])
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        sketch.AttachmentSupport = [(xy, "")]
        sketch.MapMode = "FlatFace"
        dimensionedRectangle(sketch, "A", -3, -0.5, 3, 0.5)
        dimensionedRectangle(sketch, "B", 5, 0, 8, 3)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Type = "UpToShape"
        pad.UpToShape = (shell, ["Face1", "Face2"])
        pad.Refine = False
        doc.recompute()
        if not pad.isValid():
            raise ScenarioError(f"the pad is invalid: {pad.getStatusString()}")
        point = body.newObject("PartDesign::Point", "OnMiddle")
        point.AttachmentSupport = [(pad, self.names(pad, self.middle())[0])]
        point.MapMode = "CenterOfMass"
        body.Tip = pad
        doc.recompute()
        self.ref("middle", point, "AttachmentSupport", self.middle, Attached())

    def middle(self):
        """The far cap at height z that holds the point (0, 0, z): the one on the fill (the caps
        lie on B-spline faces, not planes)"""
        point = V(0, 0, self.Z)
        return face(
            where=lambda f: abs(f.BoundBox.ZMin - self.Z) < 1e-6
            and abs(f.BoundBox.ZMax - self.Z) < 1e-6
            and f.Area < 50
            and f.isInside(point, 1e-6, True)
        )

    def edit(self, doc):
        y, height = self.NEW
        sketch = doc.Profile
        sketch.setDatum("hA", App.Units.Quantity(height, App.Units.Length))
        sketch.setDatum("yA", App.Units.Quantity(y, App.Units.Length))


class PadCapPieceCoversTheWholeFill(PadCapCoversTheFill):
    """A made taller, y -3..2.5: the cap covers the whole fill."""

    NEW = (-3, 5.5)


class PadCapPieceGrowsOnOneSideOnly(PadCapCoversTheFill):
    """A made taller on one side only, y -0.5..2.5: still the only cap on the fill."""

    NEW = (-0.5, 3)
