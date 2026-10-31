# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr398-r3 (ops#522): a far EDGE piece's saved point is its centre of mass, which for an
arc lies off the arc, over whatever lies inside its bend. The up-to faces its fingerprint saves
(version 6) are those under that point, not the plate the arc lay on. An arc piece lying on plate
P1 whose centre of mass falls over an island plate P3 saves P3. An edit that makes the far arc
whole on P3, passing within the old piece's reach (1 % of its length) of its old centre of mass,
leaves P3 under the saved point, so the made-whole rule may take the gone piece onto an arc on a
plate it never lay on (decision 168 asks for the same up-to face; integration breaks it,
decision 152)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge
from PartDesignTests.Scenarios import models as m

V = App.Vector
A0, A1 = math.radians(30), math.radians(150)


def flat(points):
    return Part.Face(Part.makePolygon([V(x, y, 10) for x, y in points + points[:1]]))


def dProfile(cx, cy, r):
    """An arc of radius r about (cx, cy) from 30 to 150 degrees, closed by its chord."""
    arc = Part.ArcOfCircle(Part.Circle(V(cx, cy, 0), V(0, 0, 1), r), A0, A1)
    chord = Part.LineSegment(arc.EndPoint, arc.StartPoint)
    return [arc, chord]


class ArcCentroidOverIsland(Scenario):
    """Plates at z = 10 (B-spline), one shell, in `Plate`: P3, the island x -1.5..0.6, y 3..4.6
    (inside the D, clear of its arc); P4, x 3..6, y -1..3.5; P1, the square x, y -20..20 without
    them. The profile is a D: the arc r = 5 about the origin from 30 to 150 degrees and its chord
    at y = 2.5, padded UpToShape (Refine off). P4 cuts the far arc at 44.4 degrees: the piece from
    there to 150 degrees (9.21 long) lies on P1, its centre of mass at (-0.543, 4.288, 10) over P3.
    The edit moves the D to (-0.543, 3.46) and makes it r = 0.8 (the sketch's two geometries keep
    their IDs): the far arc is whole on P3, its top 0.028 from that centre of mass (reach 0.092).
    The piece is gone, and the arc made whole lies on another plate: the reference must break."""

    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E1")
    ISSUE = "ops#522"
    FOUND_BY = "review pr398-r3"
    TIER = "F"
    REFS = ("arc_piece",)
    to = (-0.543, 3.46, 0.8)
    moved = False

    def plates(self):
        island = [(-1.5, 3), (0.6, 3), (0.6, 4.6), (-1.5, 4.6)]
        side = [(3, -1), (6, -1), (6, 3.5), (3, 3.5)]
        outer = [(-20, -20), (20, -20), (20, 20), (-20, 20)]
        p1 = flat(outer).cut(flat(island)).cut(flat(side)).Faces[0]
        return [f.toNurbs().Faces[0] for f in (p1, flat(island), flat(side))]

    def arcPiece(self):
        if self.moved:
            return BROKEN
        return edge(contains=(0, 5, 10), where=lambda e: e.Length > 5 and e.BoundBox.ZLength < 1e-6)

    def build(self, doc):
        body = m.body(doc)
        faces = self.plates()
        plate = m.feature(doc, "Plate", Part.Shell(faces))
        profile = m.sketch(doc, "Profile", dProfile(0, 0, 5), body)
        profile.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
        profile.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
        pad.Refine = False
        doc.recompute()
        point = body.newObject("PartDesign::Point", "ArcPiece")
        point.AttachmentSupport = [(pad, self.names(pad, self.arcPiece())[0])]
        point.MapMode = "CenterOfMass"
        self.ref("arc_piece", point, "AttachmentSupport", self.arcPiece, Attached())
        body.Tip = pad

    def edit(self, doc):
        self.moved = True
        cx, cy, r = self.to
        geometry = doc.Profile.Geometry
        geometry[0].Center = V(cx, cy, 0)
        geometry[0].Radius = r
        arc = geometry[0]
        geometry[1].StartPoint = arc.EndPoint
        geometry[1].EndPoint = arc.StartPoint
        doc.Profile.Geometry = geometry


class ArcCentroidOverIslandControl(ArcCentroidOverIsland):
    """The control: the D moved to (-0.543, 3.3), r = 0.8: its top 0.19 from the old centre of
    mass, beyond the reach. Broken on both builds."""

    to = (-0.543, 3.3, 0.8)
