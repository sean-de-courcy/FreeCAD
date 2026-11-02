# SPDX-License-Identifier: LGPL-2.1-or-later

"""Class B's B1 cases (ops#469, ops#435; the ops repo's `corpus/predicted/B.json`): PartDesign
Pipes along closed spines, and a Spine set to another input.

Closed spines (an XZ sketch; the profile a square in the XY plane at a vertex of the spine):
- the D: a line up 10 along Z, then a 300 degree arc back to its start (`notes\\ops415-leg-names.md`
  18, ops#469's model);
- the lens: two B-spline arcs up 30 and back, which leave the bottom vertex at mirror angles to
  the profile's normal (the two ways tie);
- the ring: a closed rectangle of four lines, 30 x 20, the profile on its left leg (the review of
  fork PR 383, round 1).

The references are datum points on the joint edges and vertices at each corner, or at the
ring's corners on the joints there (the edges and vertices the legs' sides meet in). The edits
leave the solid as it was, so each reference must hold
the element at its own place, found by points on it taken from the model as built (an edge's
middle and ends, a vertex's point)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def drawnTheOtherWay(sketch, indices):
    """The sketch's lines and B-splines at `indices` drawn the other way, their ids kept."""
    geometry = sketch.Geometry
    for index in indices:
        curve = geometry[index]
        if curve.TypeId == "Part::GeomLineSegment":
            start, end = V(curve.StartPoint), V(curve.EndPoint)
            curve.StartPoint, curve.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
            curve.StartPoint, curve.EndPoint = end, start
        else:
            poles = list(curve.getPoles())[::-1]
            knots = [curve.FirstParameter + curve.LastParameter - k for k in curve.getKnots()[::-1]]
            curve.buildFromPolesMultsKnots(
                poles,
                list(curve.getMultiplicities())[::-1],
                knots,
                curve.isPeriodic(),
                curve.Degree,
                list(curve.getWeights())[::-1],
            )
    sketch.Geometry = geometry


def corners(names, per):
    """REFS: at each of `names`' corners, `per` joint edges and `per` joint vertices"""
    return tuple(f"{c}_{k}{i}" for c in names for k in ("e", "v") for i in range(per))


class ClosedPipe(Scenario):
    """A pipe along a closed spine, references on the joints at its corners (`CORNERS`: each
    corner's name and place), `PER` edges and `PER` vertices each, the nearest to the corner."""

    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E3")
    ISSUE = "ops#469"
    FOUND_BY = "port"
    TIER = "F"
    TRANSITION = "Transformed"
    PER = 4
    CORNERS = ()
    PROFILE_AT = (0, 0, 0)

    def spine(self):
        raise NotImplementedError

    def build(self, doc):
        body = m.body(doc)
        path = m.sketch(doc, "Path", self.spine(), body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-1, -1, 1, 1), body)
        profile.Placement = App.Placement(V(*self.PROFILE_AT), App.Rotation())
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        shape = pipe.Shape
        for corner, place in self.CORNERS:
            at = V(*place)
            for kind, elements in (("e", shape.Edges), ("v", shape.Vertexes)):

                def where(element):
                    return element.Point if kind == "v" else element.valueAt(
                        (element.FirstParameter + element.LastParameter) / 2
                    )

                nearest = sorted(
                    elements,
                    key=lambda e: (round((where(e) - at).Length, 6), tuple(round(c, 6) for c in where(e))),
                )[: self.PER]
                for i, element in enumerate(nearest):
                    key = f"{corner}_{kind}{i}"
                    point = V(where(element))
                    if kind == "v":
                        expect = lambda p=point: vertex(p)  # noqa: E731
                    else:
                        # its middle and its ends: at a closed spine's seam the shell's start and
                        # end edges may share a middle
                        ends = [V(v.Point) for v in element.Vertexes]

                        def expect(p=point, ends=ends):
                            return edge(
                                contains=p,
                                where=lambda e: len(e.Vertexes) == len(ends)
                                and all(
                                    min((V(v.Point) - q).Length for v in e.Vertexes) < 1e-6
                                    for q in ends
                                ),
                            )

                    datum = body.newObject("PartDesign::Point", "On_" + key)
                    datum.AttachmentSupport = [(pipe, self.names(pipe, expect()))]
                    datum.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                    self.ref(key, datum, "AttachmentSupport", expect, Attached())


class ClosedD(ClosedPipe):
    abstract = True
    CORNERS = (("a", (0, 0, 0)), ("b", (0, 0, 10)))
    REFS = corners(("a", "b"), 4)

    def spine(self):
        arc = Part.ArcOfCircle(V(0, 10, 0), V(-18.66025, 5, 0), V(0, 0, 0))
        return [Part.LineSegment(V(0, 0, 0), V(0, 10, 0)), arc]


class ClosedDLineReversed(ClosedD):
    """The D's line drawn the other way (its id kept): every joint stays (ops#469: 18 silent
    on integration 770da0fde7, `proto_b` flip0)."""

    abstract = False

    def edit(self, doc):
        drawnTheOtherWay(doc.Path, [0])


class ClosedDLinesReordered(ClosedD):
    """The D's arc listed first, then its line (`proto_b` flipall's partner)."""

    abstract = False

    def edit(self, doc):
        geometry = doc.Path.Geometry
        doc.Path.Geometry = [geometry[1], geometry[0]]


class ClosedDProfileSlid(ClosedD):
    """The D's profile moved from the vertex at z = 0 to the one at z = 10 (the review of class
    B, CC1): no corner's names pass to the other vertex."""

    abstract = False
    AXES = ("M3", "E4")

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(0, 0, 10), App.Rotation())


class ClosedLens(ClosedPipe):
    abstract = True
    CORNERS = (("a", (0, 0, 0)), ("b", (0, 0, 30)))
    REFS = corners(("a", "b"), 4)

    def spine(self):
        return [
            Part.ArcOfCircle(V(0, 0, 0), V(11.51, 15, 0), V(0, 30, 0)).toBSpline(),
            Part.ArcOfCircle(V(0, 30, 0), V(-11.51, 15, 0), V(0, 0, 0)).toBSpline(),
        ]


class ClosedLensBothReversed(ClosedLens):
    """Both arcs of the lens drawn the other way, "Right corner": the two corners lie between
    the same two edges and are told apart by the start (row 322: silent on integration)."""

    abstract = False
    TRANSITION = "Right corner"

    def edit(self, doc):
        drawnTheOtherWay(doc.Path, [0, 1])


class ClosedLensTieArcReversed(ClosedLens):
    """One arc of the lens drawn the other way, "Transformed": both ways leave the profile alike,
    and the way stored decides (B1 (a'))."""

    abstract = False
    AXES = ("M3", "E3", "E4")

    def edit(self, doc):
        drawnTheOtherWay(doc.Path, [0])


class ClosedRing(ClosedPipe):
    """The ring drawn from its corner `START` (0 bottom left, then as drawn: top left, top
    right, bottom right), the profile at `PROFILE_Z` on the left leg, "Right corner"."""

    abstract = True
    AXES = ("M3", "E4")
    FOUND_BY = "review pr383-r1"
    TRANSITION = "Right corner"
    CORNERS = (("bl", (0, 0, 0)), ("tl", (0, 0, 20)), ("tr", (30, 0, 20)), ("br", (30, 0, 0)))
    REFS = corners(("bl", "tl", "tr", "br"), 4)
    START = 0
    PROFILE_Z = 4

    @property
    def PROFILE_AT(self):
        return (0, 0, self.PROFILE_Z)

    def spine(self):
        points = [(0, 0), (0, 20), (30, 20), (30, 0)]
        points = points[self.START :] + points[: self.START]
        return [
            Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in zip(points, points[1:] + points[:1])
        ]


class ClosedRingProfileSlidAlongLeg(ClosedRing):
    """The profile slid from z = 4 to z = 16, past the leg's middle."""

    abstract = False

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(0, 0, 16), App.Rotation())


class ClosedRingProfileSlidPastMiddle(ClosedRing):
    """The profile slid from z = 9 to z = 11, across the leg's middle."""

    abstract = False
    PROFILE_Z = 9

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(0, 0, 11), App.Rotation())


class ClosedRingTiedStartRecomputed(ClosedRing):
    """The ring drawn from its top right corner, the profile at the left leg's middle (both
    left corners equally near), recomputed with nothing changed."""

    abstract = False
    START = 2
    PROFILE_Z = 10

    def edit(self, doc):
        doc.Pipe.touch()


class ClosedRingSlidThenPickedAnew(ClosedRing):
    """The profile slid from z = 4 to z = 16 and recomputed; then the Spine set from the whole
    sketch to its four edges listed, or to an equal copy of the sketch: no other input, so the
    stored start stays (the cloud reading review of fork PR 383 round 2, N1)."""

    abstract = True
    FOUND_BY = "review pr383-r2"
    AXES = ("M3", "E4", "E5")

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(0, 0, 16), App.Rotation())
        doc.recompute()
        self.pick(doc)


class ClosedRingSlidThenEdgesListed(ClosedRingSlidThenPickedAnew):
    abstract = False

    def pick(self, doc):
        doc.Pipe.Spine = (doc.Path, ["Edge1", "Edge2", "Edge3", "Edge4"])


class ClosedRingSlidThenRelinkedToACopy(ClosedRingSlidThenPickedAnew):
    abstract = False

    def pick(self, doc):
        body = doc.Pipe.getParentGeoFeatureGroup()
        copy = m.sketch(doc, "Copy", doc.Path.Geometry, body, placement=XZ)
        doc.Pipe.Spine = (copy, [])


class ClosedRingSlidThenMultisectionAndBack(ClosedRingSlidThenPickedAnew):
    """The same, then a recompute in Multisection mode with a section at z = 18, and back to
    one profile (N2)."""

    abstract = False

    def pick(self, doc):
        body = doc.Pipe.getParentGeoFeatureGroup()
        section = m.sketch(doc, "Section", m.rectangle(-1, -1, 1, 1), body)
        section.Placement = App.Placement(V(0, 0, 18), App.Rotation())
        doc.Pipe.Transformation = "Multisection"
        doc.Pipe.Sections = [section]
        doc.recompute()
        doc.Pipe.Sections = []
        doc.Pipe.Transformation = "Constant"


class SpineSetAnew(Scenario):
    """A Right corner pipe of a 4 x 4 square with a round hole along an L (up 30, right 20 in
    an XZ sketch), the profile at its start; then the Spine is set to another L, drawn the
    other way and 100 along x (from (120, 30) left 20, then down 30), and the profile moved to
    that L's drawn start (120, 0, 30), facing along x. The references: the two caps. The right
    answer is where a new pipe on the new L puts them: the profile's cap at the profile, the
    other at (100, 0, 0) (ops#435; the review of class B, CC2: 22 of 56 names at the other end
    on integration)."""

    abstract = True
    area = "pipe_closed"
    CLASSES = ("B",)
    AXES = ("M3", "E5")
    ISSUE = "ops#435"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("cap_profile", "cap_far")
    OTHER_SKETCH = False

    def build(self, doc):
        body = m.body(doc)
        first = m.polyline([(0, 0), (0, 30), (20, 30)])
        second = m.polyline([(120, 30), (100, 30), (100, 0)])
        if self.OTHER_SKETCH:
            path = m.sketch(doc, "Path", first, body, placement=XZ)
            m.sketch(doc, "Other", second, body, placement=XZ)
        else:
            path = m.sketch(doc, "Path", first + second, body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2) + [m.circle(0, 0, 0.8)], body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [] if self.OTHER_SKETCH else ["Edge1", "Edge2"])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        for key, before, after in (
            # the one face in the plane through the leg's end, across it
            ("cap_profile", face("plane", through=(0, 0, 0)), face("plane", through=(120, 0, 30))),
            ("cap_far", face("plane", through=(20, 0, 30)), face("plane", through=(100, 0, 0))),
        ):
            sketch = body.newObject("Sketcher::SketchObject", "On_" + key)
            sketch.AttachmentSupport = [(pipe, self.names(pipe, before))]
            sketch.MapMode = "FlatFace"
            # before the edit (stepName None) the cap as built, after it the new pipe's
            self.ref(
                key,
                sketch,
                "AttachmentSupport",
                lambda b=before, a=after: a if self.stepName else b,
                Attached(),
            )

    def edit(self, doc):
        if self.OTHER_SKETCH:
            doc.Pipe.Spine = (doc.Other, [])
        else:
            doc.Pipe.Spine = (doc.Path, ["Edge3", "Edge4"])
        doc.Profile.Placement = App.Placement(V(120, 0, 30), App.Rotation(V(0, 1, 0), -90))


class SpineRepickedInTheSameSketch(SpineSetAnew):
    """The other L in the same sketch (row 267b)."""

    abstract = False


class SpineRelinkedToAnotherSketch(SpineSetAnew):
    """The other L in another sketch (row 267)."""

    abstract = False
    OTHER_SKETCH = True
