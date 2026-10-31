# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr398-r4 (ops#522): the made-whole rule measures the up-to faces under a far piece's
saved point, but takes the holder (the far edge made whole) anywhere within an edge's reach of
that point (1 % of the old piece's length, holdsSavedCentre()). A far edge crossing a seam between
two plates at a shallow angle leaves a long piece on the first plate whose centre lies within that
reach of the seam. An edit moving the profile just across the seam makes the far edge whole on
the second plate: the first plate's piece is gone, and the first plate still lies under its saved
point, so the saved up-to face matches while the edge made whole lies on another plate (decision
168 asks for the same up-to face; integration breaks it, decision 152)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge
from PartDesignTests.Scenarios import models as m

V = App.Vector


def flatPlate(outline):
    corners = [V(x, y, 10) for x, y in outline]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


class EdgeReachAcrossSeam(Scenario):
    """Plates at z = 10 (B-spline), one shell: P1 x -10..0 and P2 x 0..10, y -12..32. The profile
    is the quadrilateral (-0.1, 0), (3, 0), (3, 20), (0.02, 20), padded UpToShape (Refine off): its
    left edge crosses the seam x = 0 at y = 16.67, so its far edge has a piece on P1 from (-0.1, 0)
    to (0, 16.67), 16.67 long (reach 0.167), centre (-0.05, 8.33, 10). The edit moves the profile
    by `move` along x through its attachment offset: by 0.101 the far left edge runs from
    (0.001, 0) to (0.121, 20), wholly on P2, 0.101 from that centre. The P1 piece is gone: its
    reference must break."""

    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E5")
    ISSUE = "ops#522"
    FOUND_BY = "review pr398-r4"
    TIER = "F"
    REFS = ("p1_piece",)
    move = 0.101
    moved = False

    def p1Piece(self):
        if self.moved:
            return BROKEN
        return edge(contains=(-0.05, 25.0 / 3, 10), where=lambda e: e.BoundBox.ZLength < 1e-6)

    def build(self, doc):
        body = m.body(doc)
        faces = [flatPlate(((-10, -12), (0, -12), (0, 32), (-10, 32))),
                 flatPlate(((0, -12), (10, -12), (10, 32), (0, 32)))]
        plate = m.feature(doc, "Plate", Part.Shell(faces))
        profile = m.sketch(doc, "Profile", m.polygon([(-0.1, 0), (3, 0), (3, 20), (0.02, 20)]), body)
        profile.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
        profile.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face1", "Face2"])
        pad.Refine = False
        doc.recompute()
        point = body.newObject("PartDesign::Point", "P1Piece")
        point.AttachmentSupport = [(pad, self.names(pad, self.p1Piece())[0])]
        point.MapMode = "CenterOfMass"
        self.ref("p1_piece", point, "AttachmentSupport", self.p1Piece, Attached())
        body.Tip = pad

    def edit(self, doc):
        self.moved = True
        doc.Profile.AttachmentOffset = App.Placement(V(self.move, 0, 0), App.Rotation())


class EdgeReachAcrossSeamFar(EdgeReachAcrossSeam):
    """The control: moved by 0.3, the far left edge 0.3 from the old centre, beyond the reach."""

    move = 0.3
