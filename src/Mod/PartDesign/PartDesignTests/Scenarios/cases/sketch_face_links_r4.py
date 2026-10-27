# SPDX-License-Identifier: LGPL-2.1-or-later
"""Design pr384-r4 (class E, E1; ops#264 e2; the class note's ruling of 2026-10-27): a face
link's projected geometry after the edits that set its pairing signals against each other.

Each old geometry's source name, its place, and (for geometry saved before E1, without a source
name) its position in an unchanged list are votes; the face's loops (the projected edges chained
by their ends, oriented counter-clockwise) arbitrate between the pairs already settled. These
cases are the ruling's proof cases: the hole row moved by its pitch with a corner cut, the first
line redrawn in place, the attacks that leave nothing settled (expected loud), the mirror (read
by side), a lone arc, round 3's composed edits made through the sketch's Placement, its
AttachmentOffset and a moved support (the attack set's paths, ops#519), the attack set's reversed
profile, and pre-E1 geometry made for real: the saved file's `Source` attributes removed before
the edit. The review's centred redraws f and g are `sketch_face_redraw.py`'s (fork PR 387).

Every model is designed geometry: a profile padded 10 high, a sketch at z = 0 projecting the
pad's top face, and a circle (or a point) held by one constraint on one projected geometry. The
reference judged is the sketch's face link; its outcome is where the constraint is."""

import shutil

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6

SQUARE = [(0, 0), (20, 0), (20, 20), (0, 20)]
# front (0,0)-(10,0), the step wall x = 10 (0..5), the step y = 5 (10..20), the right line x = 20
# (5..10), the back line y = 10, the left line x = 0: lines 0 to 5
Z_PROFILE = [(0, 0), (10, 0), (10, 5), (20, 5), (20, 10), (0, 10)]
PLATE = [(0, 0), (40, 0), (40, 20), (0, 20)]


def onLine(g, axis, value, span):
    """Whether geometry g is a line on axis = value spanning span (lo, hi) in the other
    coordinate."""
    if not hasattr(g, "StartPoint"):
        return False
    other = "y" if axis == "x" else "x"
    ends = (g.StartPoint, g.EndPoint)
    if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
        return False
    lo, hi = sorted(getattr(p, other) for p in ends)
    return abs(lo - span[0]) < TOL and abs(hi - span[1]) < TOL


def hasEnds(g, a, b):
    """Whether geometry g is a line from a to b, either way."""
    if not hasattr(g, "StartPoint"):
        return False
    a, b = V(*a, 0), V(*b, 0)
    s, e = g.StartPoint, g.EndPoint
    return (s.isEqual(a, TOL) and e.isEqual(b, TOL)) or (s.isEqual(b, TOL) and e.isEqual(a, TOL))


def geoIdOf(sketch, match):
    found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and match(g)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected geometries match")
    return found[0]


class CircleOnLine(Outcome):
    """The sketch computes, its PointOnObject constraint names the projected line `on()` before
    the edit and `after()` after it, and the circle's centre lies on that line. A line is
    ("x" or "y", value, (lo, hi)), or ("ends", (x0, y0), (x1, y1))."""

    def __init__(self, on, after):
        self.on, self.after = on, after

    @staticmethod
    def matches(g, line):
        if line[0] == "ends":
            return hasEnds(g, line[1], line[2])
        return onLine(g, *line)

    def compare(self, scenario, consumer, target, expectation):
        line = self.on() if scenario.stepName is None else self.after()
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        held = consumer.ExternalGeo[-constraint.Second - 1]
        if not self.matches(held, line):
            return False, f"the constraint is on {held.StartPoint} - {held.EndPoint}"
        # PointOnObject holds the centre on the line through the segment
        centre = consumer.Geometry[constraint.First].Center
        if centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class PointOnHole(Outcome):
    """The point Coincident with a projected circle's centre: before the edit at `before`, after
    it at `after` (the constraint names the circle there, and the point is there)."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        x, y = self.before() if scenario.stepName is None else self.after()
        constraint = [c for c in consumer.Constraints if c.Type == "Coincident"][0]
        circle = consumer.ExternalGeo[-constraint.Second - 1]
        if not hasattr(circle, "Center") or not circle.Center.isEqual(V(x, y, 0), TOL):
            return False, f"the point is on the hole at {getattr(circle, 'Center', None)}"
        point = consumer.Geometry[constraint.First]
        if not V(point.X, point.Y, 0).isEqual(V(x, y, 0), TOL):
            return False, f"the point is at {point}"
        return True, ""


class FaceLinkR4(Scenario):
    """The profile (`corners`, and circles r 3 at `holes`), padded 10 high; a sketch at z = 0
    projects its top face. The consumer: a circle r 1 on the projected line `before()` at
    `circleAt()`, or (with `holes`) a point on the hole at `pointAt()`."""

    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "design pr384-r4"
    TIER = "F"
    AXES = ("M8", "E5")
    SIZE = 40
    SCALE = 1.0
    REFS = ("circle_on_line",)
    corners = SQUARE
    holes = ()
    height = 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def build(self, doc):
        s = self.s
        body = m.body(doc)
        geometry = m.polygon([s(*p) for p in self.corners])
        geometry += [m.circle(*s(*c), s(3)) for c in self.holes]
        profile = m.sketch(doc, "Profile", geometry, body)
        pad = m.pad(body, profile, s(self.height))
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        if self.holes:
            x, y = self.pointAt()
            hole = geoIdOf(
                sketch, lambda g: hasattr(g, "Radius") and g.Center.isEqual(V(x, y, 0), TOL)
            )
            point = sketch.addGeometry(Part.Point(V(x, y, 0)), False)
            sketch.addConstraint(Sketcher.Constraint("Coincident", point, 1, hole, 3))
            outcome = PointOnHole(self.pointAt, self.afterEdit)
        else:
            line = geoIdOf(sketch, lambda g: onLine(g, *self.before()))
            circle = sketch.addGeometry(m.circle(*self.circleAt(), s(1)), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, s(1)))
            outcome = self.outcome()
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace, outcome)

    def outcome(self):
        return CircleOnLine(self.before, self.afterEdit)

    def moveLines(self, doc, lines):
        """Moves the profile's lines {index: ((x0, y0), (x1, y1))} (unscaled) in place, keeping
        their geometry IDs; a line may turn round (its start goes away from both ends first)."""
        s = self.s
        geometry = doc.Profile.Geometry
        for index, (a, b) in lines.items():
            line = geometry[index]
            line.StartPoint = V(*s(-777, -777), 0)
            line.EndPoint = V(*s(*b), 0)
            line.StartPoint = V(*s(*a), 0)
        doc.Profile.Geometry = geometry

    def addLines(self, doc, points):
        doc.Profile.addGeometry(m.polyline([self.s(*p) for p in points]), False)

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class SavedBeforeE1:
    """The model saved, its projected geometry's source names removed from the file, and opened
    again before the edit: geometry saved before E1 in its first rebuild after opening (the
    ruling's R9; setting Source from Python doesn't reach the sketch's geometry). Listed before
    the case's class: `class XNoSource(SavedBeforeE1, X)`."""

    def edit(self, doc):
        self.doc = doc = m.reopenWithoutSources(self, doc)
        super().edit(doc)


# ---- the hole row ------------------------------------------------------------------------------


class ExternalFaceHoleRowMovedByPitchCornerCut(FaceLinkR4):
    """The cloud review's leftover risk: a 40 x 20 plate with holes r 3 at (10, 10) and (20, 10),
    a point Coincident with the right hole's centre. In one edit the row moves +10 (the circles
    keep their IDs: the left hole lands on the right hole's old place) and the back-right corner
    is cut 5 x 5. The count changes, so position says nothing, and place pairs the look-alike:
    silent on integration and on round 3's head. A circle's name outranks place (the Sketcher
    reissues a circle's ID only at the same centre): (30, 10)."""

    AXES = ("M8", "E1", "E5")
    REFS = ("point_on_right_hole",)
    corners = PLATE
    holes = ((10, 10), (20, 10))

    def pointAt(self):
        return self.s(20, 10)

    def afterEdit(self):
        return self.s(30, 10)

    def edit(self, doc):
        s = self.s
        geometry = doc.Profile.Geometry
        geometry[4].Center = V(*s(20, 10), 0)
        geometry[5].Center = V(*s(30, 10), 0)
        doc.Profile.Geometry = geometry
        self.moveLines(doc, {1: ((40, 0), (40, 15)), 2: ((35, 20), (0, 20))})
        self.addLines(doc, [(40, 15), (35, 20)])


class ExternalFaceHoleRowMovedByPitchCornerCutNoSource(
    SavedBeforeE1, ExternalFaceHoleRowMovedByPitchCornerCut
):
    """The same on geometry saved before E1: no name to contest the look-alike's place, and the
    count changed. The ruling's one residual (R7): it lasts one rebuild (the rebuild stamps the
    names), needs a composed edit, and no file predates E1; the stricter rule would break the
    plain corner cut of every pre-E1 sketch with a hole constraint."""

    AXES = ("M8", "E1", "E5", "E9")
    ACCEPTED = {
        "point_on_right_hole|V2s": "decision 58 (the class E ruling 2026-10-27, R7: geometry "
        "saved before E1, its first rebuild, a hole slid onto its neighbour's place with a count "
        "change)"
    }


# ---- the square --------------------------------------------------------------------------------


class SquareCase(FaceLinkR4):
    abstract = True
    REFS = ("circle_on_line",)
    on = ("x", 0)

    def before(self):
        axis, value = self.on
        return (axis, self.s(value), self.s(0, 20))

    def circleAt(self):
        axis, value = self.on
        return self.s(value, 5) if axis == "x" else self.s(5, value)


class ExternalFaceFirstLineRedrawnInPlace(SquareCase):
    """The front line deleted and drawn again in place (its ID comes back by the point clusters,
    so its name too); the face's wire may start from another edge. The circle on the left line
    at x = 0. Silent on integration (a new find); right: x = 0."""

    AXES = ("M8", "E2", "E5")

    def afterEdit(self):
        return self.before()

    def edit(self, doc):
        doc.Profile.delGeometry(0)
        self.addLines(doc, [(0, 0), (20, 0)])


class ExternalFaceFirstLineRedrawnInPlaceNoSource(
    SavedBeforeE1, ExternalFaceFirstLineRedrawnInPlace
):
    """The same on geometry saved before E1: position (the stored order) and place disagree and
    no name settles it. Loud where integration was silent (the ruling's R7)."""

    AXES = ("M8", "E2", "E5", "E9")


class ExternalFaceVerticalFlipSidesRedrawn(SquareCase):
    """An attack: the front and back lines kept but swapped and reversed (front to y = 20, back
    to y = 0), the sides deleted and drawn again in place, the new right line taking the left
    line's ID. Nothing is where it wasn't and every signal is contested. The circle on the left
    line: right is x = 0, but nothing settles it, so it breaks (loud)."""

    AXES = ("M8", "E2", "E3", "E5")

    def afterEdit(self):
        return self.before()

    def edit(self, doc):
        doc.Profile.delGeometries([1, 3])  # 0: front, 1: back
        self.moveLines(doc, {0: ((20, 20), (0, 20)), 1: ((0, 0), (20, 0))})
        self.addLines(doc, [(20, 0), (20, 20)])
        self.addLines(doc, [(0, 20), (0, 0)])


class ExternalFaceRedrawSidesNeighboursReversedMovedOut(SquareCase):
    """Round 1's reissue with the front and back lines also moved off their lines (y = -3 and
    23, reversed): nothing is at its old place, and the new right line (25, -3)-(25, 23) takes
    the deleted left line's ID. Every pair is by name only, in an order no loop has: the batch
    is rejected and the constrained line breaks (loud; the intent was x = 25)."""

    AXES = ("M8", "E2", "E3", "E5")
    on = ("x", 20)

    def afterEdit(self):
        return ("x", self.s(25), self.s(-3, 23))

    def edit(self, doc):
        doc.Profile.delGeometries([1, 3])
        self.moveLines(doc, {0: ((25, -3), (-5, -3)), 1: ((-5, 23), (25, 23))})
        self.addLines(doc, [(25, -3), (25, 23)])
        self.addLines(doc, [(-5, 23), (-5, -3)])


class ExternalFaceMirroredKeepsTheSide(SquareCase):
    """The square mirrored about x = 10, its lines keeping their IDs: the right line's ID is now
    at x = 0 and the left line's at x = 20, each on the other's old place. The circle on the right
    line. The face's structure (the front and back lines settled) keeps the constraint on its
    side, x = 20 (the ruling's R7 reading, the coordinator's answer 1); integration followed the
    ID across the face."""

    AXES = ("M8", "E3", "E5")
    on = ("x", 20)

    def afterEdit(self):
        return self.before()

    def edit(self, doc):
        self.moveLines(
            doc,
            {
                0: ((20, 0), (0, 0)),
                1: ((0, 0), (0, 20)),
                2: ((0, 20), (20, 20)),
                3: ((20, 20), (20, 0)),
            },
        )


class ExternalFaceRightSideSlanted(SquareCase):
    """The right line deleted and a slanted line (20, 0)-(25, 20) drawn, the back line stretched
    to (25, 20): one edge replaces one edge between the same neighbours. Nothing but the arc
    between the front and back lines pairs it (a lone arc): the circle on the slanted line."""

    AXES = ("M8", "E5")
    on = ("x", 20)

    def afterEdit(self):
        return ("ends", self.s(20, 0), self.s(25, 20))

    def edit(self, doc):
        self.moveLines(doc, {2: ((25, 20), (0, 20))})
        doc.Profile.delGeometry(1)
        self.addLines(doc, [(20, 0), (25, 20)])


class ExternalFaceProfileReversed(SquareCase):
    """The attack set's find (ops#519, pattern `reversed`): the square's four lines drawn from
    their other ends, IDs kept (the solid, the top face and its edges are the same). The reversed
    wire lists the face's edges in another order: on integration the circle on the right line
    moved 20 mm onto x = 0, silently. Names and places pair every line: x = 20."""

    AXES = ("M8", "E3")
    FOUND_BY = "attack set (ops#519) reversed"
    on = ("x", 20)

    def afterEdit(self):
        return self.before()

    def edit(self, doc):
        profile = doc.Profile
        ids = [profile.getGeometryId(i) for i in range(profile.GeometryCount)]
        geometry = profile.Geometry
        for i, line in enumerate(geometry):
            geometry[i] = Part.LineSegment(line.EndPoint, line.StartPoint)
        profile.Geometry = geometry
        for i, geometryId in enumerate(ids):
            profile.setGeometryId(i, geometryId)


class MovedSquare(SquareCase):
    """The square's lines moved by `moves` ({index: ((x0, y0), (x1, y1))}), keeping their IDs."""

    abstract = True
    moves = {}

    def edit(self, doc):
        self.moveLines(doc, self.moves)


class ExternalFaceMovedByWidthNoSource(SavedBeforeE1, MovedSquare):
    """Round 2's move by the width on geometry saved before E1: the square moved 20 to the right,
    the left line landing on the old right line's place. Position pairs the unchanged list (its
    loop's order kept), and the arcs drop the slide: the circle on the right line, x = 40."""

    AXES = ("M8", "E5", "E9")
    on = ("x", 20)
    moves = {
        0: ((20, 0), (40, 0)),
        1: ((40, 0), (40, 20)),
        2: ((40, 20), (20, 20)),
        3: ((20, 20), (20, 0)),
    }

    def afterEdit(self):
        return ("x", self.s(40), self.s(0, 20))


class ExternalFaceDiagonalMoveNoSource(SavedBeforeE1, MovedSquare):
    """The square moved by (20, 20) on geometry saved before E1: no place pairs at all; position
    does. The circle on the right line: x = 40 (20..40)."""

    AXES = ("M8", "E5", "E9")
    on = ("x", 20)
    moves = {
        0: ((20, 20), (40, 20)),
        1: ((40, 20), (40, 40)),
        2: ((40, 40), (20, 40)),
        3: ((20, 40), (20, 20)),
    }

    def afterEdit(self):
        return ("x", self.s(40), self.s(20, 40))


# ---- the Z profile -----------------------------------------------------------------------------


class ZCase(FaceLinkR4):
    abstract = True
    corners = Z_PROFILE


class ExternalFaceStepTurnedMovedByWidthWall(ZCase):
    """Round 3's turned step moved by the width (the Z profile moved 20 to the right, its step
    going down instead of up), the circle on the step wall x = 10 (0..5). Right: the wall at
    x = 30 (-5..0)."""

    AXES = ("M8", "E3", "E5")

    def before(self):
        return ("x", self.s(10), self.s(0, 5))

    def circleAt(self):
        return self.s(10, 2.5)

    def afterEdit(self):
        return ("x", self.s(30), self.s(-5, 0))

    def edit(self, doc):
        self.moveLines(
            doc,
            {
                0: ((20, 0), (30, 0)),
                1: ((30, 0), (30, -5)),
                2: ((30, -5), (40, -5)),
                3: ((40, -5), (40, 10)),
                4: ((40, 10), (20, 10)),
                5: ((20, 10), (20, 0)),
            },
        )


class ExternalFaceZMirrored(ZCase):
    """The Z profile mirrored about x = 10, its lines keeping their IDs: the right line's ID lands
    at x = 0 (5..10) and the left's at x = 20 (0..10), on each other's old places; the step wall
    and the back line stay. The circle on the right line x = 20 (5..10): read by side, the line at
    x = 20 (0..10), the left line's ID (the ruling's R7)."""

    AXES = ("M8", "E3", "E5")

    def before(self):
        return ("x", self.s(20), self.s(5, 10))

    def circleAt(self):
        return self.s(20, 7.5)

    def afterEdit(self):
        return ("x", self.s(20), self.s(0, 10))

    def edit(self, doc):
        new = [((20, 0), (10, 0)), ((10, 0), (10, 5)), ((10, 5), (0, 5)),
               ((0, 5), (0, 10)), ((0, 10), (20, 10)), ((20, 10), (20, 0))]
        self.moveLines(doc, dict(enumerate(new)))


# ---- round 3's composed edits through the sketch's paths (the attack set's, ops#519) -----------


class MovedByPath:
    """Round 3's composed edits with the move of 20 along x made by the profile's Placement
    ("placement"), its AttachmentOffset once attached to the XY plane ("attachment"), or a datum
    plane it is attached to ("support"), the cut or turn made in the profile's own coordinates.
    A move of the sketch changes every projected coordinate at once and no ID or name; the loops
    are read from the projection, so each path is the geometry edit's case. Listed before the
    case's class."""

    path = "placement"

    def build(self, doc):
        super().build(doc)
        profile = doc.Profile
        xy = m.originFeature(doc.Body, "XY_Plane")
        if self.path == "attachment":
            placement = profile.Placement
            profile.AttachmentSupport = [(xy, "")]
            profile.MapMode = "FlatFace"
            profile.AttachmentOffset = placement
        elif self.path == "support":
            plane = doc.addObject("PartDesign::Plane", "Support")
            doc.Body.insertObject(plane, profile, False)
            plane.AttachmentSupport = [(xy, "")]
            plane.MapMode = "FlatFace"
            plane.AttachmentOffset = profile.Placement
            profile.AttachmentSupport = [(plane, "")]
            profile.MapMode = "FlatFace"
            profile.AttachmentOffset = App.Placement()
        doc.recompute()

    def edit(self, doc):
        self.localEdit(doc)
        owner, name = {
            "placement": (doc.Profile, "Placement"),
            "attachment": (doc.Profile, "AttachmentOffset"),
            "support": (doc.getObject("Support"), "AttachmentOffset"),
        }[self.path]
        placement = getattr(owner, name)
        placement.Base += V(self.s(20), 0, 0)
        setattr(owner, name, placement)


class CornerCutMovedByWidth(MovedByPath, SquareCase):
    """Round 3's silent find: the square moved 20 to the right and its front-left corner cut; the
    left line lands on the old right line's place. The circle on the right line: x = 40."""

    abstract = True
    AXES = ("M8", "E1", "E5", "E7")
    on = ("x", 20)

    def afterEdit(self):
        return ("x", self.s(40), self.s(0, 20))

    def localEdit(self, doc):
        self.moveLines(doc, {0: ((5, 0), (20, 0)), 3: ((0, 20), (0, 5))})
        self.addLines(doc, [(0, 5), (5, 0)])


class ExternalFaceCornerCutMovedByPlacement(CornerCutMovedByWidth):
    path = "placement"


class ExternalFaceCornerCutMovedByAttachmentOffset(CornerCutMovedByWidth):
    path = "attachment"


class ExternalFaceCornerCutMovedBySupport(CornerCutMovedByWidth):
    path = "support"


class CornerCutBackRightMovedByWidth(CornerCutMovedByWidth):
    """The same with the back-right corner cut: x = 40 (0..15)."""

    abstract = True

    def afterEdit(self):
        return ("x", self.s(40), self.s(0, 15))

    def localEdit(self, doc):
        self.moveLines(doc, {1: ((20, 0), (20, 15)), 2: ((15, 20), (0, 20))})
        self.addLines(doc, [(20, 15), (15, 20)])


class ExternalFaceCornerCutBackRightMovedByPlacement(CornerCutBackRightMovedByWidth):
    path = "placement"


class ExternalFaceCornerCutBackRightMovedByAttachmentOffset(CornerCutBackRightMovedByWidth):
    path = "attachment"


class ExternalFaceCornerCutBackRightMovedBySupport(CornerCutBackRightMovedByWidth):
    path = "support"


class StepTurnedMovedByWidth(MovedByPath, ZCase):
    """Round 3's silent find: the Z profile moved 20 to the right and its step turned down; the
    left line lands on the old right line's place. The circle on the right line x = 20 (5..10):
    x = 40 (-5..10)."""

    AXES = ("M8", "E3", "E5", "E7")

    abstract = True

    def before(self):
        return ("x", self.s(20), self.s(5, 10))

    def circleAt(self):
        return self.s(20, 7.5)

    def afterEdit(self):
        return ("x", self.s(40), self.s(-5, 10))

    def localEdit(self, doc):
        self.moveLines(
            doc, {1: ((10, 0), (10, -5)), 2: ((10, -5), (20, -5)), 3: ((20, -5), (20, 10))}
        )


class ExternalFaceStepTurnedMovedByPlacement(StepTurnedMovedByWidth):
    path = "placement"


class ExternalFaceStepTurnedMovedByAttachmentOffset(StepTurnedMovedByWidth):
    path = "attachment"


class ExternalFaceStepTurnedMovedBySupport(StepTurnedMovedByWidth):
    path = "support"
