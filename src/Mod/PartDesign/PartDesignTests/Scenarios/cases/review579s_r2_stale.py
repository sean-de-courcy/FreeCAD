"""Review pr579s-r2: a record kept stale across a failed intermediate.

A free sketch Profile (rim 1, a rectangle 3600 x 45 at y = 0, and one external line from Anchor) is
the input; Comp is a Part::Compound of it (directly, or of an App::Part holding it); Top is a free
sketch projecting Comp's line at y = 0. Step 1 draws rim 2 and breaks Anchor (Profile fails). Step 2
touches Comp only (Profile is not re-run: no filter on integration, so Comp and Top run there and
Top's record is taken with rim 2 in the model; on the PR Comp fails again and does not run). Step 3
deletes rim 1, slides rim 2 onto y = 0 and makes Anchor good: a break."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, ExternalCoincides, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class StaleBase(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r2"
    TIER = "F"
    SIZE = 3600
    REFS = ("external",)
    length, thickness = 3600, 45
    container = None  # None: Comp links Profile directly; else a container type
    edited = False
    fix = True

    def lineAtZero(self):
        return edge("line", direction=X, through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.lineAtZero()

    def anchorEdge(self):
        return Part.makeLine(App.Vector(0, -self.s(3000), 0), App.Vector(self.s(100), -self.s(3000), 0))

    def build(self, doc):
        L, T = self.s(self.length, self.thickness)
        anchor = m.feature(doc, "Anchor", self.anchorEdge())
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
        profile.addExternal("Anchor", "Edge1")
        comp = doc.addObject("Part::Compound", "Comp")
        if self.container:
            group = doc.addObject(self.container, "Assy")
            group.addObject(profile)
            comp.Links = [group]
        else:
            comp.Links = [profile]
        doc.recompute()
        top = m.sketch(doc, "Top", [])
        top.addExternal("Comp", self.names(comp, self.lineAtZero())[0])
        doc.recompute()
        self.ref("external", top, "ExternalGeometry", lambda: self.want(), ExternalCoincides())

    def drawAndBreak(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)
        doc.Anchor.Shape = Part.Vertex(App.Vector(0, -self.s(3000), 0))

    def touchComp(self, doc):
        doc.Comp.touch()

    def slideAndFix(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True
        if self.fix:
            doc.Anchor.Shape = self.anchorEdge()


class DirectCompTouchSlidFixed(StaleBase):
    """Comp a Part::Compound of Profile itself."""
    steps = ("drawAndBreak", "touchComp", "slideAndFix")


class CtrCompTouchSlidFixed(StaleBase):
    """Comp a Part::Compound of an App::Part holding Profile."""
    container = "App::Part"
    steps = ("drawAndBreak", "touchComp", "slideAndFix")


class FolderCompTouchSlidFixed(StaleBase):
    container = "App::DocumentObjectGroup"
    steps = ("drawAndBreak", "touchComp", "slideAndFix")


class DirectCompSlidFixed(StaleBase):
    """No touch step (debt shape: wrong on both if the record is stale)."""
    steps = ("drawAndBreak", "slideAndFix")


class DirectCompTouchSlidStill(StaleBase):
    """The slide without the fix: Profile still fails."""
    fix = False
    steps = ("drawAndBreak", "touchComp", "slideAndFix")


class DirectCompNoFailControl(StaleBase):
    """Control: no failure; Comp touched between."""
    steps = ("drawOnly", "touchComp", "slideAndFix")

    def drawOnly(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)


class DirectCompResolveTopSlidFixed(StaleBase):
    """Diagnostic: as DirectCompSlidFixed with Top run alone (a resolution) between the break and
    the slide. Right here and wrong without the step: the record is the one not refreshed."""
    steps = ("drawAndBreak", "resolveTop", "slideAndFix")

    def resolveTop(self, doc):
        doc.Top.recompute()


class CtrResolveTopSlidFixed(StaleBase):
    container = "App::Part"
    steps = ("drawAndBreak", "resolveTop", "slideAndFix")

    def resolveTop(self, doc):
        doc.Top.recompute()
