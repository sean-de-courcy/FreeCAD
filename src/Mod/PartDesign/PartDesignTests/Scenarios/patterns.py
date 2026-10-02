# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Patterns: a chamfer on one instance's hole edge and a sketch on another instance's face
follow their instances when the pattern's occurrences, spacing or direction change. Two patterns
of one original: a sketch on one pattern's instance stays there when the other pattern changes
(ops#55). A two-step pattern (a MultiTransform, a LinearPattern with a second direction): a
sketch on an instance stays there when an earlier step's count changes (ops#6)."""

import os
import shutil
import tempfile

import FreeCAD as App

from .harness import BROKEN, Attached, Chamfered, Scenario, ScenarioError, X, Y, Z, edge, face
from . import models as m

V = App.Vector


class PatternEdit(Scenario):
    """A plate 5 high; on it a square boss 10 x 10, 5 high, with a hole of radius 2 through its
    centre and the plate. The boss and the hole are patterned. A chamfer (0.5) on the top edge
    of instance 2's hole; a sketch attached to the top face of instance 3's boss. Instance 1 is
    the original. Subclasses place the instances (`instanceCentre`)."""

    abstract = True
    area = "patterns"
    MULTI = True
    REFS = ("chamfer_instance2_hole", "sketch_instance3_face")
    plateHeight, bossHeight, bossSize, holeRadius = 5, 5, 10, 2
    bossCentre = V(8, 8, 0)

    def instanceCentre(self, k):
        """The centre of instance k's boss, in the XY plane."""
        raise NotImplementedError

    def plateProfile(self):
        raise NotImplementedError

    def pattern(self, body, originals):
        """Adds the pattern to the body once its Originals are set: a Transformed feature
        without Originals counts as a MultiTransform's child, and the body neither makes it
        the Tip nor gives it a BaseFeature."""
        raise NotImplementedError

    def top(self):
        return self.plateHeight + self.bossHeight

    def holeEdge(self, k):
        centre = self.instanceCentre(k) + V(0, 0, self.top())
        return edge("circle", center=centre, radius=self.holeRadius)

    def bossFace(self, k):
        # beside the hole, inside the boss
        inside = self.instanceCentre(k) + self.besideHole(k) + V(0, 0, self.top())
        return face("plane", normal=Z, through=(0, 0, self.top()), contains=inside)

    def besideHole(self, k):
        return V(0, -3.5, 0)

    def chamferedEdge(self):
        return self.holeEdge(2)

    def attachedFace(self):
        return self.bossFace(3)

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        plate = m.sketch(doc, "PlateSketch", self.plateProfile(), body)
        m.pad(body, plate, self.plateHeight, "Plate")
        c, h = self.bossCentre, self.bossSize / 2
        square = m.rectangle(c.x - h, c.y - h, c.x + h, c.y + h)
        bossSketch = m.sketch(doc, "BossSketch", square, body, z=self.plateHeight)
        boss = m.pad(body, bossSketch, self.bossHeight, "Boss")
        holeSketch = m.sketch(
            doc, "HoleSketch", [m.circle(c.x, c.y, self.holeRadius)], body, z=self.top()
        )
        hole = m.pocketThroughAll(body, holeSketch, "Hole")
        pattern = self.pattern(body, [boss, hole])
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pattern, self.names(pattern, self.chamferedEdge()))
        chamfer.Size = 0.5
        onBoss = body.newObject("Sketcher::SketchObject", "OnBoss")
        onBoss.AttachmentSupport = [(pattern, self.names(pattern, self.attachedFace())[0])]
        onBoss.MapMode = "FlatFace"
        self.ref("chamfer_instance2_hole", chamfer, "Base", self.chamferedEdge, Chamfered(0.5))
        self.ref("sketch_instance3_face", onBoss, "AttachmentSupport", self.attachedFace,
                 Attached())


class LinearPatternEdit(PatternEdit):
    """A plate 70 x 70, the boss centred at (8, 8); a LinearPattern along X, 3 occurrences,
    18 apart ("Spacing" mode; "Extent" mode keeps the overall length instead, 36, so an edit of
    the occurrences moves the instances)."""

    abstract = True
    direction, spacing, occurrences = X, 18, 3
    patternMode = "Spacing"

    def plateProfile(self):
        return m.rectangle(0, 0, 70, 70)

    def instanceCentre(self, k):
        return self.bossCentre + self.direction * (self.spacing * (k - 1))

    def pattern(self, body, originals):
        pattern = self.doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = originals
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Mode = self.patternMode
        if self.patternMode == "Extent":
            pattern.Length = self.spacing * (self.occurrences - 1)
        else:
            pattern.Offset = self.spacing
        pattern.Occurrences = self.occurrences
        body.addObject(pattern)
        return pattern


class LinearOccurrences(LinearPatternEdit):
    """A fourth occurrence: 3 -> 4; instances 1-3 stay where they are."""

    def edit(self, doc):
        doc.LinearPattern.Occurrences = 4


class LinearFewerOccurrences(LinearPatternEdit):
    """One occurrence fewer: 3 -> 2. Instance 3 is gone, and the sketch on its boss should
    break. Its siblings' top faces are named as it is up to the instance number (the TRF
    section's index, ops#55): the reference solver's pattern-sibling guard (ops#7) must break
    the reference instead of moving it to one of them."""

    gone = False

    def attachedFace(self):
        return BROKEN if self.gone else super().attachedFace()

    def edit(self, doc):
        doc.LinearPattern.Occurrences = 2
        self.gone = True


class LinearFewerOccurrencesExtent(LinearFewerOccurrences):
    """As LinearFewerOccurrences in "Extent" mode: instance 2 moves onto instance 3's place, so
    geometry alone finds a face where instance 3's was. It is instance 2's: the sketch on
    instance 3 must still break, and the chamfer follow instance 2."""

    patternMode = "Extent"

    def edit(self, doc):
        super().edit(doc)
        self.spacing = 36


class LinearOccurrencesExtent(LinearOccurrences):
    """As LinearOccurrences in "Extent" mode: the four instances close up to 12 apart."""

    patternMode = "Extent"

    def edit(self, doc):
        super().edit(doc)
        self.spacing = 12


class LinearSpacing(LinearPatternEdit):
    """The spacing shrinks: 18 -> 15."""

    def edit(self, doc):
        doc.LinearPattern.Offset = 15
        self.spacing = 15


class LinearLengthExtent(LinearPatternEdit):
    """In "Extent" mode the overall length shrinks: 36 -> 30, so the spacing 18 -> 15."""

    patternMode = "Extent"

    def edit(self, doc):
        doc.LinearPattern.Length = 30
        self.spacing = 15


class LinearDirection(LinearPatternEdit):
    """The pattern runs along Y instead of X."""

    def edit(self, doc):
        doc.LinearPattern.Direction = (m.originFeature(self.bodyObject, "Y_Axis"), [""])
        self.direction = Y


class PolarPatternEdit(PatternEdit):
    """A round plate of radius 35 around the Z axis, the boss centred at (22, 0); a PolarPattern
    around Z, 4 occurrences, 60 degrees apart ("Spacing" mode; "Extent" mode keeps the overall
    angle instead, 180 degrees)."""

    abstract = True
    bossCentre = V(22, 0, 0)
    step, occurrences, sense = 60, 4, 1
    patternMode = "Spacing"

    def plateProfile(self):
        return [m.circle(0, 0, 35)]

    def rotation(self, k):
        return App.Rotation(Z, self.sense * self.step * (k - 1))

    def instanceCentre(self, k):
        return self.rotation(k).multVec(self.bossCentre)

    def besideHole(self, k):
        return self.rotation(k).multVec(V(0, -3.5, 0))

    def pattern(self, body, originals):
        pattern = self.doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        pattern.Originals = originals
        pattern.Axis = (m.originFeature(body, "Z_Axis"), [""])
        pattern.Mode = self.patternMode
        if self.patternMode == "Extent":
            pattern.Angle = self.step * (self.occurrences - 1)
        else:
            pattern.Offset = self.step
        pattern.Occurrences = self.occurrences
        body.addObject(pattern)
        return pattern


class PolarOccurrences(PolarPatternEdit):
    """A fifth occurrence: 4 -> 5; instances 1-4 stay where they are."""

    def edit(self, doc):
        doc.PolarPattern.Occurrences = 5


class PolarOccurrencesExtent(PolarOccurrences):
    """As PolarOccurrences in "Extent" mode: the five instances close up to 45 degrees apart."""

    patternMode = "Extent"

    def edit(self, doc):
        super().edit(doc)
        self.step = 45


class PolarFewerOccurrences(PolarPatternEdit):
    """Three occurrences, 60 degrees apart, then one fewer: 3 -> 2. Instance 3 is gone, and the
    sketch on its boss should break; the chamfer stays on instance 2."""

    occurrences = 3
    gone = False

    def attachedFace(self):
        return BROKEN if self.gone else super().attachedFace()

    def edit(self, doc):
        doc.PolarPattern.Occurrences = 2
        self.gone = True


class PolarFewerOccurrencesExtent(PolarFewerOccurrences):
    """As PolarFewerOccurrences in "Extent" mode (120 degrees): instance 2 turns onto instance
    3's place. The sketch on instance 3 must still break, and the chamfer follow instance 2."""

    patternMode = "Extent"

    def edit(self, doc):
        super().edit(doc)
        self.step = 120


class PolarSpacing(PolarPatternEdit):
    """The angle between instances shrinks: 60 -> 45 degrees."""

    def edit(self, doc):
        doc.PolarPattern.Offset = 45
        self.step = 45


class PolarAngleExtent(PolarPatternEdit):
    """In "Extent" mode the overall angle shrinks: 180 -> 135 degrees, so the step 60 -> 45."""

    patternMode = "Extent"

    def edit(self, doc):
        doc.PolarPattern.Angle = 135
        self.step = 45


class PolarDirection(PolarPatternEdit):
    """The pattern turns the other way (Reversed)."""

    def edit(self, doc):
        doc.PolarPattern.Reversed = True
        self.sense = -1


class TwoPatternsEdit(Scenario):
    """Two LinearPatterns of one original, a 10 x 10 x 10 block at the origin: PatY along Y,
    then PatX along X, each 3 occurrences 30 apart ("Spacing" mode), so the chain is original ->
    PatY -> PatX and PatX's result holds five blocks. Sketches attached to PatX's result, on the
    top faces of PatX's instance 3 (x 60..70) and PatY's instance 3 (y 60..70). Then PatX's
    occurrences go 3 -> 2 -> 3, and PatY's the same way. With one fewer occurrence the pattern's
    instance 3 is gone: its sketch's reference breaks, and the other sketch stays on its block.
    With 3 again, each sketch is back on its own block.

    V2 told the instances apart by the element map's duplicate counter alone, with nothing of
    the pattern in their names: when PatY lost an instance, PatX's counters shifted, and the
    sketch on PatY's instance 3 landed on one of PatX's blocks, silently (ops#55). Instance k now
    ends in a section `_;_;<pattern>;TRF;<k>;<type>;0;MOD;_`, so a lost instance's name is
    missing; the Attacher may still keep its old index (ops#68). Subclasses make the original
    (`original`)."""

    abstract = True
    area = "patterns"
    REFS = ("sketch_x3_face", "sketch_y3_face")
    STEPS = {
        "xTwo": ("PatX", 2),
        "xThree": ("PatX", 3),
        "yTwo": ("PatY", 2),
        "yThree": ("PatY", 3),
    }
    steps = tuple(STEPS)
    size, spacing = 10, 30
    patternMode = "Spacing"

    def original(self, doc, body):
        raise NotImplementedError

    def topFace(self, x, y):
        centre = (x + self.size / 2, y + self.size / 2, self.size)
        return face("plane", normal=Z, through=centre, contains=centre)

    def x3Face(self):
        return BROKEN if self.stepName == "xTwo" else self.topFace(2 * self.spacing, 0)

    def y3Face(self):
        return BROKEN if self.stepName == "yTwo" else self.topFace(0, 2 * self.spacing)

    def pattern(self, doc, body, original, name, axis):
        """Adds the pattern after the Tip once its Originals are set (see PatternEdit)."""
        pattern = doc.addObject("PartDesign::LinearPattern", name)
        pattern.Originals = [original]
        pattern.Direction = (m.originFeature(body, axis), [""])
        pattern.Mode = self.patternMode
        if self.patternMode == "Extent":
            pattern.Length = 2 * self.spacing
        else:
            pattern.Offset = self.spacing
        pattern.Occurrences = 3
        pattern.Refine = False
        body.addObject(pattern)
        return pattern

    def build(self, doc):
        body = m.body(doc)
        original = self.original(doc, body)
        patY = self.pattern(doc, body, original, "PatY", "Y_Axis")
        patX = self.pattern(doc, body, original, "PatX", "X_Axis")
        doc.recompute()
        if patX.BaseFeature != patY or patY.BaseFeature != original:
            raise ScenarioError("the chain isn't original -> PatY -> PatX")
        for name, ref, expect in (
            ("OnX3", "sketch_x3_face", self.x3Face),
            ("OnY3", "sketch_y3_face", self.y3Face),
        ):
            sketch = body.newObject("Sketcher::SketchObject", name)
            sketch.AttachmentSupport = [(patX, self.names(patX, expect())[0])]
            sketch.MapMode = "FlatFace"
            # No outcome check: the blocks' top faces are coplanar, so a sketch on the wrong one
            # has the same placement. The stored reference alone tells them apart.
            self.ref(ref, sketch, "AttachmentSupport", expect)

    def _occurrences(self, doc):
        name, occurrences = self.STEPS[self.stepName]
        doc.getObject(name).Occurrences = occurrences

    xTwo = xThree = yTwo = yThree = _occurrences


class TwoPatternsBox(TwoPatternsEdit):
    """The original is an AdditiveBox, the body's first feature: its AddSubShape has no element
    map, so the instances' names start from the box's index names (`Face6;_;<Box>;MKR;...`)."""

    def original(self, doc, body):
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = self.size
        return box


class TwoPatternsBoxOnPlate(TwoPatternsEdit):
    """The original is an AdditiveBox on a plate (an AdditiveBox 100 x 100 x 2 under it, from
    (-10, -10, -2)): its AddSubShape has an element map, so the instances' names start from the
    box's mapped names."""

    def original(self, doc, body):
        plate = body.newObject("PartDesign::AdditiveBox", "Plate")
        plate.Length = plate.Width = 100
        plate.Height = 2
        plate.Placement.Base = V(-10, -10, -2)
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = self.size
        return box


class TwoPatternsPad(TwoPatternsEdit):
    """The original is a Pad of a 10 x 10 square on the XY plane, 10 long."""

    def original(self, doc, body):
        square = m.sketch(doc, "Square", m.rectangle(0, 0, self.size, self.size), body)
        return m.pad(body, square, self.size)


class TwoPatternsBoxExtent(TwoPatternsBox):
    """As TwoPatternsBox in "Extent" mode (60 long): with one fewer occurrence, the pattern's
    instance 2 moves onto instance 3's place."""

    patternMode = "Extent"


class TwoPatternsBoxOnPlateExtent(TwoPatternsBoxOnPlate):
    """As TwoPatternsBoxOnPlate in "Extent" mode."""

    patternMode = "Extent"


class TwoPatternsPadExtent(TwoPatternsPad):
    """As TwoPatternsPad in "Extent" mode."""

    patternMode = "Extent"


class PatternStepsEdit(Scenario):
    """A two-step pattern of one original, a 10 x 10 x 10 block at the origin: 3 instances along
    X, 30 apart, times 2 along Y, 30 apart ("Spacing" mode), so its result holds six blocks.
    Sketches sit on the top faces of the y = 30 row (x = 0, 30, 60) and of the block at (30, 0).
    Then the X step's occurrences go 3 -> 2 -> 3, and the Y step's 2 -> 1 -> 2. With one fewer
    X occurrence, the block at (60, 30) is gone and its sketch's reference breaks; with Y at 1 the
    whole y = 30 row is gone. Every other sketch stays on its block, and with the counts back each
    is on its own block again.

    The instances were numbered by their place in the flattened list of transformations, so an
    edit of the earlier step's count renumbered the later instances under the same names: the
    sketch on (0, 30) moved to (30, 30), silently, even in V2s (ops#6). Each TRF section now holds
    one number per step (`...;TRF;2:2;F;0;MOD;_` for (30, 30)). Subclasses make the pattern
    (`pattern`) and say how to set a step's count (`setCount`).

    In "Extent" mode (`patternMode`) each step keeps its overall length (60 along X, 30 along Y),
    so one occurrence fewer moves the later instances: with X at 2, instance 2 is at x = 60, in
    instance 3's place. A sketch follows its instance there, and the one on the lost instance
    breaks; geometry alone would find instance 2's face where instance 3's was."""

    abstract = True
    area = "patterns"
    patternMode = "Spacing"
    INITIAL = {"x": 3, "y": 2}
    REFS = ("sketch_00_30_face", "sketch_30_30_face", "sketch_60_30_face", "sketch_30_00_face")
    BLOCKS = {
        "sketch_00_30_face": (0, 1),
        "sketch_30_30_face": (1, 1),
        "sketch_60_30_face": (2, 1),
        "sketch_30_00_face": (1, 0),
    }
    STEPS = {
        "xTwo": ("x", 2),
        "xThree": ("x", 3),
        "yOne": ("y", 1),
        "yTwo": ("y", 2),
    }
    steps = tuple(STEPS)
    size, spacing = 10, 30

    def pattern(self, doc, body, original):
        raise NotImplementedError

    def setCount(self, doc, step, count):
        raise NotImplementedError

    def linear(self, doc, body, name, axis, occurrences):
        pattern = doc.addObject("PartDesign::LinearPattern", name)
        pattern.Direction = (m.originFeature(body, axis), [""])
        pattern.Mode = self.patternMode
        if self.patternMode == "Extent":
            pattern.Length = self.spacing * (occurrences - 1)
        else:
            pattern.Offset = self.spacing
        pattern.Occurrences = occurrences
        return pattern

    def counts(self):
        """The two steps' counts after the current step (the steps run in order)."""
        x, y = self.INITIAL["x"], self.INITIAL["y"]
        done = self.steps[: self.steps.index(self.stepName) + 1] if self.stepName else ()
        for name in done:
            step, count = self.STEPS.get(name, (None, None))
            if step == "x":
                x = count
            elif step == "y":
                y = count
        return x, y

    def pitch(self, step, count):
        """How far apart the step's instances are with `count` occurrences."""
        if self.patternMode != "Extent":
            return self.spacing
        return self.spacing * (self.INITIAL[step] - 1) / (count - 1) if count > 1 else 0

    def topFace(self, ref):
        i, j = self.BLOCKS[ref]
        x, y = self.counts()
        if i >= x or j >= y:
            return BROKEN
        centre = (
            i * self.pitch("x", x) + self.size / 2,
            j * self.pitch("y", y) + self.size / 2,
            self.size,
        )
        return face("plane", normal=Z, through=centre, contains=centre)

    def build(self, doc):
        body = m.body(doc)
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = self.size
        pattern = self.pattern(doc, body, box)
        doc.recompute()
        for ref in self.REFS:
            _, x, y, _ = ref.split("_")
            sketch = body.newObject("Sketcher::SketchObject", f"On{x}{y}")
            expect = lambda ref=ref: self.topFace(ref)
            sketch.AttachmentSupport = [(pattern, self.names(pattern, expect())[0])]
            sketch.MapMode = "FlatFace"
            # No outcome check: the blocks' top faces are coplanar (see TwoPatternsEdit).
            self.ref(ref, sketch, "AttachmentSupport", expect)

    def _count(self, doc):
        step, count = self.STEPS[self.stepName]
        self.setCount(doc, step, count)

    xTwo = xThree = yOne = yTwo = _count


class MultiTransformSteps(PatternStepsEdit):
    """The pattern is a MultiTransform of LinX (along X) then LinY (along Y)."""

    def pattern(self, doc, body, original):
        multi = doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        multi.Originals = [original]
        multi.Refine = False
        body.addObject(multi)
        linX = self.linear(doc, body, "LinX", "X_Axis", 3)
        linY = self.linear(doc, body, "LinY", "Y_Axis", 2)
        # The steps belong to the body too, as in TestMultiTransform
        body.addObject(linX)
        body.addObject(linY)
        multi.Transformations = [linX, linY]
        return multi

    def setCount(self, doc, step, count):
        doc.getObject("LinX" if step == "x" else "LinY").Occurrences = count


class LinearDirection2Steps(PatternStepsEdit):
    """The pattern is one LinearPattern along X with a second direction along Y."""

    def pattern(self, doc, body, original):
        pattern = self.linear(doc, body, "LinearPattern", "X_Axis", 3)
        pattern.Originals = [original]
        pattern.Direction2 = (m.originFeature(body, "Y_Axis"), [""])
        pattern.Mode2 = self.patternMode
        pattern.Spacings2 = []  # a new pattern's is [0.0], a gap of 0 (ops#93)
        if self.patternMode == "Extent":
            pattern.Length2 = self.spacing
        else:
            pattern.Offset2 = self.spacing
        pattern.Occurrences2 = 2
        pattern.Refine = False
        body.addObject(pattern)
        return pattern

    def setCount(self, doc, step, count):
        prop = "Occurrences" if step == "x" else "Occurrences2"
        setattr(doc.getObject("LinearPattern"), prop, count)


class MultiTransformStepsExtent(MultiTransformSteps):
    """MultiTransformSteps in "Extent" mode: one occurrence fewer moves the later instances."""

    patternMode = "Extent"


class LinearDirection2StepsExtent(LinearDirection2Steps):
    """LinearDirection2Steps in "Extent" mode: one occurrence fewer moves the later instances."""

    patternMode = "Extent"


class MultiTransformStepsReopened(MultiTransformSteps):
    """As MultiTransformSteps, with the document saved, closed and opened again after `xTwo`:
    the per-step numbers (`2:2`) go through the saved element map, where ':' would end a name if
    it were taken for a separator (ops#6)."""

    steps = ("xTwo", "reopen", "xThree", "yOne", "yTwo")

    def reopen(self, doc):
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        self.doc = App.openDocument(path)
        self.documents.append(self.doc.Name)
        for obj in self.doc.Objects:
            obj.touch()

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


def removeStep(doc, name):
    """Removes a MultiTransform's feature from its Transformations, its body and the document."""
    obj = doc.getObject(name)
    for multi in obj.InList:
        if multi.isDerivedFrom("PartDesign::MultiTransform"):
            multi.Transformations = [f for f in multi.Transformations if f != obj]
    obj.getParentGeoFeatureGroup().removeObject(obj)
    doc.removeObject(name)


class MultiTransformReorder(MultiTransformSteps):
    """MultiTransformSteps' model, its features reordered instead of counted: `swap` makes
    Transformations [LinY, LinX], `swapBack` restores it; `insert` puts a new LinZ (2 along Z,
    30 apart: blocks above the others) at the front, and `dropInserted` removes it again. The
    blocks stay where they are (the translations commute), and every sketch must stay on its
    block. A block's number follows the features' creation order (their object IDs), not their
    place in Transformations, so none of these edits renumbers an instance (ops#6). With the
    digits in Transformations' order, `swap` traded (0, 30)'s `1:2` and (30, 0)'s `2`: both
    sketches moved, in V2s too, since the exact name was found."""

    steps = ("swap", "swapBack", "insert", "dropInserted")

    def swap(self, doc):
        multi = doc.getObject("MultiTransform")
        multi.Transformations = list(reversed(multi.Transformations))

    swapBack = swap

    def insert(self, doc):
        multi = doc.getObject("MultiTransform")
        linZ = self.linear(doc, multi.getParentGeoFeatureGroup(), "LinZ", "Z_Axis", 2)
        multi.getParentGeoFeatureGroup().addObject(linZ)
        multi.Transformations = [linZ] + multi.Transformations

    def dropInserted(self, doc):
        removeStep(doc, "LinZ")


class MultiTransformRemoveStep(MultiTransformSteps):
    """LinX, LinY and LinZ (2 along Z, 30 apart: blocks above the others), made in that order;
    then LinY is removed. The y = 30 row is gone, and its three sketches should break; the one
    on (30, 0) stays. LinY's digit was the middle one, so LinZ's moves into its place: (30, 30)'s
    `2:2` now names the block above (30, 0), and the sketch moves there, silently, in V2s too.
    Removing a step feature that isn't the newest is the edit the creation-order digits don't
    cover (ops#6, accepted and listed)."""

    steps = ("removeY",)

    def pattern(self, doc, body, original):
        multi = super().pattern(doc, body, original)
        linZ = self.linear(doc, body, "LinZ", "Z_Axis", 2)
        body.addObject(linZ)
        multi.Transformations = multi.Transformations + [linZ]
        return multi

    def counts(self):
        return (3, 1) if self.stepName == "removeY" else (3, 2)

    def removeY(self, doc):
        removeStep(doc, "LinY")


class MultiTransformRecreateStep(MultiTransformSteps):
    """LinX is deleted and made again, the same, as a user redoing it. The blocks are where they
    were, and every sketch should stay. The new LinX's object ID is the highest, so its digit
    now comes after LinY's: (0, 30)'s `1:2` and (30, 0)'s `2` trade blocks, silently, in V2s too
    (ops#6, accepted and listed, as removing a step feature that isn't the newest)."""

    steps = ("recreateX",)

    def recreateX(self, doc):
        multi = doc.getObject("MultiTransform")
        removeStep(doc, "LinX")
        linX = self.linear(doc, multi.getParentGeoFeatureGroup(), "LinXAgain", "X_Axis", 3)
        multi.getParentGeoFeatureGroup().addObject(linX)
        multi.Transformations = [linX] + multi.Transformations
