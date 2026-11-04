"""Review pr579-r5 (ops#579 round 5): the transform's base link in onChanged (c4b0d4be99) and the
take's skip (f47f42addc).

ConvertToMultiTransform*: PartDesign_MultiTransform with a standalone Mirrored selected converts it
(Gui/Command.cpp CmdPartDesignMultiTransform): the Tip moves to the solid before the Mirrored, a new
MultiTransform goes in after it, and the command copies the Mirrored's Originals, TransformMode and
BaseFeature onto it, moves the Mirrored into it and empties its Originals. Since c4b0d4be99, setting
the MultiTransform's Originals links its base in onChanged (setBaseProperty), which also reroutes the
next solid, the Mirrored, onto the MultiTransform; the command's next line copies the Mirrored's
BaseFeature, now the MultiTransform itself. The steps are the command's own, as Python.

The model: a 600 x 300 x 300 block centred on the origin, a 100 x 100 x 50 boss on its top at
x 100..200, its mirror in the YZ plane, and a 100 x 100 x 20 cap at the centre after it. Judged by
a sketch outside the Body on the block's front face (y = -150) and the Body's volume.

FrameMovedWhileDown*: the first Pad fails on its own (Length 0) in the edit that moves its profile
sketch's Placement 500 along y (its frame: no new geometry, so the take's skip leaves the record);
then the Pad is fixed. The front face moved with the Pad: the reference follows it to y = 500, as
the control (the move alone) does."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Scenario, Y, face
from PartDesignTests.Scenarios import models as m


class AttachedWithBodyVolume(Attached):
    """Attached, and the Body's volume is the scenario's expected one. A Body member or the Body
    left touched by the recompute (a dependency cycle: "The graph must be a DAG", nothing in it
    recomputes) is loud: broken, not wrong."""

    def check(self, scenario, consumer, target, expectation):
        body = scenario.doc.Body
        stale = [o.Name for o in body.Group + [body] if "Touched" in o.State]
        if stale:
            return "broken", f"still touched after the recompute (a cycle?): {stale}"
        return super().check(scenario, consumer, target, expectation)

    def compare(self, scenario, consumer, target, expectation):
        ok, why = super().compare(scenario, consumer, target, expectation)
        if not ok:
            return ok, why
        want = scenario.bodyVolume()
        body = scenario.doc.Body
        if not body.isValid():
            return False, "Body has an error"
        got = body.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"Body volume {got:.1f}, expected {want:.1f}"
        return True, ""


class ConvertToMultiTransform(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r5"
    TIER = "F"
    SIZE = 600
    REFS = ("front",)
    withCap = True
    convert = True

    def front(self):
        return face("plane", normal=-Y, through=self.s(0, -150, 150))

    def bodyVolume(self):
        L, W, H, b, h, c = self.s(600, 300, 300, 100, 50, 20)
        return L * W * H + 2 * b * b * h + (b * b * c if self.withCap else 0)

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(*self.s(-300, -150, 300, 150)), body)
        m.pad(body, base, self.s(300), "Pad1")
        bossSketch = m.sketch(doc, "BossSketch", m.rectangle(*self.s(100, -50, 200, 50)), body,
                              z=self.s(300))
        boss = m.pad(body, bossSketch, self.s(50), "Boss")
        doc.recompute()
        mirrored = body.newObject("PartDesign::Mirrored", "Mirrored")
        mirrored.Originals = [boss]
        mirrored.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        body.Tip = mirrored
        doc.recompute()
        if self.withCap:
            capSketch = m.sketch(doc, "CapSketch", m.rectangle(*self.s(-50, -50, 50, 50)), body,
                                 z=self.s(300))
            m.pad(body, capSketch, self.s(20), "Cap")
            doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front, AttachedWithBodyVolume())

    def edit(self, doc):
        body, trFeat = doc.Body, doc.Mirrored
        if not self.convert:
            doc.Boss.Length = self.s(50)  # a no-op edit: the control
            return
        # CmdPartDesignMultiTransform::activated, a Transformed selected (Command.cpp)
        oldTip = body.Tip
        prevFeature = doc.Boss  # getPrevSolidFeature(trFeat): the solid before it
        body.Tip = prevFeature  # PartDesign_MoveTip on the previous solid
        feat = body.newObject("PartDesign::MultiTransform", "MultiTransform")
        feat.Originals = trFeat.Originals
        feat.TransformMode = trFeat.TransformMode
        feat.BaseFeature = trFeat.BaseFeature
        feat.Transformations = [trFeat]
        trFeat.Originals = []
        doc.recompute()  # finishFeature: updateActive
        if oldTip != trFeat:
            body.Tip = oldTip  # PartDesign_MoveTip back
        else:
            body.Tip = feat  # the insert point on the MultiTransform (the user's next step)
        doc.recompute()


class ConvertToMultiTransformWithCap(ConvertToMultiTransform):
    """A cap after the Mirrored: the Tip goes back to it after the conversion."""


class ConvertToMultiTransformAtTip(ConvertToMultiTransform):
    """The Mirrored is the Tip: the command leaves the Tip on the boss; then it is set on the
    MultiTransform."""

    withCap = False


class ConvertToMultiTransformControl(ConvertToMultiTransform):
    convert = False


class FrameMovedWhileDown(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:3600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579-r5"
    TIER = "F"
    SIZE = 3600
    REFS = ("front",)
    frontY = 0
    fail = True
    steps = ("moveAndBreak", "fix")

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, self.s(self.frontY), 0))

    def build(self, doc):
        L, T, H = self.s(3600, 45, 300)
        b1 = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), b1)
        m.pad(b1, profile, H, "Pad1")
        doc.recompute()
        top = b1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(doc.Pad1, self.names(doc.Pad1, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", self.frontFace, Attached())

    def moveAndBreak(self, doc):
        doc.Profile.Placement = App.Placement(App.Vector(0, self.s(500), 0), App.Rotation())
        self.frontY = 500
        if self.fail:
            doc.Pad1.Length = 0

    def fix(self, doc):
        doc.Pad1.Length = self.s(300)


class FrameMovedWhileDownOwnFail(FrameMovedWhileDown):
    pass


class FrameMovedWhileDownControl(FrameMovedWhileDown):
    fail = False


class ConvertToMultiTransformAtTipThenEdit(ConvertToMultiTransformAtTip):
    """Converted at the Tip, then the boss is made 80 high: the Body follows."""

    steps = ("edit", "grow")
    grown = False

    def bodyVolume(self):
        L, W, H, b, h = self.s(600, 300, 300, 100, 80 if self.grown else 50)
        return L * W * H + 2 * b * b * h

    def grow(self, doc):
        doc.Boss.Length = self.s(80)
        self.grown = True
