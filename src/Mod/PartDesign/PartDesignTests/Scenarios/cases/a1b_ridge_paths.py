# Review subagent (sonnet) for fork PR A1b round 1: the ridge plates through save/reopen, undo/redo.

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Reopens, Scenario, face
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



class RidgeReopenThenMove(Reopens, Ridge):
    """Step 1: saved, closed and opened again (the v6 fingerprints read from the file); step 2: the
    profile moves 0.6 by placement."""

    steps = ("reopen", "step_move")

    def step_move(self, doc):
        self.move(doc, 0.6)


class RidgeMoveThenReopen(Reopens, Ridge):
    """Step 1: the profile moves 0.6; step 2: saved and reopened (the fingerprints written after the
    move)."""

    REFS = ("piece",)
    steps = ("step_move", "reopen")

    def step_move(self, doc):
        self.move(doc, 0.6)


class RidgeUndoRedo(Ridge):
    """Step 1: the profile moves 0.6 (one transaction); step 2: undone; step 3: redone."""

    steps = ("step_move", "step_undo", "step_redo")

    def build(self, doc):
        doc.UndoMode = 1
        super().build(doc)

    def step_move(self, doc):
        doc.openTransaction("move")
        self.move(doc, 0.6)
        doc.commitTransaction()

    def step_undo(self, doc):
        doc.undo()
        self.total = 0.0

    def step_redo(self, doc):
        doc.redo()
        self.total = 0.6

    def strip(self):
        # a reference lost at the move stays lost through the undo (the undo restores the old
        # property values, including the broken one's stored link)
        return super().strip()
