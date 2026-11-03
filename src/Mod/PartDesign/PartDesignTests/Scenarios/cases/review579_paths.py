"""Review pr579-r1 (ops#579): paths into a failed input that the PR's judging (S1) doesn't follow
or newly follows.

1. Through a container: a free sketch Profile inside an App::Part (or a folder); a Part::Compound
   of the container; a free sketch Top projecting the compound's rim-1 line at y = 0. The
   compound's link is to the container, whose Group link S1 doesn't read as an input (ruling 5),
   so the compound and Top run on the failed sketch where integration's filter left them out.
2. A Body member failed by S1: Top is a sketch inside a Body projecting the free Profile's line;
   S1 fails it, the Body's rule claims it and purges it (not touched).
3. F5 -> F4: a free sketch outside the Body attached to a failed Pocket's floor (an element made
   by the failed feature: absent from its pass-through)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    BROKEN, Attached, ExternalCoincides, Scenario, X, Z, edge, face,
)
from PartDesignTests.Scenarios.harness import Outcome, expectedNames, _sameEdge, tolerance
from PartDesignTests.Scenarios import models as m


class BoundEdge(Outcome):
    """A SubShapeBinder of an edge: its shape holds the expected edge (xdoc_fail.py's)."""

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


class CtrRim(Scenario):
    """Profile: rim 1, a rectangle 3600 x 45 at y = 0, and one external line from Anchor (a Part
    feature, far off), both inside a container. Comp: a Part::Compound of the container. Top: a
    free sketch projecting Comp's line at y = 0."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r1"
    TIER = "F"
    SIZE = 3600
    REFS = ("external",)
    length, thickness = 3600, 45
    containerType = "App::Part"
    edited = False

    def lineAtZero(self):
        return edge("line", direction=X, through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.lineAtZero()

    def anchorEdge(self):
        return Part.makeLine(App.Vector(0, -self.s(3000), 0), App.Vector(self.s(100), -self.s(3000), 0))

    def build(self, doc):
        L, T = self.s(self.length, self.thickness)
        group = doc.addObject(self.containerType, "Assy")
        anchor = m.feature(doc, "Anchor", self.anchorEdge())
        group.addObject(anchor)
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
        group.addObject(profile)
        profile.addExternal("Anchor", "Edge1")
        doc.recompute()
        comp = doc.addObject("Part::Compound", "Comp")
        comp.Links = [group]
        doc.recompute()
        top = m.sketch(doc, "Top", [])
        top.addExternal("Comp", self.names(comp, self.lineAtZero())[0])
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


class CtrFailSiblingSlid(CtrRim):
    """Rim 2 drawn and Anchor broken (Profile made, then failed); then rim 1 deleted and rim 2
    dragged onto y = 0 (still failing). A break."""

    steps = ("drawAndBreak", "slide")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        self.breakAnchor(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class CtrFailSiblingSlidFixed(CtrFailSiblingSlid):
    """As CtrFailSiblingSlid, Anchor made good again in the slide's edit."""

    steps = ("drawAndBreak", "slideAndFix")

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        doc.Anchor.Shape = self.anchorEdge()


class CtrFailThenSlidTwoSteps(CtrRim):
    """Anchor broken first; then rim 2 drawn; then rim 1 deleted and rim 2 dragged onto y = 0."""

    steps = ("breakFirst", "draw", "slide")

    def breakFirst(self, doc):
        self.breakAnchor(doc)

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class CtrSiblingSlidControl(CtrRim):
    """The control: no failure."""

    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)


class FolderFailSiblingSlid(CtrFailSiblingSlid):
    containerType = "App::DocumentObjectGroup"


class FolderFailSiblingSlidFixed(CtrFailSiblingSlidFixed):
    containerType = "App::DocumentObjectGroup"


class BodyTopRim(CtrRim):
    """As held_records_r3's ExternalRim (Profile free, Anchor free), Top a SubShapeBinder inside a
    Body binding Profile's line at y = 0 (a Body member failed by S1 is claimed and purged)."""

    abstract = True

    def build(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.feature(doc, "Anchor", self.anchorEdge())
        doc.recompute()
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
        profile.addExternal("Anchor", "Edge1")
        doc.recompute()
        body = m.body(doc)
        binder = body.newObject("PartDesign::SubShapeBinder", "Top")
        binder.Support = [(profile, tuple(self.names(profile, self.lineAtZero())))]
        doc.recompute()
        self.ref("external", binder, "Support", lambda: self.want(), BoundEdge())


class BodyTopFailSiblingSlid(BodyTopRim, CtrFailSiblingSlid):
    pass


class BodyTopFailSiblingSlidFixed(BodyTopRim, CtrFailSiblingSlidFixed):
    pass


class BodyTopFailThenSlidTwoSteps(BodyTopRim, CtrFailThenSlidTwoSteps):
    pass


class OutsideOnFailedPocket(Scenario):
    """A Body: a 600 x 300 pad 300 high; a pocket 100 deep from a circle r 50 drawn at z = 300.
    A free sketch outside the Body is attached to the pocket's floor (z = 200). The pocket fails
    (length 0); then it is made good (the floor at z = 200 again)."""

    area = "attachment"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("floor",)
    steps = ("failAndTaller", "fix")
    failed = False

    def floor(self):
        return face("plane", normal=Z, through=(0, 0, self.s(200)))

    def want(self):
        return BROKEN if self.failed else self.floor()

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300))
        hole = m.sketch(doc, "Hole", [m.circle(*self.s(300, 150, 50))], body, z=self.s(300))
        m.pocket(body, hole, self.s(100))
        doc.recompute()
        pocket = doc.Pocket
        top = m.sketch(doc, "Outside", [])
        top.AttachmentSupport = [(pocket, self.names(pocket, self.floor())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("floor", top, "AttachmentSupport", lambda: self.want(), Attached())

    def failAndTaller(self, doc):
        doc.Pocket.Length = 0
        self.failed = True

    def fix(self, doc):
        doc.Pocket.Length = self.s(100)
        self.failed = False


class CtrBoxFails(Scenario):
    """An App::Part holding a Part::Box 600 x 300 x 300; Comp, a Part::Compound of the App::Part;
    a free sketch attached to Comp's top face (z = 300). The box fails (Length 0) and keeps its
    old shape: Comp reads a failed input through the container, so the sketch must break, loudly
    (decision 250 (1): the set is upstream's filtered in-list)."""

    area = "attachment"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("top",)
    failed = False

    def top(self):
        return face("plane", normal=Z, through=(0, 0, self.s(300)))

    def want(self):
        return BROKEN if self.failed else self.top()

    def build(self, doc):
        group = doc.addObject("App::Part", "Assy")
        box = m.box(doc, "Box", self.s(600, 300, 300))
        group.addObject(box)
        comp = doc.addObject("Part::Compound", "Comp")
        comp.Links = [group]
        doc.recompute()
        sk = m.sketch(doc, "OnTop", [])
        sk.AttachmentSupport = [(comp, self.names(comp, self.top())[0])]
        sk.MapMode = "FlatFace"
        doc.recompute()
        self.ref("top", sk, "AttachmentSupport", lambda: self.want(), Attached())

    def edit(self, doc):
        doc.Box.Length = 0
        self.failed = True
