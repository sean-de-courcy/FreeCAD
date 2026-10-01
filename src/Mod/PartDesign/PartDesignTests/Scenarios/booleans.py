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

"""Booleans: references to faces and edges of a fuse, cut or common (Part and PartDesign) follow
their elements when the tool moves and faces nearby split, merge or appear."""

import FreeCAD as App

from .harness import BROKEN, Attached, Chamfered, Scenario, X, Y, Z, edge, face
from . import models as m

V = App.Vector


class BooleanModel(Scenario):
    """A base block 20 x 20 x 10 at the origin and a tool bar 4 x 30 x 4 at (tx, ty, tz),
    crossing the block along Y."""

    abstract = True
    area = "booleans"
    tx, ty, tz = 8, -5, 8
    bar = (4, 30, 4)

    def attach(self, doc, name, target, predicate, body=None):
        if body is None:
            sketch = doc.addObject("Sketcher::SketchObject", name)
        else:
            sketch = body.newObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = [(target, self.names(target, predicate)[0])]
        sketch.MapMode = "FlatFace"
        return sketch

    def move(self, obj, **position):
        for axis, value in position.items():
            setattr(self, axis, value)
        obj.Placement.Base = V(self.tx, self.ty, self.tz)

    # Elements of the base block

    def baseLeft(self):
        return face("plane", normal=-X, through=(0, 0, 0))

    def baseTop(self):
        """The base's top face, or its piece at x < tx."""
        return face("plane", normal=Z, through=(0, 0, 10), contains=(2, 10, 10))

    def baseLeftTopEdge(self):
        return edge("line", direction=Y, through=(0, 0, 10))

    # Elements of the bar

    def barEnd(self):
        return face("plane", normal=-Y, through=(0, self.ty, 0))

    def slotFloor(self):
        """A cut's floor (the bar's bottom face, facing up); gone once the bar is off the block."""
        if self.tz >= 10:
            return BROKEN
        return face("plane", normal=Z, through=(0, 0, self.tz), contains=(self.tx + 2, 10, self.tz))


# ---------------------------------------------------------------------------------------------
# Part: Part::Fuse, Part::Cut and Part::Common of two Part::Box, sketches attached to the result
# ---------------------------------------------------------------------------------------------


class PartBoolean(BooleanModel):
    abstract = True
    operation = None

    def attachments(self):
        """(reference name, expectation) of each sketch attached to the result."""
        raise NotImplementedError

    def build(self, doc):
        m.box(doc, "Base", (20, 20, 10))
        m.box(doc, "Bar", self.bar, at=(self.tx, self.ty, self.tz))
        result = doc.addObject(self.operation, "Boolean")
        result.Base, result.Tool = doc.Base, doc.Bar
        doc.recompute()
        for ref, expect in self.attachments():
            sketch = self.attach(doc, "On_" + ref, result, expect())
            self.ref(ref, sketch, "AttachmentSupport", expect, Attached())


class PartFuse(PartBoolean):
    """Part::Fuse: the bar crosses the block's top (z 8..12) and splits the top face in two;
    sketches on the block's left face, the top face's left piece and the bar's front end."""

    abstract = True
    operation = "Part::Fuse"
    REFS = ("base_left", "base_top", "bar_end")

    def attachments(self):
        return [("base_left", self.baseLeft), ("base_top", self.baseTop), ("bar_end", self.barEnd)]


class PartFuseLift(PartFuse):
    """The bar is lifted off the block (z 12..16): the top face's two pieces merge into one."""

    def edit(self, doc):
        self.move(doc.Bar, tz=12)


class PartFuseSlide(PartFuse):
    """The bar slides along X: x 8..12 -> 14..18."""

    def edit(self, doc):
        self.move(doc.Bar, tx=14)


class PartFuseSink(PartFuse):
    """The bar sinks into the block (z 3..7): the top face is whole again, and the front and back
    faces get a hole each."""

    def edit(self, doc):
        self.move(doc.Bar, tz=3)


class PartFuseDrop(PartFuse):
    """The bar starts above the block (z 12..16) and drops to cross its top (z 8..12): the whole
    top face splits in two, and its pieces carry the face's name under another op code (MKR
    whole, FUS as the pieces' prefix). The sketch on it lies on either piece."""

    tz = 12

    def edit(self, doc):
        self.move(doc.Bar, tz=8)


class PartCut(PartBoolean):
    """Part::Cut: the bar cuts a slot across the block's top (z 8..10) and splits the top face in
    two; sketches on the block's left face, the top face's left piece and the slot's floor."""

    abstract = True
    operation = "Part::Cut"
    REFS = ("base_left", "base_top", "slot_floor")

    def attachments(self):
        return [
            ("base_left", self.baseLeft),
            ("base_top", self.baseTop),
            ("slot_floor", self.slotFloor),
        ]


class PartCutSlide(PartCut):
    """The slot slides along X: x 8..12 -> 14..18."""

    def edit(self, doc):
        self.move(doc.Bar, tx=14)


class PartCutDeepen(PartCut):
    """The slot gets deeper: its floor goes from z = 8 to z = 5."""

    def edit(self, doc):
        self.move(doc.Bar, tz=5)


class PartCutLift(PartCut):
    """The bar is lifted off the block (z 12..16): nothing is cut, the top face is whole again,
    and the slot's floor is gone."""

    def edit(self, doc):
        self.move(doc.Bar, tz=12)


class PartCommon(PartBoolean):
    """Part::Common: the block x 8..12, y 0..20, z 8..10 where the bar crosses the top; sketches
    on its top (the base's top face), its front (the base's front face) and its left side (the
    bar's)."""

    abstract = True
    operation = "Part::Common"
    REFS = ("common_top", "common_front", "common_side")

    def attachments(self):
        return [
            ("common_top", self.commonTop),
            ("common_front", self.commonFront),
            ("common_side", self.commonSide),
        ]

    def commonTop(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def commonFront(self):
        """The base's front face; gone from the result once the bar no longer spans the block."""
        return BROKEN if self.ty > 0 else face("plane", normal=-Y, through=(0, 0, 0))

    def commonSide(self):
        return face("plane", normal=-X, through=(self.tx, 0, 0))


class PartCommonSlide(PartCommon):
    """The bar slides along X: x 8..12 -> 14..18."""

    def edit(self, doc):
        self.move(doc.Bar, tx=14)


class PartCommonShift(PartCommon):
    """The bar shifts along Y and no longer spans the block (y 5..35): the common's front face is
    now the bar's end, and the block's front face is gone from the result."""

    def edit(self, doc):
        self.move(doc.Bar, ty=5)


# ---------------------------------------------------------------------------------------------
# PartDesign: a Boolean of the base body with a tool body, then a chamfer and a sketch
# ---------------------------------------------------------------------------------------------


class PartDesignBoolean(BooleanModel):
    """Body BaseBody: the block, padded; body ToolBody: the bar, padded and placed by the body's
    placement. A PartDesign::Boolean in BaseBody, then a chamfer (0.5) on an edge and a sketch
    attached to a face of the Boolean."""

    abstract = True
    MULTI = True
    REFS = ("chamfer_edge", "sketch_face")
    booleanType = None

    def chamferedEdge(self):
        raise NotImplementedError

    def attachedFace(self):
        raise NotImplementedError

    def build(self, doc):
        tool = doc.addObject("PartDesign::Body", "ToolBody")
        barProfile = m.sketch(doc, "BarProfile", m.rectangle(0, 0, self.bar[0], self.bar[1]), tool)
        m.pad(tool, barProfile, self.bar[2], "BarPad")
        tool.Placement.Base = V(self.tx, self.ty, self.tz)
        base = doc.addObject("PartDesign::Body", "BaseBody")
        profile = m.sketch(doc, "BaseProfile", m.rectangle(0, 0, 20, 20), base)
        m.pad(base, profile, 10, "BasePad")
        boolean = base.newObject("PartDesign::Boolean", "Boolean")
        boolean.Type = self.booleanType
        boolean.addObjects([tool])
        doc.recompute()
        chamfer = base.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (boolean, self.names(boolean, self.chamferedEdge()))
        chamfer.Size = 0.5
        sketch = self.attach(doc, "OnBoolean", boolean, self.attachedFace(), base)
        self.ref("chamfer_edge", chamfer, "Base", self.chamferedEdge, Chamfered(0.5))
        self.ref("sketch_face", sketch, "AttachmentSupport", self.attachedFace, Attached())


class PartDesignFuse(PartDesignBoolean):
    """Fuse: the bar crosses the block's top; the chamfer on the block's left top edge, the
    sketch on the bar's front end."""

    abstract = True
    booleanType = "Fuse"

    def chamferedEdge(self):
        return self.baseLeftTopEdge()

    def attachedFace(self):
        return self.barEnd()


class PartDesignFuseSlide(PartDesignFuse):
    """The tool body slides along X: x 8..12 -> 14..18."""

    def edit(self, doc):
        self.move(doc.ToolBody, tx=14)


class PartDesignCut(PartDesignBoolean):
    """Cut: the bar cuts a slot across the block's top; the chamfer on the block's left top
    edge, the sketch on the slot's floor."""

    abstract = True
    booleanType = "Cut"

    def chamferedEdge(self):
        return self.baseLeftTopEdge()

    def attachedFace(self):
        return self.slotFloor()


class PartDesignCutSlide(PartDesignCut):
    """The tool body slides along X: x 8..12 -> 14..18."""

    def edit(self, doc):
        self.move(doc.ToolBody, tx=14)


class PartDesignCutLift(PartDesignCut):
    """The tool body is lifted off the block (z 12..16): nothing is cut, and the slot's floor is
    gone."""

    def edit(self, doc):
        self.move(doc.ToolBody, tz=12)


class PartDesignCommon(PartDesignBoolean):
    """Common: the block x 8..12, y 0..20, z 8..10; the chamfer on its front top edge (where the
    base's top and front faces meet), the sketch on its left side (the bar's)."""

    abstract = True
    booleanType = "Common"

    def chamferedEdge(self):
        return edge("line", direction=X, through=(0, 0, 10))

    def attachedFace(self):
        return face("plane", normal=-X, through=(self.tx, 0, 0))


class PartDesignCommonSlide(PartDesignCommon):
    """The tool body slides along X: x 8..12 -> 14..18."""

    def edit(self, doc):
        self.move(doc.ToolBody, tx=14)


# ---------------------------------------------------------------------------------------------
# The reference solver (ops#7): two faces merge into one
# ---------------------------------------------------------------------------------------------


class SolverMergeTwo(Scenario):
    """Part::Fuse (refined) of box A (10 x 10 x 10 at the origin) and box B (10 x 10 x 8 at
    x = 12); a sketch on A's top and one on B's top. B grows to 10 high and moves to x = 10: it
    touches A, the tops are coplanar, and the refined fusion merges them into one face
    (x 0..20). Both sketches should follow onto the merged face, each from its own owner."""

    area = "booleans"
    REFS = ("a_top", "b_top")
    merged = False

    def topA(self):
        if self.merged:
            return face("plane", normal=Z, through=(0, 0, 10), contains=(15, 5, 10))
        return face("plane", normal=Z, through=(0, 0, 10), contains=(5, 5, 10))

    def topB(self):
        if self.merged:
            return face("plane", normal=Z, through=(0, 0, 10), contains=(5, 5, 10))
        return face("plane", normal=Z, through=(0, 0, 8), contains=(17, 5, 8))

    def build(self, doc):
        m.box(doc, "A", (10, 10, 10))
        m.box(doc, "B", (10, 10, 8), at=(12, 0, 0))
        fusion = doc.addObject("Part::Fuse", "Fusion")
        fusion.Base, fusion.Tool = doc.A, doc.B
        fusion.Refine = True
        doc.recompute()
        for ref, predicate in (("a_top", self.topA), ("b_top", self.topB)):
            sketch = doc.addObject("Sketcher::SketchObject", "On_" + ref)
            sketch.AttachmentSupport = [(fusion, self.names(fusion, predicate())[0])]
            sketch.MapMode = "FlatFace"
            self.ref(ref, sketch, "AttachmentSupport", predicate, Attached())

    def edit(self, doc):
        doc.B.Height = 10
        doc.B.Placement.Base = V(10, 0, 0)
        self.merged = True
