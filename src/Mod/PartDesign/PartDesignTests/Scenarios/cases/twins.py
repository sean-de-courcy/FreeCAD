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

"""Corpus cases (class A, ops#468; ops repo `notes/naming-class-A.md` sections 5 and 7): elements
told apart within a group of twins. Ported from the class A prototype (`work/500/proto_a.py`) for
fork PR A2: where an edge crosses a hole twice, its two crossing points; an edit adds or removes one
of them, slides them, or flips the edge's direction with the geometry unchanged (a switch point of
the side role, `naming-class-A.md` 4.1); and fallback-named lists on a periodic face whose split is
turned.

Every reference is a datum point on the element (a vertex, or an edge's centre). The expected
element is defined by its place on the edited model: the crossing on the same side of the hole's
axis, the arc at the same split; where it no longer exists the reference must break."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Predicate, Scenario, edge, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def onCircle(where, description):
    """A vertex whose point passes `where(point, tol)`."""
    return Predicate("Vertex", description, [lambda v, tol: where(v.Point, tol)])


class TwinCase(Scenario):
    abstract = True
    area = "twins"
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "port"
    TIER = "F"

    def point(self, doc, name, target, expect, body=None, mode="Vertex"):
        """A datum point on the element `expect()` selects on `target`, as reference `name`."""
        if body is not None:
            point = body.newObject("PartDesign::Point", name)
        else:
            point = doc.addObject("Part::DatumPoint", name)
        point.AttachmentSupport = [(target, self.names(target, expect())[0])]
        point.MapMode = mode
        self.ref(name, point, "AttachmentSupport", expect)
        return point


# A box cut by a cylinder that crosses its front bottom edge twice ----------------------------

# The cylinder (radius 1, axis along Z through (cx, -0.3)) meets the edge y = 0, z = 0 at
# x = cx -+ HALF
HALF = math.sqrt(1 - 0.3**2)


class BoxCylinderCrossings(TwinCase):
    """A 10 mm box (Part::Box) cut by a cylinder of radius 1 along Z through (cx, -0.3), 12 high
    (Part::Cut): the cylinder crosses the box's front bottom edge (y = 0, z = 0) at
    x = cx -+ 0.954, `lo` and `hi`, where they lie on the edge. The cylinder moves to cx1."""

    abstract = True
    AXES = ("M3", "E1")
    cx0 = cx1 = 5.0

    def crossing(self, side):
        x = self.cx + side * HALF
        if not 1e-6 < x < 10 - 1e-6:
            return BROKEN
        return vertex((x, 0, 0))

    def build(self, doc):
        self.cx = self.cx0
        box = doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 10
        self.cylinder = doc.addObject("Part::Cylinder", "Cylinder")
        self.cylinder.Radius = 1
        self.cylinder.Height = 12
        self.cylinder.Placement = App.Placement(V(self.cx, -0.3, -1), App.Rotation())
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = box, self.cylinder
        doc.recompute()
        for name, side in (("lo", -1), ("hi", 1)):
            if name in self.REFS:
                self.point(doc, name, cut, lambda side=side: self.crossing(side))
        doc.recompute()

    def edit(self, doc):
        self.cx = self.cx1
        self.cylinder.Placement = App.Placement(V(self.cx, -0.3, -1), App.Rotation())
        doc.recompute()


class BoxCylinderCrossingsSlide(BoxCylinderCrossings):
    __doc__ = BoxCylinderCrossings.__doc__ + " Both crossings slide 0.5 along the edge."
    REFS = ("lo", "hi")
    cx1 = 5.5


class BoxCylinderCrossingsTwoToOne(BoxCylinderCrossings):
    __doc__ = (
        BoxCylinderCrossings.__doc__
        + " To cx = 0.5: `lo` leaves the edge past its end, `hi` stays alone. Its reference stays"
        + " on it; `lo`'s breaks."
    )
    REFS = ("lo", "hi")
    cx1 = 0.5


class BoxCylinderCrossingsToTheFarEnd(BoxCylinderCrossings):
    __doc__ = (
        BoxCylinderCrossings.__doc__
        + " To cx = 9.5: `hi` leaves the edge past its far end, `lo` stays alone."
    )
    REFS = ("lo", "hi")
    cx1 = 9.5


class BoxCylinderCrossingsOneToTwo(BoxCylinderCrossings):
    __doc__ = (
        BoxCylinderCrossings.__doc__
        + " From cx = 9.5 (`lo` alone on the edge) to 5: `hi` appears; `lo`'s reference stays on"
        + " `lo`."
    )
    REFS = ("lo",)
    cx0, cx1 = 9.5, 5.0


# A PartDesign pad with a through hole whose rim crosses its front edges ----------------------


class PadHoleCrossings(TwinCase):
    """A PartDesign pad 20 x 10 x 5 with a through pocket of a circle of radius 2 centred on its
    front edge, (cx, 0): the hole's rim crosses the front bottom and top edges at x = cx -+ 2
    (`lo`/`hi`, z 0 and 5); the circle's seam vertex is the top `hi` crossing. The circle's centre
    moves to cx1 (the sketch geometry moved, its id kept)."""

    abstract = True
    AXES = ("M3", "E1")
    REFS = ("lo_z0", "lo_z5", "hi_z0", "hi_z5")
    cx0 = cx1 = 10.0

    def crossing(self, side, z):
        x = self.cx + side * 2
        if not 1e-6 < x < 20 - 1e-6:
            return BROKEN
        return vertex((x, 0, z))

    def build(self, doc):
        self.cx = self.cx0
        body = m.body(doc)
        profile = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 5)
        doc.recompute()
        self.hole = m.sketch(doc, "HoleSketch", [m.circle(self.cx, 0, 2)], body, z=5)
        pocket = m.pocketThroughAll(body, self.hole, "Hole")
        doc.recompute()
        for side, label in ((-1, "lo"), (1, "hi")):
            for z in (0, 5):
                self.point(
                    doc,
                    f"{label}_z{z}",
                    pocket,
                    lambda side=side, z=z: self.crossing(side, z),
                    body=body,
                )
        doc.recompute()

    def edit(self, doc):
        self.cx = self.cx1
        geometry = self.hole.Geometry
        geometry[0].Center = V(self.cx, 0, 0)
        self.hole.Geometry = geometry
        doc.recompute()


class PadHoleCrossingsSlide(PadHoleCrossings):
    __doc__ = PadHoleCrossings.__doc__ + " The hole slides 0.5 along the edge."
    cx1 = 10.5


class PadHoleCrossingsToTheStart(PadHoleCrossings):
    __doc__ = PadHoleCrossings.__doc__ + " To cx = 2.5, near the edge's start."
    cx1 = 2.5


class PadHoleCrossingsFromTheStart(PadHoleCrossings):
    __doc__ = PadHoleCrossings.__doc__ + " From cx = 2.5 back to 10."
    cx0, cx1 = 2.5, 10.0


class PadHoleCrossingsPastTheEnd(PadHoleCrossings):
    __doc__ = (
        PadHoleCrossings.__doc__
        + " To cx = 18.5: the `hi` crossings leave the edges past their far end; their references"
        + " break."
    )
    cx1 = 18.5


# ops#468: a hole across a Pipe's joint --------------------------------------------------------


def walk(lengths, turns):
    """The polyline's points (x, z): legs of `lengths`, each turned by `turns` (degrees) from the
    one before, starting up Z."""
    points = [(0.0, 0.0)]
    heading = 0.0
    for i, length in enumerate(lengths):
        if i:
            heading += turns[i - 1]
        a = math.radians(heading)
        x, z = points[-1]
        points.append((x + length * math.sin(a), z + length * math.cos(a)))
    return points


class PipeJointHoleCrossings(TwinCase):
    """ops#468's model: a 4 x 4 square swept along a polyline in XZ (legs 30, 20, 20, turned 40 and
    20 degrees; Transition Transformed, Refine), and a pocket through it of a circle of radius 0.5
    in the YZ plane centred `dz` above the first bend (z = 30 + dz, midplane, through the pipe
    along X). The circle crosses the joint edges where the first two legs meet: its vertexes there
    are labelled by their x and y signs (`xm_yp` is x < 0, y > 0); the circle's seam (y = 0.5,
    z = zc) is a vertex too, and one of the crossings when it lies on a joint edge. An edit moves
    the joint (the first leg 30.3 long, or the path turned 2 degrees about Y): a crossing may
    appear, go, or become the seam's vertex. The expected element is the crossing with the same
    signs, else the seam's vertex on the same side of x (where the crossing reached the seam),
    else none."""

    abstract = True
    AXES = ("M3", "E1")
    dz = 0.0
    change = "leg"
    radius = 0.5

    def labelled(self, x, y):
        """The expectation for the crossing with x sign `x` and y sign `y`."""
        zc = 30 + self.dz
        shape = self.pocket.Shape

        def onHole(p, tol):
            return abs(math.hypot(p.y, p.z - zc) - self.radius) < tol

        def seam(p, tol):
            return abs(p.y - self.radius) < tol and abs(p.z - zc) < tol

        def crossing(p, tol):
            return onHole(p, tol) and not seam(p, tol) and p.x * x > 0 and p.y * y > 0

        def seamOnSide(p, tol):
            return seam(p, tol) and p.x * x > 0

        found = onCircle(crossing, f"crossing x{x:+d} y{y:+d}")
        if found.select(shape):
            return found
        onSeam = onCircle(seamOnSide, f"seam vertex x{x:+d}")
        if y > 0 and onSeam.select(shape):
            return onSeam
        return BROKEN

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), body)
        self.path = m.sketch(
            doc, "Path", m.polyline(walk([30, 20, 20], [40, 20])), body, placement=XZ
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = True
        doc.recompute()
        hole = m.sketch(
            doc,
            "Hole",
            [m.circle(0, 30 + self.dz, self.radius)],
            body,
            placement=App.Placement(V(0, 0, 0), App.Rotation(V(1, 1, 1), 120)),
        )
        self.pocket = body.newObject("PartDesign::Pocket", "Cut")
        self.pocket.Profile = hole
        self.pocket.Type = 1
        self.pocket.Midplane = True
        self.pocket.Refine = True
        doc.recompute()
        for x, xs in ((-1, "m"), (1, "p")):
            for y, ys in ((-1, "m"), (1, "p")):
                name = f"x{xs}_y{ys}"
                if name in self.REFS:
                    self.point(
                        doc, name, self.pocket, lambda x=x, y=y: self.labelled(x, y), body=body
                    )
        doc.recompute()

    def edit(self, doc):
        if self.change == "leg":
            points = walk([30.3, 20, 20], [40, 20])
            m.setLines(self.path, {i: (points[i], points[i + 1]) for i in range(len(points) - 1)})
        else:
            self.path.Placement = App.Placement(
                V(0, 0, 0), App.Rotation(V(0, 1, 0), 2).multiply(XZ.Rotation)
            )
        doc.recompute()


class PipeJointHoleSeamLeavesTheJoint(PipeJointHoleCrossings):
    __doc__ = (
        PipeJointHoleCrossings.__doc__
        + " dz = 0: on x < 0 the seam lies on the joint and the other crossing is alone; the leg"
        + " made 30.3 takes the joint off the seam, and two crossings appear there (1 -> 2)."
    )
    REFS = ("xm_ym", "xp_yp", "xp_ym")


class PipeJointHoleSeamLeavesTheJointTurned(PipeJointHoleSeamLeavesTheJoint):
    __doc__ = PipeJointHoleSeamLeavesTheJoint.__doc__ + " The path turned 2 degrees instead."
    AXES = ("M3", "E7")
    change = "rot"


class PipeJointHoleCrossingReachesTheSeam(PipeJointHoleCrossings):
    __doc__ = (
        PipeJointHoleCrossings.__doc__
        + " dz = 0.3: two crossings on x < 0; the longer leg brings one of them onto the seam"
        + " (2 -> 1)."
    )
    REFS = ("xm_ym", "xm_yp", "xp_yp", "xp_ym")
    dz = 0.3


class PipeJointHoleCrossingsStay(PipeJointHoleCrossings):
    __doc__ = PipeJointHoleCrossings.__doc__ + " dz = 0.2: the crossings stay twins."
    REFS = ("xm_ym", "xm_yp", "xp_yp", "xp_ym")
    dz = 0.2


class PipeJointHoleCrossingsStayNear(PipeJointHoleCrossings):
    __doc__ = PipeJointHoleCrossings.__doc__ + " dz = 0.1: the crossings stay twins."
    REFS = ("xm_ym", "xm_yp", "xp_yp", "xp_ym")
    dz = 0.1


class PipeJointHoleCrossingsStayTurned(PipeJointHoleCrossings):
    __doc__ = (
        PipeJointHoleCrossings.__doc__
        + " dz = -0.1, the path turned 2 degrees: the crossings stay twins."
    )
    AXES = ("M3", "E7")
    REFS = ("xm_ym", "xm_yp", "xp_yp", "xp_ym")
    dz = -0.1
    change = "rot"


# The side role's switch points: the crossed edge's direction flips, the geometry stays --------


class FusedBoxesSectionCrossings(TwinCase):
    """Model B of `naming-class-A.md` 4.1: box A 10 mm at the origin and box B 10 mm at
    (5, -5, 2) in a Part::MultiFuse, cut by a cylinder of radius 1 along Z through (cx, 0.3): the
    fuse's section edge y = 0, z = 2 (A's front face meets B's bottom face) is crossed twice, at
    x = cx -+ 0.954 (`xm`, `xp`)."""

    abstract = True
    REFS = ("xm", "xp")
    cx0 = cx1 = 7.5
    reorder = False

    def crossing(self, side):
        return vertex((self.cx + side * HALF, 0, 2))

    def build(self, doc):
        self.cx = self.cx0
        self.a = doc.addObject("Part::Box", "A")
        self.a.Length = self.a.Width = self.a.Height = 10
        self.b = doc.addObject("Part::Box", "B")
        self.b.Length = self.b.Width = self.b.Height = 10
        self.b.Placement = App.Placement(V(5, -5, 2), App.Rotation())
        self.fuse = doc.addObject("Part::MultiFuse", "Fuse")
        self.fuse.Shapes = [self.a, self.b]
        self.cylinder = doc.addObject("Part::Cylinder", "Cylinder")
        self.cylinder.Radius = 1
        self.cylinder.Height = 20
        self.cylinder.Placement = App.Placement(V(self.cx, 0.3, -3), App.Rotation())
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = self.fuse, self.cylinder
        doc.recompute()
        self.point(doc, "xm", cut, lambda: self.crossing(-1))
        self.point(doc, "xp", cut, lambda: self.crossing(1))
        doc.recompute()

    def edit(self, doc):
        if self.reorder:
            self.fuse.Shapes = [self.b, self.a]
        self.cx = self.cx1
        self.cylinder.Placement = App.Placement(V(self.cx, 0.3, -3), App.Rotation())
        doc.recompute()


class FusedBoxesSectionCrossingsReordered(FusedBoxesSectionCrossings):
    __doc__ = (
        FusedBoxesSectionCrossings.__doc__
        + " The MultiFuse's Shapes reordered to B, A: the section edge's curve is reversed, the"
        + " geometry unchanged. A name that reaches the other crossing must not stay silently."
    )
    AXES = ("M4", "E4")
    reorder = True


class FusedBoxesSectionCrossingsReorderedAndShifted(FusedBoxesSectionCrossings):
    __doc__ = (
        FusedBoxesSectionCrossings.__doc__ + " Reordered, and the cylinder shifted 0.3 along X."
    )
    AXES = ("M4", "E4", "E1")
    reorder = True
    cx1 = 7.8


class FusedBoxesSectionCrossingsShifted(FusedBoxesSectionCrossings):
    __doc__ = (
        FusedBoxesSectionCrossings.__doc__
        + " The cylinder shifted 0.3 along X, the order kept (the control)."
    )
    AXES = ("M4", "E1")
    cx1 = 7.8


class RevolvedRingRimCrossings(TwinCase):
    """Model A of `naming-class-A.md` 4.1: a ring revolved 360 degrees about Z from a rectangle
    x 10..20, z 0..5 on XZ (PartDesign Revolution), with a through pocket of a circle of radius 1
    centred (0, 20) on its top: the hole crosses the ring's outer rim circle (radius 20, z = 5)
    twice, at x = -+0.9997 (`xm`, `xp`). Revolution.Reversed is turned on: the solid is the same,
    the rim circle's direction flips."""

    AXES = ("M3", "E4")
    REFS = ("xm", "xp")

    def crossing(self, side):
        y = (400 - 1 + 400) / 40  # x^2 + y^2 = 400 and x^2 + (y - 20)^2 = 1
        return vertex((side * math.sqrt(400 - y * y), y, 5))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(10, 0, 20, 5), body, placement=XZ)
        self.revolution = body.newObject("PartDesign::Revolution", "Revolution")
        self.revolution.Profile = profile
        self.revolution.ReferenceAxis = (profile, ["V_Axis"])
        self.revolution.Angle = 360
        doc.recompute()
        hole = m.sketch(doc, "HoleSketch", [m.circle(0, 20, 1)], body, z=5)
        pocket = m.pocketThroughAll(body, hole, "Hole")
        doc.recompute()
        self.point(doc, "xm", pocket, lambda: self.crossing(-1), body=body)
        self.point(doc, "xp", pocket, lambda: self.crossing(1), body=body)
        doc.recompute()

    def edit(self, doc):
        self.revolution.Reversed = True
        doc.recompute()


# Fallback-named lists on a periodic face: the split turned (CC3) -------------------------------


class SplitCylinderOffsetLists(TwinCase):
    """TestNamingDump's OffsetSplitCylinder: a sketch of two half circles (radius 5, the split at
    angle a0 and a0 + pi) extruded 10 along Z as a solid (Part::Extrusion), offset by 1
    (Part::Offset, Join Arc). The offset's two lines at the split and the four rim arcs over it
    are named from the faces around them (UPP lists of two), told apart by their place on a
    half-cylinder. A datum point sits at each one's centre. The split is turned to a1 (the arcs'
    ranges moved, their ids kept), or (`rigid`) the sketch is turned as a whole: each reference
    stays on the element at the same split, of the same kind and height."""

    abstract = True
    AXES = ("M6", "E7")
    ISSUE = "ops#500"
    REFS = ("s0_line", "s1_line", "s0_top", "s0_bottom", "s1_top", "s1_bottom")
    a0 = 0.0
    a1 = 0.1
    rigid = False

    def member(self, split, kind, height):
        """The edge at the split `split` (0: angle a, 1: a + pi) of kind 'Line' or 'Arc', at height
        'mid', 'top' or 'bottom'."""
        angle = self.angle + split * math.pi

        def where(e):
            u0, u1 = e.ParameterRange
            p = e.valueAt((u0 + u1) / 2)
            off = abs((math.atan2(p.y, p.x) - angle + math.pi) % (2 * math.pi) - math.pi)
            if off > 1e-3:
                return False
            if kind == "Line":
                return isinstance(e.Curve, Part.Line)
            if isinstance(e.Curve, Part.Line):
                return False
            return (p.z > 5) == (height == "top")

        return edge(where=where)

    def refSpecs(self):
        return {
            "s0_line": (0, "Line", "mid"),
            "s1_line": (1, "Line", "mid"),
            "s0_top": (0, "Arc", "top"),
            "s0_bottom": (0, "Arc", "bottom"),
            "s1_top": (1, "Arc", "top"),
            "s1_bottom": (1, "Arc", "bottom"),
        }

    def build(self, doc):
        self.angle = self.a0
        circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 5)
        arcs = [Part.ArcOfCircle(circle, a, a + math.pi) for a in (self.a0, self.a0 + math.pi)]
        self.profile = m.sketch(doc, "Profile", arcs)
        cylinder = doc.addObject("Part::Extrusion", "Cylinder")
        cylinder.Base = self.profile
        cylinder.DirMode = "Custom"
        cylinder.Dir = V(0, 0, 1)
        cylinder.LengthFwd = 10
        cylinder.Solid = True
        offset = doc.addObject("Part::Offset", "Offset")
        offset.Source = cylinder
        offset.Value = 1
        doc.recompute()
        for name, spec in self.refSpecs().items():
            self.point(doc, name, offset, lambda spec=spec: self.member(*spec), mode="CenterOfMass")
        doc.recompute()

    def edit(self, doc):
        if self.rigid:
            self.profile.Placement = App.Placement(
                V(0, 0, 0), App.Rotation(V(0, 0, 1), math.degrees(self.a1 - self.a0))
            )
        else:
            geometry = self.profile.Geometry
            for g, a in zip(geometry, (self.a1, self.a1 + math.pi)):
                g.setParameterRange(a, a + math.pi)
            self.profile.Geometry = geometry
        self.angle = self.a1
        doc.recompute()


class SplitCylinderOffsetListsTurned(SplitCylinderOffsetLists):
    __doc__ = SplitCylinderOffsetLists.__doc__ + " The split turned by 0.1 rad."


class SplitCylinderOffsetListsTurnedBack(SplitCylinderOffsetLists):
    __doc__ = SplitCylinderOffsetLists.__doc__ + " The split turned by -0.1 rad."
    a1 = -0.1


class SplitCylinderOffsetListsTurnedHalf(SplitCylinderOffsetLists):
    __doc__ = SplitCylinderOffsetLists.__doc__ + " The split turned by 0.5 rad."
    a1 = 0.5


class SplitCylinderOffsetListsTurnedFromAnAngle(SplitCylinderOffsetLists):
    __doc__ = SplitCylinderOffsetLists.__doc__ + " The split at 0.3 rad turned to 0.4 rad."
    a0, a1 = 0.3, 0.4


class SplitCylinderOffsetListsTurnedOne(SplitCylinderOffsetLists):
    __doc__ = SplitCylinderOffsetLists.__doc__ + " The split turned by 1 rad."
    a1 = 1.0


class SplitCylinderOffsetListsRigid(SplitCylinderOffsetLists):
    __doc__ = SplitCylinderOffsetLists.__doc__ + " The sketch turned by 0.1 rad as a whole."
    AXES = ("M6", "X1")
    rigid = True
