"""Review pr579s-r2 (container variants of pr564son-r4 (ops#564 round 4): cross-document made-then-failed. Document B: free sketch
Profile (rim 1 at y = 0, an external link to Part feature Anchor). Document A: a SubShapeBinder of
Profile's rim-1 line at y = 0. Round 3's T-R3-1 rule (an included object left touched doesn't hold)
tests `object->getDocument() == _RecomputeEnded`: an object of B included in A's recompute and left
touched (the sketch made its shape and then failed) still holds a record at A's end."""

import os
import shutil
import tempfile

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    BROKEN, Outcome, Scenario, X, edge, expectedNames, _sameEdge, tolerance,
)
from PartDesignTests.Scenarios import models as m


class BoundEdge(Outcome):
    """A SubShapeBinder of an edge: its shape holds the expected edge."""

    def compare(self, scenario, consumer, target, expectation):
        expected = [target.Shape.getElement(n) for n in expectedNames(expectation, target.Shape)]
        got = consumer.Shape.Edges
        if len(got) != len(expected):
            return False, f"{len(got)} edges bound for {len(expected)}"
        tol = tolerance(target.Shape)
        for e in expected:
            if not any(_sameEdge(g, e, tol) for g in got):
                return False, f"no bound edge at {e.CenterOfMass}"
        return True, ""



class XCtr(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r2"
    TIER = "F"
    SIZE = 3600
    REFS = ("binder",)
    length, thickness = 3600, 20
    edited = False
    containerType = "App::Part"

    def lineAtZero(self):
        return edge("line", direction=X, through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.lineAtZero()

    def path(self, doc):
        return os.path.join(self.folder, doc.Name + ".FCStd")

    def anchorEdge(self):
        return Part.makeLine(App.Vector(0, -self.s(3000), 0), App.Vector(self.s(100), -self.s(3000), 0))

    def build(self, doc):
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="NamingScenario"))
        L, T = self.s(self.length, self.thickness)
        B = self.newDocument("B")
        B.saveAs(self.path(B))
        m.feature(B, "Anchor", self.anchorEdge())
        B.recompute()
        profile = m.sketch(B, "Profile", m.rectangle(0, 0, L, T))
        profile.addExternal("Anchor", "Edge1")
        group = B.addObject(self.containerType, "Assy")
        group.addObject(profile)
        comp = B.addObject("Part::Compound", "Comp")
        comp.Links = [group]
        B.recompute()
        B.save()
        doc.saveAs(self.path(doc))
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(comp, tuple(self.names(comp, self.lineAtZero())))]
        doc.recompute()
        self.target = B
        self.ref("binder", binder, "Support", lambda: self.want(), BoundEdge())

    def drawRim2(self, B):
        L, T = self.s(self.length, self.thickness)
        B.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def breakAnchor(self, B):
        B.Anchor.Shape = Part.Vertex(App.Vector(0, -self.s(3000), 0))

    def slideRim2(self, B):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(B.Profile, 0, 0, L, T, first=4)
        B.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class XCtrControlNoFail(XCtr):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(self.target)
        doc.recompute()

    def slide(self, doc):
        self.slideRim2(self.target)
        self.target.recompute()
        doc.recompute()


class XCtrFailARecompute(XCtr):
    """Rim 2 drawn and the anchor broken in B; only A recomputed. Then slide, the anchor made good,
    B then A recomputed."""
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(self.target)
        self.breakAnchor(self.target)
        doc.recompute()

    def slide(self, doc):
        self.slideRim2(self.target)
        self.target.Anchor.Shape = self.anchorEdge()
        self.target.recompute()
        doc.recompute()


class XCtrFailBRecompute(XCtr):
    """B recomputed (not A) in the first step."""
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(self.target)
        self.breakAnchor(self.target)
        self.target.recompute()

    def slide(self, doc):
        self.slideRim2(self.target)
        self.target.Anchor.Shape = self.anchorEdge()
        self.target.recompute()
        doc.recompute()


class XCtrFailStaysFailing(XCtr):
    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(self.target)
        self.breakAnchor(self.target)
        doc.recompute()

    def slide(self, doc):
        self.slideRim2(self.target)
        doc.recompute()


class XFolderFailBRecompute(XCtrFailBRecompute):
    containerType = "App::DocumentObjectGroup"
