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
follow their instances when the pattern's occurrences, spacing or direction change."""

import FreeCAD as App

from .harness import Attached, Chamfered, Scenario, X, Y, Z, edge, face
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
    18 apart ("Spacing" mode)."""

    abstract = True
    direction, spacing, occurrences = X, 18, 3

    def plateProfile(self):
        return m.rectangle(0, 0, 70, 70)

    def instanceCentre(self, k):
        return self.bossCentre + self.direction * (self.spacing * (k - 1))

    def pattern(self, body, originals):
        pattern = self.doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = originals
        pattern.Direction = (m.originFeature(body, "X_Axis"), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = self.spacing
        pattern.Occurrences = self.occurrences
        body.addObject(pattern)
        return pattern


class LinearOccurrences(LinearPatternEdit):
    """A fourth occurrence: 3 -> 4; instances 1-3 stay where they are."""

    def edit(self, doc):
        doc.LinearPattern.Occurrences = 4


class LinearSpacing(LinearPatternEdit):
    """The spacing shrinks: 18 -> 15."""

    def edit(self, doc):
        doc.LinearPattern.Offset = 15
        self.spacing = 15


class LinearDirection(LinearPatternEdit):
    """The pattern runs along Y instead of X."""

    def edit(self, doc):
        doc.LinearPattern.Direction = (m.originFeature(self.bodyObject, "Y_Axis"), [""])
        self.direction = Y


class PolarPatternEdit(PatternEdit):
    """A round plate of radius 35 around the Z axis, the boss centred at (22, 0); a PolarPattern
    around Z, 4 occurrences, 60 degrees apart ("Spacing" mode)."""

    abstract = True
    bossCentre = V(22, 0, 0)
    step, occurrences, sense = 60, 4, 1

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
        pattern.Mode = "Spacing"
        pattern.Offset = self.step
        pattern.Occurrences = self.occurrences
        body.addObject(pattern)
        return pattern


class PolarOccurrences(PolarPatternEdit):
    """A fifth occurrence: 4 -> 5; instances 1-4 stay where they are."""

    def edit(self, doc):
        doc.PolarPattern.Occurrences = 5


class PolarSpacing(PolarPatternEdit):
    """The angle between instances shrinks: 60 -> 45 degrees."""

    def edit(self, doc):
        doc.PolarPattern.Offset = 45
        self.step = 45


class PolarDirection(PolarPatternEdit):
    """The pattern turns the other way (Reversed)."""

    def edit(self, doc):
        doc.PolarPattern.Reversed = True
        self.sense = -1
