# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr383-r6gs (fork PR 383, round 6, the second fix 475a82449c, decision 180): the closed
spine's unpaired path now accepts the start by the lines' names where the translation fit's best
start and way (bestFitOf) agree with it, read in the body where no frame of the profile turned,
else in each frame that turned; two stored names on the spine at the places one cyclic order gives
them suffice.

What these cases aim at:
- a frame of the profile that turns while the ring does not (the placement of the profile turned
  and its lines turned back, so the solid is as it was): the fit is read in a frame that carries the
  ring to a place it isn't at (`ProfilePlacementTurned*`);
- a closed spine of two edges (the D): the names give the cyclic order both ways, so the way can't
  be told by them (`DTurned*`, `DScaledFar`);
- the names' shifts by a symmetry, a mirror, lines drawn anew with the others' IDs shifted
  (`Ids*`, `*Redrawn*`): the start by the names must not agree with the fit on a wrong corner;
- the start corner moved far with a turn or a stretched profile, the fix's earlier families.

The ring as in `pipe_closed_r6fs.py` (copied: a case imports only harness and models): a closed
rectangle of four lines on the XZ plane, (0, 0) -> (0, H) -> (W, H) -> (W, 0) -> (0, 0), W = 30,
H = 20 (sketch x = global X, sketch y = global Z), a square profile 2A x 2B (normal Z, along the
left leg) at the bottom left corner, "Right corner". The D as in `pipe_closed.py`."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached,
    Filleted,
    Scenario,
    X,
    Y,
    Z,
    edge,
    face,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def xyPlane(body):
    return [
        f for f in body.Origin.OriginFeatures if "XY_Plane" in (getattr(f, "Role", ""), f.Name)
    ][0]


class Ring(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E7")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6gs"
    TIER = "F"
    SIZE = 80
    SCALE = 1.0
    REFS = (
        "datum_left_outer",
        "datum_top_outer",
        "sketch_bottom_inner",
        "fillet_top_front",
        "point_top_right",
        "point_bottom_left",
    )
    turn = 0
    width = 30
    height = 20
    bottom = 0  # the bottom line's z (unscaled)
    halfX = 2
    halfY = 2
    facePad = False  # the profile is the top face of a Pad of the square

    W = property(lambda self: self.s(self.width))
    H = property(lambda self: self.s(self.height))
    Z0 = property(lambda self: self.s(self.bottom))
    A = property(lambda self: self.s(self.halfX))
    B = property(lambda self: self.s(self.halfY))

    def rot(self):
        return App.Rotation(Z, self.turn)

    def at(self, x, y, z):
        return self.rot().multVec(V(x, y, z))

    def along(self, d):
        return self.rot().multVec(d)

    def leftOuter(self):
        return face("plane", normal=self.along(-X), contains=self.at(-self.A, 0, (self.Z0 + self.H) / 2))

    def topOuter(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.H + self.A))

    def bottomInner(self):
        return face("plane", normal=self.along(Z), contains=self.at(self.W / 2, 0, self.Z0 + self.A))

    def topFront(self):
        return edge(
            "line",
            direction=self.along(X),
            through=self.at(0, -self.B, self.H + self.A),
            contains=self.at(self.W / 2, -self.B, self.H + self.A),
        )

    def topRight(self):
        return vertex(self.at(self.W + self.A, -self.B, self.H + self.A))

    def bottomLeft(self):
        return vertex(self.at(-self.A, -self.B, self.Z0 - self.A))

    def spinePlacement(self):
        return App.Placement(V(), self.rot().multiply(App.Rotation(X, 90)))

    def profilePlacement(self):
        return App.Placement(self.at(0, 0, 0), self.rot())

    def profileLink(self, doc):
        if not self.facePad:
            return self.profile
        self.profile.AttachmentSupport = [(xyPlane(self.body), "")]
        self.profile.MapMode = "FlatFace"
        self.profile.AttachmentOffset = self.profilePlacement()
        pad = m.pad(self.body, self.profile, self.s(1))
        pad.Reversed = True
        doc.recompute()
        top = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        return (pad, top)

    def corners(self):
        w, h = self.W, self.H
        return [(0, 0), (0, h), (w, h), (w, 0)]

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        self.spine = m.sketch(doc, "Spine", m.polygon(self.corners()), body, placement=self.spinePlacement())
        a, b = self.A, self.B
        self.profile = m.sketch(doc, "Square", m.rectangle(-a, -b, a, b), body, placement=self.profilePlacement())
        link = self.profileLink(doc)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = link
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        kinds = {
            "datum_left_outer": ("PartDesign::Plane", self.leftOuter, "FlatFace"),
            "datum_top_outer": ("PartDesign::Plane", self.topOuter, "FlatFace"),
            "sketch_bottom_inner": ("Sketcher::SketchObject", self.bottomInner, "FlatFace"),
            "point_top_right": ("PartDesign::Point", self.topRight, "Vertex"),
            "point_bottom_left": ("PartDesign::Point", self.bottomLeft, "Vertex"),
        }
        made = {}
        for name in self.REFS:
            if name in kinds:
                kind, predicate, mode = kinds[name]
                obj = body.newObject(kind, name)
                obj.AttachmentSupport = [(pipe, self.names(pipe, predicate()))]
                obj.MapMode = mode
                made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())
        if "fillet_top_front" in self.REFS:
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (pipe, self.names(pipe, self.topFront()))
            fillet.Radius = self.s(0.5)
            self.ref("fillet_top_front", fillet, "Base", self.topFront, Filleted(self.s(0.5)))

    # ---- edits
    def lines(self):
        """The ring's four lines as drawn: (start, end) in sketch coordinates, left up, top right,
        right down, bottom back."""
        w, h, z = self.W, self.H, self.Z0
        return [((0, z), (0, h)), ((0, h), (w, h)), ((w, h), (w, z)), ((w, z), (0, z))]

    def assign(self, lines, redraw=()):
        """lines[i]: the (start, end) the line object in slot i takes (IDs kept); slots in `redraw`
        get a new line (a new ID)."""
        g = self.spine.Geometry
        for i in range(len(lines)):
            if i not in redraw:
                g[i].StartPoint, g[i].EndPoint = V(100 + 10 * i, 100, 0), V(105 + 10 * i, 105, 0)
        for i, (p, q) in enumerate(lines):
            if i in redraw:
                g[i] = Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
            else:
                g[i].StartPoint, g[i].EndPoint = V(p[0], p[1], 0), V(q[0], q[1], 0)
        self.spine.Geometry = g

    def widen(self, width):
        self.width = width
        self.assign(self.lines())

    def turnModel(self, degrees):
        self.turn = degrees
        self.spine.Placement = self.spinePlacement()
        if self.profile.AttachmentSupport:
            self.profile.AttachmentOffset = self.profilePlacement()
        else:
            self.profile.Placement = self.profilePlacement()

    def stretchProfileY(self, factor):
        g = self.profile.Geometry
        for line in g:
            s, e = line.StartPoint, line.EndPoint
            line.StartPoint, line.EndPoint = V(s.x, s.y * factor, 0), V(e.x, e.y * factor, 0)
        self.profile.Geometry = g
        self.halfY *= factor

    def lower(self, z):
        """The bottom line moved to z (unscaled), the left and right lines lengthened."""
        self.bottom = z
        self.assign(self.lines())


# ---- (c) a frame of the profile that turns while the ring does not


class ProfilePlacementTurned(Ring):
    """The profile sketch's Placement turned by `DEG` degrees about its normal (Z), its lines
    turned back in the sketch so that, in the body, the profile is where and as it was (every line
    ID on the side it was): one edit; the solid is as it was. The profile's placement frame turns
    (the geometry frame, taken from the body's points, does not); the ring doesn't, so a frame that
    carries the ring carries it to a place it isn't at. Every reference stays."""

    AXES = ("M3", "E3")
    DEG = 180

    def edit(self, doc):
        back = App.Rotation(Z, -self.DEG)
        g = self.profile.Geometry
        for line in g:
            line.StartPoint, line.EndPoint = back.multVec(line.StartPoint), back.multVec(line.EndPoint)
        self.profile.Geometry = g
        self.profile.Placement = App.Placement(V(), App.Rotation(Z, self.DEG))


class ProfilePlacementTurned90(ProfilePlacementTurned):
    DEG = 90


class ProfilePlacementTurned37(ProfilePlacementTurned):
    DEG = 37


class ProfilePlacementTurned180AndWidened(ProfilePlacementTurned):
    """The same, and the right line moved to x = 34 (a small move: the fit is clear; no start corner
    moves), in one recompute."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        ProfilePlacementTurned.edit(self, doc)
        self.widen(34)


class ProfilePlacementTurned90AndWidened(ProfilePlacementTurned90):
    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        ProfilePlacementTurned.edit(self, doc)
        self.widen(34)


class ProfilePlacementTurned37AndWidened(ProfilePlacementTurned37):
    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        ProfilePlacementTurned.edit(self, doc)
        self.widen(34)


class ProfilePlacementTurned180AndLowered(ProfilePlacementTurned):
    """The same, and the bottom line moved to z = -4 (the start corner moves down the leg), in one
    recompute."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        ProfilePlacementTurned.edit(self, doc)
        self.lower(-4)


class ProfilePlacementTurned180AndWidenedFar(ProfilePlacementTurned):
    """The same, and the right line moved to x = 50 (the fit isn't clear), in one recompute."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        ProfilePlacementTurned.edit(self, doc)
        self.widen(50)


class ProfileStretchedY4AndWidened(Ring):
    """The profile stretched in sketch y by 4 (B from 2 to 8: its geometry frame turns 31 degrees)
    and the right line moved to x = 34, in one recompute."""

    AXES = ("M3", "E1", "E2")
    FACTOR = 4

    def edit(self, doc):
        self.stretchProfileY(self.FACTOR)
        self.widen(34)


class ProfileStretchedY4TurnedAndWidenedFar(ProfileStretchedY4AndWidened):
    """Stretched in y by 4, the right line moved to x = 50 and the model turned 120 degrees."""

    AXES = ("M3", "E1", "E2", "E7")

    def edit(self, doc):
        self.stretchProfileY(self.FACTOR)
        self.widen(50)
        self.turnModel(120)


# ---- (a) the names' start agreeing with a wrong start


class IdsShifted2FarWiden(Ring):
    """The ring unchanged in the body but for the right line moved to x = 50, the four line objects
    each drawing the geometry of the one two places on (IDs shifted by 2, a symmetry of the
    rectangle's cyclic order): the first object is now the right leg drawn down. The fit (not clear)
    reads the start at the bottom left corner; the names give the opposite corner."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        self.width = 50
        L = self.lines()
        self.assign([L[(i + 2) % 4] for i in range(4)])


class IdsShifted2Turned180(Ring):
    """The whole model turned 180 degrees about Z (sketch profile: both placements turn) and the
    four line objects each drawing the geometry of the one two places on (IDs shifted by 2), in one
    recompute. The geometry frame and the placement frame both turn by half a turn."""

    AXES = ("M3", "E7", "E3")

    def edit(self, doc):
        L = self.lines()
        self.assign([L[(i + 2) % 4] for i in range(4)])
        self.turnModel(180)


class IdsShifted2Turned180Face(IdsShifted2Turned180):
    """The same with the profile the top face of a Pad (the placement frame stays, the geometry
    frame turns)."""

    facePad = True


class IdsShifted2Turned180Widened(Ring):
    """IdsShifted2Turned180 and the right line moved to x = 34."""

    AXES = ("M3", "E7", "E3", "E2")

    def edit(self, doc):
        self.width = 34
        L = self.lines()
        self.assign([L[(i + 2) % 4] for i in range(4)])
        self.turnModel(180)


class MirroredFarWiden(Ring):
    """Every line drawn mirrored about the ring's vertical axis (x -> W - x, IDs kept) with the right
    side at x = 50: the first object is now the right leg drawn up. The ring is the same ring."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        self.assign(
            [((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0)), ((0, 0), (w, 0))]
        )


class LinesTradedInPairsFar(Ring):
    """The top and bottom lines trade their geometry (IDs kept), the right line at x = 50."""

    AXES = ("M3", "E3", "E2")

    def edit(self, doc):
        self.width = 50
        w, h = self.W, self.H
        self.assign(
            [((0, 0), (0, h)), ((w, 0), (0, 0)), ((w, h), (w, 0)), ((0, h), (w, h))]
        )


# ---- (b) lines drawn anew with other changes


class TopAndRightLegsRedrawnFar(Ring):
    """The top and right legs deleted and drawn anew (at z = 40 and x = 50: both far), the left and
    bottom lines lengthened to meet them. Two stored names remain, at the adjacent places 0 and 3."""

    AXES = ("M3", "E3", "E2")
    REFS = ("datum_left_outer", "sketch_bottom_inner", "point_bottom_left")

    def edit(self, doc):
        self.width, self.height = 50, 40
        self.assign(self.lines(), redraw=(1, 2))


class TopAndBottomLegsRedrawnFar(Ring):
    """The top leg drawn anew at z = 40 and the bottom leg drawn anew (same z = 0): two stored names
    remain, at the opposite places 0 and 2 (the left and right lines)."""

    AXES = ("M3", "E3", "E2")
    REFS = ("datum_left_outer", "point_bottom_left")

    def edit(self, doc):
        self.height = 40
        self.assign(self.lines(), redraw=(1, 3))


class TopAndRightLegsRedrawnTurned(Ring):
    """The top and right legs drawn anew and the model turned 120 degrees, in one recompute (two
    stored names remain, at adjacent places)."""

    AXES = ("M3", "E7", "E3")
    REFS = ("datum_left_outer", "sketch_bottom_inner", "point_bottom_left")

    def edit(self, doc):
        self.assign(self.lines(), redraw=(1, 2))
        self.turnModel(120)


class TopLegRedrawnOthersShiftedFar(Ring):
    """The top leg drawn anew (a new line in slot 1) and the other three objects each drawing the
    geometry of the next place (shifted by one round the ring), the right line at x = 50."""

    AXES = ("M3", "E3", "E2")
    REFS = ("datum_left_outer", "sketch_bottom_inner", "point_bottom_left")

    def edit(self, doc):
        self.width = 50
        L = self.lines()
        self.assign([L[(i + 1) % 4] for i in range(4)], redraw=(1,))


# ---- (c) the start corner moved far, with a turn or a stretched profile


class RingTurnedAndLoweredFar(Ring):
    """The bottom line moved to z = -15 and the model turned 120 degrees, in one recompute."""

    AXES = ("M3", "E7", "E2")

    def edit(self, doc):
        self.lower(-15)
        self.turnModel(120)


# ---- the D: a closed spine of two edges


class D(Scenario):
    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "review pr383-r6gs"
    TIER = "F"
    SIZE = 40
    SCALE = 1.0
    REFS = tuple(f"a_{k}{i}" for k in ("e", "v") for i in range(4))
    turn = 0
    length = 10

    def rot(self):
        return App.Rotation(Z, self.turn)

    def spinePlacement(self):
        return App.Placement(V(), self.rot().multiply(XZ.Rotation))

    def profilePlacement(self):
        return App.Placement(V(), self.rot())

    def arcOf(self, L):
        return Part.ArcOfCircle(V(0, L, 0), V(-1.8660254037844386 * L, L / 2, 0), V(0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        L = self.length
        self.path = m.sketch(
            doc,
            "Path",
            [Part.LineSegment(V(0, 0, 0), V(0, L, 0)), self.arcOf(L)],
            body,
            placement=self.spinePlacement(),
        )
        self.profile = m.sketch(doc, "Profile", m.rectangle(-1, -1, 1, 1), body)
        self.profile.Placement = self.profilePlacement()
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = False
        self.pipe = pipe
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        shape = pipe.Shape
        at = V(0, 0, 0)
        for kind, elements in (("e", shape.Edges), ("v", shape.Vertexes)):

            def where(element, kind=kind):
                return element.Point if kind == "v" else element.valueAt(
                    (element.FirstParameter + element.LastParameter) / 2
                )

            nearest = sorted(
                elements,
                key=lambda e: (round((where(e) - at).Length, 6), tuple(round(c, 6) for c in where(e))),
            )[:4]
            for i, element in enumerate(nearest):
                key = f"a_{kind}{i}"
                point = V(where(element))
                if kind == "v":
                    expect = lambda p=point: vertex(self.rot().multVec(p))  # noqa: E731
                else:
                    ends = [V(v.Point) for v in element.Vertexes]

                    def expect(p=point, ends=ends):
                        q = self.rot()
                        turned = [q.multVec(e) for e in ends]
                        return edge(
                            contains=q.multVec(p),
                            where=lambda e: len(e.Vertexes) == len(turned)
                            and all(
                                min((V(v.Point) - t).Length for v in e.Vertexes) < 1e-6
                                for t in turned
                            ),
                        )

                datum = body.newObject("PartDesign::Point", "On_" + key)
                datum.AttachmentSupport = [(pipe, self.names(pipe, expect()))]
                datum.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                self.ref(key, datum, "AttachmentSupport", expect, Attached())

    def turnModel(self, degrees):
        self.turn = degrees
        self.path.Placement = self.spinePlacement()
        self.profile.Placement = self.profilePlacement()

    def setLength(self, L):
        g = self.path.Geometry
        g[0].EndPoint = V(0, L, 0)
        g[1].Center = V(-0.8660254037844386 * L, L / 2, 0)
        g[1].Radius = L
        self.path.Geometry = g
        self.length = L


class DTurned(D):
    """The D turned 120 degrees about Z with its profile (one edit)."""

    def edit(self, doc):
        self.turnModel(120)


class DTurnedAndLonger(D):
    """The D turned 120 degrees and its line lengthened from 10 to 14 (the arc with it), in one
    recompute."""

    AXES = ("M3", "E3", "E7")

    def edit(self, doc):
        self.setLength(14)
        self.turnModel(120)


class DScaledFar(D):
    """The D scaled from 10 to 20 (no turn: the fit isn't clear)."""

    def edit(self, doc):
        self.setLength(20)


class DScaledSmall(D):
    """Control: the D scaled from 10 to 11."""

    def edit(self, doc):
        self.setLength(11)
