"""Review pr579s-r3 (ops#579 round 3): a Body whose BaseFeature fails. The Body no longer continues
past an error in its FeatureBase (decision 254), so its members fail without running; on
integration a FeatureBase that fails by itself (its source is a Body whose first feature failed:
an empty shape) is claimed, passes the empty shape through, and the members run, breaking their
references loudly and finding them again when the source is whole.

B0 / Slab: the base. Rim 1 is a 3600 x 45 rectangle at y = 0 with one external line from Anchor
(a Part feature, far off). B1: a Body on it, holding a sketch Top attached to the front face (y = 0)
of its FeatureBase."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m


class BaseRim(Scenario):
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
    baseKind = "body"
    edited = False

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.frontFace()

    def anchorEdge(self):
        return Part.makeLine(App.Vector(0, -self.s(3000), 0), App.Vector(self.s(100), -self.s(3000), 0))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        m.feature(doc, "Anchor", self.anchorEdge())
        doc.recompute()
        if self.baseKind == "body":
            b0 = m.body(doc)
            profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), b0)
            m.pad(b0, profile, H)
            base = b0
        else:
            profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
            profile.addExternal("Anchor", "Edge1")
            slab = doc.addObject("Part::Extrusion", "Slab")
            slab.Base = profile
            slab.DirMode = "Normal"
            slab.LengthFwd = H
            slab.Solid = True
            base = slab
        doc.recompute()
        b1 = doc.addObject("PartDesign::Body", "Body1")
        b1.BaseFeature = base
        doc.recompute()
        fb = b1.Group[0]
        top = b1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(fb, self.names(fb, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def breakAnchor(self, doc):
        if self.baseKind == "body":
            doc.Pad.Length = 0
        else:
            doc.Anchor.Shape = Part.Vertex(App.Vector(0, -self.s(3000), 0))

    def fixAnchor(self, doc):
        if self.baseKind == "body":
            doc.Pad.Length = self.s(self.height)
        else:
            doc.Anchor.Shape = self.anchorEdge()

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class BodyBaseDrawBreakSlide(BaseRim):
    steps = ("drawAndBreak", "slide")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakAnchor(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class BodyBaseDrawBreakSlideFixed(BodyBaseDrawBreakSlide):
    steps = ("drawAndBreak", "slideAndFix")

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixAnchor(doc)


class BodyBaseBreakDrawSlide(BaseRim):
    steps = ("breakFirst", "draw", "slide")

    def breakFirst(self, doc):
        self.breakAnchor(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class BodyBaseBreakDrawSlideFixed(BodyBaseBreakDrawSlide):
    steps = ("breakFirst", "draw", "slideAndFix")

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixAnchor(doc)


class BodyBaseBreakDrawFixSlide(BaseRim):
    """Broken first; rim 2 drawn while broken; Anchor fixed (nothing else); then the slide."""
    steps = ("breakFirst", "draw", "fix", "slide")

    def breakFirst(self, doc):
        self.breakAnchor(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def fix(self, doc):
        self.fixAnchor(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class BodyBaseControl(BaseRim):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


def _slab(cls):
    return type(cls.__name__.replace("BodyBase", "SlabBase"), (cls,), {"baseKind": "extrusion"})


SlabBaseDrawBreakSlide = _slab(BodyBaseDrawBreakSlide)
SlabBaseDrawBreakSlideFixed = _slab(BodyBaseDrawBreakSlideFixed)
SlabBaseBreakDrawSlide = _slab(BodyBaseBreakDrawSlide)
SlabBaseBreakDrawSlideFixed = _slab(BodyBaseBreakDrawSlideFixed)
SlabBaseBreakDrawFixSlide = _slab(BodyBaseBreakDrawFixSlide)
SlabBaseControl = _slab(BodyBaseControl)
