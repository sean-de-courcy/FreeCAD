"""Review pr579s-r3 (ops#579 round 3): a Body B1 on a Body B0 whose first feature fails. B0 is empty
and valid, B1's FeatureBase fails by itself ("BaseFeature has an empty shape"). On integration that
failure is claimed: the FeatureBase passes the empty shape through and B1's own features run, so a
reference into one of them is solved (its record is refreshed) while B0 is down. On the PR the Body
doesn't continue (decision 254): B1's features fail without running and the record stays as it was.

B0: a 100 x 100 x 100 block far off (x = 9000), padded from a sketch in B0. B1: a Body on B0 holding
Profile (rim 1, a rectangle 3600 x 45 at y = 0), Pad (up 300) and Top, a sketch attached to the
front face (y = 0) of the Pad (B1's own feature)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m


class OwnRim(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r3"
    TIER = "F"
    SIZE = 3600
    REFS = ("front",)
    length, thickness, height = 3600, 45, 300
    edited = False

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.frontFace()

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        b0 = m.body(doc)
        ground = m.sketch(doc, "Ground", m.rectangle(self.s(9000), self.s(1000), self.s(9100), self.s(1100)), b0)
        m.pad(b0, ground, self.s(100), "GroundPad")
        doc.recompute()
        b1 = doc.addObject("PartDesign::Body", "Body1")
        b1.BaseFeature = b0
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), b1)
        pad = m.pad(b1, profile, H)
        doc.recompute()
        top = b1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(pad, self.names(pad, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def breakBase(self, doc):
        doc.GroundPad.Length = 0

    def fixBase(self, doc):
        doc.GroundPad.Length = self.s(100)

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class OwnRimDrawBreakSlideFixed(OwnRim):
    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakBase(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixBase(doc)


class OwnRimDrawBreakSlide(OwnRim):
    steps = ("drawAndBreak", "slide")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakBase(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class OwnRimBreakDrawSlideFixed(OwnRim):
    steps = ("breakFirst", "draw", "slideAndFix")

    def breakFirst(self, doc):
        self.breakBase(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixBase(doc)


class OwnRimBreakDrawFixSlide(OwnRim):
    steps = ("breakFirst", "draw", "fix", "slide")

    def breakFirst(self, doc):
        self.breakBase(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def fix(self, doc):
        self.fixBase(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class OwnRimControl(OwnRim):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class BoxRim(OwnRim):
    """As OwnRim, B1 on a Part::Box far off (the S1 failure: unclaimed on integration, whose filter
    leaves the FeatureBase and B1's features unrun)."""

    abstract = True
    baseBox = None

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        m.box(doc, "Stock", self.s(100, 100, 100), at=self.s(9000, 1000, 0))
        doc.recompute()
        b1 = doc.addObject("PartDesign::Body", "Body1")
        b1.BaseFeature = doc.Stock
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), b1)
        pad = m.pad(b1, profile, H)
        doc.recompute()
        top = b1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(pad, self.names(pad, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def breakBase(self, doc):
        doc.Stock.Length = 0

    def fixBase(self, doc):
        doc.Stock.Length = self.s(100)


class BoxRimDrawBreakSlideFixed(BoxRim, OwnRimDrawBreakSlideFixed):
    pass


class BoxRimBreakDrawSlideFixed(BoxRim, OwnRimBreakDrawSlideFixed):
    pass


class BoxRimControl(BoxRim, OwnRimControl):
    pass


class OwnRimRedrawWhileDown(OwnRim):
    """Rim 1 deleted and redrawn in place while B1 is stopped (one edit with the break); then the
    fix alone. A redraw in place: the redrawn face (quiet) or a break. The record taken at the
    failing recompute's end (decision 256) dates the redrawn lines as there before, so it breaks,
    the held family's accepted verdict (held_records_r4 ShapedFailRedrawnInPlace,
    ExtrusionFailRedrawnSetter). Found by the record-take's designer (ops#579)."""

    FOUND_BY = "designer pr579 record-take"
    steps = ("redrawAndBreak", "fix")

    def redrawAndBreak(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        self.breakBase(doc)

    def fix(self, doc):
        self.fixBase(doc)
