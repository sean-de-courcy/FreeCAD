# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr398-r3 (ops#522): a reference to a far cap piece of Pad A, made through a LATER
extrusion B (Pad B fuses A, so the piece is a face of B's shape and the reference's target is B).
The up-to hook runs against the TARGET feature (B), i.e. B's own UpToShape/UpToFace and Direction,
not A's plates. B's up-to plate Q is static and lies on the sweep line through A's piece's point,
so the faces under the point "are the saved ones" although A's plates moved under A's profile
(decision 152's hazard). The strip must break; the piece is the whole cap."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


def flatPlate(outline, z):
    corners = [V(x, y, z) for x, y in outline]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


class DownstreamPad(Scenario):
    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E1")
    ISSUE = "ops#522"
    FOUND_BY = "review pr398-r3"
    TIER = "F"
    REFS = ("strip", "piece")
    moved = False
    bUpTo = "Q"  # "Q" (static plate), "Plates" (A's own plates)
    bType = "UpToShape"

    def shift(self):
        return -0.12 if self.moved else 0.0

    def build(self, doc):
        body = m.body(doc)
        plates = m.feature(doc, "Plate", Part.Shell([
            flatPlate(((-10, -12), (0, -12), (0, 12), (-10, 12)), 10),
            flatPlate(((0, -12), (10, -12), (10, 12), (0, 12)), 10)]))
        q = m.feature(doc, "Q", Part.Shell([flatPlate(((-20, -30), (20, -30), (20, 30), (-20, 30)), 30)]))
        xy = m.originFeature(body, "XY_Plane")
        pa = m.sketch(doc, "ProfileA", m.rectangle(-0.1, -10, 0.3, 10), body)
        pa.AttachmentSupport = [(xy, "")]
        pa.MapMode = "FlatFace"
        padA = body.newObject("PartDesign::Pad", "PadA")
        padA.Profile = pa
        padA.Type = "UpToShape"
        padA.UpToShape = (plates, ["Face1", "Face2"])
        padA.Refine = False
        doc.recompute()
        pb = m.sketch(doc, "ProfileB", m.rectangle(0.2, -5, 6, 5), body)
        pb.AttachmentSupport = [(xy, "")]
        pb.MapMode = "FlatFace"
        padB = body.newObject("PartDesign::Pad", "PadB")
        padB.Profile = pb
        padB.Refine = False
        if self.bUpTo == "Q":
            if self.bType == "UpToShape":
                padB.Type = "UpToShape"
                padB.UpToShape = (q, ["Face1"])
            else:
                padB.Type = "UpToFace"
                padB.UpToFace = (q, ["Face1"])
        else:
            padB.Type = "UpToShape"
            padB.UpToShape = (plates, ["Face1", "Face2"])
        doc.recompute()
        body.Tip = padB
        for name in self.REFS:
            expect = getattr(self, name)
            point = body.newObject("PartDesign::Point", name.capitalize())
            point.AttachmentSupport = [(padB, self.names(padB, expect())[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        body.Tip = padB

    def edit(self, doc):
        self.moved = True
        doc.Plate.Placement = App.Placement(V(-0.12, 0, 0), App.Rotation())
        doc.PadA.UpToShape = (doc.Plate, ["Face1", "Face2"])
        if self.bUpTo != "Q":
            doc.PadB.UpToShape = (doc.Plate, ["Face1", "Face2"])

    def strip(self):
        return BROKEN if self.moved else face(contains=(-0.05, 0, 10))

    def piece(self):
        return face(contains=(0.05, 0, 10))


class DownstreamPadBShape(DownstreamPad):
    """B pads up to the static plate Q (UpToShape); A's plates move -0.12 in x."""


class DownstreamPadBFace(DownstreamPad):
    """B pads up to the static plate Q (UpToFace)."""

    bType = "UpToFace"


class DownstreamPadBSamePlates(DownstreamPad):
    """B pads up to A's plates too: the up-to faces under the point move with them."""

    bUpTo = "Plates"
