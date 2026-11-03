"""Review pr564opus-r3 (ops#564 round 3): the end-of-recompute hold of round 2's R2-2 fix: the
reference's object (closure[0]) left touched keeps the record held past the recompute. A sketch
whose external link is gone builds its shape and then fails (SketchObject::execute()), so it is
made and left touched: the record is kept from before the edit that the made shape already holds.
A rim drawn in that edit and dragged onto the vacated place in the next one then reads as drawn
since (a redraw in place) where it was in the model at the last resolution (FailedPadSiblingSlid's
rule, held_records_r2s.py)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, ExternalCoincides, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class ExternalRim(Scenario):
    """A free sketch Profile: rim 1, a rectangle 3600 x 45 at y = 0 (geometry 0-3), and one
    external line from Anchor (a Part feature holding one edge, far off). A free sketch Top in the
    same plane projects Profile's rim-1 line at y = 0 (its external geometry)."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r3"
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

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def breakAnchor(self, doc):
        doc.Anchor.Shape = Part.Vertex(App.Vector(0, -self.s(3000), 0))

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class ShapedFailSiblingSlid(ExternalRim):
    """Rim 2 drawn at y = 2000 and Anchor's edge gone in one edit: Profile builds rim 1 and rim 2,
    then fails on its external link (touched); recomputed. Then rim 1 deleted and rim 2 dragged
    onto y = 0; recomputed (Profile still failing). Rim 2 was in Profile's shape at the last
    resolution: a move onto the vacated place, a break."""

    steps = ("drawAndBreak", "slide")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakAnchor(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class ShapedFailSiblingSlidFixed(ExternalRim):
    """As ShapedFailSiblingSlid, the external link made good again in the slide's edit (Profile
    recomputes without error there)."""

    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakAnchor(doc)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        doc.Anchor.Shape = self.anchorEdge()


class ShapedSiblingSlidControl(ExternalRim):
    """The control: rim 2 drawn (no failure), recomputed; then rim 1 deleted and rim 2 dragged
    onto y = 0. A break."""

    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class ShapedFailThenSlidTwoSteps(ExternalRim):
    """Anchor's edge gone first (Profile fails, touched); then rim 2 drawn (Profile builds it,
    still failing); then rim 1 deleted and rim 2 dragged onto y = 0. A break."""

    steps = ("breakFirst", "draw", "slide")

    def breakFirst(self, doc):
        self.breakAnchor(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class ShapedFailSiblingSlidThin(ShapedFailSiblingSlid):
    """ShapedFailSiblingSlid with rims 20 thick (under 1 % of the diagonal: rim 2's far line is a
    near second candidate)."""

    thickness = 20


class ShapedSiblingSlidThinControl(ShapedSiblingSlidControl):
    """The control, rims 20 thick."""

    thickness = 20


class ShapedFailSiblingSlidFixedThin(ShapedFailSiblingSlidFixed):
    """ShapedFailSiblingSlidFixed with rims 20 thick (Profile fails in the first edit only)."""

    thickness = 20
