"""Review pr579s-r4: the record-take (decision 256) and the first-solid-feature stop (255 (1), 257).

A Body with Profile (rim 1, a rectangle 3600 x 45 at y = 0), Pad1 (up 300) whose Length is an
expression on an outside box Gauge, and Top, a sketch attached to the front face (y = 0) of Pad1.
Gauge.Length = 0 makes Gauge fail and Pad1 fail without running (unclaimed, S1)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Reopens, Scenario, face
from PartDesignTests.Scenarios import models as m


class Gauge(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r4"
    TIER = "F"
    SIZE = 3600
    REFS = ("front",)
    length, thickness, height = 3600, 45, 300
    frontY = 0
    edited = False

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, self.s(self.frontY), 0))

    def want(self):
        return BROKEN if self.edited else self.frontFace()

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        m.box(doc, "Gauge", self.s(10, 10, 10), at=self.s(9000, 1000, 0))
        b1 = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), b1)
        pad = m.pad(b1, profile, H)
        pad.setExpression("Length", "Gauge.Length * %s" % (self.height / 10.0 * self.scale))
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
        doc.Gauge.Length = 0

    def fixBase(self, doc):
        doc.Gauge.Length = self.s(10)

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class GaugeDrawBreakSlideFixed(Gauge):
    """Rim 2 drawn with the failure; then rim 1 deleted, rim 2 slid onto its place and the fix:
    the reference into Pad1's front face breaks."""
    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakBase(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixBase(doc)


class GaugeBreakDrawSlideFixed(Gauge):
    steps = ("breakFirst", "draw", "slideAndFix")

    def breakFirst(self, doc):
        self.breakBase(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixBase(doc)


class GaugeControl(Gauge):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class GaugeMovedWhileDown(Gauge):
    """Rim 1 dragged to y = 500 (the same lines) while Pad1 is down; then the fix: the reference
    follows its face to y = 500 (what a drag does with no failure)."""
    steps = ("moveAndBreak", "fix")

    def moveAndBreak(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, self.s(500), L, self.s(500) + T, first=0)
        self.frontY = 500
        self.breakBase(doc)

    def fix(self, doc):
        self.fixBase(doc)


class GaugeMovedWhileDownControl(Gauge):
    steps = ("move",)

    def move(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, self.s(500), L, self.s(500) + T, first=0)
        self.frontY = 500


class GaugeMoveThenDrawSlide(Gauge):
    """Rim 1 dragged while down, a second rim drawn while still down, then rim 2 slid onto the
    dragged rim's place together with the fix."""
    steps = ("moveAndBreak", "draw", "slideAndFix")

    def moveAndBreak(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, self.s(500), L, self.s(500) + T, first=0)
        self.frontY = 500
        self.breakBase(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def slideAndFix(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, self.s(500), L, self.s(500) + T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True
        self.fixBase(doc)


class GaugeDrawElsewhereDeleteFixed(Gauge):
    """While down rim 1 is deleted and a new rim drawn elsewhere (y = 2000): the face is gone."""
    steps = ("editAndBreak", "fix")

    def editAndBreak(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)
        self.edited = True
        self.breakBase(doc)

    def fix(self, doc):
        self.fixBase(doc)


class OwnFail(Gauge):
    """Pad1.Length = 0 itself: Pad1 runs and fails (unclaimed since 255 (1)), its shape stays."""
    abstract = True

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        b1 = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), b1)
        pad = m.pad(b1, profile, H)
        doc.recompute()
        top = b1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(pad, self.names(pad, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def breakBase(self, doc):
        doc.Pad.Length = 0

    def fixBase(self, doc):
        doc.Pad.Length = self.s(self.height)


class OwnFailDrawBreakSlideFixed(OwnFail, GaugeDrawBreakSlideFixed):
    pass


class OwnFailBreakDrawSlideFixed(OwnFail, GaugeBreakDrawSlideFixed):
    pass


class OwnFailMovedWhileDown(OwnFail, GaugeMovedWhileDown):
    pass


class Pad2Gauge(Scenario):
    """A claimed failure: a 3600 x 1800 x 100 block (BasePad) and a second Pad (rim 1 a rectangle
    3600 x 45 at y = 0, up 300) whose Length is an expression on Gauge; Top attached to Pad's
    front face. Gauge.Length = 0: Pad fails in S1, its Body continues (BasePad is healthy), the
    rule claims it and writes the pass-through."""
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#589"
    FOUND_BY = "review pr579s-r4"
    TIER = "F"
    SIZE = 3600
    REFS = ("front",)
    length, thickness, height = 3600, 45, 300
    edited = False
    frontY = 100

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, self.s(self.frontY), self.s(100)))

    def want(self):
        return BROKEN if self.edited else self.frontFace()

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        m.box(doc, "Gauge", self.s(10, 10, 10), at=self.s(9000, 1000, 0))
        b1 = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, L, self.s(1800)), b1)
        m.pad(b1, base, self.s(100), "BasePad")
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, self.s(100), L, self.s(100) + T), b1, z=self.s(100))
        pad = m.pad(b1, profile, H, "Pad")
        pad.setExpression("Length", "Gauge.Length * %s" % (self.height / 10.0 * self.scale))
        doc.recompute()
        top = b1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(pad, self.names(pad, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(1000), L, self.s(1000) + T), False)

    def breakBase(self, doc):
        doc.Gauge.Length = 0

    def fixBase(self, doc):
        doc.Gauge.Length = self.s(10)

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, self.s(100), L, self.s(100) + T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class Pad2GaugeDrawBreakSlideFixed(Pad2Gauge):
    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakBase(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixBase(doc)


class Pad2GaugeControl(Pad2Gauge):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class Pad2OwnFailDrawBreakSlideFixed(Pad2Gauge):
    """Pad.Length = 0 itself (a claimed failure on integration and on the PR)."""
    steps = ("drawAndBreak", "slideAndFix")

    def build(self, doc):
        super().build(doc)
        doc.Pad.setExpression("Length", None)

    def breakBase(self, doc):
        doc.Pad.Length = 0

    def fixBase(self, doc):
        doc.Pad.Length = self.s(self.height)

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakBase(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixBase(doc)


class GaugeDownReopen(Reopens, GaugeDrawBreakSlideFixed):
    """The document is saved and reopened while Pad1 is down (rim 2 drawn); then the slide and the
    fix. The taken record is saved with the property."""
    steps = ("drawAndBreak", "reopen", "slideAndFix")


class OwnFailDownReopen(Reopens, OwnFailDrawBreakSlideFixed):
    steps = ("drawAndBreak", "reopen", "slideAndFix")


class Parked(Scenario):
    """A reorder parks a reference (ops#127): Body with BasePad (3600 x 1800 x 100), Sk2 attached to
    BasePad's top face and Pad2 (rim 1 a rectangle 3600 x 45 at y = 100, up 300) on it; Top attached
    to Pad2's front face (y = 100). Step 1: rim 2 drawn in Sk2 and Sk2 + Pad2 moved above BasePad
    (Sk2's reference to BasePad is parked, Pad2 the Body's first solid feature, additive, fails).
    Step 2: Sk2 and Pad2 moved back below it, rim 2 slid onto rim 1's place, rim 1 deleted."""
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r4"
    TIER = "F"
    SIZE = 3600
    REFS = ("front",)
    length, thickness, height = 3600, 45, 300
    edited = False
    steps = ("drawAndPark", "unparkAndSlide")

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, self.s(100), self.s(100)))

    def want(self):
        return BROKEN if self.edited else self.frontFace()

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        b = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, L, self.s(1800)), b)
        m.pad(b, base, self.s(100), "BasePad")
        doc.recompute()
        sk2 = b.newObject("Sketcher::SketchObject", "Sk2")
        sk2.AttachmentSupport = [(doc.BasePad, self.names(doc.BasePad, face("plane", normal=(0, 0, 1), through=(0, 0, self.s(100))))[0])]
        sk2.MapMode = "FlatFace"
        sk2.addGeometry(m.rectangle(0, self.s(100), L, self.s(100) + T), False)
        pad = m.pad(b, sk2, H, "Pad")
        doc.recompute()
        top = b.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(pad, self.names(pad, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def drawAndPark(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Sk2.addGeometry(m.rectangle(0, self.s(1000), L, self.s(1000) + T), False)
        doc.Body.reorderObject([doc.Sk2, doc.Pad], None, True)

    def unparkAndSlide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Sk2, 0, self.s(100), L, self.s(100) + T, first=4)
        doc.Sk2.delGeometries([0, 1, 2, 3])
        self.edited = True
        doc.Body.reorderObject([doc.Sk2, doc.Pad], doc.BasePad, True)


class ParkedControl(Parked):
    steps = ("draw", "slide")

    def draw(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Sk2.addGeometry(m.rectangle(0, self.s(1000), L, self.s(1000) + T), False)

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Sk2, 0, self.s(100), L, self.s(100) + T, first=4)
        doc.Sk2.delGeometries([0, 1, 2, 3])
        self.edited = True


class ThroughPad2(Scenario):
    """A reference to a face of the first Pad seen through a claimed-failed second one: Profile
    (rim 1, 3600 x 45 at y = 0), Pad (up 300), Boss (a 100 x 40 boss on Pad's top, up 50, its Length
    an expression on Gauge) and Top attached to the face of Boss's shape that is Pad's front face
    (y = 0). Gauge.Length = 0 fails Boss in S1 (its Body continues: Pad is healthy); the rule claims
    it and writes the pass-through, Pad's shape."""
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r4"
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
        m.box(doc, "Gauge", self.s(10, 10, 10), at=self.s(9000, 1000, 0))
        b1 = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), b1)
        m.pad(b1, profile, H, "Pad")
        doc.recompute()
        bs = m.sketch(doc, "BossSketch", m.rectangle(self.s(1000), self.s(10), self.s(1100), self.s(40)), b1, z=H)
        boss = m.pad(b1, bs, self.s(50), "Boss")
        boss.setExpression("Length", "Gauge.Length * %s" % (5.0 * self.scale))
        doc.recompute()
        top = b1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(boss, self.names(boss, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class ThroughPad2DrawBreakSlideFixed(ThroughPad2):
    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        doc.Gauge.Length = 0

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        doc.Gauge.Length = self.s(10)


class ThroughPad2DrawSlideWhileDown(ThroughPad2):
    steps = ("breakDown", "draw", "slide", "fix")

    def breakDown(self, doc):
        doc.Gauge.Length = 0

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)

    def fix(self, doc):
        doc.Gauge.Length = self.s(10)


class ThroughPad2Control(ThroughPad2):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class GaugeBothFaces(Gauge):
    """Two references into Pad1: Top on the front face (y = 0) and Rear on the back face
    (y = 45, the same rim's other edge). Rim 2 drawn with the failure, then rim 1 deleted and rim 2
    slid onto its place with the fix: both break."""
    REFS = ("front", "rear")
    steps = ("drawAndBreak", "slideAndFix")

    def rearFace(self):
        return face("plane", normal=(0, 1, 0), through=(0, self.s(self.thickness), 0))

    def wantRear(self):
        return BROKEN if self.edited else self.rearFace()

    def build(self, doc):
        super().build(doc)
        rear = doc.Body.newObject("Sketcher::SketchObject", "Rear")
        rear.AttachmentSupport = [(doc.Pad, self.names(doc.Pad, self.rearFace())[0])]
        rear.MapMode = "FlatFace"
        doc.recompute()
        self.ref("rear", rear, "AttachmentSupport", lambda: self.wantRear(), Attached())

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakBase(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixBase(doc)


class GaugeBothFacesControl(GaugeBothFaces):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)
