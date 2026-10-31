# Review subagent (sonnet) for fork PR A1b round 1: the ridge profile moves out (the strip is
# gone), back (the strip is there again), and out again. The solver runs between the Pad's new
# Placement and its new shape (the Pad's positionByPrevious()/Placement set before the shape is
# made again): in the move back, the old shape is the whole cap and the Placement is the one the
# strip's saved point was taken in, so the made-whole rule takes the strip.
import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class Ridge(Scenario):
    """Plates z = 10 + 2x (x -4..0) and z = 10 - 2x (x 0..4.5), meeting at 53 degrees, one shell, B-spline
    faces; the rectangle x -0.5..3, y 0..8 padded up to them. Strip on plate 1, piece on plate 2.
    All lengths scaled by self.scale. The profile is moved by the `mover` in each of the `moves`
    (dx per step, cumulative)."""

    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E5", "X4:20")
    ISSUE = "ops#522"
    FOUND_BY = "review prA1b-r1"
    TIER = "F"
    SIZE = 20
    REFS = ("strip", "piece")
    mover = "placement"
    order = (0, 1)
    moves = (0.6,)

    def __init__(self, config):
        super().__init__(config)
        self.total = 0.0  # profile shift so far, scale 1

    def plate(self, x0, x1, height):
        s = self.s
        corners = [V(*s(x, y, height(x))) for x, y in ((x0, -10), (x1, -10), (x1, 10), (x0, 10))]
        return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]

    def plates(self):
        return [
            self.plate(-4, 0, lambda x: 10 + 2 * x),
            self.plate(0, 4.5, lambda x: 10 - 2 * x),
        ]

    def build(self, doc):
        body = m.body(doc)
        faces = self.plates()
        plate = m.feature(doc, "Plate", Part.Shell(faces))
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(-0.5, 0, 3, 8)), body)
        xy = m.originFeature(body, "XY_Plane")
        if self.mover == "datum":
            datum = body.newObject("PartDesign::Plane", "DP")
            datum.AttachmentSupport = [(xy, "")]
            datum.MapMode = "FlatFace"
            profile.AttachmentSupport = [(datum, "")]
            profile.MapMode = "FlatFace"
        elif self.mover == "offset":
            profile.AttachmentSupport = [(xy, "")]
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

    def move(self, doc, dx):
        self.total += dx
        shift = App.Placement(V(self.s(self.total), 0, 0), App.Rotation())
        if self.mover == "offset":
            doc.Profile.AttachmentOffset = shift
        elif self.mover == "placement":
            doc.Profile.Placement = shift
        elif self.mover == "datum":
            doc.DP.AttachmentOffset = shift
        elif self.mover == "sketch":
            m.moveRectangle(doc.Profile, *self.s(-0.5 + self.total, 0, 3 + self.total, 8))

    def reorder(self, doc):
        faces = self.plates()
        doc.Plate.Shape = Part.Shell([faces[i] for i in (1, 0)])
        doc.Pad.UpToShape = (doc.Plate, ["Face%d" % i for i in range(1, len(faces) + 1)])

    def edit(self, doc):
        if self.order == (1, 0):
            self.reorder(doc)
        for dx in self.moves:
            self.move(doc, dx)

    def onCap(self, x):
        z = 10 + 2 * x if x < 0 else 10 - 2 * x
        return face(contains=self.s(x, 4, z))

    def strip(self):
        x0 = -0.5 + self.total
        if x0 >= 0:
            return BROKEN
        return self.onCap(x0 / 2)

    def piece(self):
        x0 = max(0, -0.5 + self.total)
        x1 = 3 + self.total
        return self.onCap((x0 + x1) / 2)



class RidgeMoveBackAgain(Ridge):
    """Out 0.6 (the strip is gone), back (the strip is there again, by its own name), out again."""

    steps = ("step_out", "step_back", "step_out2")

    def step_out(self, doc):
        self.move(doc, 0.6)

    def step_back(self, doc):
        self.move(doc, -0.6)

    def step_out2(self, doc):
        self.move(doc, 0.6)


class RidgeMoveBackAgainStripOnly(RidgeMoveBackAgain):
    REFS = ("strip",)


class RidgeMoveBackAgainOffset(RidgeMoveBackAgain):
    mover = "offset"


class RidgeMoveBackAgainDatum(RidgeMoveBackAgain):
    mover = "datum"


class RidgeMoveBackAgainSketch(RidgeMoveBackAgain):
    """The profile moved inside its sketch (no Placement change)."""

    mover = "sketch"


class RidgeMoveBackAgainReordered(RidgeMoveBackAgain):
    """As RidgeMoveBackAgain with the shell rebuilt the other way first (nothing moved)."""

    steps = ("step_reorder", "step_out", "step_back", "step_out2")

    def step_reorder(self, doc):
        self.reorder(doc)
