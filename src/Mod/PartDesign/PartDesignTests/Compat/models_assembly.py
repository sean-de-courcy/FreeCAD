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

"""The corpus's Assembly models (FreeCAD-CH ops#323 PR B2, notes/beta-compatibility.md 3.6,
D3's Assembly list 1-4; 6, the determinism check, runs in AsmMotion's builder).

Upstream's Python joints (`JointObject.py`), solved by the Ondsel solver headless (FreeCADCmd
imports pivy for them). Each builder checks the solved placements against the designed ones, so
a model whose solve goes wrong never enters a generation; the records then pin every link's and
part's `Placement` and every joint's `Placement1/2`. The reopened assemblies run upstream's
`migrationScript`s in `onDocumentRestored`, which the gate thereby pins too. Same conventions
as `models.py`."""

import math

import FreeCAD as App

from PartDesignTests.Compat.models import TOP, V, faceWhere, planeFacing, vertexAt
from PartDesignTests.Compat.models_partdesign import block, newBody
from PartDesignTests.Scenarios import models as m

TOL = 1e-6


def newAssembly(container, name="Assembly"):
    """An assembly with its joint group, in a document or inside another assembly."""
    if isinstance(container, App.Document):
        assembly = container.addObject("Assembly::AssemblyObject", name)
    else:
        assembly = container.newObject("Assembly::AssemblyObject", name)
    jointsName = "Joints" if name == "Assembly" else name + "Joints"
    joints = assembly.newObject("Assembly::JointGroup", jointsName)
    return assembly, joints


def link(doc, assembly, name, target, placement):
    """An App::Link to `target`, in the assembly, at `placement`."""
    obj = doc.addObject("App::Link", name)
    obj.LinkedObject = target
    obj.Placement = placement
    assembly.addObject(obj)
    return obj


def ground(joints, part, name="GroundedJoint"):
    import JointObject

    joint = joints.newObject("App::FeaturePython", name)
    JointObject.GroundedJoint(joint, part)
    return joint


def joint(joints, name, kind, refs, **props):
    """A joint of `kind` (JointObject.JointTypes) between refs [[part, [element, vertex]], ...],
    its properties set before it is connected (connecting it solves the assembly)."""
    import JointObject

    obj = joints.newObject("App::FeaturePython", name)
    JointObject.Joint(obj, JointObject.JointTypes.index(kind))
    for key, value in props.items():
        setattr(obj, key, value)
    obj.Proxy.setJointConnectors(obj, refs)
    return obj


def solve(assembly):
    result = assembly.solve()
    if result != 0:
        raise AssertionError(f"{assembly.Name}: solve returned {result}")
    assembly.Document.recompute()


def assertAt(actual, expected, what):
    if (actual - expected).Length > TOL:
        raise AssertionError(f"{what} at {actual}, expected {expected}")


def topAndBottom(shape, height):
    """The names of a block's top face and its (0, 0, height) corner, and of its bottom face
    and its (0, 0, 0) corner, in the shape's own coordinates."""
    top = faceWhere(shape, planeFacing(TOP, V(0, 0, height)))
    bottom = faceWhere(shape, planeFacing(V(0, 0, -1), V(0, 0, 0)))
    return (top, vertexAt(shape, V(0, 0, height))), (bottom, vertexAt(shape, V(0, 0, 0)))


def AsmFastened(make):
    """The fastened case (Onshape's fastened mate): two Bodies from a part file in the same
    folder inserted as App::Links, a Grounded joint and two Fixed joints, face to face.

    AsmFastenedParts: Base, a 40 x 20 x 10 block (0..40); Plate, a 20 x 20 x 5 block (0..20).
    AsmFastened: LinkBase (grounded, at the origin); LinkPlate, its bottom face on Base's top
    face, corner (0, 0, 0) on (0, 0, 10): at (0, 0, 10); LinkPlate001 the same with Offset1
    (20, 0, 0) on Base's side: at (20, 0, 10). Both plates start a little off and turned."""
    parts = make("AsmFastenedParts")
    base = newBody(parts, "Base")
    block(base, 0, 0, 40, 20, 10, "BasePad")
    plate = newBody(parts, "Plate")
    block(plate, 0, 0, 20, 20, 5, "PlatePad")
    parts.recompute()
    doc = make("AsmFastened")
    assembly, joints = newAssembly(doc)
    linkBase = link(doc, assembly, "LinkBase", base, App.Placement())
    tilted = App.Rotation(V(0, 0, 1), 4)
    linkPlate = link(doc, assembly, "LinkPlate", plate, App.Placement(V(1, -1, 13), tilted))
    linkPlate2 = link(doc, assembly, "LinkPlate001", plate, App.Placement(V(22, 1, 12), tilted))
    doc.recompute()
    ground(joints, linkBase)
    baseTop, _ = topAndBottom(base.Shape, 10)
    _, plateBottom = topAndBottom(plate.Shape, 5)
    joint(joints, "Fixed", "Fixed", [[linkBase, list(baseTop)], [linkPlate, list(plateBottom)]])
    joint(
        joints,
        "Fixed001",
        "Fixed",
        [[linkBase, list(baseTop)], [linkPlate2, list(plateBottom)]],
        Offset1=App.Placement(V(20, 0, 0), App.Rotation()),
    )
    solve(assembly)
    for obj, at in ((linkPlate, V(0, 0, 10)), (linkPlate2, V(20, 0, 10))):
        assertAt(obj.Placement.Base, at, obj.Name)
        if not obj.Placement.Rotation.isIdentity(TOL):
            raise AssertionError(f"{obj.Name} turned {obj.Placement.Rotation}")
    return {"volumes": {"AsmFastenedParts#BasePad": 8000, "AsmFastenedParts#PlatePad": 2000}}


def AsmMotion(make):
    """Motion joints, compared after the solve, and the determinism check (two solves in one
    build give the same placements exactly: 3.6, item 6).

    A grounded Part box Ground, 60 x 60 x 5 (0..60), and two grounded cylinders standing on it:
    Hub, radius 5, 5 high, at (10, 10, 5); Sleeve, radius 3, 6 high, at (40, 40, 5).
    - Revolute: Wheel, a cylinder, radius 8, 2 high, its bottom circular edge on Hub's top
      circular edge: its axis on Hub's, its bottom at z 10.
    - Slider: Slide, a 10 x 4 x 4 box, its bottom front edge (y 0) along Ground's top front edge
      (y 0, z 5).
    - Cylindrical, with LengthMin -2, LengthMax 5, AngleMin -30, AngleMax 30 set: Rod, a cylinder,
      radius 1, 20 high, its bottom circular edge on Sleeve's top circular edge's axis.
    - Distance 7: Lifted, a 5 mm cube, its bottom face 7 from Ground's top face (z 12).
    - Angle 30: Tilted, a 5 mm cube, its bottom face at 30 degrees to Ground's top face.
    - Parallel: Level, a 5 mm cube, its top face parallel to Ground's top face.
    Each moving part starts near its place, so the solve has one nearby answer."""
    doc = make("AsmMotion")
    assembly, joints = newAssembly(doc)

    def cylinder(name, radius, height, at):
        obj = assembly.newObject("Part::Cylinder", name)
        obj.Radius, obj.Height = radius, height
        obj.Placement = at if isinstance(at, App.Placement) else App.Placement(at, App.Rotation())
        return obj

    def box(name, size, at):
        obj = assembly.newObject("Part::Box", name)
        obj.Length, obj.Width, obj.Height = size
        obj.Placement = at if isinstance(at, App.Placement) else App.Placement(at, App.Rotation())
        return obj

    groundBox = box("Ground", (60, 60, 5), V(0, 0, 0))
    hub = cylinder("Hub", 5, 5, V(10, 10, 5))
    sleeve = cylinder("Sleeve", 3, 6, V(40, 40, 5))
    wheel = cylinder("Wheel", 8, 2, App.Placement(V(10.5, 9.5, 10.5), App.Rotation(V(1, 0, 0), 3)))
    slide = box("Slide", (10, 4, 4), App.Placement(V(20, 0.5, 5.5), App.Rotation(V(0, 0, 1), 2)))
    rod = cylinder("Rod", 1, 20, App.Placement(V(40.3, 40.2, 12), App.Rotation(V(1, 0, 0), 2)))
    lifted = box("Lifted", (5, 5, 5), V(50, 5, 11))
    tilted = box("Tilted", (5, 5, 5), App.Placement(V(50, 20, 10), App.Rotation(V(1, 0, 0), 25)))
    level = box("Level", (5, 5, 5), App.Placement(V(50, 50, 10), App.Rotation(V(1, 0, 0), 5)))
    doc.recompute()
    for obj in (groundBox, hub, sleeve):
        ground(joints, obj, "Grounded" + obj.Name)

    def circle(obj, z):
        """The circular edge at local height z, twice (its centre is the joint's origin)."""
        edges = [
            f"Edge{i + 1}"
            for i, e in enumerate(obj.Shape.Edges)
            if hasattr(e.Curve, "Radius")
            and abs(e.Curve.Center.z - obj.Placement.multVec(V(0, 0, z)).z) < 0.5
        ]
        if len(edges) != 1:
            raise AssertionError(f"{obj.Name}: {len(edges)} circular edges at {z}")
        return [edges[0], edges[0]]

    def face(obj, local):
        """The face whose centre is at `local` in the object's own coordinates, twice."""
        point = obj.Placement.multVec(local)
        found = [
            f"Face{i + 1}"
            for i, f in enumerate(obj.Shape.Faces)
            if (f.CenterOfMass - point).Length < 1e-6
        ]
        if len(found) != 1:
            raise AssertionError(f"{obj.Name}: {len(found)} faces at {local}")
        return [found[0], found[0]]

    def frontEdge(obj, z):
        point = obj.Placement.multVec(V(obj.Length.Value / 2, 0, z))
        found = [
            f"Edge{i + 1}"
            for i, e in enumerate(obj.Shape.Edges)
            if (e.CenterOfMass - point).Length < 1e-6
        ]
        if len(found) != 1:
            raise AssertionError(f"{obj.Name}: {len(found)} edges at its front, z {z}")
        return [found[0], found[0]]

    joint(joints, "Revolute", "Revolute", [[hub, circle(hub, 5)], [wheel, circle(wheel, 0)]])
    joint(
        joints,
        "Slider",
        "Slider",
        [[groundBox, frontEdge(groundBox, 5)], [slide, frontEdge(slide, 0)]],
    )
    joint(
        joints,
        "Cylindrical",
        "Cylindrical",
        [[sleeve, circle(sleeve, 6)], [rod, circle(rod, 0)]],
        EnableLengthMin=True,
        EnableLengthMax=True,
        EnableAngleMin=True,
        EnableAngleMax=True,
        LengthMin=-2,
        LengthMax=5,
        AngleMin=-30,
        AngleMax=30,
    )
    groundTop = face(groundBox, V(30, 30, 5))
    for name, part, local, props in (
        ("Distance", lifted, V(2.5, 2.5, 0), {"Distance": 7}),
        ("Angle", tilted, V(2.5, 2.5, 0), {"Angle": 30}),
        ("Parallel", level, V(2.5, 2.5, 5), {}),
    ):
        joint(joints, name, name, [[groundBox, groundTop], [part, face(part, local)]], **props)
    solve(assembly)
    moving = (wheel, slide, rod, lifted, tilted, level)
    first = {obj.Name: App.Placement(obj.Placement) for obj in moving}
    solve(assembly)
    for obj in moving:
        if obj.Placement != first[obj.Name]:
            raise AssertionError(
                f"AsmMotion: a second solve moved {obj.Name}: {first[obj.Name]} -> {obj.Placement}"
            )
    z = V(0, 0, 1)
    axis = wheel.Placement.Rotation.multVec(z)
    assertAt(wheel.Placement.Base, V(10, 10, 10), "Wheel")
    if abs(abs(axis.z) - 1) > TOL:
        raise AssertionError(f"Wheel's axis is {axis}")
    edgeStart = slide.Placement.Base
    if abs(edgeStart.y) > TOL or abs(edgeStart.z - 5) > TOL:
        raise AssertionError(f"Slide's front edge starts at {edgeStart}")
    rodAxis = rod.Placement.Rotation.multVec(z)
    if abs(rod.Placement.Base.x - 40) > TOL or abs(rod.Placement.Base.y - 40) > TOL:
        raise AssertionError(f"Rod at {rod.Placement.Base}, not on Sleeve's axis")
    if abs(abs(rodAxis.z) - 1) > TOL:
        raise AssertionError(f"Rod's axis is {rodAxis}")
    if abs(abs(lifted.Shape.BoundBox.ZMin - 5) - 7) > TOL:
        raise AssertionError(f"Lifted's bottom at z {lifted.Shape.BoundBox.ZMin}")
    tiltedNormal = tilted.Placement.Rotation.multVec(z)
    angle = math.degrees(math.acos(max(-1.0, min(1.0, abs(tiltedNormal.z)))))
    if abs(angle - 30) > 1e-4:
        raise AssertionError(f"Tilted's bottom is at {angle} degrees")
    levelNormal = level.Placement.Rotation.multVec(z)
    if abs(abs(levelNormal.z) - 1) > TOL:
        raise AssertionError(f"Level's top faces {levelNormal}")
    return {}


def AsmEditedPart(make):
    """A part edited after the solve: the joint references follow the edited face across files.

    AsmEditedParts: a VarSet with Height; Body, a 20 x 20 block (0..20) padded `VarSet.Height`.
    AsmEdited: LinkLower to Body (grounded); LinkUpper to Body, its bottom face fixed on
    LinkLower's top face, corner on corner. Built with Height 10 and solved (LinkUpper at z 10),
    then Height set to 15, the part recomputed and the assembly solved again: LinkUpper at
    z 15. Saved so, both files."""
    parts = make("AsmEditedParts")
    varset = parts.addObject("App::VarSet", "VarSet")
    varset.addProperty("App::PropertyLength", "Height")
    varset.Height = 10
    body = newBody(parts, "Body")
    pad = block(body, 0, 0, 20, 20, 10)
    pad.setExpression("Length", "VarSet.Height")
    parts.recompute()
    doc = make("AsmEdited")
    assembly, joints = newAssembly(doc)
    lower = link(doc, assembly, "LinkLower", body, App.Placement())
    upper = link(doc, assembly, "LinkUpper", body, App.Placement(V(1, 1, 12), App.Rotation()))
    doc.recompute()
    ground(joints, lower)
    top, bottom = topAndBottom(body.Shape, 10)
    joint(joints, "Fixed", "Fixed", [[lower, list(top)], [upper, list(bottom)]])
    solve(assembly)
    assertAt(upper.Placement.Base, V(0, 0, 10), "LinkUpper before the edit")
    varset.Height = 15
    parts.recompute()
    doc.recompute()
    solve(assembly)
    assertAt(upper.Placement.Base, V(0, 0, 15), "LinkUpper after the edit")
    return {"volumes": {"AsmEditedParts#Pad": 6000}}


def AsmSubAssembly(make):
    """A sub-assembly inside an assembly, with a joint to one of its parts.

    Assembly: Base, a grounded 30 x 30 x 5 box (0..30). SubAssembly inside it: BoxA, a 10 mm
    cube, grounded in the sub-assembly; BoxB, a 10 x 10 x 4 box, fixed on BoxA's top face,
    corner on corner. In Assembly, a Fixed joint puts BoxA's bottom face on Base's top face,
    corner (0, 0, 0) on (10, 10, 5): BoxA's bottom corner at (10, 10, 5), BoxB's at
    (10, 10, 15)."""
    doc = make("AsmSubAssembly")
    assembly, joints = newAssembly(doc)
    base = assembly.newObject("Part::Box", "Base")
    base.Length, base.Width, base.Height = 30, 30, 5
    sub, subJoints = newAssembly(assembly, "SubAssembly")
    boxA = sub.newObject("Part::Box", "BoxA")
    boxA.Length = boxA.Width = boxA.Height = 10
    boxB = sub.newObject("Part::Box", "BoxB")
    boxB.Length, boxB.Width, boxB.Height = 10, 10, 4
    doc.recompute()
    aTop, aBottom = topAndBottom(boxA.Shape, 10)
    _, bBottom = topAndBottom(boxB.Shape, 4)
    boxB.Placement = App.Placement(V(1, 1, 12), App.Rotation())
    sub.Placement = App.Placement(V(12, 9, 8), App.Rotation())
    doc.recompute()
    ground(subJoints, boxA, "GroundedBoxA")
    joint(subJoints, "FixedB", "Fixed", [[boxA, list(aTop)], [boxB, list(bBottom)]])
    solve(sub)
    ground(joints, base)
    baseTop = faceWhere(base.Shape, planeFacing(TOP, V(0, 0, 5)))
    joint(
        joints,
        "Fixed",
        "Fixed",
        [[base, [baseTop, vertexAt(base.Shape, V(0, 0, 5))]],
         [sub, [f"BoxA.{aBottom[0]}", f"BoxA.{aBottom[1]}"]]],
        Offset1=App.Placement(V(10, 10, 0), App.Rotation()),
    )
    solve(assembly)
    placed = sub.Placement.multiply(boxA.Placement)
    assertAt(placed.Base, V(10, 10, 5), "BoxA")
    assertAt(sub.Placement.multiply(boxB.Placement).Base, V(10, 10, 15), "BoxB")
    return {}


MODELS = [AsmFastened, AsmMotion, AsmEditedPart, AsmSubAssembly]
