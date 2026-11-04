"""Review pr579-r2 (ops#579 round 2, decision 253): readers of a failed object through a chain,
a container, a subname path or a Link, at the switch point where the failed sketch made its
shape (rim 2 drawn) and then failed, and is made good in the edit that slides rim 2 onto rim 1's
vacated place.

Shared model (held_records_r3's ExternalRim): a free sketch Profile, rim 1 a rectangle 3600 x 45
at y = 0, and one external line from Anchor (a Part feature far off). Step 1: rim 2 drawn at
y = 2000 and Anchor broken (Profile builds both rims, then fails). Step 2: rim 1 deleted, rim 2
dragged onto y = 0 (its lines keep their geometry IDs), and (Fixed) Anchor made good. Rim 2 was in
Profile's shape before the slide: a move onto the vacated place, so every reference to rim 1's
line breaks."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    BROKEN, Attached, Z, face, ExternalCoincides, Outcome, Scenario, X, edge, expectedNames, _sameEdge,
    tolerance,
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


class Rim(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r2"
    TIER = "F"
    SIZE = 3600
    REFS = ("ref",)
    length, thickness = 3600, 45
    edited = False
    fix = False
    steps = ("drawAndBreak", "slide")

    def lineAtZero(self):
        return edge("line", direction=X, through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.lineAtZero()

    def anchorEdge(self):
        return Part.makeLine(App.Vector(0, -self.s(3000), 0),
                             App.Vector(self.s(100), -self.s(3000), 0))

    def makeProfile(self, doc):
        L, T = self.s(self.length, self.thickness)
        anchor = m.feature(doc, "Anchor", self.anchorEdge())
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
        profile.addExternal("Anchor", "Edge1")
        doc.recompute()
        return anchor, profile

    def projectLine(self, doc, target):
        """Top: a free sketch projecting target's line at y = 0."""
        top = m.sketch(doc, "Top", [])
        top.addExternal(target.Name, self.names(target, self.lineAtZero())[0])
        doc.recompute()
        self.ref("ref", top, "ExternalGeometry", lambda: self.want(), ExternalCoincides())

    def setter(self, doc):
        pass

    def drawAndBreak(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)
        doc.Anchor.Shape = Part.Vertex(App.Vector(0, -self.s(3000), 0))
        self.setter(doc)

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        if self.fix:
            doc.Anchor.Shape = self.anchorEdge()
        self.edited = True


class ChainFailSiblingSlid(Rim):
    """No container: Comp a Part::Compound of Profile itself (a direct dependant, round 1's rule),
    Top projects Comp's line at y = 0. Profile still failing in the slide."""

    def build(self, doc):
        _, profile = self.makeProfile(doc)
        comp = doc.addObject("Part::Compound", "Comp")
        comp.Links = [profile]
        doc.recompute()
        self.projectLine(doc, comp)


class ChainFailSiblingSlidFixed(ChainFailSiblingSlid):
    """As ChainFailSiblingSlid, Anchor made good in the slide's edit."""

    fix = True


class ChainSiblingSlidControl(ChainFailSiblingSlid):
    """The control: Anchor never broken."""

    def drawAndBreak(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)


class CtrPlane(Rim):
    """Profile and Anchor in an App::Part Assy; Comp a Part::Compound of Assy; a Part Plane
    attached NormalToEdge to Comp's line at y = 0 (a setter can be applied to its support)."""

    abstract = True

    def build(self, doc):
        group = doc.addObject("App::Part", "Assy")
        anchor, profile = self.makeProfile(doc)
        group.addObject(anchor)
        group.addObject(profile)
        comp = doc.addObject("Part::Compound", "Comp")
        comp.Links = [group]
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(comp, self.names(comp, self.lineAtZero())[0])]
        plane.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("ref", plane, "AttachmentSupport", lambda: self.want(), Attached())


class CtrPlaneFailSiblingSlidFixed(CtrPlane):
    """Fixed in the slide, no setter."""

    fix = True


class CtrPlaneFailSiblingSlidFixedSetter(CtrPlane):
    """Fixed in the slide; the Plane's support set again in the break's edit (a setter)."""

    fix = True

    def setter(self, doc):
        doc.EdgePlane.AttachmentSupport = doc.EdgePlane.AttachmentSupport


class LinkCtr(Rim):
    """Profile and Anchor in an App::Part Assy; Lnk an App::Link to Assy; Comp a Part::Compound of
    Lnk; Top projects Comp's line at y = 0."""

    abstract = True

    def build(self, doc):
        group = doc.addObject("App::Part", "Assy")
        anchor, profile = self.makeProfile(doc)
        group.addObject(anchor)
        group.addObject(profile)
        doc.recompute()
        link = doc.addObject("App::Link", "Lnk")
        link.LinkedObject = group
        comp = doc.addObject("Part::Compound", "Comp")
        comp.Links = [link]
        doc.recompute()
        self.projectLine(doc, comp)


class LinkCtrFailSiblingSlid(LinkCtr):
    pass


class LinkCtrFailSiblingSlidFixed(LinkCtr):
    fix = True


class NestedCtr(Rim):
    """Profile and Anchor in an App::Part Inner inside an App::Part Outer; Comp a Part::Compound
    of Outer; Top projects Comp's line at y = 0."""

    abstract = True

    def build(self, doc):
        outer = doc.addObject("App::Part", "Outer")
        inner = doc.addObject("App::Part", "Inner")
        outer.addObject(inner)
        anchor, profile = self.makeProfile(doc)
        inner.addObject(anchor)
        inner.addObject(profile)
        comp = doc.addObject("Part::Compound", "Comp")
        comp.Links = [outer]
        doc.recompute()
        self.projectLine(doc, comp)


class NestedCtrFailSiblingSlid(NestedCtr):
    pass


class BodyPocketBesideFailedMember(Scenario):
    """An App::Part Lib holds Ref (a Part::Box 100 cubed, far off) and Spare (a Part::Box
    600 x 300 x 300 that nothing reads). A Body: a 600 x 300 pad 300 high; a pocket 100 deep from
    a circle r 50 drawn at z = 300 in sketch Hole, which also projects Ref's line from LibBinder,
    a SubShapeBinder in the Body of the whole of Lib (Support (Lib, ())). A free sketch outside the Body is attached to the pocket's
    floor (z = 200); a Body sketch is attached to the pad's top (z = 300). Edit: Spare fails
    (Length 0, keeps its old shape): nothing the model reads changed; then Spare is made good."""

    area = "attachment"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r2"
    TIER = "F"
    SIZE = 600
    REFS = ("floor", "top")
    steps = ("breakSpare", "fixSpare")

    def floor(self):
        return face("plane", normal=Z, through=(0, 0, self.s(200)))

    def top(self):
        return face("plane", normal=Z, through=(0, 0, self.s(300)))

    def build(self, doc):
        lib = doc.addObject("App::Part", "Lib")
        ref = m.box(doc, "Ref", self.s(100, 100, 100), at=(0, -self.s(3000), 0))
        lib.addObject(ref)
        spare = m.box(doc, "Spare", self.s(600, 300, 300), at=(0, -self.s(5000), 0))
        lib.addObject(spare)
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300))
        hole = m.sketch(doc, "Hole", [m.circle(*self.s(300, 150, 50))], body, z=self.s(300))
        m.pocket(body, hole, self.s(100))
        doc.recompute()
        binder = body.newObject("PartDesign::SubShapeBinder", "LibBinder")
        binder.Support = [(lib, ())]
        doc.recompute()
        lineName = self.names(binder, edge("line", direction=X, through=(0, -self.s(3000), 0)))[0]
        hole.addExternal("LibBinder", lineName)
        doc.recompute()
        out = m.sketch(doc, "Outside", [])
        out.AttachmentSupport = [(doc.Pocket, self.names(doc.Pocket, self.floor())[0])]
        out.MapMode = "FlatFace"
        onTop = body.newObject("Sketcher::SketchObject", "OnTop")
        onTop.AttachmentSupport = [(doc.Pocket, self.names(doc.Pocket, self.top())[0])]
        onTop.MapMode = "FlatFace"
        doc.recompute()
        self.ref("floor", out, "AttachmentSupport", self.floor, Attached())
        self.ref("top", onTop, "AttachmentSupport", self.top, Attached())

    def breakSpare(self, doc):
        doc.Spare.Length = 0

    def fixSpare(self, doc):
        doc.Spare.Length = self.s(600)

