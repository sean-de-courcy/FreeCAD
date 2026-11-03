"""Review pr564opus-r4 (ops#564 round 4): the end of a recompute now takes a record whose reference's
object or element's holder (closure[0] and [1]) the run included and left touched (round 3's
literal rule). Probes: the take from a target held by the roll-back bar with twins, with the closure
changed (a Pad's Profile switched while behind the bar), and with a sketch made then failed on a
redraw in place."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    Attached, BROKEN, Chamfered, ExternalCoincides, Scenario, X, edge,
)
from PartDesignTests.Scenarios import models as m


class R4Base(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r4"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235
    edited = False

    def topEdge(self, y=0):
        return edge("line", direction=X, through=(0, self.s(y), self.s(self.height)))

    def want(self):
        return self.topEdge()

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def poly(self, y):
        L, T = self.s(self.length, self.thickness)
        y = self.s(y)
        return m.polygon([(L, y + T), (L, y), (0, y), (0, y + T)])

    def block(self, y):
        L, T, B = self.s(self.length, self.thickness, 100)
        y = self.s(y)
        return m.rectangle(L - B, y + T, L, y + T + B)

    def chamferOn(self, doc, body, pad):
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.topEdge()))
        chamfer.Size = self.s(5)
        doc.recompute()
        self.ref("chamfer", chamfer, "Base", lambda: self.want(), Chamfered(self.s(5)))


# ---------------------------------------------------------------------------------------------
# twins behind the roll-back bar
# ---------------------------------------------------------------------------------------------


class TwinBar(R4Base):
    """Two equal rims A (y = 0) and B (y = 2000), 3600 x 45, 235 high (Rims), each on a block
    100 x 100, H/2 high, at its far inner corner (Pad0: the same block under each rim, so the
    model keeps its translation symmetry); a Chamfer (5) on A's outer top edge (y = 0). Edits roll
    the Tip back to Pad0 (Rims and the Chamfer behind the bar) first."""

    abstract = True

    def build(self, doc):
        H = self.s(self.height)
        body = m.body(doc)
        blocks = m.sketch(doc, "Blocks", self.block(0) + self.block(2000), body)
        m.pad(body, blocks, H / 2, "Pad0")
        profile = m.sketch(doc, "Profile", self.rect(0) + self.rect(2000), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        self.chamferOn(doc, body, pad)

    def barOn(self, doc):
        doc.Body.Tip = doc.Pad0
        doc.recompute()

    def barOff(self, doc):
        doc.Body.Tip = doc.Chamfer
        doc.recompute()


class TwinBarARedrawnSetBase(TwinBar):
    """Behind the bar: A redrawn in place (new IDs), the Base set again; recompute; the Tip
    forward; recompute. A redraw in place: A's redrawn edge (quiet), or a break; never B's."""

    def edit(self, doc):
        self.barOn(doc)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.poly(0), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        self.barOff(doc)


class TwinBarARedrawnNoSetter(TwinBar):
    """The control: the same without the setter."""

    def edit(self, doc):
        self.barOn(doc)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.poly(0), False)
        doc.recompute()
        self.barOff(doc)


class TwinBarBothRedrawnSetBase(TwinBar):
    """Behind the bar: both rims redrawn in place (B first, then A), the Base set again;
    recompute; the Tip forward; recompute. A's redrawn edge, or a break; never B's."""

    def edit(self, doc):
        self.barOn(doc)
        doc.Profile.delGeometries([0, 1, 2, 3, 4, 5, 6, 7])
        doc.Profile.addGeometry(self.poly(2000), False)
        doc.Profile.addGeometry(self.poly(0), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        self.barOff(doc)


class TwinBarADeletedBSlidSetBase(TwinBar):
    """Behind the bar: A deleted and B dragged onto A's place (IDs kept), the Base set again;
    recompute; the Tip forward; recompute. B was there: break."""

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        self.barOn(doc)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        self.edited = True
        self.barOff(doc)


# ---------------------------------------------------------------------------------------------
# the closure changed behind the bar: the Pad's Profile switched
# ---------------------------------------------------------------------------------------------


class SwitchBar(R4Base):
    """A block Pad0 (100 x 100, H/2) at the rim's far inner corner; rims at y = 0 and 2000 padded
    from sketch Profile (A) (Rims); a Chamfer (5) on rim 1's outer top edge (y = 0). Step 1
    (`away`): a sketch B with the same two rims drawn and the Pad's Profile switched to it: the same
    edge, now B's. Step 2 (`back`) behind the bar: the Tip rolled back to Pad0, A edited, the Profile
    switched back to A, the Base set again, recompute, the Tip forward."""

    abstract = True
    steps = ("away", "back")

    def build(self, doc):
        H = self.s(self.height)
        body = m.body(doc)
        blocks = m.sketch(doc, "Blocks", self.block(0), body)
        m.pad(body, blocks, H / 2, "Pad0")
        profile = m.sketch(doc, "Profile", self.rect(0) + self.rect(2000), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        self.chamferOn(doc, body, pad)

    def away(self, doc):
        b = m.sketch(doc, "B", self.rect(0) + self.rect(2000), doc.Body)
        doc.Rims.Profile = b

    def editA(self, doc):
        pass

    def back(self, doc):
        doc.Body.Tip = doc.Pad0
        doc.recompute()
        self.editA(doc)
        doc.Rims.Profile = doc.Profile
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()


class SwitchBarBackSlid(SwitchBar):
    """In A, rim 1's lines deleted and rim 2 dragged (IDs kept) to y = 0, behind the bar. Rim 2 was
    in A when the reference was made: break."""

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def editA(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class SwitchBarBackRedrawn(SwitchBar):
    """In A, rim 1 redrawn in place (new IDs), behind the bar: the person's edge is the redrawn one
    (a break is loud, not wrong)."""

    def editA(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.poly(0), False)


class SwitchBarBack(SwitchBar):
    """A unchanged: the edge the reference was made on."""


# ---------------------------------------------------------------------------------------------
# a sketch made then failed, with a redraw in place
# ---------------------------------------------------------------------------------------------


class ExternalRimR4(Scenario):
    """As held_records_r3.ExternalRim: a free sketch Profile with rim 1 (3600 x 45 at y = 0) and an
    external line from Anchor; a free sketch Top projects Profile's line at y = 0."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r4"
    TIER = "F"
    SIZE = 3600
    REFS = ("external",)
    length, thickness = 3600, 45
    edited = False

    def lineAtZero(self):
        return edge("line", direction=X, through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.lineAtZero()

    def anchorEdge(self):
        return Part.makeLine(App.Vector(0, -self.s(3000), 0), App.Vector(self.s(100), -self.s(3000), 0))

    def build(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.feature(doc, "Anchor", self.anchorEdge())
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
        profile.addExternal("Anchor", "Edge1")
        doc.recompute()
        top = m.sketch(doc, "Top", [])
        top.addExternal("Profile", self.names(profile, self.lineAtZero())[0])
        doc.recompute()
        self.ref("external", top, "ExternalGeometry", lambda: self.want(), ExternalCoincides())

    def breakAnchor(self, doc):
        doc.Anchor.Shape = Part.Vertex(App.Vector(0, -self.s(3000), 0))

    def fixAnchor(self, doc):
        doc.Anchor.Shape = self.anchorEdge()

    def redraw(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)


class ShapedFailRedrawnInPlace(ExternalRimR4):
    """Rim 1 redrawn in place and Anchor's edge gone in one edit (Profile builds the redrawn rim,
    then fails); recomputed; then Anchor's edge back; recomputed. A redraw in place: the redrawn
    line (quiet) or a break."""

    steps = ("redrawAndBreak", "fix")

    def redrawAndBreak(self, doc):
        self.redraw(doc)
        self.breakAnchor(doc)

    def fix(self, doc):
        self.fixAnchor(doc)


class ShapedFailDrawnThenRedrawSlide(ExternalRimR4):
    """Rim 2 drawn and Anchor's edge gone (Profile built, failed); recomputed; then rim 1 redrawn
    in place, still failing; recomputed; then rim 1's
    redrawn lines deleted and rim 2 dragged onto y = 0 with Anchor fixed; recomputed. Rim 2 was in
    the model at the last resolution: break."""

    steps = ("drawAndBreak", "redrawSet", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakAnchor(doc)

    def redrawSet(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)

    def slideAndFix(self, doc):
        L, T = self.s(self.length, self.thickness)
        count = len(doc.Profile.Geometry)
        # rim 2 is geometry 0-3 now (the redraw appended after it); the redrawn rim 1 the last four
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=0)
        doc.Profile.delGeometries(list(range(count - 4, count)))
        self.fixAnchor(doc)
        self.edited = True


# ---------------------------------------------------------------------------------------------
# the target left touched and not made (a Part extrusion of a sketch made then failed)
# ---------------------------------------------------------------------------------------------


class ExtrusionFail(ExternalRimR4):
    """A free sketch Profile (rim 1, 3600 x 45 at y = 0, and an external line from Anchor), a
    Part Extrusion Ext of it (235 high), and a Part Plane attached (NormalToEdge) to Ext's outer
    top edge (y = 0). Profile failing leaves Ext and the Plane touched and not made."""

    abstract = True
    REFS = ("plane",)
    height = 235

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.s(self.height)))

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        m.feature(doc, "Anchor", self.anchorEdge())
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
        profile.addExternal("Anchor", "Edge1")
        ext = doc.addObject("Part::Extrusion", "Ext")
        ext.Base = profile
        ext.DirMode = "Custom"
        ext.Dir = App.Vector(0, 0, 1)
        ext.LengthFwd = H
        ext.Solid = True
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(ext, self.names(ext, self.topEdge())[0])]
        plane.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("plane", plane, "AttachmentSupport", lambda: self.want(), Attached())

    def setter(self, doc):
        doc.EdgePlane.AttachmentSupport = doc.EdgePlane.AttachmentSupport

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class ExtrusionFailSiblingSlidSetter(ExtrusionFail):
    """Rim 2 drawn at y = 2000 and Anchor's edge gone, the Plane's support set again (a setter):
    Profile builds both rims and fails, Ext not made; recomputed. Then rim 1 deleted and rim 2
    dragged onto y = 0, Anchor fixed; recomputed. Rim 2 was in Profile's shape at the last
    resolution (held_records_r3.ShapedFailSiblingSlid's rule): break."""

    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakAnchor(doc)
        self.setter(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        self.fixAnchor(doc)


class ExtrusionFailRedrawnSetter(ExtrusionFail):
    """Rim 1 redrawn in place and Anchor's edge gone, the support set again; recomputed (Ext not
    made); Anchor fixed; recomputed. A redraw in place: the redrawn edge (quiet) or a break."""

    steps = ("redrawAndBreak", "fix")

    def want(self):
        return self.topEdge()

    def redrawAndBreak(self, doc):
        self.redraw(doc)
        self.breakAnchor(doc)
        self.setter(doc)

    def fix(self, doc):
        self.fixAnchor(doc)


class ExtrusionSiblingSlidControl(ExtrusionFail):
    """The control: rim 2 drawn (no failure), recomputed; rim 1 deleted and rim 2 dragged onto
    y = 0. Break."""

    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)
