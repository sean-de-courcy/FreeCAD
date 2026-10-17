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

"""The CI reopen corpus's models (FreeCAD-CH ops#323, notes/beta-compatibility.md 3.6).

Each model is designed here, with its parameters stated, and built from nothing (no file input).
`make_generation.py` builds them with a given build, saves them and their records into a
generation folder, and `TestCompatCorpus` reopens them on every PR. A model's builder takes
`make(stem)`, which returns a new document saved as `<stem>.FCStd`, and returns the expected
values that make_generation checks before saving (`volumes`: {object name, or `stem#name` in a
model of several documents: volume}; and every object valid), so a model that builds wrongly
never enters a generation. `make` sets new documents up as a beta user's are: V2 naming,
InternNames and the reference solver on, set explicitly so a preference can't change them.

B1's list (3.6, "about ten, the core") is here; B2's are in the `models_*` modules, by group.
"""

import math
import os

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6


def faceWhere(shape, test):
    found = [i + 1 for i, f in enumerate(shape.Faces) if test(f)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} faces match, expected one")
    return f"Face{found[0]}"


def edgeWhere(shape, test):
    found = [i + 1 for i, e in enumerate(shape.Edges) if test(e)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} edges match, expected one")
    return f"Edge{found[0]}"


def vertexAt(shape, point):
    found = [i + 1 for i, v in enumerate(shape.Vertexes) if (v.Point - point).Length < TOL]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} vertexes at {point}, expected one")
    return f"Vertex{found[0]}"


def planeFacing(normal, through):
    """A test for a planar face with this outward normal whose plane holds the point."""

    def test(face):
        if not isinstance(face.Surface, Part.Plane):
            return False
        u0, u1, v0, v1 = face.ParameterRange
        n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        return (n - normal).Length < TOL and abs(
            (through - face.Surface.Position).dot(normal)
        ) < TOL

    return test


def lineThrough(a, b):
    """A test for a straight edge from a to b (either way round)."""
    a, b = V(*a), V(*b)

    def test(edge):
        if not isinstance(edge.Curve, Part.Line) or len(edge.Vertexes) != 2:
            return False
        p, q = edge.Vertexes[0].Point, edge.Vertexes[1].Point
        return ((p - a).Length < TOL and (q - b).Length < TOL) or (
            (p - b).Length < TOL and (q - a).Length < TOL
        )

    return test


def attachedSketch(body, name, support, geometry, mapMode="FlatFace"):
    """A sketch attached to `support` ((object, sub) or an origin feature)."""
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.AttachmentSupport = [support if isinstance(support, tuple) else (support, "")]
    sketch.MapMode = mapMode
    sketch.addGeometry(geometry, False)
    return sketch


def plane(body, role):
    return m.originFeature(body, role)


TOP = V(0, 0, 1)


# ---------------------------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------------------------


def PadPocket(make):
    """Pads and pockets on origin planes and on a face, each kind of extent once.

    A 40 x 30 x 10 block (sketch on the XY plane, 0..40 x 0..30, Pad to a length); a blind hole,
    radius 5, 4 deep, at (20, 15) from a sketch on the block's top face (Pocket to a length); a
    tunnel x 5..15, z 3..7 through the block along y from a sketch on the XZ plane (Pocket
    through all, symmetric to its plane); a boss, radius 2, at (y 15, z 5) on the block's left
    face from a sketch on the YZ plane (Pad with two lengths: 3 into the block, 6 out of it)."""
    doc = make("PadPocket")
    body = m.body(doc)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 40, 30))
    pad = m.pad(body, base, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    holeSketch = attachedSketch(body, "HoleSketch", (pad, top), [m.circle(20, 15, 5)])
    hole = m.pocket(body, holeSketch, 4, "Hole")
    tunnelSketch = attachedSketch(
        body, "TunnelSketch", plane(body, "XZ_Plane"), m.rectangle(5, 3, 15, 7)
    )
    tunnel = body.newObject("PartDesign::Pocket", "Tunnel")
    tunnel.Profile = tunnelSketch
    tunnel.Type = "ThroughAll"
    tunnel.SideType = "Symmetric"
    bossSketch = attachedSketch(body, "BossSketch", plane(body, "YZ_Plane"), [m.circle(15, 5, 2)])
    boss = body.newObject("PartDesign::Pad", "Boss")
    boss.Profile = bossSketch
    boss.SideType = "Two sides"
    boss.Length = 3
    boss.Length2 = 6
    doc.recompute()
    return {"volumes": {"Boss": 40 * 30 * 10 - math.pi * 25 * 4 - 10 * 4 * 30 + math.pi * 4 * 6}}


def ExternalGeometry(make):
    """A sketch with external geometry, an edge and a vertex, constrained to them.

    A 30 x 20 x 8 block (0..30 x 0..20); a sketch on its top face with the top back edge
    (y = 20) and the top front right vertex (30, 0) as external geometry; in it a circle,
    radius 3, centred on the vertex, and a 10 x 4 rectangle whose top side is parallel to the
    edge, 2 from it (y 14..18, x 5..15). Both pocketed 3 deep."""
    doc = make("ExternalGeometry")
    body = m.body(doc)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 30, 20))
    pad = m.pad(body, base, 8)
    doc.recompute()
    shape = pad.Shape
    top = faceWhere(shape, planeFacing(TOP, V(0, 0, 8)))
    sketch = attachedSketch(body, "Sketch001", (pad, top), [m.circle(30, 0, 3)])
    sketch.addGeometry(m.rectangle(5, 14, 15, 18), False)
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", 1 + i, 2, 1 + (i + 1) % 4, 1))
    sketch.addExternal(pad.Name, edgeWhere(shape, lineThrough((0, 20, 8), (30, 20, 8))))
    sketch.addExternal(pad.Name, vertexAt(shape, V(30, 0, 8)))
    # external geometry: -3 the edge, -4 the vertex
    sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -4, 1))
    sketch.addConstraint(Sketcher.Constraint("Radius", 0, 3))
    sketch.addConstraint(Sketcher.Constraint("Parallel", 3, -3))
    sketch.addConstraint(Sketcher.Constraint("Distance", 3, 1, -3, 2))
    pocket = m.pocket(body, sketch, 3)
    doc.recompute()
    quarter = math.pi * 9 / 4 * 3
    return {"volumes": {"Pocket": 30 * 20 * 8 - quarter - 10 * 4 * 3}}


def FilletChamfer(make):
    """Fillet and chamfer on edges across a pocket.

    A 40 x 20 x 10 block (0..40 x 0..20); a slot x 15..25 across its whole top (y -5..25 in the
    sketch on the top face), 4 deep; a fillet, radius 1, on the slot's two bottom edges (z = 6,
    x = 15 and 25); a chamfer, size 1, on the slot's two top edges (z = 10)."""
    doc = make("FilletChamfer")
    body = m.body(doc)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 40, 20))
    pad = m.pad(body, base, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    slotSketch = attachedSketch(body, "SlotSketch", (pad, top), m.rectangle(15, -5, 25, 25))
    slot = m.pocket(body, slotSketch, 4, "Slot")
    doc.recompute()
    bottom = [edgeWhere(slot.Shape, lineThrough((x, 0, 6), (x, 20, 6))) for x in (15, 25)]
    fillet = body.newObject("PartDesign::Fillet", "Fillet")
    fillet.Base = (slot, bottom)
    fillet.Radius = 1
    doc.recompute()
    rims = [edgeWhere(fillet.Shape, lineThrough((x, 0, 10), (x, 20, 10))) for x in (15, 25)]
    chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
    chamfer.Base = (fillet, rims)
    chamfer.Size = 1
    doc.recompute()
    rounds = 2 * (1 - math.pi / 4) * 20  # the fillets add material in the slot's corners
    bevels = 2 * 0.5 * 20  # the chamfers take it off the rims
    return {"volumes": {"Chamfer": 40 * 20 * 10 - 10 * 4 * 20 + rounds - bevels}}


def Patterns(make):
    """A linear and a polar pattern, each with its direction from an edge.

    A 60 x 60 x 10 block centred on the origin; a hole, radius 3, 5 deep, at (-10, -20), and a
    linear pattern of it along the block's top front edge (y = -30), 16 long, 3 occurrences; a
    cylinder boss, radius 10, 10 high, on the block's centre, a hole in it, radius 1.5, 4 deep,
    at (6, 0), and a polar pattern of that around the boss's top circular edge, 4 occurrences
    over 360 degrees."""
    doc = make("Patterns")
    body = m.body(doc)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(-30, -30, 30, 30))
    block = m.pad(body, base, 10, "Block")
    doc.recompute()
    top = faceWhere(block.Shape, planeFacing(TOP, V(0, 0, 10)))
    front = edgeWhere(block.Shape, lineThrough((-30, -30, 10), (30, -30, 10)))
    holeSketch = attachedSketch(body, "HoleSketch", (block, top), [m.circle(-10, -20, 3)])
    hole = m.pocket(body, holeSketch, 5, "Hole")
    doc.recompute()
    linear = body.newObject("PartDesign::LinearPattern", "LinearPattern")
    linear.Originals = [hole]
    linear.Direction = (block, [front])
    linear.Length = 16
    linear.Occurrences = 3
    body.Tip = linear  # newObject leaves the Tip (the roll-back bar, ops#127) before a pattern
    doc.recompute()
    bossTop = faceWhere(linear.Shape, planeFacing(TOP, V(0, 0, 10)))
    bossSketch = attachedSketch(body, "BossSketch", (linear, bossTop), [m.circle(0, 0, 10)])
    boss = m.pad(body, bossSketch, 10, "Boss")
    doc.recompute()
    rim = edgeWhere(
        boss.Shape,
        lambda e: isinstance(e.Curve, Part.Circle)
        and abs(e.Curve.Radius - 10) < TOL
        and abs(e.Curve.Center.z - 20) < TOL,
    )
    capFace = faceWhere(boss.Shape, planeFacing(TOP, V(0, 0, 20)))
    pinSketch = attachedSketch(body, "PinSketch", (boss, capFace), [m.circle(6, 0, 1.5)])
    pin = m.pocket(body, pinSketch, 4, "PinHole")
    doc.recompute()
    polar = body.newObject("PartDesign::PolarPattern", "PolarPattern")
    polar.Originals = [pin]
    polar.Axis = (boss, [rim])
    polar.Angle = 360
    polar.Occurrences = 4
    body.Tip = polar
    doc.recompute()
    volume = 60 * 60 * 10 - 3 * math.pi * 9 * 5 + math.pi * 100 * 10 - 4 * math.pi * 2.25 * 4
    return {"volumes": {"PolarPattern": volume}}


def VarSetDriven(make):
    """A VarSet driving a Pad length, a pattern count and a sketch constraint.

    VarSet: Height 12, Count 3, Width 25. A rectangle 0..Width x 0..20, fully constrained, its
    width constraint named `width` set by `VarSet.Width`, padded `VarSet.Height`; a hole, radius
    2, at (4, 10) through all, patterned along the sketch's horizontal axis, 15 long,
    `VarSet.Count` occurrences."""
    doc = make("VarSetDriven")
    varset = doc.addObject("App::VarSet", "VarSet")
    varset.addProperty("App::PropertyLength", "Height")
    varset.addProperty("App::PropertyInteger", "Count")
    varset.addProperty("App::PropertyLength", "Width")
    varset.Height = 12
    varset.Count = 3
    varset.Width = 25
    body = m.body(doc)
    sketch = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 25, 20))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", 3))
    sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
    width = sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 25))
    sketch.renameConstraint(width, "width")
    sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 20))
    sketch.setExpression("Constraints.width", "VarSet.Width")
    pad = m.pad(body, sketch, 12)
    pad.setExpression("Length", "VarSet.Height")
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 12)))
    holeSketch = attachedSketch(body, "HoleSketch", (pad, top), [m.circle(4, 10, 2)])
    hole = m.pocketThroughAll(body, holeSketch, "Hole")
    pattern = body.newObject("PartDesign::LinearPattern", "LinearPattern")
    pattern.Originals = [hole]
    pattern.Direction = (sketch, ["H_Axis"])
    pattern.Length = 15
    pattern.Occurrences = 3
    pattern.setExpression("Occurrences", "VarSet.Count")
    body.Tip = pattern  # newObject leaves the Tip (the roll-back bar, ops#127) before a pattern
    doc.recompute()
    return {"volumes": {"LinearPattern": 25 * 20 * 12 - 3 * math.pi * 4 * 12}}


def VarSetCopyDriven(make):
    """A copy of a made-up Onshape export (`App::VarSetCopy`, ops#317 PR E1) driving a Box.

    The export: Width `40 mm`, Depth `3/4 in` (19.05 mm), Height `#Width / 4 + 2 mm` (12 mm),
    written to a temporary folder and imported with `freecad.variables.copies` (the copy keeps
    that folder as its source path; a reopen doesn't read it). A Box whose Length, Width and
    Height are the copy's Width, Depth and Height."""
    import json
    import tempfile

    from freecad.variables import copies

    doc = make("VarSetCopyDriven")
    folder = tempfile.mkdtemp(prefix="VarSetCopyDriven")
    path = os.path.join(folder, "Studio.json")
    variables = [("Width", "40 mm"), ("Depth", "3/4 in"), ("Height", "#Width / 4 + 2 mm")]
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"variableStudioReference": None, "variables": [
            {"type": "LENGTH", "name": name, "value": None, "description": "",
             "expression": text} for name, text in variables]}], f)
    copy = copies.import_studios(doc, [path]).copies[0]
    box = m.box(doc, "Box", (1, 1, 1))
    box.setExpression("Length", f"{copy.Name}.Width")
    box.setExpression("Width", f"{copy.Name}.Depth")
    box.setExpression("Height", f"{copy.Name}.Height")
    doc.recompute()
    return {"volumes": {"Box": 40 * 19.05 * 12}}


def SubShapeBinder(make):
    """A SubShapeBinder of a feature's face in a second Body, with a sketch and a Pad on it.

    Body: a 20 x 20 x 10 block (0..20). Body001: a binder of the block's top face, a sketch
    attached to the binder's face with a circle, radius 4, at (10, 10), padded 5 (a cylinder on
    z 10..15)."""
    doc = make("SubShapeBinder")
    body = m.body(doc)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 20, 20))
    pad = m.pad(body, base, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    body2 = doc.addObject("PartDesign::Body", "Body001")
    binder = body2.newObject("PartDesign::SubShapeBinder", "Binder")
    binder.Support = [(pad, (top,))]
    doc.recompute()
    sketch = attachedSketch(body2, "Sketch001", (binder, "Face1"), [m.circle(10, 10, 4)])
    cylinder = m.pad(body2, sketch, 5, "Pad001")
    doc.recompute()
    return {"volumes": {"Pad": 4000, "Pad001": math.pi * 16 * 5}}


def ReorderBar(make):
    """A Body rolled back with features held below the bar (ops#127).

    A 20 x 20 x 10 block (0..20); boss A, 4 x 4 x 5 at (1, 1) on the top; boss B, 4 x 4 x 5 at
    (15, 15); hole C, radius 2, 3 deep, at (10, 10). The bar is after boss A: B and C are held,
    the Body's shape is the block with boss A."""
    doc = make("ReorderBar")
    body = m.body(doc)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 20, 20))
    block = m.pad(body, base, 10, "Block")
    doc.recompute()
    top = faceWhere(block.Shape, planeFacing(TOP, V(0, 0, 10)))
    a = m.pad(
        body, attachedSketch(body, "BossASketch", (block, top), m.rectangle(1, 1, 5, 5)), 5, "BossA"
    )
    b = m.pad(
        body,
        attachedSketch(body, "BossBSketch", (block, top), m.rectangle(15, 15, 19, 19)),
        5,
        "BossB",
    )
    c = m.pocket(
        body, attachedSketch(body, "HoleCSketch", (block, top), [m.circle(10, 10, 2)]), 3, "HoleC"
    )
    doc.recompute()
    body.rollTo(a)
    doc.recompute()
    return {"volumes": {"BossA": 4000 + 80, "HoleC": 4000 + 160 - math.pi * 4 * 3}}


def GuessRecord(make):
    """A reference broken on purpose by an edit, guessed by the solver and saved with its record.

    A rectangle 0..20 x 0..10 padded 10; a fillet, radius 1, on its vertical edge at (20, 0).
    The rectangle is then drawn again 0.5 over in x, every geometry id new: the fillet's edge
    is guessed (kind `geometric`, the scenario SolverRedrawShifted) onto the edge at
    (20.5, 0)."""
    doc = make("GuessRecord")
    body = m.body(doc)
    profile = attachedSketch(body, "Profile", plane(body, "XY_Plane"), m.rectangle(0, 0, 20, 10))
    pad = m.pad(body, profile, 10)
    doc.recompute()
    fillet = body.newObject("PartDesign::Fillet", "Fillet")
    fillet.Base = (pad, [edgeWhere(pad.Shape, lineThrough((20, 0, 0), (20, 0, 10)))])
    fillet.Radius = 1
    doc.recompute()
    profile.deleteAllGeometry()
    profile.addGeometry(m.polygon([(20.5, 10), (20.5, 0), (0.5, 0), (0.5, 10)]), False)
    doc.recompute()
    kinds = [row.get("guess_kind") for row in App.getReferenceReport(fillet)]
    if "geometric" not in kinds:
        raise AssertionError(f"GuessRecord: no geometric guess, report {kinds}")
    return {"volumes": {"Fillet": 2000 - (1 - math.pi / 4) * 10}}


def DatumPlane(make):
    """An attached datum plane with an offset, and a sketch and a Pad on it.

    A 30 x 30 x 10 block (0..30); a datum plane attached to its top face, offset 5 up and turned
    15 degrees about its x axis (origin (0, 0, 15)); on it a circle, radius 4, at (15, 15),
    padded 12 towards the block (reversed), into it. The post's axis meets the top face at
    t = (5 + 15 sin 15) / cos 15 from the datum plane, and the oblique cut lies wholly within the
    post (t +- 4 tan 15 is within 0..12), so the post adds 16 pi t above the block."""
    doc = make("DatumPlane")
    body = m.body(doc)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 30, 30))
    pad = m.pad(body, base, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    datum = body.newObject("PartDesign::Plane", "DatumPlane")
    datum.AttachmentSupport = [(pad, top)]
    datum.MapMode = "FlatFace"
    datum.AttachmentOffset = App.Placement(V(0, 0, 5), App.Rotation(V(1, 0, 0), 15))
    doc.recompute()
    sketch = attachedSketch(body, "Sketch001", datum, [m.circle(15, 15, 4)])
    post = m.pad(body, sketch, 12, "Post")
    post.Reversed = True
    doc.recompute()
    a = math.radians(15)
    t = (5 + 15 * math.sin(a)) / math.cos(a)
    return {"volumes": {"Post": 30 * 30 * 10 + 16 * math.pi * t}}


def TwoDocuments(make):
    """The two-document pair: an App::Link to a Body in a part file, and a binder through it.

    TwoDocumentsPart: a Body with a 20 x 10 x 5 block (0..20 x 0..10). TwoDocuments: an
    App::Link to that Body, placed at (30, 0, 0); a Body with a binder of the linked block's top
    face (through the link), a sketch on the binder with a circle, radius 3, at (40, 5), padded
    4 (z 5..9)."""
    part = make("TwoDocumentsPart")
    body = m.body(part)
    base = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 20, 10))
    pad = m.pad(body, base, 5)
    part.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 5)))
    assembly = make("TwoDocuments")
    link = assembly.addObject("App::Link", "PartLink")
    link.LinkedObject = body
    link.Placement = App.Placement(V(30, 0, 0), App.Rotation())
    body2 = m.body(assembly)
    binder = body2.newObject("PartDesign::SubShapeBinder", "Binder")
    binder.Support = [(link, (top,))]
    assembly.recompute()
    sketch = attachedSketch(body2, "Sketch", (binder, "Face1"), [m.circle(40, 5, 3)])
    m.pad(body2, sketch, 4)
    assembly.recompute()
    return {"volumes": {"TwoDocumentsPart#Pad": 1000, "TwoDocuments#Pad": math.pi * 9 * 4}}


def ReorderBarRollForward(docs):
    """ReorderBar's held features, recomputed: the bar moved to the end. Returns their names,
    which the gate compares with the saved record (their shapes as computed before the bar was
    rolled back)."""
    doc = docs["ReorderBar"]
    body = doc.getObject("Body")
    body.rollTo(doc.getObject("HoleC"))
    doc.recompute()
    return ["BossBSketch", "BossB", "HoleCSketch", "HoleC"]


# Models with features the recompute pass can't reach (held below the reorder bar): after that
# pass, the gate calls the step and compares the objects it names (TestCompatCorpus).
ROLL_FORWARD = {"ReorderBar": ReorderBarRollForward}


# The B1 models, in generation order.
MODELS = {
    f.__name__: f
    for f in (
        PadPocket,
        ExternalGeometry,
        FilletChamfer,
        Patterns,
        VarSetDriven,
        SubShapeBinder,
        ReorderBar,
        GuessRecord,
        DatumPlane,
        TwoDocuments,
    )
}

# B2's models (3.6), by group: each module lists its builders in generation order.
from PartDesignTests.Compat import models_partdesign  # noqa: E402 (uses this module's helpers)
from PartDesignTests.Compat import models_part  # noqa: E402
from PartDesignTests.Compat import models_sketcher  # noqa: E402
from PartDesignTests.Compat import models_assembly  # noqa: E402
from PartDesignTests.Compat import models_studio  # noqa: E402

for _group in (models_partdesign, models_part, models_sketcher, models_assembly, models_studio):
    MODELS.update((f.__name__, f) for f in _group.MODELS)

# ops#317 PR E1: a variables copy, for the next generation.
MODELS[VarSetCopyDriven.__name__] = VarSetCopyDriven
