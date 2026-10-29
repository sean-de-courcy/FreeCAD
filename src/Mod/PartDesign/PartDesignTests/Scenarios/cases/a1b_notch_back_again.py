# Review subagent (sonnet) for fork PR A1b round 1: the notch plates (L-shaped plate, the square,
# the rest); the profile square moves by its sketch's Placement out onto the square plate (the L
# piece is gone), back, and out again. Same path as a1b_move_back_again.py with a flat-plate model
# and a face-shaped (not strip-shaped) gone piece.

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


def flatPlate(outline, z=10):
    corners = [V(x, y, z) for x, y in outline]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


class NotchBackAgain(Scenario):
    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E5")
    ISSUE = "ops#522"
    FOUND_BY = "review prA1b-r1"
    TIER = "F"
    REFS = ("l_piece", "square")
    steps = ("step_out", "step_back", "step_out2")
    mover = "placement"
    d = 0.5

    def __init__(self, config):
        super().__init__(config)
        self.total = 0.0

    def plates(self):
        outlines = (
            ((-10, -10), (4, -10), (4, 1), (1, 1), (1, 10), (-10, 10)),
            ((1, 1), (4, 1), (4, 10), (1, 10)),
            ((4, -10), (20, -10), (20, 10), (4, 10)),
        )
        return [flatPlate(o) for o in outlines]

    def build(self, doc):
        body = m.body(doc)
        faces = self.plates()
        plate = m.feature(doc, "Plate", Part.Shell(faces))
        profile = m.sketch(doc, "Profile", m.rectangle(0.5, 0.5, 2.5, 2.5), body)
        xy = m.originFeature(body, "XY_Plane")
        if self.mover == "datum":
            datum = body.newObject("PartDesign::Plane", "DP")
            datum.AttachmentSupport = [(xy, "")]
            datum.MapMode = "FlatFace"
            profile.AttachmentSupport = [(datum, "")]
            profile.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
        pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            expect = getattr(self, name)
            point = body.newObject("PartDesign::Point", name.capitalize())
            point.AttachmentSupport = [(pad, self.names(pad, expect())[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        body.Tip = pad

    def move(self, doc, to):
        self.total = to
        shift = App.Placement(V(to, to, 0), App.Rotation())
        if self.mover == "datum":
            doc.DP.AttachmentOffset = shift
        else:
            doc.Profile.Placement = shift

    def step_out(self, doc):
        self.move(doc, self.d)

    def step_back(self, doc):
        self.move(doc, 0.0)

    def step_out2(self, doc):
        self.move(doc, self.d)

    def l_piece(self):
        return BROKEN if self.total else face(contains=(0.75, 2, 10))

    def square(self):
        s = self.total
        return face(contains=(2 + s, 2 + s, 10))


class NotchBackAgainPlacement(NotchBackAgain):
    pass


class NotchBackAgainDatum(NotchBackAgain):
    mover = "datum"
