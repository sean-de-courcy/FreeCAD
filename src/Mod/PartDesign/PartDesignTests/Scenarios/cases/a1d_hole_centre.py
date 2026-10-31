# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr398-r4 (Sonnet), ops#522: the arc find's twin for FACES with a small hole.

A far face piece's saved point is its inside point when the fingerprint has one, else its centre
of mass. Version 5 saves an inside point only for a face whose area falls short of 0.98 of its
CONVEX hull's. A piece with a small hole (under 2 % of its hull) around its centroid has no inside
point: the saved point is the centre of mass, in the hole, over an island plate, not over the
plate the piece lies on. elementUpToFaces() (faces) saves the island; the made-whole rule then
needs the new cap to contain the saved point (holdsPointAlong: the sweep line meets the cap inside
it) and the plates under the point to be the saved ones, the island. A cap redrawn wholly on the
island, around the old centre, passes both, though the old piece lay on the plate round the island.

Model (lengths x scale): the profile is the square x, y -2..2 with a hole 0.5 x 0.5 centred at
(-0.25, 0). Plates at z = 10 (B-spline faces, one shell): P1 x -20..1.5 with the island
x -0.5..0, y -0.25..0.25 cut out; P3 the island; P2 x 1.5..20. The cap splits at x = 1.5: the left
piece (area 15.75 of a hull 16: no inside point) lies on P1, its centre of mass (-0.25, 0) in the
hole over P3. Edit: the outer lines move to x -0.45..-0.05, y -0.2..0.2 and the hole's to
x -0.18..-0.08, y -0.05..0.05 inside the sketch (the lines keep their IDs): the whole cap lies on
the island P3, round the old centre. The left piece lay on P1 and is gone: the reference must
break."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class HoleCentre(Scenario):
    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E1")
    ISSUE = "ops#522"
    FOUND_BY = "review pr398-r4"
    TIER = "F"
    SIZE = 40
    REFS = ("left_piece",)
    island = True
    # the edit: outer rectangle, hole rectangle (x0, y0, x1, y1)
    outer = (-0.45, -0.2, -0.05, 0.2)
    hole = (-0.18, -0.05, -0.08, 0.05)
    moved = False

    def flat(self, points):
        k = self.scale
        corners = [V(x * k, y * k, 10 * k) for x, y in points]
        return Part.Face(Part.makePolygon(corners + corners[:1]))

    def plates(self):
        island = [(-0.5, -0.25), (0, -0.25), (0, 0.25), (-0.5, 0.25)]
        p1 = self.flat([(-20, -20), (1.5, -20), (1.5, 20), (-20, 20)])
        if self.island:
            p1 = p1.cut(self.flat(island)).Faces[0]
        p2 = self.flat([(1.5, -20), (20, -20), (20, 20), (1.5, 20)])
        faces = [p1, p2] + ([self.flat(island)] if self.island else [])
        return [f.toNurbs().Faces[0] for f in faces]

    def leftPiece(self):
        k = self.scale
        if self.moved:
            # the old piece lay on P1 (round the island), the cap redrawn lies on the island
            # when there is one: broken; without one, on P1 still: the cap follows
            return BROKEN if self.island else face(contains=(-0.4 * k, 0.15 * k, 10 * k))
        return face(contains=(-1.5 * k, 1.5 * k, 10 * k))

    def build(self, doc):
        k = self.scale
        body = m.body(doc)
        faces = self.plates()
        plate = m.feature(doc, "Plate", Part.Shell(faces))
        lines = m.rectangle(-2 * k, -2 * k, 2 * k, 2 * k) + m.rectangle(
            -0.5 * k, -0.25 * k, 0 * k, 0.25 * k
        )
        profile = m.sketch(doc, "Profile", lines, body)
        profile.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
        profile.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
        pad.Refine = False
        doc.recompute()
        point = body.newObject("PartDesign::Point", "LeftPiece")
        point.AttachmentSupport = [(pad, self.names(pad, self.leftPiece())[0])]
        point.MapMode = "CenterOfMass"
        self.ref("left_piece", point, "AttachmentSupport", self.leftPiece, Attached())
        body.Tip = pad

    def edit(self, doc):
        self.moved = True
        k = self.scale
        m.moveRectangle(doc.Profile, *[v * k for v in self.outer], first=0)
        m.moveRectangle(doc.Profile, *[v * k for v in self.hole], first=4)


class HoleCentreOverIsland(HoleCentre):
    """As described: the cap redrawn wholly on the island, round the old centre of mass."""


class HoleCentreNoIsland(HoleCentre):
    """The control: no island (P1 whole under the hole): the cap redrawn at the same place lies on
    P1, the plate the old piece lay on: the reference follows it (made whole on the same plate)."""

    island = False
