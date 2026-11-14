"""Review pr590-r1 (ops#590, f695555287): a transform leaves its Body's chain when its Originals are
emptied or its mode set to Features with none, and joins it again when they are set back.

The model (SIZE 600): a 600 x 300 x 100 block centred on the origin in x and y, a cylindrical boss A
(radius 40, 50 high) on its top at x -200, y 0, a transform of A after it, and a fillet (radius 10)
of the top circular edge of A's copy at x 200 (centre (200, 0, 150)) after the transform. The
fillet's Base is judged: the copy's top edge on the transform, and the fillet built on the
transform, the Body holding A's copies and nothing in error.

SwapRoundTrip: a LinearPattern of A along X (400, 3: copies at x 0 and 200). The task panel's
Originals field takes A out and puts it back (each write recomputes): Originals = [], recompute,
Originals = [A].

ModeRoundTrip: a whole-shape Mirrored (YZ) of the block and A (copy at x 200). The task panel's mode
buttons: Features (no Originals listed), recompute, Whole shape.

UndoEmpty: the LinearPattern; Originals = [] in a transaction, recompute, undo.

The expected result is the same edge after each edit: each edit leaves the model as it was."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Filleted, Scenario, edge
from PartDesignTests.Scenarios import models as m


class FilletedOnTransform(Filleted):
    """Filleted, on the transform (BaseFeature), the Body valid and holding A and its copies."""

    def check(self, scenario, consumer, target, expectation):
        body = scenario.doc.Body
        bad = [o.Name for o in body.Group + [body] if "Touched" in o.State or (
            o.isDerivedFrom("PartDesign::Feature") and not o.isValid())]
        if bad:
            return "broken", f"in error or touched after the recompute: {bad}"
        return super().check(scenario, consumer, target, expectation)

    def compare(self, scenario, consumer, target, expectation):
        base = consumer.BaseFeature
        if base is None or base.Name != scenario.transformName:
            return False, f"fillet built on {base.Name if base else None}, not the transform"
        want = scenario.patternVolume()
        got = base.Shape.Volume
        if abs(got - want) > 1e-6 * want:
            return False, f"transform volume {got:.1f}, expected {want:.1f}"
        return super().compare(scenario, consumer, target, expectation)


class R590(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#590"
    FOUND_BY = "review pr590-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("copy_edge",)
    transformName = "LP"
    copies = 3

    def copyEdge(self):
        return edge("circle", center=self.s(200, 0, 150), radius=self.s(40))

    def patternVolume(self):
        import math
        L, W, H, r, h = self.s(600, 300, 100, 40, 50)
        return L * W * H + self.copies * math.pi * r * r * h

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(*self.s(-300, -150, 300, 150)), body)
        m.pad(body, base, self.s(100), "Pad1")
        bossS = m.sketch(doc, "BossAS", [m.circle(*self.s(-200, 0, 40))], body, z=self.s(100))
        m.pad(body, bossS, self.s(50), "BossA")
        doc.recompute()
        tr = self.transform(doc, body)
        body.Tip = tr
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (tr, self.names(tr, self.copyEdge()))
        fillet.Radius = self.s(10)
        self.ref("copy_edge", fillet, "Base", self.copyEdge, FilletedOnTransform(self.s(10)))

    def transform(self, doc, body):
        lp = body.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [doc.BossA]
        lp.Direction = (m.originFeature(body, "X_Axis"), [""])
        lp.Length = self.s(400)
        lp.Occurrences = 3
        return lp


class SwapRoundTrip(R590):
    """Originals = [], recompute, Originals = [A] (the task panel's field, each write recomputed)."""

    def edit(self, doc):
        doc.LP.Originals = []
        doc.recompute()
        doc.LP.Originals = [doc.BossA]


class ModeRoundTrip(R590):
    """A whole-shape Mirrored: mode Features with no Originals, recompute, Whole shape."""

    transformName = "Mirrored"
    copies = 2

    def transform(self, doc, body):
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.TransformMode = "Whole shape"
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        return mir

    def edit(self, doc):
        doc.Mirrored.TransformMode = "Features"
        doc.recompute()
        doc.Mirrored.TransformMode = "Whole shape"


class UndoEmpty(R590):
    """Originals = [] in a transaction, recompute, undo."""

    def edit(self, doc):
        doc.UndoMode = 1
        doc.openTransaction("empty")
        doc.LP.Originals = []
        doc.commitTransaction()
        doc.recompute()
        doc.undo()


class ConvertFillet(R590):
    """A Mirrored (YZ) of A with the fillet on its copy's top edge, converted to a MultiTransform
    as PartDesign_MultiTransform does it (the Tip back to A, the MultiTransform added, its
    Originals, mode and BaseFeature copied, the Mirrored made its step, its Originals emptied, a
    recompute, the Tip back to the fillet), then A made 80 high: the fillet's edge at z 180."""

    transformName = "MultiTransform"
    copies = 2
    steps = ("convert", "grow")
    bossTop = 150
    whole = False

    def copyEdge(self):
        return edge("circle", center=self.s(200, 0, self.bossTop), radius=self.s(40))

    def patternVolume(self):
        import math
        L, W, H, r, h = self.s(600, 300, 100, 40, self.bossTop - 100)
        return L * W * H + self.copies * math.pi * r * r * h

    def transform(self, doc, body):
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        if self.whole:
            mir.TransformMode = "Whole shape"
        else:
            mir.Originals = [doc.BossA]
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        return mir

    def build(self, doc):
        self.transformName = "Mirrored"
        super().build(doc)

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
        self.transformName = "MultiTransform"

    def grow(self, doc):
        doc.BossA.Length = self.s(80)
        self.bossTop = 180


class ConvertFilletWhole(ConvertFillet):
    """ConvertFillet with a whole-shape Mirrored."""

    whole = True


class TwoTransformsFillet(R590):
    """A at x -200, y -60 with the fillet on its own top edge; from Python, the Tip on A, a
    LinearPattern of A (X, 400, 3) and a Mirrored of A (XZ) are added before the fillet, the Tip
    back to the fillet, one recompute: the fillet keeps A's own edge, on the Mirrored."""

    transformName = "Mirrored"
    copies = 4

    def copyEdge(self):
        return edge("circle", center=self.s(-200, -60, 150), radius=self.s(40))

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(*self.s(-300, -150, 300, 150)), body)
        m.pad(body, base, self.s(100), "Pad1")
        bossS = m.sketch(doc, "BossAS", [m.circle(*self.s(-200, -60, 40))], body, z=self.s(100))
        a = m.pad(body, bossS, self.s(50), "BossA")
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (a, self.names(a, self.copyEdge()))
        fillet.Radius = self.s(10)
        self.transformName = "BossA"
        self.copies = 1
        self.ref("copy_edge", fillet, "Base", self.copyEdge, FilletedOnTransform(self.s(10)))

    def edit(self, doc):
        body = doc.Body
        body.Tip = doc.BossA
        lp = body.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [doc.BossA]
        lp.Direction = (m.originFeature(body, "X_Axis"), [""])
        lp.Length = self.s(400)
        lp.Occurrences = 3
        body.Tip = lp
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.Originals = [doc.BossA]
        mir.MirrorPlane = (m.originFeature(body, "XZ_Plane"), [""])
        body.Tip = mir
        body.Tip = doc.Fillet
        self.transformName = "Mirrored"
        self.copies = 4


from PartDesignTests.Scenarios.harness import Attached, Y, face  # noqa: E402


class AttachedWithBodyVolume(Attached):
    """Attached, and the Body's volume is the scenario's expected one; a Body member in error or
    left touched is loud: broken."""

    def check(self, scenario, consumer, target, expectation):
        body = scenario.doc.Body
        # A transform of nothing is red, as Onshape's is (ops#640): the scenario names it
        red = set(scenario.redTransforms())
        bad = [o.Name for o in body.Group + [body] if o.Name not in red and (
            "Touched" in o.State or (o.isDerivedFrom("PartDesign::Feature") and not o.isValid()))]
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


class DeleteOnlyOriginal(Scenario):
    """The block, boss A, a LinearPattern of A (X, 400, 3) and, unless `last`, a 100 x 80 x 20 cap
    at x -50..50, y 60..140 after it. A is deleted as the GUI does it (Body.removeObject, then the
    document's): the Body is the block (and the cap), and the pattern of nothing is red ('Select
    features to pattern.', Onshape's rule, ops#640). Judged by a sketch outside the Body on the
    block's front face and the Body's volume."""

    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#590"
    FOUND_BY = "review pr590-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("front",)
    last = False
    bosses = 3

    def front(self):
        return face("plane", normal=-Y, through=self.s(0, -150, 50))

    def redTransforms(self):
        """The pattern, once A is deleted: a pattern of nothing is red (ops#640)."""
        return ("LP",) if self.bosses == 0 else ()

    def bodyVolume(self):
        import math
        L, W, H, r, h, cw, cl, ch = self.s(600, 300, 100, 40, 50, 100, 80, 20)
        return L * W * H + self.bosses * math.pi * r * r * h + (0 if self.last else cw * cl * ch)

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(*self.s(-300, -150, 300, 150)), body)
        m.pad(body, base, self.s(100), "Pad1")
        bossS = m.sketch(doc, "BossAS", [m.circle(*self.s(-200, 0, 40))], body, z=self.s(100))
        m.pad(body, bossS, self.s(50), "BossA")
        doc.recompute()
        lp = body.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [doc.BossA]
        lp.Direction = (m.originFeature(body, "X_Axis"), [""])
        lp.Length = self.s(400)
        lp.Occurrences = 3
        body.Tip = lp
        doc.recompute()
        if not self.last:
            capS = m.sketch(doc, "CapS", m.rectangle(*self.s(-50, 60, 50, 140)), body,
                            z=self.s(100))
            m.pad(body, capS, self.s(20), "Cap")
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front, AttachedWithBodyVolume())

    def edit(self, doc):
        doc.Body.removeObject(doc.BossA)
        doc.removeObject("BossA")
        self.bosses = 0


class DeleteOnlyOriginalCap(DeleteOnlyOriginal):
    pass


class DeleteOnlyOriginalLast(DeleteOnlyOriginal):
    last = True


class DeleteOnlyOriginalUndo(DeleteOnlyOriginal):
    """DeleteOnlyOriginalCap's delete in a transaction, a recompute, then undone: the Body is the
    block, A's three copies and the cap again."""

    def edit(self, doc):
        doc.UndoMode = 1
        doc.openTransaction("delete")
        doc.Body.removeObject(doc.BossA)
        doc.removeObject("BossA")
        doc.commitTransaction()
        doc.recompute()
        doc.undo()


class DeleteOnlyOriginalUndoRedo(DeleteOnlyOriginal):
    """DeleteOnlyOriginalUndo, then redone (recomputed between): the block and the cap."""

    steps = ("delete", "back", "again")

    def delete(self, doc):
        doc.UndoMode = 1
        doc.openTransaction("delete")
        doc.Body.removeObject(doc.BossA)
        doc.removeObject("BossA")
        doc.commitTransaction()
        self.bosses = 0

    def back(self, doc):
        doc.undo()
        self.bosses = 3

    def again(self, doc):
        doc.redo()
        self.bosses = 0


class ConvertUndoRedo(ConvertFillet):
    """ConvertFillet's conversion in a transaction, then undone (the Mirrored again, the fillet's
    edge at z 150 on it), then redone (on the MultiTransform)."""

    steps = ("convert", "back", "again")

    def convert(self, doc):
        doc.UndoMode = 1
        doc.openTransaction("convert")
        super().convert(doc)
        doc.commitTransaction()

    def back(self, doc):
        doc.undo()
        self.transformName = "Mirrored"

    def again(self, doc):
        doc.redo()
        self.transformName = "MultiTransform"


class ReorderPatternPastCap(DeleteOnlyOriginal):
    """DeleteOnlyOriginalCap's model; the LinearPattern is moved after the cap (ops#127's
    reorder), then back before it: the Body is unchanged."""

    steps = ("down", "up")

    def down(self, doc):
        body = doc.Body
        body.reorderObject([doc.LP], doc.Cap, True)
        body.Tip = doc.LP

    def up(self, doc):
        body = doc.Body
        body.reorderObject([doc.LP], doc.BossA, True)
        body.Tip = doc.Cap


class ReorderCapBeforePattern(DeleteOnlyOriginal):
    """The cap moved before the LinearPattern, then before A: the Body is unchanged."""

    steps = ("before", "top")

    def before(self, doc):
        doc.Body.reorderObject([doc.Cap], doc.LP, False)
        doc.Body.Tip = doc.LP

    def top(self, doc):
        doc.Body.reorderObject([doc.Cap, doc.CapS], doc.BossAS, False)
        doc.Body.Tip = doc.LP


class ExpressionModeOff(DeleteOnlyOriginal):
    """A whole-shape Mirrored (YZ) of the block and A in place of the pattern, the cap after it,
    its mode bound to a VarSet's integer (1, Whole shape); the integer set to 0 (Features, no
    Originals: the mirror off, and red, 'Select features to mirror.', ops#640), then back to 1.
    Each change applied by a recompute."""

    steps = ("off", "on")
    bosses = 2

    def redTransforms(self):
        return ("Mirrored",) if self.bosses == 1 else ()

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(*self.s(-300, -150, 300, 150)), body)
        m.pad(body, base, self.s(100), "Pad1")
        bossS = m.sketch(doc, "BossAS", [m.circle(*self.s(-200, 0, 40))], body, z=self.s(100))
        m.pad(body, bossS, self.s(50), "BossA")
        doc.recompute()
        vs = doc.addObject("App::VarSet", "VarSet")
        vs.addProperty("App::PropertyInteger", "Mode")
        vs.Mode = 1
        mir = body.newObject("PartDesign::Mirrored", "Mirrored")
        mir.TransformMode = "Whole shape"
        mir.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        mir.setExpression("TransformMode", "VarSet.Mode")
        body.Tip = mir
        doc.recompute()
        capS = m.sketch(doc, "CapS", m.rectangle(*self.s(-50, 60, 50, 140)), body, z=self.s(100))
        m.pad(body, capS, self.s(20), "Cap")
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnFront")
        sketch.AttachmentSupport = [(body, self.names(body, self.front())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("front", sketch, "AttachmentSupport", self.front, AttachedWithBodyVolume())

    def off(self, doc):
        doc.VarSet.Mode = 0
        doc.recompute()
        self.bosses = 1

    def on(self, doc):
        doc.VarSet.Mode = 1
        doc.recompute()
        self.bosses = 2
