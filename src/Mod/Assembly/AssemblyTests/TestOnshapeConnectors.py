# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#683; notes/assemblies-design.md sections 3 and 6a): Onshape's implicit mate
# connectors and its Fastened mate, by position on designed parts.
#
# - C2: a connector's frame on a planar face (Z out of the material, X the first of the part's
#   +x, +y, +z not parallel to Z) and on an edge or vertex picked alone (oracle 12, GC-B2); the
#   mate is first = second x Reorient x Flip x Translate x Rotate (GC-B1.2, B1.3, GB31).
# - The missing picks: an arc's midpoint, the part's origin, a vertex of an inserted sketch
#   (GC-A1, GC-A4).
#
# The expected results are geometric: frames from the rule, placements from GB31's numbers (a
# designed mate in Onshape: box 40 x 20 x 10 at the origin, box 20 x 10 x 5 at x 60..80).

import math
import os
import shutil
import tempfile

import FreeCAD as App
import Part

import JointObject
import UtilsAssembly

from AssemblyTests.TestCore import AssemblyTestBase

X, Y, Z = App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)
S = math.sqrt(0.5)


def rows(r):
    """A rotation from its matrix rows"""
    return App.Rotation(App.Matrix(*r[0], 0, *r[1], 0, *r[2], 0, 0, 0, 0, 1))


class TestOnshapeConnectors(AssemblyTestBase):
    def setUp(self):
        super().setUp()
        self.assembly.Type = "Assembly"

    # --- helpers ----------------------------------------------------------------------------

    def part(self, name, shape, placement=None):
        obj = self.assembly.newObject("Part::Feature", name)
        obj.Shape = shape
        if placement is not None:
            obj.Placement = placement
        self.doc.recompute()
        return obj

    def faceWithNormal(self, obj, normal):
        for i, face in enumerate(obj.Shape.Faces):
            if face.Surface.TypeId != "Part::GeomPlane":
                continue
            n = obj.Placement.Rotation.inverted().multVec(UtilsAssembly.outwardNormal(face))
            if n.isEqual(normal, 1e-9):
                return f"Face{i + 1}"
        self.fail(f"no face with normal {normal}")

    def ref(self, obj, element, point=None):
        ref = [self.assembly, [f"{obj.Name}.{element}"]]
        return UtilsAssembly.addVertexToReference(ref, point or element)

    def connector(self, obj, element, point=None):
        """The connector in the part's axes"""
        return UtilsAssembly.findPlacement(self.ref(obj, element, point))

    def assertVec(self, got, expected, msg=""):
        self.assertTrue(got.isEqual(App.Vector(expected), 1e-6), f"{msg}: {got}, expected {expected}")

    def assertFrame(self, plc, x, y, z, msg=""):
        r = plc.Rotation
        self.assertVec(r.multVec(X), x, msg + " X")
        self.assertVec(r.multVec(Y), y, msg + " Y")
        self.assertVec(r.multVec(Z), z, msg + " Z")

    def assertPlacement(self, obj, expected, msg=""):
        got = obj.Placement
        self.assertTrue(got.Base.isEqual(expected.Base, 1e-6), f"{msg}: T {got.Base}, expected {expected.Base}")
        self.assertTrue(
            got.Rotation.isSame(expected.Rotation, 1e-6),
            f"{msg}: R {got.Rotation.toMatrix()}, expected {expected.Rotation.toMatrix()}",
        )

    def fastened(self, first, firstElt, second, secondElt, firstPoint=None, secondPoint=None):
        """A Fastened mate picked as the dialog does: the first pick moves onto the second"""
        joint = self.jointgroup.newObject("App::FeaturePython", "Fastened")
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(
            joint,
            [
                [first, [firstElt, firstPoint or firstElt]],
                [second, [secondElt, secondPoint or secondElt]],
            ],
        )
        return joint

    def globalConnectors(self, joint):
        return (
            UtilsAssembly.getJcsGlobalPlc(joint.Placement1, joint.Reference1),
            UtilsAssembly.getJcsGlobalPlc(joint.Placement2, joint.Reference2),
        )

    # --- C2: the frames (GC-B2) -------------------------------------------------------------

    def test_box_face_frames(self):
        """Every face of a box: Z out of the material, X the first part axis not along Z. The box
        is placed and turned in the assembly: the frame is the part's, not the assembly's."""
        box = self.part(
            "Box", Part.makeBox(40, 20, 10), App.Placement(App.Vector(5, 6, 7), App.Rotation(30, 20, 10))
        )
        table = (
            (Z, X, Y, Z),
            (-Z, X, -Y, -Z),
            (-Y, X, Z, -Y),
            (Y, X, -Z, Y),
            (-X, Y, -Z, -X),
            (X, Y, Z, X),
        )
        for normal, x, y, z in table:
            with self.subTest(normal=normal):
                face = self.faceWithNormal(box, normal)
                plc = self.connector(box, face)
                self.assertFrame(plc, x, y, z, f"face {normal}")
                # the face's corners take the face's frame
                vertex = UtilsAssembly.findVertexNameInObject(box.Shape.getElement(face).Vertexes[0], box)
                self.assertFrame(self.connector(box, face, vertex), x, y, z, f"corner of face {normal}")

    def test_tilted_face_frame(self):
        # A prism whose sloped face has the outward normal (0, -1, 1)/sqrt2
        profile = Part.Face(
            Part.makePolygon([App.Vector(0, 0, 0), App.Vector(0, 20, 0), App.Vector(0, 20, 20), App.Vector(0, 0, 0)])
        )
        prism = self.part("Prism", profile.extrude(App.Vector(30, 0, 0)))
        face = self.faceWithNormal(prism, App.Vector(0, -S, S))
        self.assertFrame(self.connector(prism, face), X, App.Vector(0, S, S), App.Vector(0, -S, S), "tilted")

    def test_edge_and_vertex_alone(self):
        """An edge picked alone: Z along it, X the first part axis not along it. A vertex alone:
        the part's axes."""
        box = self.part("Box", Part.makeBox(40, 20, 10))
        edge = None
        for i, e in enumerate(box.Shape.Edges):
            pts = [v.Point for v in e.Vertexes]
            if all(abs(p.y) < 1e-9 and abs(p.z - 10) < 1e-9 for p in pts):
                edge = f"Edge{i + 1}"
        plc = self.connector(box, edge)
        self.assertVec(plc.Base, (20, 0, 10), "the edge's midpoint")
        z = plc.Rotation.multVec(Z)
        self.assertAlmostEqual(abs(z.x), 1.0, places=9, msg="Z along the edge")
        self.assertVec(plc.Rotation.multVec(X), Y, "X")
        self.assertVec(plc.Rotation.multVec(Y), z.cross(Y), "Y = Z x X")
        vertex = UtilsAssembly.findVertexNameInObject(box.Shape.getElement(edge).Vertexes[0], box)
        self.assertFrame(self.connector(box, vertex), X, Y, Z, "vertex")

    # --- C2: the mate (GB31, GC-B1.2, GC-B1.3) ----------------------------------------------

    def gb31(self):
        """GB31: Part 1 (40 x 20 x 10 at the origin) top-face centre first, then Part 2's
        (20 x 10 x 5 at x 60..80) front-face centre, normal -y. Part 1 moves."""
        p1 = self.part("Part1", Part.makeBox(40, 20, 10))
        p2 = self.part("Part2", Part.makeBox(20, 10, 5, App.Vector(60, 0, 0)))
        joint = self.fastened(p1, self.faceWithNormal(p1, Z), p2, self.faceWithNormal(p2, -Y))
        return p1, p2, joint

    def test_gb31_as_onshape(self):
        p1, p2, joint = self.gb31()
        self.assertPlacement(p1, App.Placement(App.Vector(50, 10, -7.5), rows(((1, 0, 0), (0, 0, -1), (0, 1, 0)))), "no offset")
        self.assertPlacement(p2, App.Placement(), "the second pick stays")

        joint.Offset2 = App.Placement(App.Vector(5, 7, 3), App.Rotation())
        self.assertEqual(self.assembly.solve(), 0)
        self.assertPlacement(p1, App.Placement(App.Vector(55, 7, -0.5), rows(((1, 0, 0), (0, 0, -1), (0, 1, 0)))), "offset 5, 7, 3")

        joint.Proxy.flipOnePart(joint)
        self.assertEqual(self.assembly.solve(), 0)
        self.assertPlacement(p1, App.Placement(App.Vector(55, -7, 5.5), rows(((1, 0, 0), (0, 0, 1), (0, -1, 0)))), "Flip primary")

        joint.Reorient = 1
        self.assertEqual(self.assembly.solve(), 0)
        self.assertPlacement(p1, App.Placement(App.Vector(67, -7, -12.5), rows(((0, 1, 0), (0, 0, 1), (1, 0, 0)))), "Reorient after Flip")
        self.assertPlacement(p2, App.Placement(), "the second pick still stays")

    def test_offset_along_the_first_connectors_axes(self):
        """Flipped or not, reoriented or not: the first connector sits at the second's plus the
        offset along the first connector's own axes (oracle 12)"""
        offset = App.Vector(5, 7, 3)
        for flip in (False, True):
            for turns in (0, 1, 2):
                with self.subTest(flip=flip, turns=turns):
                    if self.jointgroup.Group:
                        for o in list(self.jointgroup.Group) + [self.doc.getObject("A"), self.doc.getObject("B")]:
                            self.doc.removeObject(o.Name)
                        self.doc.recompute()
                    a = self.part("A", Part.makeBox(40, 20, 10))
                    b = self.part("B", Part.makeBox(20, 10, 5, App.Vector(60, 0, 0)))
                    joint = self.fastened(a, self.faceWithNormal(a, Z), b, self.faceWithNormal(b, Z))
                    joint.Offset2 = App.Placement(offset, App.Rotation())
                    if flip:
                        joint.Proxy.flipOnePart(joint)
                    joint.Reorient = turns
                    self.assertEqual(self.assembly.solve(), 0)
                    c1, c2 = self.globalConnectors(joint)
                    raw2 = UtilsAssembly.getJcsGlobalPlc(UtilsAssembly.findPlacement(joint.Reference2), joint.Reference2)
                    self.assertVec(c1.Base - raw2.Base, c1.Rotation.multVec(offset), "along the first's axes")
                    facing = c1.Rotation.multVec(Z).dot(raw2.Rotation.multVec(Z))
                    self.assertAlmostEqual(facing, -1.0 if flip else 1.0, places=6, msg="flipped" if flip else "same way")
                    self.assertAlmostEqual(
                        c1.Rotation.multVec(X).dot(raw2.Rotation.multVec(X)),
                        (1, 0, -1)[turns],
                        places=6,
                        msg="the quarter turns",
                    )

    def test_flipped_top_faces_with_offset(self):
        """Oracle 12, flipped with the first pick the one turned: (5, -7, -3) along the second's
        axes, i.e. (5, 7, 3) along the first's"""
        a = self.part("A", Part.makeBox(40, 20, 10))
        b = self.part("B", Part.makeBox(20, 10, 5, App.Vector(60, 0, 0)))
        joint = self.fastened(a, self.faceWithNormal(a, Z), b, self.faceWithNormal(b, Z))
        joint.Offset2 = App.Placement(App.Vector(5, 7, 3), App.Rotation())
        joint.Proxy.flipOnePart(joint)
        self.assertEqual(self.assembly.solve(), 0)
        self.assertPlacement(b, App.Placement(), "B stays")
        centre = a.Placement.multVec(App.Vector(20, 10, 10))
        self.assertVec(centre, App.Vector(70, 5, 5) + App.Vector(5, -7, -3), "A's top centre")

    def test_rotation_offset_after_the_translation(self):
        """GC-B1.3: the rotation offset turns the first connector about the second's Z after the
        translation: unflipped, A's top centre at B's + (5, 7, 3), A turned +30 degrees"""
        a = self.part("A", Part.makeBox(40, 20, 10))
        b = self.part("B", Part.makeBox(20, 10, 5, App.Vector(60, 0, 0)))
        joint = self.fastened(a, self.faceWithNormal(a, Z), b, self.faceWithNormal(b, Z))
        joint.Offset2 = App.Placement(App.Vector(5, 7, 3), App.Rotation(Z, 30))
        self.assertEqual(self.assembly.solve(), 0)
        centre = a.Placement.multVec(App.Vector(20, 10, 10))
        self.assertVec(centre, (75, 12, 8), "A's top centre")
        self.assertTrue(a.Placement.Rotation.isSame(App.Rotation(Z, 30), 1e-9), a.Placement.Rotation)

    # --- the missing picks -------------------------------------------------------------------

    def halfDisc(self):
        """A half disc, radius 10, 5 thick: its top face's rim is an open arc, midpoint (0, 10, 5)"""
        disc = self.part("Disc", Part.makeCylinder(10, 5, App.Vector(), Z, 180))
        for i, e in enumerate(disc.Shape.Edges):
            if e.Curve.TypeId == "Part::GeomCircle" and not e.isClosed() and abs(e.Curve.Location.z - 5) < 1e-9:
                return disc, f"Edge{i + 1}"
        self.fail("no top arc")

    def test_arc_midpoint_offered_and_placed(self):
        disc, arc = self.halfDisc()
        cands = UtilsAssembly.connectorCandidates(self.ref(disc, arc))
        mids = [(p, n) for p, n, k in cands if k == "midpoint"]
        self.assertEqual(len(mids), 1, cands)
        self.assertVec(mids[0][0], (0, 10, 5), "offered on the arc")
        plc = self.connector(disc, arc, mids[0][1])
        self.assertVec(plc.Base, (0, 10, 5), "the arc's midpoint")
        z = plc.Rotation.multVec(Z)
        self.assertAlmostEqual(abs(z.x), 1.0, places=9, msg="Z along the arc there")
        # and from the top face, with the face's frame
        top = self.faceWithNormal(disc, Z)
        fromFace = [n for p, n, k in UtilsAssembly.connectorCandidates(self.ref(disc, top)) if k == "midpoint"]
        arcMid = [n for n in fromFace if self.connector(disc, top, n).Base.isEqual(App.Vector(0, 10, 5), 1e-6)]
        self.assertEqual(len(arcMid), 1, fromFace)
        self.assertFrame(self.connector(disc, top, arcMid[0]), X, Y, Z, "the face's frame")

    def test_mate_on_an_arc_midpoint_survives_reopen(self):
        disc, arc = self.halfDisc()
        top = self.faceWithNormal(disc, Z)
        name = [n for p, n, k in UtilsAssembly.connectorCandidates(self.ref(disc, top)) if k == "midpoint" and p.isEqual(App.Vector(0, 10, 5), 1e-6)][0]
        peg = self.part("Peg", Part.makeBox(4, 4, 4, App.Vector(50, 50, 50)))
        self.fastened(peg, self.faceWithNormal(peg, -Z), disc, top, None, name)
        bottomCentre = App.Vector(52, 52, 50)
        self.assertVec(peg.Placement.multVec(bottomCentre), (0, 10, 5), "the peg on the midpoint")
        names = disc.Name, peg.Name, self.assembly.Name
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "arcmid.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            disc, peg, assemblyName = self.doc.getObject(names[0]), self.doc.getObject(names[1]), names[2]
            disc.Shape = Part.makeCylinder(12, 5, App.Vector(), Z, 180)  # a bigger disc: the peg follows
            self.doc.recompute()
            assembly = self.doc.getObject(assemblyName)
            self.assertEqual(assembly.solve(), 0)
            self.assertVec(peg.Placement.multVec(bottomCentre), (0, 12, 5), "after reopen and an edit")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_part_origin_offered_and_mated(self):
        """A face offers its part's origin; the mate puts the first pick's origin, with its axes,
        on the second's connector"""
        q = self.part("Q", Part.makeBox(20, 10, 5, App.Vector(100, 0, 0)))
        p = self.part("P", Part.makeBox(6, 6, 6), App.Placement(App.Vector(-30, 40, 7), App.Rotation(10, 20, 30)))
        top = self.faceWithNormal(p, Z)
        origin = [(pt, n) for pt, n, k in UtilsAssembly.connectorCandidates(self.ref(p, top)) if k == "origin"]
        self.assertEqual(len(origin), 1)
        self.assertVec(UtilsAssembly.shapeToGlobal(self.ref(p, top), origin[0][0]), (-30, 40, 7), "drawn at the origin")
        self.assertTrue(self.connector(p, top, origin[0][1]).isIdentity(), "the part's origin and axes")
        self.fastened(p, top, q, self.faceWithNormal(q, Z), origin[0][1])
        self.assertPlacement(p, App.Placement(App.Vector(110, 5, 5), App.Rotation()), "P's origin on Q's top centre")

    def test_sketch_vertex_of_an_inserted_sketch(self):
        """GC-A4: Onshape's mates sit on vertices of sketches inserted into the assembly. A sketch
        inserted (a link, as Insert makes it) can be picked at a vertex and mated to."""
        import Sketcher  # noqa: F401

        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 5, 0)))
        self.doc.recompute()
        inserted = self.assembly.newObject("App::Link", "SketchInstance")
        inserted.LinkedObject = sketch
        inserted.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        grounded = self.jointgroup.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(grounded, inserted)
        self.doc.recompute()
        vertex = None
        for i, v in enumerate(Part.getShape(inserted).Vertexes):
            if inserted.Placement.inverse().multVec(v.Point).isEqual(App.Vector(10, 5, 0), 1e-6):
                vertex = f"Vertex{i + 1}"
        self.assertIsNotNone(vertex, [v.Point for v in Part.getShape(inserted).Vertexes])
        # the dialog's pick: the clicked vertex's component is the inserted sketch
        comp, sub = UtilsAssembly.getComponentReference(self.assembly, self.assembly, f"{inserted.Name}.{vertex}")
        self.assertIs(comp, inserted)
        self.assertEqual(sub, vertex)
        peg = self.part("Peg", Part.makeBox(4, 4, 4), App.Placement(App.Vector(-50, 0, 0), App.Rotation()))
        self.fastened(peg, self.faceWithNormal(peg, -Z), inserted, vertex)
        self.assertVec(peg.Placement.multVec(App.Vector(2, 2, 0)), (110, 5, 0), "the peg on the vertex")
        self.assertPlacement(inserted, App.Placement(App.Vector(100, 0, 0), App.Rotation()), "the sketch stays")
