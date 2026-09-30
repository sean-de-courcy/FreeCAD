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

"""Upstream issues, rebuilt from their descriptions as designed models (read on GitHub; their
attached files are not used). Each scenario names its issue: those the naming PR is said to fix
(15484, 14129, 26889, 14643, 20096), and open ones it doesn't claim (15485, 15486, 28604, 29154,
30515). 17041 isn't here: its description is a video only. Where a description leaves the model
open, the scenario takes the simplest model with the behaviour it describes."""

import FreeCAD as App

from .harness import (
    Attached,
    Chamfered,
    ExternalCoincides,
    Filleted,
    Scenario,
    X,
    Y,
    Z,
    edge,
    face,
)
from . import models as m

V = App.Vector


def attach(body, name, target, subs, doc=None):
    """A sketch attached flat to target's face (in the body, or in the document)."""
    if body is not None:
        sketch = body.newObject("Sketcher::SketchObject", name)
    else:
        sketch = doc.addObject("Sketcher::SketchObject", name)
    sketch.AttachmentSupport = [(target, subs[0])]
    sketch.MapMode = "FlatFace"
    return sketch


def external(doc, body, name, target, subs, z):
    """A sketch at height z with target's edge as external geometry."""
    sketch = m.sketch(doc, name, [], body, z=z)
    sketch.addExternal(target.Name, subs[0])
    return sketch


class Issue15484ConstructionSwap(Scenario):
    """Upstream issue 15484: a rectangle 0..20 x 0..10 with a zigzag beside its right side in
    construction mode, padded 10; two circles sketched on the top face and pocketed 2 deep; a
    fillet on the left top edge. Then the right side becomes construction geometry and the zigzag
    normal geometry."""

    area = "issues"
    MULTI = True
    REFS = ("top_face", "left_top_edge")

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def leftTopEdge(self):
        return edge("line", direction=Y, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        zigzag = m.polyline([(20, 0), (22, 2.5), (20, 5), (22, 7.5), (20, 10)])
        profile.addGeometry(zigzag, True)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        circles = attach(body, "Circles", pad, self.names(pad, self.topFace()))
        circles.addGeometry([m.circle(5, 5, 2), m.circle(12, 5, 2)], False)
        pocket = m.pocket(body, circles, 2)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, self.leftTopEdge()))
        fillet.Radius = 1
        self.ref("top_face", circles, "AttachmentSupport", self.topFace, Attached())
        self.ref("left_top_edge", fillet, "Base", self.leftTopEdge, Filleted(1))

    def edit(self, doc):
        for index in (1, 4, 5, 6, 7):  # the right side, then the zigzag's four lines
            doc.Profile.toggleConstruction(index)


class Issue14129StretchPocketFace(Scenario):
    """Upstream issue 14129 ("index 11 out of bound 10"): a block 0..20 x 0..10 x 0..10 with a hole
    (x 14..18, y 3..7) pocketed through it; sketches attached to the hole's left wall (x = 14)
    and to the back face. The block's right side is dragged from x = 20 to x = 16, over the hole,
    which opens into a notch: the hole's right wall goes, and the faces after it renumber."""

    area = "issues"
    REFS = ("hole_wall", "back_face")

    def holeWall(self):
        return face("plane", normal=X, through=(14, 0, 0))

    def backFace(self):
        return face("plane", normal=Y, through=(0, 10, 0))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "HoleSketch", m.rectangle(14, 3, 18, 7), body, z=10)
        hole = m.pocketThroughAll(body, sketch, "Hole")
        doc.recompute()
        onWall = attach(body, "OnWall", hole, self.names(hole, self.holeWall()))
        onBack = attach(body, "OnBack", hole, self.names(hole, self.backFace()))
        self.ref("hole_wall", onWall, "AttachmentSupport", self.holeWall, Attached())
        self.ref("back_face", onBack, "AttachmentSupport", self.backFace, Attached())

    def edit(self, doc):
        m.moveRectangle(doc.Profile, 0, 0, 16, 10)


class Issue26889FilletThenPocket(Scenario):
    """Upstream issue 26889: a cube 0..10 each way (a pad), a fillet, radius 1, on its vertical
    edge at x = 10, y = 0. A pocket (x 2..5, y 5..8, 3 deep) is sketched on the top face nearby
    and inserted before the fillet."""

    area = "issues"
    MULTI = True
    REFS = ("vertical_edge",)

    def verticalEdge(self):
        return edge("line", direction=Z, through=(10, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 10, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.verticalEdge()))
        fillet.Radius = 1
        self.ref("vertical_edge", fillet, "Base", self.verticalEdge, Filleted(1))

    def edit(self, doc):
        body = self.bodyObject
        body.Tip = doc.Pad
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(2, 5, 5, 8), body, z=10)
        m.pocket(body, sketch, 3)
        body.Tip = doc.Fillet


class Issue14643DeleteChamfer(Scenario):
    """Upstream issue 14643: a cube 0..10 each way (a pad); chamfer A, size 1, on the vertical edge
    at x = 10, y = 0; chamfer B, size 0.5, on A's back top edge (y = 10, z = 10), which A leaves as
    it was. A is deleted as the GUI does it: B should move to the pad's edge. (The issue's other
    case, B on an edge A trims, waits for `notes/scenarios.md` section 16's question.)"""

    area = "issues"
    MULTI = True
    REFS = ("chamfer_edge",)

    def verticalEdge(self):
        return edge("line", direction=Z, through=(10, 0, 0))

    def backTopEdge(self):
        return edge("line", direction=X, through=(0, 10, 10))

    def build(self, doc):
        body = m.body(doc)
        self.bodyObject = body
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 10, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        chamferA = body.newObject("PartDesign::Chamfer", "ChamferA")
        chamferA.Base = (pad, self.names(pad, self.verticalEdge()))
        chamferA.Size = 1
        doc.recompute()
        chamferB = body.newObject("PartDesign::Chamfer", "ChamferB")
        chamferB.Base = (chamferA, self.names(chamferA, self.backTopEdge()))
        chamferB.Size = 0.5
        self.ref("chamfer_edge", chamferB, "Base", self.backTopEdge, Chamfered(0.5))

    def edit(self, doc):
        self.bodyObject.removeObject(doc.ChamferA)
        doc.removeObject("ChamferA")


class Issue20096PocketPassesPad(Scenario):
    """Upstream issue 20096: a block 0..30 x 0..10 x 0..10; a boss (x 20..24, y 0..3, 5 high) on
    its top; a pocket (x 5..12, y 5..9, 3 deep) in the top. A sketch on the pocket's floor and one
    with the pocket's right rim edge as external geometry. The pocket widens to x = 26: its right
    edge passes the boss's edges."""

    area = "issues"
    REFS = ("pocket_floor", "pocket_rim")
    right = 12

    def floor(self):
        return face("plane", normal=Z, through=(0, 0, 7))

    def rim(self):
        return edge("line", direction=Y, through=(self.right, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 30, 10), body)
        m.pad(body, profile, 10)
        boss = m.sketch(doc, "BossSketch", m.rectangle(20, 0, 24, 3), body, z=10)
        m.pad(body, boss, 5, name="Boss")
        sketch = m.sketch(doc, "PocketSketch", m.rectangle(5, 5, 12, 9), body, z=10)
        pocket = m.pocket(body, sketch, 3)
        doc.recompute()
        onFloor = attach(body, "OnFloor", pocket, self.names(pocket, self.floor()))
        rim = external(doc, body, "OnRim", pocket, self.names(pocket, self.rim()), 10)
        self.ref("pocket_floor", onFloor, "AttachmentSupport", self.floor, Attached())
        self.ref("pocket_rim", rim, "ExternalGeometry", self.rim, ExternalCoincides())

    def edit(self, doc):
        m.moveRectangle(doc.PocketSketch, 5, 5, 26, 9)
        self.right = 26


class Issue15485RotateTool(Scenario):
    """Upstream issue 15485: Part::Cut of a block 0..20 x 0..20 x 0..10 by a bar 4 x 8 (20 high)
    centred at (10, 10); sketches on the two walls of the cavity that the bar's +X and +Y faces
    make. The bar turns 90 degrees about its vertical axis: each wall should move with the bar
    face that makes it (history), not stay where it was."""

    area = "issues"
    REFS = ("wall_from_x", "wall_from_y")
    angle = 0

    def placement(self):
        turn = App.Placement(V(10, 10, -5), App.Rotation(Z, self.angle))
        return turn.multiply(App.Placement(V(-2, -4, 0), App.Rotation()))

    def wallFromX(self):
        """The cavity wall of the bar's local +X face (x = 2 from its centre)."""
        if self.angle == 0:
            return face("plane", normal=-X, through=(12, 0, 0))
        return face("plane", normal=-Y, through=(0, 12, 0))

    def wallFromY(self):
        """The cavity wall of the bar's local +Y face (y = 4 from its centre)."""
        if self.angle == 0:
            return face("plane", normal=-Y, through=(0, 14, 0))
        return face("plane", normal=X, through=(6, 0, 0))

    def build(self, doc):
        m.box(doc, "Block", (20, 20, 10))
        bar = m.box(doc, "Bar", (4, 8, 20))
        bar.Placement = self.placement()
        cut = doc.addObject("Part::Cut", "Cut")
        cut.Base, cut.Tool = doc.Block, bar
        doc.recompute()
        for ref, predicate in (("wall_from_x", self.wallFromX), ("wall_from_y", self.wallFromY)):
            sketch = attach(None, "On_" + ref, cut, self.names(cut, predicate()), doc)
            self.ref(ref, sketch, "AttachmentSupport", predicate, Attached())

    def edit(self, doc):
        self.angle = 90
        doc.Bar.Placement = self.placement()


class Issue15486PadType(Scenario):
    """Upstream issue 15486: a C-shaped profile in the XZ plane (floor z 0..2, post x 0..4, roof
    z 12..14, x 0..30) padded 10; a pillar (x 20..26, y -8..-2) padded from the floor "up to
    first", which reaches the roof; a sketch on the pillar's +X face. The pillar's type changes to
    a length of 5."""

    area = "issues"
    REFS = ("pillar_side",)

    def pillarSide(self):
        return face("plane", normal=X, through=(26, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        xz = App.Placement(V(), m.rotationFromAxes((1, 0, 0), (0, 0, 1)))  # normal -Y
        c = [(0, 0), (30, 0), (30, 2), (4, 2), (4, 12), (30, 12), (30, 14), (0, 14)]
        profile = m.sketch(doc, "Profile", m.polygon(c), body, placement=xz)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "PillarSketch", m.rectangle(20, -8, 26, -2), body, z=2)
        pillar = m.pad(body, sketch, 1, name="Pillar")
        pillar.Type = "UpToFirst"
        doc.recompute()
        onSide = attach(body, "OnSide", pillar, self.names(pillar, self.pillarSide()))
        self.ref("pillar_side", onSide, "AttachmentSupport", self.pillarSide, Attached())

    def edit(self, doc):
        doc.Pillar.Type = "Length"
        doc.Pillar.Length = 5


class Issue28604SketchHeight(Scenario):
    """Upstream issue 28604: a plate 0..30 x 0..20 x 0..5; a small pad (x 3..8, y 3..6, 4 high)
    and a larger one (x 12..25, y 4..16, 3 high) on it; sketches on the larger pad's top and right
    faces. The small pad's rectangle gets lower in the sketch: y 3..6 -> 3..5."""

    area = "issues"
    REFS = ("top_face", "right_face")

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 8))

    def rightFace(self):
        return face("plane", normal=X, through=(25, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 30, 20), body)
        m.pad(body, plate, 5, name="PlatePad")
        small = m.sketch(doc, "SmallSketch", m.rectangle(3, 3, 8, 6), body, z=5)
        m.pad(body, small, 4, name="SmallPad")
        large = m.sketch(doc, "LargeSketch", m.rectangle(12, 4, 25, 16), body, z=5)
        pad = m.pad(body, large, 3, name="LargePad")
        doc.recompute()
        onTop = attach(body, "OnTop", pad, self.names(pad, self.topFace()))
        onRight = attach(body, "OnRight", pad, self.names(pad, self.rightFace()))
        self.ref("top_face", onTop, "AttachmentSupport", self.topFace, Attached())
        self.ref("right_face", onRight, "AttachmentSupport", self.rightFace, Attached())

    def edit(self, doc):
        m.moveRectangle(doc.SmallSketch, 3, 3, 8, 5)


class Issue29154PadLength(Scenario):
    """Upstream issue 29154: an arm (a pad of a 10 x 10 square in the YZ plane, 56 long along X);
    a sketch on its end face with a hole (radius 2, 10 deep), a chamfer on the hole's rim, a
    fillet on the arm's front top edge, and a sketch with that edge as external geometry. The arm
    gets 5 shorter."""

    area = "issues"
    MULTI = True
    REFS = ("end_face", "hole_rim", "front_top_edge", "front_edge_external")
    length = 56

    def endFace(self):
        return face("plane", normal=X, through=(self.length, 0, 0))

    def holeRim(self):
        return edge("circle", center=(self.length, 5, 5), radius=2)

    def frontTopEdge(self):
        return edge("line", direction=X, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        yz = App.Placement(V(), m.rotationFromAxes((0, 1, 0), (0, 0, 1)))  # normal +X
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 10, 10), body, placement=yz)
        pad = m.pad(body, profile, self.length)
        doc.recompute()
        onEnd = attach(body, "OnEnd", pad, self.names(pad, self.endFace()))
        doc.recompute()
        # the attacher picks the sketch's axes: put the circle where (y, z) = (5, 5)
        centre = onEnd.Placement.inverse().multVec(V(self.length, 5, 5))
        onEnd.addGeometry(m.circle(centre.x, centre.y, 2), False)
        hole = m.pocket(body, onEnd, 10, "Hole")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (hole, self.names(hole, self.holeRim()))
        chamfer.Size = 0.5
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (chamfer, self.names(chamfer, self.frontTopEdge()))
        fillet.Radius = 1
        side = external(doc, body, "OnSide", pad, self.names(pad, self.frontTopEdge()), 10)
        self.ref("end_face", onEnd, "AttachmentSupport", self.endFace, Attached())
        self.ref("hole_rim", chamfer, "Base", self.holeRim, Chamfered(0.5))
        self.ref("front_top_edge", fillet, "Base", self.frontTopEdge, Filleted(1))
        self.ref("front_edge_external", side, "ExternalGeometry", self.frontTopEdge,
                 ExternalCoincides())

    def edit(self, doc):
        doc.Pad.Length = 51
        self.length = 51


class Issue30515ResizeCylinder(Scenario):
    """Upstream issue 30515: a body whose base feature is a Part::Cylinder (radius 6.5, 20 high);
    a collar revolved around Z (x 5..9, z 8..12) fused onto it; sketches with the collar's inner
    and outer top circles as external geometry, and one on the collar's top face. The cylinder's
    radius changes to 6.05."""

    area = "issues"
    REFS = ("inner_circle", "outer_circle", "collar_top")
    radius = 6.5

    def innerCircle(self):
        return edge("circle", center=(0, 0, 12), radius=self.radius)

    def outerCircle(self):
        return edge("circle", center=(0, 0, 12), radius=9)

    def collarTop(self):
        return face("plane", normal=Z, through=(0, 0, 12))

    def build(self, doc):
        cylinder = doc.addObject("Part::Cylinder", "Cylinder")
        cylinder.Radius, cylinder.Height = self.radius, 20
        body = m.body(doc)
        body.BaseFeature = cylinder
        xz = App.Placement(V(), m.rotationFromAxes((1, 0, 0), (0, 0, 1)))
        profile = m.sketch(doc, "CollarSketch", m.rectangle(5, 8, 9, 12), body, placement=xz)
        collar = body.newObject("PartDesign::Revolution", "Collar")
        collar.Profile = profile
        collar.ReferenceAxis = (profile, ["V_Axis"])
        collar.Angle = 360
        doc.recompute()
        inner = external(doc, body, "OnInner", collar, self.names(collar, self.innerCircle()), 12)
        outer = external(doc, body, "OnOuter", collar, self.names(collar, self.outerCircle()), 12)
        onTop = attach(body, "OnTop", collar, self.names(collar, self.collarTop()))
        self.ref("inner_circle", inner, "ExternalGeometry", self.innerCircle, ExternalCoincides())
        self.ref("outer_circle", outer, "ExternalGeometry", self.outerCircle, ExternalCoincides())
        self.ref("collar_top", onTop, "AttachmentSupport", self.collarTop, Attached())

    def edit(self, doc):
        doc.Cylinder.Radius = 6.05
        self.radius = 6.05
