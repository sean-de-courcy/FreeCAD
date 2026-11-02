"""Review pr564son-r1 (ops#564 round 1): the hold of a record's marks while its target is still to
be recomputed. Aimed at a hold that outlives the recompute that should end it: a holder left
touched (a single-object recompute, a feature held past the Body's roll-back bar), so the record
keeps the marks of before a later edit and a sibling dragged onto the vacated place reads as drawn
again (R3-1)."""

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class HoldBase(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r1"
    TIER = "F"
    SIZE = 4090
    length, thickness, height = 3600, 45, 235

    def topEdge(self, y=0):
        y, H = self.s(y, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def drawSecond(self, doc):
        doc.Profile.addGeometry(self.rect(2000), False)

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])


class SingleRecomputeThenSlide(HoldBase):
    """Rim 1 alone (y = 0), a datum Plane in the Body and a Part Plane outside it attached to its
    outer top edge. One step: rim 2 (y = 2000) drawn and the sketch, Pad and both planes
    recomputed one by one (obj.recompute(), the document not), then rim 1's lines deleted and rim 2
    dragged (IDs kept) to y = 0, then the document recomputes. Rim 2 was in the model when the
    references last resolved: both must break (R3-1)."""

    REFS = ("inner", "plane")
    steps = ("go",)
    edited = False

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def build(self, doc):
        H = self.s(self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.rect(0), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        inner = body.newObject("PartDesign::Plane", "InnerPlane")
        inner.AttachmentSupport = [(pad, self.names(pad, self.topEdge())[0])]
        inner.MapMode = "NormalToEdge"
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(body, self.names(body, self.topEdge())[0])]
        plane.MapMode = "NormalToEdge"
        self.ref("inner", inner, "AttachmentSupport", lambda: self.want(), Attached())
        self.ref("plane", plane, "AttachmentSupport", lambda: self.want(), Attached())

    def go(self, doc):
        self.drawSecond(doc)
        for name in ("Profile", "Rims", "InnerPlane", "EdgePlane"):
            getattr(doc, name).recompute()
        self.slide(doc)
        self.edited = True


class SingleRecomputeOfHoldersOnly(SingleRecomputeThenSlide):
    """As above but the sketch and the Pad are recomputed with the document's recompute of just
    those two (doc.recompute([...])), then the holders one by one."""

    def go(self, doc):
        self.drawSecond(doc)
        doc.recompute([doc.Profile, doc.Rims])
        doc.InnerPlane.recompute()
        doc.EdgePlane.recompute()
        self.slide(doc)
        self.edited = True


class RollBackHeldSlide(HoldBase):
    """Rim 1 alone. A sketch S2 (a small square) attached to rim 1's outer top edge (NormalToEdge)
    and a Pad on it; the Tip is rolled back to the rims' Pad, so S2 and its Pad are held. One
    step: rim 2 (y = 2000) drawn, recompute, rim 1 deleted and rim 2 dragged (IDs kept) to y = 0,
    recompute, the Tip brought forward (the document recomputes): S2 resolves now. Rim 2 was in
    the model long before: S2 must break."""

    REFS = ("s2",)
    steps = ("go",)
    edited = False

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def build(self, doc):
        H = self.s(self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.rect(0), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        s2 = body.newObject("Sketcher::SketchObject", "S2")
        s2.AttachmentSupport = [(pad, self.names(pad, self.topEdge())[0])]
        s2.MapMode = "NormalToEdge"
        s2.addGeometry(m.rectangle(-5, -5, 5, 5), False)
        doc.recompute()
        pad3 = m.pad(body, s2, self.s(10), "Pad3")
        doc.recompute()
        self.ref("s2", s2, "AttachmentSupport", lambda: self.want(), Attached())

    def go(self, doc):
        body = doc.Body
        body.Tip = doc.Rims
        doc.recompute()
        self.drawSecond(doc)
        doc.recompute()
        self.slide(doc)
        doc.recompute()
        self.edited = True
        body.Tip = doc.Pad3


class RollBackHeldSlideRedraw(RollBackHeldSlide):
    """The same roll-back, the in-place redraw instead of a sibling: rim 1 deleted and drawn again
    (new IDs), with the Tip rolled back and forward around it. Decision 97 Q3's redraw: the edge
    redrawn (a warned guess is right too)."""

    def want(self):
        return self.topEdge()

    def go(self, doc):
        body = doc.Body
        body.Tip = doc.Rims
        doc.recompute()
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.rect(0), False)
        doc.recompute()
        body.Tip = doc.Pad3


class SingleRecomputeThenSlideThick(SingleRecomputeThenSlide):
    """The same, rims 100 thick (beyond d_max): integration breaks on its own."""

    thickness = 100


class SingleRecomputeOfHoldersOnlyThick(SingleRecomputeOfHoldersOnly):
    """The same, rims 100 thick."""

    thickness = 100


class RollBackHeldSlideThick(RollBackHeldSlide):
    """The same, rims 100 thick."""

    thickness = 100


class SingleRecomputeSetterSlideThick(SingleRecomputeThenSlideThick):
    """As SingleRecomputeThenSlideThick, and the holders' references set again (a dialog's OK)
    before the slide, between the single recomputes and the document's."""

    def go(self, doc):
        self.drawSecond(doc)
        for name in ("Profile", "Rims", "InnerPlane", "EdgePlane"):
            getattr(doc, name).recompute()
        doc.InnerPlane.AttachmentSupport = doc.InnerPlane.AttachmentSupport
        doc.EdgePlane.AttachmentSupport = doc.EdgePlane.AttachmentSupport
        self.slide(doc)
        self.edited = True


class OtherPadSlid(HoldBase):
    """Rim 1 (y = 0) and a spare rim (y = 4000) in Profile, padded (Rims). A Part Plane outside the
    Body attached to rim 1's outer top edge of the Body, and a datum Plane in the Body on the same
    edge of Rims. A second sketch Profile2 (rim at y = 2000) and a second Pad Pad2 are made after
    the references (the Body's closure gains them). `single`: the new features and the holders are
    recomputed one by one, else the document recomputes. One step: rim 1's lines deleted and
    Profile2's rim dragged (IDs kept) to y = 0. Rim 1 is gone and the rim there is another
    feature's, drawn after: both must break."""

    REFS = ("inner", "plane")
    steps = ("go",)
    single = False
    edited = False

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def build(self, doc):
        H = self.s(self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.rect(0) + self.rect(4000), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        inner = body.newObject("PartDesign::Plane", "InnerPlane")
        inner.AttachmentSupport = [(pad, self.names(pad, self.topEdge())[0])]
        inner.MapMode = "NormalToEdge"
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(body, self.names(body, self.topEdge())[0])]
        plane.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("inner", inner, "AttachmentSupport", lambda: self.want(), Attached())
        self.ref("plane", plane, "AttachmentSupport", lambda: self.want(), Attached())
        profile2 = m.sketch(doc, "Profile2", self.rect(2000), body)
        m.pad(body, profile2, H, "Pad2")
        if self.single:
            for name in ("Profile2", "Pad2", "InnerPlane", "EdgePlane"):
                getattr(doc, name).recompute()
        else:
            doc.recompute()

    def go(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile2, 0, 0, L, T, first=0)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class OtherPadSlidSingle(OtherPadSlid):
    """The same with the one-by-one recomputes after the references."""

    single = True
