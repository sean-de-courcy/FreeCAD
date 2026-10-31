"""Review pr379-r4s: a sibling of the old element's sketch moved into its vacated place, for
other kinds of reference (vertex, face, Pocket-made edge, hole seam vertex)."""

import math

from PartDesignTests.Scenarios.harness import (
    BROKEN, Attached, Chamfered, Filleted, OwnOrBroken, Scenario, X, Y, Z, edge, face, vertex,
)
from PartDesignTests.Scenarios import models as m


class R4RimVertexFace(Scenario):
    """Three rims 3600 x 45, 235 high, y = 0, 2000, 4045. A Point on rim 1's front-left top
    corner vertex, a sketch on rim 1's front face. Rim 1's lines deleted, rim 2's moved (IDs
    kept) to y = 0..45. Rim 1 is gone: both break."""

    area = "r4s-vacated"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r4s"
    TIER = "F"
    SIZE = 4090
    REFS = ("corner", "front")
    length, thickness, height = 3600, 45, 235
    rims = (0, 2000, 4045)
    edited = False

    def corner(self):
        return vertex(at=self.s(0, 0, self.height))

    def front(self):
        return face("plane", normal=-Y, through=(0, 0, 0))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        geometry = []
        for y in self.rims:
            geometry += m.rectangle(0, self.s(y), L, self.s(y) + T)
        profile = m.sketch(doc, "Profile", geometry, body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        point = body.newObject("PartDesign::Point", "Corner")
        point.AttachmentSupport = [(pad, self.names(pad, self.corner())[0])]
        point.MapMode = "Vertex"
        self.ref("corner", point, "AttachmentSupport", lambda: BROKEN if self.edited else self.corner(), Attached())
        sk = body.newObject("Sketcher::SketchObject", "OnFront")
        sk.AttachmentSupport = [(pad, self.names(pad, self.front())[0])]
        sk.MapMode = "FlatFace"
        self.ref("front", sk, "AttachmentSupport", lambda: BROKEN if self.edited else self.front(), Attached())

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class R4RimVertexFaceThick(R4RimVertexFace):
    thickness = 100
    rims = (0, 2000, 3990)


class R4SlotMovedIntoAVacatedPlace(Scenario):
    """A block 3600 x 4090 x 235; a Pocket 100 deep (from the top) of three slot rectangles 45
    wide at y = 1000, 2000 and 3000; a Chamfer on slot 1's near top edge (y = 1000). Slot 1's
    lines are deleted and slot 2's moved (IDs kept) to y = 1000..1045."""

    area = "r4s-vacated"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r4s"
    TIER = "F"
    SIZE = 4090
    REFS = ("chamfer",)
    width = 45
    edited = False

    def slotEdge(self, y):
        y, H = self.s(y, 235)
        return edge("line", direction=X, through=(0, y, H))

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(*self.s(0, 0, 3600, 4090)), body)
        m.pad(body, base, self.s(235), "Block")
        geometry = []
        for y in (1000, 2000, 3000):
            geometry += m.rectangle(0, self.s(y), self.s(3600) - 0, self.s(y) + self.s(self.width))
        slots = m.sketch(doc, "Slots", [], body, z=self.s(235))
        slots.addGeometry([g for g in geometry], False)
        pocket = m.pocket(body, slots, self.s(100), "Slots")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pocket, self.names(pocket, self.slotEdge(1000)))
        chamfer.Size = self.s(5)
        self.ref("chamfer", chamfer, "Base", lambda: BROKEN if self.edited else self.slotEdge(1000), Chamfered(self.s(5)))

    def edit(self, doc):
        m.moveRectangle(doc.Slots, 0, self.s(1000), self.s(3600), self.s(1000) + self.s(self.width), first=4)
        doc.Slots.delGeometries([0, 1, 2, 3])
        self.edited = True


class R4SlotMovedIntoAVacatedPlaceThick(R4SlotMovedIntoAVacatedPlace):
    width = 100


class R4HoleSeamVertex(Scenario):
    """HoleMovedIntoAVacatedPlace, with a Point on A's top rim vertex (its seam)."""

    area = "r4s-vacated"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r4s"
    TIER = "F"
    SIZE = 200
    SCALE = 3
    REFS = ("seam",)
    thick = 2
    edited = False

    def seam(self):
        return vertex(at=self.s(64, 50, self.thick))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, profile, self.s(self.thick))
        circles = [m.circle(*self.s(60, 50, 4)), m.circle(*self.s(140, 50, 4))]
        holes = m.sketch(doc, "Holes", circles, body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = holes
        pocket.Type = 1
        pocket.Midplane = True
        doc.recompute()
        point = body.newObject("PartDesign::Point", "Seam")
        point.AttachmentSupport = [(pocket, self.names(pocket, self.seam())[0])]
        point.MapMode = "Vertex"
        self.ref("seam", point, "AttachmentSupport", lambda: BROKEN if self.edited else self.seam(), Attached())

    def edit(self, doc):
        doc.Holes.moveGeometry(1, 3, m.V(*self.s(60, 50, 0)), False)
        doc.Holes.delGeometries([0])
        self.edited = True


class R4HoleSeamVertexThick(R4HoleSeamVertex):
    thick = 10
