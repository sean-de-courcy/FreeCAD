"""Review pr590s-r1 (ops#590, fix/590-transform-base f6955552): consumers that follow a transform
into and out of the Body's chain. A 600 x 300 x 300 block centred on the origin (z 0..300), boss A
(x -250..-150, y -50..50, z 300..350) and a Mirrored of A about YZ (copy at x 150..250), a consumer
after it. Edits: the pattern converted to a MultiTransform (the command's steps), A grown to 80 high,
or the pattern's Originals emptied (the copy is gone, A stays)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Extruded,
    Filleted,
    Scenario,
    X,
    Y,
    Z,
    edge,
    face,
)
from PartDesignTests.Scenarios import models as m


class P590(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#590"
    FOUND_BY = "review pr590s-r1"
    TIER = "F"
    SIZE = 600
    bossHeight = 50

    @property
    def top(self):
        return 300 + self.bossHeight

    def gone(self, predicate):
        """The element before the edit, BROKEN after it."""
        return lambda: BROKEN if self.stepName == "edit" else predicate()

    def copyTopEdge(self):
        return edge("line", direction=Y, through=self.s(250, 0, self.top))

    def origTopEdge(self):
        return edge("line", direction=Y, through=self.s(-250, 0, self.top))

    def copyTopFace(self):
        return face("plane", normal=Z, contains=self.s(200, 0, self.top))

    def boss(self, doc, body):
        base = m.sketch(doc, "Base", m.rectangle(*self.s(-300, -150, 300, 150)), body)
        m.pad(body, base, self.s(300), "Pad1")
        sk = m.sketch(doc, "BossAS", m.rectangle(*self.s(-250, -50, -150, 50)), body, z=self.s(300))
        m.pad(body, sk, self.s(50), "BossA")

    def mirrored(self, doc, body):
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.Originals = [doc.BossA]
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        body.Tip = mir
        doc.recompute()
        return mir

    def convert(self, doc):
        body, trFeat = doc.Body, doc.Mirrored
        oldTip = body.Tip
        body.Tip = doc.BossA
        feat = body.newObject("PartDesign::MultiTransform", "MultiTransform")
        feat.Originals = trFeat.Originals
        feat.TransformMode = trFeat.TransformMode
        feat.BaseFeature = trFeat.BaseFeature
        feat.Transformations = [trFeat]
        trFeat.Originals = []
        doc.recompute()
        body.Tip = oldTip

    def grow(self, doc):
        doc.BossA.Length = self.s(80)
        self.bossHeight = 80

    def build(self, doc):
        body = m.body(doc)
        self.boss(doc, body)
        mir = self.mirrored(doc, body)
        self.consumer(doc, body, mir)


class FilletCopyConvertGrow(P590):
    """A fillet (5) of the copy's top outer edge (x 250), through the pattern; the pattern is
    converted, then A grown."""

    REFS = ("fillet_copy",)
    steps = ("convert", "grow")

    def consumer(self, doc, body, mir):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (mir, self.names(mir, self.copyTopEdge()))
        fillet.Radius = self.s(5)
        body.Tip = fillet
        doc.recompute()
        self.ref("fillet_copy", fillet, "Base", self.copyTopEdge, Filleted(self.s(5)))


class FilletOrigConvertGrow(P590):
    """The same on the original boss's top outer edge (x -250), through the pattern."""

    REFS = ("fillet_orig",)
    steps = ("convert", "grow")

    def consumer(self, doc, body, mir):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (mir, self.names(mir, self.origTopEdge()))
        fillet.Radius = self.s(5)
        body.Tip = fillet
        doc.recompute()
        self.ref("fillet_orig", fillet, "Base", self.origTopEdge, Filleted(self.s(5)))


class FilletCopyEmptied(P590):
    """The copy's top outer edge filleted; the pattern's Originals emptied: the copy is gone, a
    reference to it breaks."""

    REFS = ("fillet_copy",)

    def consumer(self, doc, body, mir):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (mir, self.names(mir, self.copyTopEdge()))
        fillet.Radius = self.s(5)
        body.Tip = fillet
        doc.recompute()
        self.ref("fillet_copy", fillet, "Base", self.gone(self.copyTopEdge), Filleted(self.s(5)))

    def edit(self, doc):
        doc.Mirrored.Originals = []


class FilletOrigEmptied(P590):
    """The original's top outer edge filleted through the pattern; the pattern's Originals
    emptied: A stays, the edge is still there."""

    REFS = ("fillet_orig",)

    def consumer(self, doc, body, mir):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (mir, self.names(mir, self.origTopEdge()))
        fillet.Radius = self.s(5)
        body.Tip = fillet
        doc.recompute()
        self.ref("fillet_orig", fillet, "Base", self.origTopEdge, Filleted(self.s(5)))

    def edit(self, doc):
        doc.Mirrored.Originals = []


class FilletOrigDeleteA(P590):
    """The same, A deleted (the pattern's only original): the edge is gone."""

    REFS = ("fillet_orig",)

    def consumer(self, doc, body, mir):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (mir, self.names(mir, self.origTopEdge()))
        fillet.Radius = self.s(5)
        body.Tip = fillet
        doc.recompute()
        self.ref("fillet_orig", fillet, "Base", self.gone(self.origTopEdge), Filleted(self.s(5)))

    def edit(self, doc):
        doc.Body.removeObject(doc.BossA)
        doc.removeObject("BossA")


class SketchOnCopyConvertGrow(P590):
    """A sketch in the Body attached to the copy's top face (through the pattern); the pattern is
    converted, then A grown. The pattern is then a step with the stale shape it had (its execute()
    returns at once): the face to hold is the MultiTransform's."""

    REFS = ("sketch_copy",)
    steps = ("convert", "grow")

    def copyFaceAnyHeight(self):
        s = self.s(1)
        return face(
            "plane",
            normal=Z,
            where=lambda f: abs(f.CenterOfMass.x - 200 * s) < 1e-3 * s and f.CenterOfMass.z > 300 * s + 1e-3 * s,
        )

    def onMulti(self):
        return "MultiTransform" if self.stepName else None

    def consumer(self, doc, body, mir):
        sk = body.newObject("Sketcher::SketchObject", "OnCopy")
        sk.AttachmentSupport = [(mir, self.names(mir, self.copyTopFace())[0])]
        sk.MapMode = "FlatFace"
        doc.recompute()
        self.ref(
            "sketch_copy", sk, "AttachmentSupport", self.copyFaceAnyHeight, Attached(), self.onMulti
        )


class PadOnCopyFaceConvertGrow(P590):
    """A Pad of the copy's top face (Profile = the face of the pattern), 30 long; the pattern is
    converted, then A grown."""

    REFS = ("pad_copy_face",)
    steps = ("convert", "grow")

    def consumer(self, doc, body, mir):
        pad = body.newObject("PartDesign::Pad", "FacePad")
        pad.Profile = (mir, self.names(mir, self.copyTopFace()))
        pad.Length = self.s(30)
        body.Tip = pad
        doc.recompute()
        self.ref("pad_copy_face", pad, "Profile", self.copyTopFace, Extruded(self.s(30), Z))


class PadOnCopyFaceEmptied(P590):
    """The same; the pattern's Originals emptied: the copy's face is gone."""

    REFS = ("pad_copy_face",)

    def consumer(self, doc, body, mir):
        pad = body.newObject("PartDesign::Pad", "FacePad")
        pad.Profile = (mir, self.names(mir, self.copyTopFace()))
        pad.Length = self.s(30)
        body.Tip = pad
        doc.recompute()
        self.ref("pad_copy_face", pad, "Profile", self.gone(self.copyTopFace), Extruded(self.s(30), Z))

    def edit(self, doc):
        doc.Mirrored.Originals = []


class BodyVolume(Attached):
    """Attached, and the Body's volume is the scenario's expected one; a Body member in error or
    left touched is loud: broken."""

    def check(self, scenario, consumer, target, expectation):
        body = scenario.doc.Body
        # A transform of nothing is red, as Onshape's is (ops#640): the scenario names it
        red = set(scenario.redTransforms())
        bad = [
            o.Name
            for o in body.Group + [body]
            if o.Name not in red
            and ("Touched" in o.State or (o.isDerivedFrom("PartDesign::Feature") and not o.isValid()))
        ]
        if bad:
            return "broken", f"in error or touched after the recompute: {bad}"
        notRed = sorted(n for n in red if scenario.doc.getObject(n).isValid())
        if notRed:
            return "wrong", f"valid, expected red (a transform of nothing, ops#640): {notRed}"
        return super().check(scenario, consumer, target, expectation)

    def compare(self, scenario, consumer, target, expectation):
        ok, why = super().compare(scenario, consumer, target, expectation)
        if not ok:
            return ok, why
        want = scenario.bodyVolume()
        got = scenario.doc.Body.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"Body volume {got:.1f}, expected {want:.1f}"
        return True, ""


class PatternOfNothing(P590):
    """The pattern's only original taken out (Originals emptied) or deleted: a pattern of nothing
    is red ('Select features to mirror.', Onshape's rule, ops#640) and passes the solid before it
    through. Judged by a sketch outside the Body on the block's front face and the Body's volume.
    `capped`: a 100 x 80 x 20 cap after the pattern."""

    abstract = True
    REFS = ("front",)
    capped = False
    bossGone = False  # A deleted (else only taken out of the pattern's Originals)

    def front(self):
        return face("plane", normal=-Y, through=self.s(0, -150, 150))

    def redTransforms(self):
        return ("Mirrored",) if self.stepName == "edit" else ()

    def bodyVolume(self):
        L, W, H, b, h, cw, ch = self.s(600, 300, 300, 100, self.bossHeight, 80, 20)
        boss = 2 * b * b * h  # A and its copy
        if self.stepName == "edit":
            boss = 0 if self.bossGone else b * b * h
        cap = b * cw * ch if self.capped else 0
        return L * W * H + boss + cap

    def consumer(self, doc, body, mir):
        if self.capped:
            sk = m.sketch(doc, "CapS", m.rectangle(*self.s(-50, 60, 50, 140)), body, z=self.s(300))
            m.pad(body, sk, self.s(20), "Cap")
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front, BodyVolume())

    def edit(self, doc):
        if self.bossGone:
            doc.Body.removeObject(doc.BossA)
            doc.removeObject("BossA")
        else:
            doc.Mirrored.Originals = []


class PatternOfNothingEmptiedLast(PatternOfNothing):
    """Last in the Body, Originals emptied."""


class PatternOfNothingDeletedLast(PatternOfNothing):
    """Last in the Body, its original deleted."""

    bossGone = True


class PatternOfNothingEmptiedCap(PatternOfNothing):
    """A cap after it, Originals emptied."""

    capped = True


class PatternOfNothingDeletedCap(PatternOfNothing):
    """A cap after it, its original deleted."""

    capped = True
    bossGone = True
